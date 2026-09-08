import asyncio
import aiohttp
import os
import re
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from pymongo import MongoClient
from tqdm import tqdm
from dotenv import load_dotenv
from urllib.parse import urlparse, urljoin, quote_plus
from urllib.robotparser import RobotFileParser
import gridfs
import pandas as pd
import json
import uuid

# ================= CONFIG =================

load_dotenv()

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "medicsearch"

TIMEOUT = aiohttp.ClientTimeout(total=30)

USER_AGENT = "MedicSearchBot/1.0 (+contact)"
HEADERS = {"User-Agent": USER_AGENT}

REQUEST_DELAY_SECONDS = 1.0
MAX_PAGES_PER_QUERY = 3

QUERY_TERMS = [chr(c) for c in range(ord("a"), ord("z") + 1)]

# Ingestion officielle (API/Dumps) pour sources internes
OFFICIAL_INGESTION_ENABLED = True

# Scraping HTML DrugBank désactivé (403 Forbidden)
DRUGBANK_URLS = []
DRUGBANK_RANGE_ENABLED = False
DRUGBANK_START = 1
DRUGBANK_END = 9499
DRUGBANK_URL_TEMPLATE = "https://go.drugbank.com/drugs/DB{num:05d}"

SOURCE_SEARCH = {
    "THERIAQUE": {
        "search_url": "https://www.theriaque.org/apps/recherche/rch_simple.php",
        "result_link_regex": r"/apps/.*/fiche/|/apps/fiche/",
    },
    "VIDAL": {
        "gammes_url_template": "https://www.vidal.fr/medicaments/gammes/liste-{letter}.html",
        "substances_url_template": "https://www.vidal.fr/medicaments/substances/liste-{letter}.html",
        "result_link_regex": r"/medicaments/gammes/[^/]+\.html|/medicaments/substances/[^/]+\.html",
    },
    "HAS": {
        "search_url": "https://www.has-sante.fr/jcms/fc_2875208/fr/rechercher-une-recommandation-un-avis",
        "result_link_regex": r"/jcms/p_",
    },
    "DRUGBANKS": {
        "search_url": "https://go.drugbank.com/unearth/q?query={query}&searcher=drugs",
        "result_link_regex": r"/drugs/",
    },
    "BIOSINO": {
        "search_url": "https://www.biosino.org/cpmkg/search?keyword={query}",
        "result_link_regex": r"/cpmkg/detail\?id=",
    },
}

# ---------- THERIAQUE AUTH ----------
THERIAQUE_LOGIN = "https://www.theriaque.org/apps/contenu/accueil.php"

# ================= UTILS =================

def now_utc():
    return datetime.now(timezone.utc)

def get_nested(obj, path, default=None):
    if not path:
        return default
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur

def parse_csv_lines(text):
    lines = text.splitlines()
    if not lines:
        return {"rows": 0}
    return {"rows": len(lines) - 1}

def parse_xml_stub(text):
    return {"length": len(text)}

def build_auth_headers(prefix):
    headers = {"User-Agent": USER_AGENT}
    token = os.getenv(f"{prefix}_API_TOKEN")
    api_key = os.getenv(f"{prefix}_API_KEY")
    basic = os.getenv(f"{prefix}_API_BASIC")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if api_key:
        headers["x-api-key"] = api_key
    if basic:
        headers["Authorization"] = f"Basic {basic}"
    return headers

def get_source_config(prefix):
    return {
        "api_url": os.getenv(f"{prefix}_API_URL"),
        "api_pagination": os.getenv(f"{prefix}_API_PAGINATION", "cursor"),
        "api_items_path": os.getenv(f"{prefix}_API_ITEMS_PATH", "items"),
        "api_next_cursor_key": os.getenv(f"{prefix}_API_NEXT_CURSOR_KEY", "next_cursor"),
        "api_cursor_param": os.getenv(f"{prefix}_API_CURSOR_PARAM", "cursor"),
        "api_offset_param": os.getenv(f"{prefix}_API_OFFSET_PARAM", "offset"),
        "api_page_param": os.getenv(f"{prefix}_API_PAGE_PARAM", "page"),
        "api_limit": int(os.getenv(f"{prefix}_API_LIMIT", "500")),
        "api_format": os.getenv(f"{prefix}_API_FORMAT", "json").lower(),
        "dump_urls": [u.strip() for u in os.getenv(f"{prefix}_DUMP_URLS", "").split(",") if u.strip()],
    }

class RobotsManager:
    def __init__(self, session):
        self.session = session
        self.cache = {}

    async def allowed(self, url):
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self.cache:
            robots_url = f"{base}/robots.txt"
            rp = RobotFileParser()
            try:
                async with self.session.get(robots_url, headers=HEADERS) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        rp.parse(text.splitlines())
                    else:
                        rp.parse([])
            except Exception:
                rp.parse([])
            self.cache[base] = rp

        return self.cache[base].can_fetch(USER_AGENT, url)

async def fetch_text(session, robots, url, retries=3):
    if not await robots.allowed(url):
        print(f"⛔ robots.txt interdit: {url}")
        return {"text": None, "status": None, "blocked": True}

    for attempt in range(1, retries + 1):
        try:
            async with session.get(url, headers=HEADERS) as resp:
                if resp.status != 200:
                    return {"text": None, "status": resp.status, "blocked": False}
                text = await resp.text()
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
                return {"text": text, "status": resp.status, "blocked": False}
        except asyncio.TimeoutError:
            if attempt == retries:
                return {"text": None, "status": None, "blocked": False}
        except aiohttp.ClientError:
            if attempt == retries:
                return {"text": None, "status": None, "blocked": False}

async def fetch_stream_to_gridfs(session, robots, url, fs, metadata):
    if not await robots.allowed(url):
        print(f"⛔ robots.txt interdit: {url}")
        return None

    async with session.get(url, headers=HEADERS) as resp:
        if resp.status != 200:
            return None

        filename = url.split("/")[-1]
        grid_file = fs.new_file(filename=filename, metadata=metadata)
        async for chunk in resp.content.iter_chunked(1024 * 1024):
            grid_file.write(chunk)
        grid_file.close()
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
        return grid_file._id

async def fetch_api_page(session, url, headers, params=None):
    async with session.get(url, headers=headers, params=params) as resp:
        if resp.status != 200:
            return {"status": resp.status, "text": None}
        text = await resp.text()
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
        return {"status": resp.status, "text": text}

def find_next_page_url(soup, base_url):
    link = soup.find("a", rel=lambda v: v and "next" in v)
    if not link:
        link = soup.find("a", string=lambda t: t and t.strip().lower() in {"next", "suivant", "›", ">"})
    if link and link.get("href"):
        return urljoin(base_url, link["href"])
    return None

def extract_result_links(html, base_url, pattern):
    soup = BeautifulSoup(html, "lxml")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(pattern, href):
            links.add(urljoin(base_url, href))
    return list(links), soup

def extract_sections(soup):
    """Extrait les sections structurées d'une page RCP ANSM sans HTML"""
    sections = {}
    
    # Recherche des sections principales (divs avec class ou id)
    main_content = soup.find(['div', 'main', 'article'], class_=lambda c: c and any(x in str(c).lower() for x in ['content', 'main', 'body', 'rcp']))
    
    if not main_content:
        main_content = soup.body if soup.body else soup
    
    # Extraction par titres (h1, h2, h3, h4)
    for tag in main_content.find_all(["h1", "h2", "h3", "h4"]):
        title = tag.get_text(strip=True)
        if not title:
            continue
        
        # Collecte du contenu jusqu'au prochain titre du même niveau ou supérieur
        content_parts = []
        for sibling in tag.find_next_siblings():
            if sibling.name in ["h1", "h2", "h3", "h4"]:
                # Arrêt si on trouve un titre de même niveau ou supérieur
                if sibling.name <= tag.name:
                    break
            
            # Extraction du texte (paragraphes, listes, tableaux)
            text = sibling.get_text(separator=" ", strip=True)
            if text:
                content_parts.append(text)
        
        if content_parts:
            sections[title] = "\n\n".join(content_parts)
    
    # Si aucune section trouvée, essayer les balises <section>
    if not sections:
        for section in main_content.find_all("section"):
            section_id = section.get("id") or section.get("class")
            if section_id:
                title = str(section_id) if isinstance(section_id, str) else "_".join(section_id)
                sections[title] = section.get_text(separator="\n", strip=True)
    
    return sections

# ================= SOURCES =================

async def scrape_ansm_datasets(session, robots, db):
    print("\n🚀 START SOURCE : ANSM (datasets)")
    url = "https://base-donnees-publique.medicaments.gouv.fr/telechargement.php"
    result = await fetch_text(session, robots, url)
    if not result["text"]:
        print("⚠️  ANSM telechargement inaccessible")
        db["ANSM"].insert_one({
            "source": "ANSM",
            "url": url,
            "event": "access_failed",
            "blocked": result["blocked"],
            "status": result["status"],
            "scraped_at": now_utc(),
        })

        # Fallback: scrape RCP pages from local liens_R.xlsx
        links = load_ansm_rcp_links()
        if not links:
            return

        ansm_col = db["ANSM"]
        jobs_col = db["IMPORT_JOBS"]
        job = jobs_col.find_one({"source": "ANSM_RCP", "status": {"$in": ["RUNNING", "PAUSED"]}})
        if not job:
            job = {
                "source": "ANSM_RCP",
                "run_id": str(uuid.uuid4()),
                "status": "RUNNING",
                "last_index": 0,
                "started_at": now_utc(),
            }
            jobs_col.insert_one(job)

        start_index = job.get("last_index", 0)

        for idx, link in enumerate(tqdm(links, desc="ANSM RCP")):
            if idx < start_index:
                continue
            page_result = await fetch_text(session, robots, link)
            if not page_result["text"]:
                ansm_col.insert_one({
                    "source": "ANSM",
                    "type": "page_error",
                    "url": link,
                    "blocked": page_result["blocked"],
                    "status": page_result["status"],
                    "scraped_at": now_utc(),
                })
                jobs_col.update_one(
                    {"source": "ANSM_RCP", "run_id": job["run_id"]},
                    {"$set": {"last_index": idx, "updated_at": now_utc()}},
                )
                continue

            soup = BeautifulSoup(page_result["text"], "lxml")
            
            # Extraction du titre
            title = soup.title.text if soup.title else None
            
            # Extraction du contenu structuré (sans HTML)
            sections = extract_sections(soup)
            
            # Extraction du texte brut complet (backup)
            full_text = soup.get_text(separator="\n", strip=True)
            
            ansm_col.update_one(
                {"url": link},
                {
                    "$set": {
                        "source": "ANSM",
                        "type": "RCP",
                        "url": link,
                        "scraped_at": now_utc(),
                        "title": title,
                        "sections": sections,
                        "full_text": full_text,
                    }
                },
                upsert=True,
            )
            if idx % 50 == 0:
                jobs_col.update_one(
                    {"source": "ANSM_RCP", "run_id": job["run_id"]},
                    {"$set": {"last_index": idx, "updated_at": now_utc()}},
                )
        jobs_col.update_one(
            {"source": "ANSM_RCP", "run_id": job["run_id"]},
            {"$set": {"status": "COMPLETED", "finished_at": now_utc()}},
        )
        return

    soup = BeautifulSoup(result["text"], "lxml")
    dataset_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(href.lower().endswith(ext) for ext in [".csv", ".xml", ".zip"]):
            dataset_links.append(urljoin(url, href))

    dataset_links = list(set(dataset_links))
    print(f"⚡ {len(dataset_links)} jeux de données détectés")

    ansm_col = db["ANSM"]
    fs = gridfs.GridFS(db, collection="ANSM_FILES")

    for link in tqdm(dataset_links, desc="ANSM DATASETS"):
        file_id = await fetch_stream_to_gridfs(
            session,
            robots,
            link,
            fs,
            metadata={"source": "ANSM", "url": link, "scraped_at": now_utc()},
        )
        if file_id:
            ansm_col.update_one(
                {"url": link},
                {"$set": {"source": "ANSM", "url": link, "file_id": file_id, "scraped_at": now_utc()}},
                upsert=True,
            )

    print("✅ END SOURCE : ANSM")

async def ingest_official_source(session, db, source_name, prefix):
    if not OFFICIAL_INGESTION_ENABLED:
        return

    config = get_source_config(prefix)
    raw_col = db[f"RAW_{source_name}"]
    jobs_col = db["IMPORT_JOBS"]
    fs = gridfs.GridFS(db, collection=f"RAW_{source_name}_FILES")

    run_id = str(uuid.uuid4())
    jobs_col.insert_one({
        "source": source_name,
        "run_id": run_id,
        "status": "RUNNING",
        "started_at": now_utc(),
    })

    # 1) Dump ingestion (if provided)
    if config["dump_urls"]:
        for url in tqdm(config["dump_urls"], desc=f"{source_name} DUMPS"):
            headers = build_auth_headers(prefix)
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    raw_col.insert_one({
                        "source": source_name,
                        "type": "dump_error",
                        "url": url,
                        "status": resp.status,
                        "run_id": run_id,
                        "ingested_at": now_utc(),
                    })
                    continue

                filename = url.split("/")[-1]
                grid_file = fs.new_file(filename=filename, metadata={
                    "source": source_name,
                    "url": url,
                    "run_id": run_id,
                    "ingested_at": now_utc(),
                })
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    grid_file.write(chunk)
                grid_file.close()

                raw_col.insert_one({
                    "source": source_name,
                    "type": "dump_file",
                    "url": url,
                    "file_id": grid_file._id,
                    "run_id": run_id,
                    "ingested_at": now_utc(),
                })

    # 2) API ingestion (if provided)
    if config["api_url"]:
        headers = build_auth_headers(prefix)
        pagination = config["api_pagination"]
        limit = config["api_limit"]
        cursor = None
        offset = 0
        page = 1

        while True:
            params = {"limit": limit}
            if pagination == "cursor":
                params[config["api_cursor_param"]] = cursor
            elif pagination == "offset":
                params[config["api_offset_param"]] = offset
            elif pagination == "page":
                params[config["api_page_param"]] = page

            result = await fetch_api_page(session, config["api_url"], headers, params=params)
            if not result["text"]:
                raw_col.insert_one({
                    "source": source_name,
                    "type": "api_error",
                    "status": result["status"],
                    "params": params,
                    "run_id": run_id,
                    "ingested_at": now_utc(),
                })
                break

            if config["api_format"] == "json":
                data = json.loads(result["text"])
                items = get_nested(data, config["api_items_path"], []) or []
                raw_col.insert_one({
                    "source": source_name,
                    "type": "api_page",
                    "params": params,
                    "payload": data,
                    "run_id": run_id,
                    "ingested_at": now_utc(),
                })

                if pagination == "cursor":
                    cursor = get_nested(data, config["api_next_cursor_key"])
                    if not cursor:
                        break
                elif pagination == "offset":
                    if len(items) < limit:
                        break
                    offset += limit
                elif pagination == "page":
                    if len(items) < limit:
                        break
                    page += 1
            elif config["api_format"] == "csv":
                raw_col.insert_one({
                    "source": source_name,
                    "type": "api_page",
                    "params": params,
                    "payload": result["text"],
                    "summary": parse_csv_lines(result["text"]),
                    "run_id": run_id,
                    "ingested_at": now_utc(),
                })
                if pagination == "offset":
                    offset += limit
                elif pagination == "page":
                    page += 1
                else:
                    break
            else:  # xml or other
                raw_col.insert_one({
                    "source": source_name,
                    "type": "api_page",
                    "params": params,
                    "payload": result["text"],
                    "summary": parse_xml_stub(result["text"]),
                    "run_id": run_id,
                    "ingested_at": now_utc(),
                })
                if pagination == "offset":
                    offset += limit
                elif pagination == "page":
                    page += 1
                else:
                    break

    jobs_col.update_one(
        {"source": source_name, "run_id": run_id},
        {"$set": {"status": "COMPLETED", "finished_at": now_utc()}},
    )

def load_ansm_rcp_links():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    possible_files = [
        os.path.join(script_dir, "liens_R.xlsx"),
        os.path.join(script_dir, "..", "liens_R.xlsx"),
        os.path.join(script_dir, "..", "data", "liens_R.xlsx"),
    ]

    for file_path in possible_files:
        if os.path.exists(file_path):
            df = pd.read_excel(file_path)
            if "liens" in df.columns:
                return list(df["liens"].dropna().unique())
            first_col = df.columns[0]
            return list(df[first_col].dropna().unique())

    return []

async def theriaque_login(session):
    payload = {
        "username": os.getenv("THERIAQUE_USER"),
        "password": os.getenv("THERIAQUE_PASSWORD"),
    }

    if not payload["username"] or not payload["password"]:
        print("⚠️  THERIAQUE_USER/THERIAQUE_PASSWORD manquants. Source ignorée.")
        return False

    async with session.post(THERIAQUE_LOGIN, data=payload) as resp:
        if resp.status != 200:
            print(f"⚠️  Login Thériaque échoué (status {resp.status}).")
            return False
        print("🔐 Thériaque connecté")
        return True

async def scrape_vidal_alphabetic(session, robots, db):
    print(f"\n🚀 START SOURCE : VIDAL (alphabétique)")
    config = SOURCE_SEARCH["VIDAL"]
    source_col = db["VIDAL"]
    
    letters = [chr(c) for c in range(ord('a'), ord('z') + 1)]
    
    for letter in tqdm(letters, desc="VIDAL Lettres"):
        # Scraper les gammes
        gammes_url = config["gammes_url_template"].format(letter=letter)
        print(f"\n  📖 Scraping gammes - lettre {letter.upper()}")
        result = await fetch_text(session, robots, gammes_url)
        if result["text"]:
            source_col.update_one(
                {"source": "VIDAL", "type": "gammes_list", "letter": letter, "url": gammes_url},
                {"$set": {"raw_html": result["text"], "scraped_at": now_utc()}},
                upsert=True,
            )
            
            links, _ = extract_result_links(result["text"], gammes_url, config["result_link_regex"])
            print(f"    ✓ {len(links)} gammes trouvées")
            for link in links:
                page_result = await fetch_text(session, robots, link)
                if page_result["text"]:
                    source_col.update_one(
                        {"url": link},
                        {
                            "$set": {
                                "source": "VIDAL",
                                "type": "gamme_detail",
                                "letter": letter,
                                "url": link,
                                "scraped_at": now_utc(),
                                "raw_html": page_result["text"],
                            }
                        },
                        upsert=True,
                    )
        
        # Scraper les substances
        substances_url = config["substances_url_template"].format(letter=letter)
        print(f"  🧪 Scraping substances - lettre {letter.upper()}")
        result = await fetch_text(session, robots, substances_url)
        if result["text"]:
            source_col.update_one(
                {"source": "VIDAL", "type": "substances_list", "letter": letter, "url": substances_url},
                {"$set": {"raw_html": result["text"], "scraped_at": now_utc()}},
                upsert=True,
            )
            
            links, _ = extract_result_links(result["text"], substances_url, config["result_link_regex"])
            print(f"    ✓ {len(links)} substances trouvées")
            for link in links:
                page_result = await fetch_text(session, robots, link)
                if page_result["text"]:
                    source_col.update_one(
                        {"url": link},
                        {
                            "$set": {
                                "source": "VIDAL",
                                "type": "substance_detail",
                                "letter": letter,
                                "url": link,
                                "scraped_at": now_utc(),
                                "raw_html": page_result["text"],
                            }
                        },
                        upsert=True,
                    )
    
    print(f"\n✅ END SOURCE : VIDAL")

async def scrape_search_source(session, robots, db, source_name, requires_login=False):
    print(f"\n🚀 START SOURCE : {source_name}")
    config = SOURCE_SEARCH[source_name]
    source_col = db[source_name]

    for term in tqdm(QUERY_TERMS, desc=source_name):
        page_url = config["search_url"].format(query=quote_plus(term))
        pages = 0

        while page_url and pages < MAX_PAGES_PER_QUERY:
            result = await fetch_text(session, robots, page_url)
            if not result["text"]:
                source_col.insert_one({
                    "source": source_name,
                    "type": "search_page",
                    "query": term,
                    "url": page_url,
                    "blocked": result["blocked"],
                    "status": result["status"],
                    "scraped_at": now_utc(),
                })
                break

            source_col.update_one(
                {"source": source_name, "type": "search_page", "query": term, "url": page_url},
                {"$set": {"raw_html": result["text"], "scraped_at": now_utc()}},
                upsert=True,
            )

            links, soup = extract_result_links(result["text"], page_url, config["result_link_regex"])
            for link in links:
                page_result = await fetch_text(session, robots, link)
                if not page_result["text"]:
                    source_col.insert_one({
                        "source": source_name,
                        "type": "page_error",
                        "url": link,
                        "blocked": page_result["blocked"],
                        "status": page_result["status"],
                        "scraped_at": now_utc(),
                    })
                    continue
                source_col.update_one(
                    {"url": link},
                    {
                        "$set": {
                            "source": source_name,
                            "url": link,
                            "scraped_at": now_utc(),
                            "raw_html": page_result["text"],
                        }
                    },
                    upsert=True,
                )

            page_url = find_next_page_url(soup, page_url)
            pages += 1

    print(f"✅ END SOURCE : {source_name}")

async def scrape_drugbank_urls(session, robots, db):
    if not DRUGBANK_URLS:
        return
    print("\n🚀 START SOURCE : DRUGBANKS (manual URLs)")
    source_col = db["DRUGBANKS"]

    for url in tqdm(DRUGBANK_URLS, desc="DRUGBANKS"):
        page_result = await fetch_text(session, robots, url)
        if not page_result["text"]:
            source_col.insert_one({
                "source": "DRUGBANKS",
                "type": "page_error",
                "url": url,
                "blocked": page_result["blocked"],
                "status": page_result["status"],
                "scraped_at": now_utc(),
            })
            continue

        soup = BeautifulSoup(page_result["text"], "lxml")
        sections = extract_sections(soup)
        source_col.update_one(
            {"url": url},
            {
                "$set": {
                    "source": "DRUGBANKS",
                    "url": url,
                    "scraped_at": now_utc(),
                    "raw_html": page_result["text"],
                    "sections": sections,
                }
            },
            upsert=True,
        )

    print("✅ END SOURCE : DRUGBANKS")

async def scrape_drugbank_range(session, robots, db):
    if not DRUGBANK_RANGE_ENABLED:
        return
    print("\n🚀 START SOURCE : DRUGBANKS (range DB00001–DB09499)")
    source_col = db["DRUGBANKS"]

    for num in tqdm(range(DRUGBANK_START, DRUGBANK_END + 1), desc="DRUGBANKS RANGE"):
        url = DRUGBANK_URL_TEMPLATE.format(num=num)
        page_result = await fetch_text(session, robots, url)
        if not page_result["text"]:
            source_col.insert_one({
                "source": "DRUGBANKS",
                "type": "page_error",
                "url": url,
                "blocked": page_result["blocked"],
                "status": page_result["status"],
                "scraped_at": now_utc(),
            })
            continue

        soup = BeautifulSoup(page_result["text"], "lxml")
        sections = extract_sections(soup)
        source_col.update_one(
            {"url": url},
            {
                "$set": {
                    "source": "DRUGBANKS",
                    "url": url,
                    "scraped_at": now_utc(),
                    "raw_html": page_result["text"],
                    "sections": sections,
                }
            },
            upsert=True,
        )

    print("✅ END SOURCE : DRUGBANKS (range)")

# ================= PIPELINE =================

async def run():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    # Nettoyage collections
    print("🧹 Nettoyage des collections...")
    for name in ["ANSM", "VIDAL"]:  # ANSM et VIDAL fonctionnels
        count = db[name].count_documents({})
        if count > 0:
            db[name].delete_many({})
            print(f"  ✓ {name}: {count} documents supprimés")
    
    # Nettoyage des jobs ANSM en cours
    jobs_col = db["IMPORT_JOBS"]
    jobs_col.delete_many({"source": "ANSM_RCP"})
    print("  ✓ Jobs ANSM réinitialisés")

    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        robots = RobotsManager(session)

        print("\n" + "="*60)
        print("🚀 DÉMARRAGE DU SCRAPING - ANSM + VIDAL")
        print("="*60)
        print("✅ Sources actives:")
        print("   - ANSM (base de données publique française)")
        print("   - VIDAL (gammes et substances, navigation alphabétique)")
        print("⏸️  DrugBank: en attente validation compte")
        print("❌ THERIAQUE/HAS: nécessitent investigation supplémentaire")
        print("❌ BIOSINO: nécessite JavaScript/Selenium")
        print("="*60 + "\n")

        # ÉTAPE 1: Ingestion API/Dumps officielles (désactivées - 404)
        # print("📥 PHASE 1: Ingestion officielle (API/Dumps)")
        # print("-" * 60)
        # await ingest_official_source(session, db, "THERIAQUE", "THERIAQUE")
        # await ingest_official_source(session, db, "VIDAL", "VIDAL")
        # await ingest_official_source(session, db, "HAS", "HAS")
        # print("✅ Phase 1 terminée\n")

        # ÉTAPE 2: Scraping par recherche (désactivé - 404)
        # print("🔍 PHASE 2: Scraping par recherche")
        # print("-" * 60)
        # logged_in = await theriaque_login(session)
        # if logged_in:
        #     await scrape_search_source(session, robots, db, "THERIAQUE", requires_login=True)
        # for source in ["HAS", "VIDAL"]:
        #     await scrape_search_source(session, robots, db, source)
        # print("✅ Phase 2 terminée\n")

        # ÉTAPE 3: ANSM datasets + RCP pages (long processus)
        print("📊 SCRAPING ANSM (datasets + RCP pages)")
        print("-" * 60)
        print("⚠️  Cette phase peut prendre plusieurs heures...")
        print("📥 Datasets publics + 9804 pages RCP individuelles")
        await scrape_ansm_datasets(session, robots, db)
        print("✅ ANSM terminé\n")
        
        # ÉTAPE 4: VIDAL - navigation alphabétique
        print("📖 SCRAPING VIDAL (gammes + substances A-Z)")
        print("-" * 60)
        print("📚 Scraping de toutes les lettres (a-z)")
        print("   - Gammes (médicaments par nom commercial)")
        print("   - Substances actives")
        await scrape_vidal_alphabetic(session, robots, db)
        print("✅ VIDAL terminé\n")

        # DRUGBANK EN ATTENTE
        # await ingest_official_source(session, db, "DRUGBANKS", "DRUGBANKS")
        # await scrape_drugbank_range(session, robots, db)

    print("\n" + "="*60)
    print("🎯 SCRAPING TERMINÉ AVEC SUCCÈS")
    print("="*60)
    print("✅ Collections scrapées:")
    print("   - ANSM: Datasets + 9804 pages RCP")
    print("   - VIDAL: Gammes + Substances (A-Z)")
    print("⏸️  Sources désactivées temporairement:")
    print("   - THERIAQUE/HAS: nécessitent investigation supplémentaire")
    print("   - BIOSINO: nécessite Selenium")
    print("   - DrugBank: en attente validation compte")
    print("\n💡 Données disponibles dans MongoDB:")
    print("   - Collection ANSM: données françaises complètes")
    print("   - Collection VIDAL: médicaments et substances actives")

# ================= MAIN =================

if __name__ == "__main__":
    asyncio.run(run())

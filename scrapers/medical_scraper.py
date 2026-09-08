"""
Medical Data Scraper - Main scraping engine for medical websites
Handles EN/FR sources, structured & qualitative data extraction
"""

import asyncio
import aiohttp
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, asdict
import json

from .source_manager import SourceManager, SourceLanguage, SourceType

logger = logging.getLogger(__name__)

@dataclass
class ScrapedData:
    """Container for scraped medical data"""
    source_id: str
    source_name: str
    language: str
    data_type: str  # "structured" or "qualitative"
    category: str  # e.g., "medications", "case_studies"
    content: Dict[str, Any]
    extracted_at: datetime
    url: str
    quality_score: float  # 0-1
    has_references: bool = False
    is_anonymized: bool = False
    
    def to_dict(self):
        """Convert to dictionary for storage"""
        data = asdict(self)
        data['extracted_at'] = self.extracted_at.isoformat()
        return data

class MedicalScraper:
    """Main medical scraper with bilingual support"""
    
    def __init__(self):
        self.source_manager = SourceManager()
        self.session: Optional[aiohttp.ClientSession] = None
        self.results: List[ScrapedData] = []
        self.errors: List[Dict] = []
        
        # User agent to identify as research bot
        self.user_agent = (
            "Mozilla/5.0 (Research Bot) MedicalScraper/1.0 "
            "(+http://medicsearch.local/bot)"
        )
    
    async def initialize(self):
        """Initialize async session"""
        self.session = aiohttp.ClientSession(
            headers={"User-Agent": self.user_agent}
        )
    
    async def close(self):
        """Close async session"""
        if self.session:
            await self.session.close()
    
    async def scrape_medications(
        self,
        medication_name: Optional[str] = None,
        language: Optional[SourceLanguage] = None,
        include_interactions: bool = True,
        include_side_effects: bool = True,
    ) -> List[ScrapedData]:
        """Scrape medication information from multiple sources"""
        
        try:
            await self.initialize()
            
            # Get priority sources
            sources = self.source_manager.get_priority_sources(
                language=language,
                category="medications"
            )
            
            tasks = []
            for source in sources:
                task = self._scrape_medication_source(
                    source,
                    medication_name,
                    include_interactions,
                    include_side_effects
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, ScrapedData):
                    self.results.append(result)
                elif isinstance(result, Exception):
                    self.errors.append({
                        "error": str(result),
                        "timestamp": datetime.now().isoformat()
                    })
            
            return [r for r in self.results if isinstance(r, ScrapedData)]
            
        finally:
            await self.close()
    
    async def scrape_case_studies(
        self,
        medication_name: Optional[str] = None,
        condition: Optional[str] = None,
        language: Optional[SourceLanguage] = None,
    ) -> List[ScrapedData]:
        """Scrape clinical case studies and observations"""
        
        try:
            await self.initialize()
            
            sources = self.source_manager.get_priority_sources(
                language=language,
                source_type=SourceType.CASE_STUDY
            )
            
            # Add clinical journals
            journal_sources = self.source_manager.get_priority_sources(
                language=language,
                source_type=SourceType.CLINICAL_JOURNAL
            )
            sources.extend(journal_sources)
            
            tasks = []
            for source in sources:
                task = self._scrape_case_study_source(
                    source,
                    medication_name,
                    condition
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, ScrapedData):
                    self.results.append(result)
                elif isinstance(result, Exception):
                    logger.error(f"Error scraping case studies: {result}")
            
            return [r for r in self.results if isinstance(r, ScrapedData)]
            
        finally:
            await self.close()
    
    async def scrape_regulatory_updates(
        self,
        language: Optional[SourceLanguage] = None,
    ) -> List[ScrapedData]:
        """Scrape regulatory updates and safety alerts"""
        
        try:
            await self.initialize()
            
            sources = self.source_manager.get_priority_sources(
                language=language,
                source_type=SourceType.REGULATORY,
                max_priority=1  # Only highest priority regulatory sources
            )
            
            tasks = [self._scrape_regulatory_source(source) for source in sources]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, ScrapedData):
                    self.results.append(result)
            
            return [r for r in self.results if isinstance(r, ScrapedData)]
            
        finally:
            await self.close()
    
    async def _scrape_medication_source(
        self,
        source,
        medication_name: Optional[str],
        include_interactions: bool,
        include_side_effects: bool
    ) -> ScrapedData:
        """Scrape medication data from specific source"""
        
        try:
            # API-specific logic
            if source.id == "fda":
                return await self._scrape_fda(medication_name)
            elif source.id == "pubmed":
                return await self._scrape_pubmed(medication_name)
            elif source.id == "vidal":
                return await self._scrape_vidal(medication_name)
            elif source.id == "ansm":
                return await self._scrape_ansm(medication_name)
            elif source.id == "drugs_com":
                return await self._scrape_drugs_com(medication_name)
            else:
                # Generic scraping for other sources
                return await self._scrape_generic(source, medication_name)
                
        except Exception as e:
            logger.error(f"Error scraping {source.id}: {e}")
            raise
    
    async def _scrape_case_study_source(
        self,
        source,
        medication_name: Optional[str],
        condition: Optional[str]
    ) -> ScrapedData:
        """Scrape case study data from source"""
        
        try:
            if source.id == "bmj_case_reports":
                return await self._scrape_bmj_cases(medication_name, condition)
            elif source.id == "nejm":
                return await self._scrape_nejm_cases(medication_name, condition)
            elif source.id == "prescrire":
                return await self._scrape_prescrire_cases(medication_name, condition)
            else:
                return await self._scrape_generic(source, medication_name)
                
        except Exception as e:
            logger.error(f"Error scraping case studies from {source.id}: {e}")
            raise
    
    async def _scrape_regulatory_source(self, source) -> ScrapedData:
        """Scrape regulatory updates from source"""
        
        try:
            if source.id == "fda":
                return await self._scrape_fda_alerts()
            elif source.id == "ansm":
                return await self._scrape_ansm_alerts()
            elif source.id == "ema":
                return await self._scrape_ema_alerts()
            else:
                return await self._scrape_generic(source, "alerts")
                
        except Exception as e:
            logger.error(f"Error scraping regulatory updates from {source.id}: {e}")
            raise
    
    # Placeholder implementations for API-specific scrapers
    async def _scrape_fda(self, medication_name: Optional[str]) -> ScrapedData:
        """Scrape FDA API"""
        source = self.source_manager.get_source("fda")
        
        # FDA OpenData API example
        api_url = "https://api.fda.gov/drug/event.json"
        
        if self.session:
            try:
                async with self.session.get(
                    api_url,
                    params={"search": f"patient.drug.medicinalproduct:\"{medication_name}\"", "limit": 10}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return ScrapedData(
                            source_id=source.id,
                            source_name=source.name,
                            language="en",
                            data_type="structured",
                            category="medications",
                            content=data,
                            extracted_at=datetime.now(),
                            url=api_url,
                            quality_score=0.85
                        )
            except Exception as e:
                logger.error(f"FDA scraping error: {e}")
        
        raise Exception(f"Failed to scrape {source.name}")
    
    async def _scrape_pubmed(self, medication_name: Optional[str]) -> ScrapedData:
        """Scrape PubMed API"""
        source = self.source_manager.get_source("pubmed")
        
        # PubMed E-utilities API
        api_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        
        if self.session:
            try:
                async with self.session.get(
                    api_url,
                    params={
                        "db": "pubmed",
                        "term": medication_name,
                        "rettype": "json",
                        "tool": "MedicalScraper"
                    }
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return ScrapedData(
                            source_id=source.id,
                            source_name=source.name,
                            language="en",
                            data_type="qualitative",
                            category="research",
                            content=data,
                            extracted_at=datetime.now(),
                            url=api_url,
                            quality_score=0.90
                        )
            except Exception as e:
                logger.error(f"PubMed scraping error: {e}")
        
        raise Exception(f"Failed to scrape {source.name}")
    
    async def _scrape_vidal(self, medication_name: Optional[str]) -> ScrapedData:
        """Scrape VIDAL database"""
        source = self.source_manager.get_source("vidal")
        
        # VIDAL typically requires web scraping or API key
        # This is a placeholder for actual implementation
        
        return ScrapedData(
            source_id=source.id,
            source_name=source.name,
            language="fr",
            data_type="structured",
            category="medications",
            content={
                "placeholder": "VIDAL scraping requires authentication or special access"
            },
            extracted_at=datetime.now(),
            url=source.url,
            quality_score=0.0
        )
    
    async def _scrape_ansm(self, medication_name: Optional[str]) -> ScrapedData:
        """Scrape ANSM database"""
        source = self.source_manager.get_source("ansm")
        
        return ScrapedData(
            source_id=source.id,
            source_name=source.name,
            language="fr",
            data_type="structured",
            category="medications",
            content={
                "placeholder": "ANSM scraping requires specific implementation"
            },
            extracted_at=datetime.now(),
            url=source.url,
            quality_score=0.0
        )
    
    async def _scrape_drugs_com(self, medication_name: Optional[str]) -> ScrapedData:
        """Scrape Drugs.com"""
        source = self.source_manager.get_source("drugs_com")
        
        return ScrapedData(
            source_id=source.id,
            source_name=source.name,
            language="en",
            data_type="structured",
            category="medications",
            content={
                "placeholder": "Drugs.com scraping requires web scraping implementation"
            },
            extracted_at=datetime.now(),
            url=source.url,
            quality_score=0.0
        )
    
    async def _scrape_bmj_cases(self, medication_name: Optional[str], condition: Optional[str]) -> ScrapedData:
        """Scrape BMJ Case Reports"""
        source = self.source_manager.get_source("bmj_case_reports")
        
        return ScrapedData(
            source_id=source.id,
            source_name=source.name,
            language="en",
            data_type="qualitative",
            category="case_studies",
            content={"placeholder": "BMJ case scraping implementation"},
            extracted_at=datetime.now(),
            url=source.url,
            quality_score=0.85,
            is_anonymized=True
        )
    
    async def _scrape_nejm_cases(self, medication_name: Optional[str], condition: Optional[str]) -> ScrapedData:
        """Scrape NEJM Case Records"""
        source = self.source_manager.get_source("nejm")
        
        return ScrapedData(
            source_id=source.id,
            source_name=source.name,
            language="en",
            data_type="qualitative",
            category="case_studies",
            content={"placeholder": "NEJM case scraping implementation"},
            extracted_at=datetime.now(),
            url=source.url,
            quality_score=0.90,
            is_anonymized=True
        )
    
    async def _scrape_prescrire_cases(self, medication_name: Optional[str], condition: Optional[str]) -> ScrapedData:
        """Scrape Revue Prescrire"""
        source = self.source_manager.get_source("prescrire")
        
        return ScrapedData(
            source_id=source.id,
            source_name=source.name,
            language="fr",
            data_type="qualitative",
            category="case_studies",
            content={"placeholder": "Prescrire case scraping implementation"},
            extracted_at=datetime.now(),
            url=source.url,
            quality_score=0.88,
            is_anonymized=True
        )
    
    async def _scrape_fda_alerts(self) -> ScrapedData:
        """Scrape FDA regulatory alerts"""
        source = self.source_manager.get_source("fda")
        
        return ScrapedData(
            source_id=source.id,
            source_name=source.name,
            language="en",
            data_type="structured",
            category="safety_alerts",
            content={"alerts": []},
            extracted_at=datetime.now(),
            url=source.url,
            quality_score=0.95
        )
    
    async def _scrape_ansm_alerts(self) -> ScrapedData:
        """Scrape ANSM regulatory alerts"""
        source = self.source_manager.get_source("ansm")
        
        return ScrapedData(
            source_id=source.id,
            source_name=source.name,
            language="fr",
            data_type="structured",
            category="safety_alerts",
            content={"alerts": []},
            extracted_at=datetime.now(),
            url=source.url,
            quality_score=0.95
        )
    
    async def _scrape_ema_alerts(self) -> ScrapedData:
        """Scrape EMA regulatory alerts"""
        source = self.source_manager.get_source("ema")
        
        return ScrapedData(
            source_id=source.id,
            source_name=source.name,
            language="bi",
            data_type="structured",
            category="safety_alerts",
            content={"alerts": []},
            extracted_at=datetime.now(),
            url=source.url,
            quality_score=0.95
        )
    
    async def _scrape_generic(self, source, query: str) -> ScrapedData:
        """Generic web scraping for other sources"""
        
        return ScrapedData(
            source_id=source.id,
            source_name=source.name,
            language=source.language.value,
            data_type="unstructured",
            category="general",
            content={"query": query},
            extracted_at=datetime.now(),
            url=source.url,
            quality_score=0.5
        )
    
    def export_results(self, format: str = "json") -> str:
        """Export scraping results in various formats"""
        if format == "json":
            return json.dumps([r.to_dict() for r in self.results], indent=2, default=str)
        elif format == "csv":
            import csv
            import io
            output = io.StringIO()
            if self.results:
                writer = csv.DictWriter(output, fieldnames=self.results[0].to_dict().keys())
                writer.writeheader()
                for result in self.results:
                    writer.writerow(result.to_dict())
            return output.getvalue()
        else:
            raise ValueError(f"Unsupported format: {format}")

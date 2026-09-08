"""
Medical Source Manager - Manages authorized medical data sources
Bilingual (EN/FR) source configuration and prioritization
"""

from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass

class SourceLanguage(Enum):
    ENGLISH = "en"
    FRENCH = "fr"
    BILINGUAL = "bi"

class SourceType(Enum):
    REGULATORY = "regulatory"  # FDA, ANSM, EMA
    MEDICAL_DATABASE = "database"  # PubMed, Vidal
    CLINICAL_JOURNAL = "journal"  # BMJ, NEJM, Prescrire
    PROFESSIONAL_FORUM = "forum"  # Medscape, Figure 1
    CASE_STUDY = "case_study"  # Case reports
    HEALTHCARE_PORTAL = "portal"  # WebMD, Mayo Clinic

@dataclass
class MedicalSource:
    """Represents a medical information source"""
    id: str
    name: str
    url: str
    language: SourceLanguage
    source_type: SourceType
    priority: int  # 1 (highest) to 5 (lowest)
    requires_auth: bool = False
    rate_limit: int = 100  # requests per hour
    supports_search: bool = True
    data_categories: List[str] = None
    
    def __post_init__(self):
        if self.data_categories is None:
            self.data_categories = []

class SourceManager:
    """Manages and prioritizes medical data sources"""
    
    # ENGLISH SOURCES
    SOURCES_EN = {
        "fda": MedicalSource(
            id="fda",
            name="FDA - Drugs@FDA",
            url="https://www.fda.gov/drugs",
            language=SourceLanguage.ENGLISH,
            source_type=SourceType.REGULATORY,
            priority=1,
            data_categories=["medications", "side_effects", "interactions", "regulatory_status"]
        ),
        "pubmed": MedicalSource(
            id="pubmed",
            name="PubMed",
            url="https://pubmed.ncbi.nlm.nih.gov/",
            language=SourceLanguage.ENGLISH,
            source_type=SourceType.MEDICAL_DATABASE,
            priority=1,
            data_categories=["research", "clinical_trials", "drug_interactions", "efficacy"]
        ),
        "mayo_clinic": MedicalSource(
            id="mayo_clinic",
            name="Mayo Clinic",
            url="https://www.mayoclinic.org/",
            language=SourceLanguage.ENGLISH,
            source_type=SourceType.HEALTHCARE_PORTAL,
            priority=2,
            data_categories=["medications", "side_effects", "patient_education"]
        ),
        "drugs_com": MedicalSource(
            id="drugs_com",
            name="Drugs.com",
            url="https://www.drugs.com/",
            language=SourceLanguage.ENGLISH,
            source_type=SourceType.MEDICAL_DATABASE,
            priority=2,
            data_categories=["medications", "interactions", "side_effects", "dosages"]
        ),
        "rxlist": MedicalSource(
            id="rxlist",
            name="RxList",
            url="https://www.rxlist.com/",
            language=SourceLanguage.ENGLISH,
            source_type=SourceType.HEALTHCARE_PORTAL,
            priority=2,
            data_categories=["medications", "side_effects", "interactions"]
        ),
        "webmd": MedicalSource(
            id="webmd",
            name="WebMD",
            url="https://www.webmd.com/",
            language=SourceLanguage.ENGLISH,
            source_type=SourceType.HEALTHCARE_PORTAL,
            priority=2,
            data_categories=["medications", "conditions", "side_effects"]
        ),
        "bmj_case_reports": MedicalSource(
            id="bmj_case_reports",
            name="BMJ Case Reports",
            url="https://casereports.bmj.com/",
            language=SourceLanguage.ENGLISH,
            source_type=SourceType.CLINICAL_JOURNAL,
            priority=1,
            data_categories=["case_studies", "clinical_observations", "adverse_events"]
        ),
        "nejm": MedicalSource(
            id="nejm",
            name="NEJM Case Records",
            url="https://www.nejm.org/",
            language=SourceLanguage.ENGLISH,
            source_type=SourceType.CLINICAL_JOURNAL,
            priority=1,
            data_categories=["case_studies", "research", "clinical_trials"]
        ),
        "medscape": MedicalSource(
            id="medscape",
            name="Medscape",
            url="https://www.medscape.com/",
            language=SourceLanguage.ENGLISH,
            source_type=SourceType.PROFESSIONAL_FORUM,
            priority=2,
            requires_auth=True,
            data_categories=["clinical_insights", "professional_discussions", "cases"]
        ),
    }
    
    # FRENCH SOURCES
    SOURCES_FR = {
        "ansm": MedicalSource(
            id="ansm",
            name="ANSM - Agence Nationale de Sécurité du Médicament",
            url="https://ansm.sante.fr/",
            language=SourceLanguage.FRENCH,
            source_type=SourceType.REGULATORY,
            priority=1,
            data_categories=["medications", "safety_alerts", "regulatory_status", "interactions"]
        ),
        "vidal": MedicalSource(
            id="vidal",
            name="VIDAL",
            url="https://www.vidal.fr/",
            language=SourceLanguage.FRENCH,
            source_type=SourceType.MEDICAL_DATABASE,
            priority=1,
            data_categories=["medications", "interactions", "side_effects", "dosages", "therapeutic_class"]
        ),
        "eureka_sante": MedicalSource(
            id="eureka_sante",
            name="Eurekasanté",
            url="https://eurekasante.vidal.fr/",
            language=SourceLanguage.FRENCH,
            source_type=SourceType.HEALTHCARE_PORTAL,
            priority=2,
            data_categories=["medications", "health_conditions", "patient_education"]
        ),
        "prescrire": MedicalSource(
            id="prescrire",
            name="Revue Prescrire",
            url="https://www.prescrire.org/",
            language=SourceLanguage.FRENCH,
            source_type=SourceType.CLINICAL_JOURNAL,
            priority=1,
            requires_auth=True,
            data_categories=["drug_evaluations", "safety_reviews", "therapeutic_value"]
        ),
        "health_canada_fr": MedicalSource(
            id="health_canada_fr",
            name="Health Canada - French",
            url="https://www.canada.ca/fr/sante",
            language=SourceLanguage.FRENCH,
            source_type=SourceType.REGULATORY,
            priority=1,
            data_categories=["medications", "safety", "approvals"]
        ),
    }
    
    # BILINGUAL SOURCES
    SOURCES_BILINGUAL = {
        "who": MedicalSource(
            id="who",
            name="WHO - World Health Organization",
            url="https://www.who.int/",
            language=SourceLanguage.BILINGUAL,
            source_type=SourceType.REGULATORY,
            priority=1,
            data_categories=["drugs", "classifications", "guidelines"]
        ),
        "ema": MedicalSource(
            id="ema",
            name="European Medicines Agency",
            url="https://www.ema.europa.eu/",
            language=SourceLanguage.BILINGUAL,
            source_type=SourceType.REGULATORY,
            priority=1,
            data_categories=["medications", "approvals", "safety_updates"]
        ),
        "researchgate": MedicalSource(
            id="researchgate",
            name="ResearchGate",
            url="https://www.researchgate.net/",
            language=SourceLanguage.BILINGUAL,
            source_type=SourceType.PROFESSIONAL_FORUM,
            priority=2,
            data_categories=["research", "discussions", "case_studies"]
        ),
    }
    
    def __init__(self):
        self.all_sources: Dict[str, MedicalSource] = {
            **self.SOURCES_EN,
            **self.SOURCES_FR,
            **self.SOURCES_BILINGUAL
        }
    
    def get_priority_sources(
        self,
        language: Optional[SourceLanguage] = None,
        source_type: Optional[SourceType] = None,
        category: Optional[str] = None,
        max_priority: int = 3
    ) -> List[MedicalSource]:
        """Get sources filtered and sorted by priority"""
        sources = list(self.all_sources.values())
        
        # Filter by language
        if language:
            sources = [s for s in sources if s.language in (language, SourceLanguage.BILINGUAL)]
        
        # Filter by type
        if source_type:
            sources = [s for s in sources if s.source_type == source_type]
        
        # Filter by category
        if category:
            sources = [s for s in sources if category in s.data_categories]
        
        # Filter by priority
        sources = [s for s in sources if s.priority <= max_priority]
        
        # Sort by priority
        return sorted(sources, key=lambda s: s.priority)
    
    def get_bilingual_sources(self, category: Optional[str] = None) -> tuple[List[MedicalSource], List[MedicalSource]]:
        """Get paired EN/FR sources for the same category"""
        en_sources = self.get_priority_sources(SourceLanguage.ENGLISH, category=category)
        fr_sources = self.get_priority_sources(SourceLanguage.FRENCH, category=category)
        return en_sources, fr_sources
    
    def get_source(self, source_id: str) -> Optional[MedicalSource]:
        """Get a specific source by ID"""
        return self.all_sources.get(source_id)


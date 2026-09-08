"""
Medical Data Processor - Validates, structures, and enriches scraped medical data
Handles translation, anonymization, and storage
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass
import hashlib

logger = logging.getLogger(__name__)

@dataclass
class MedicationInfo:
    """Structured medication information"""
    name: str
    generic_name: Optional[str] = None
    brand_names: List[str] = None
    dosages: List[str] = None
    side_effects: List[str] = None
    interactions: List[str] = None
    indications: List[str] = None
    contraindications: List[str] = None
    therapeutic_class: Optional[str] = None
    atc_code: Optional[str] = None
    regulatory_status: Optional[str] = None
    sources: List[Dict] = None
    language: str = "en"
    
    def __post_init__(self):
        if self.brand_names is None:
            self.brand_names = []
        if self.dosages is None:
            self.dosages = []
        if self.side_effects is None:
            self.side_effects = []
        if self.interactions is None:
            self.interactions = []
        if self.indications is None:
            self.indications = []
        if self.contraindications is None:
            self.contraindications = []
        if self.sources is None:
            self.sources = []

@dataclass
class CaseStudy:
    """Structured clinical case study"""
    case_id: str  # Anonymized identifier
    medication_names: List[str]
    condition: Optional[str] = None
    patient_demographics: Optional[str] = None  # Anonymized (e.g., "40-year-old female")
    clinical_outcome: Optional[str] = None
    adverse_events: List[str] = None
    clinical_notes: Optional[str] = None
    source: str = ""
    source_url: str = ""
    published_date: Optional[str] = None
    language: str = "en"
    is_anonymized: bool = True
    
    def __post_init__(self):
        if self.adverse_events is None:
            self.adverse_events = []

class DataProcessor:
    """Process and validate scraped medical data"""
    
    def __init__(self):
        self.processed_data: List[Dict] = []
        self.validation_errors: List[Dict] = []
    
    def process_medication_data(
        self,
        raw_data: Dict[str, Any],
        source_id: str,
        language: str = "en"
    ) -> Optional[MedicationInfo]:
        """Process and validate medication data from scraping results"""
        
        try:
            medication = MedicationInfo(
                name=raw_data.get("name", ""),
                generic_name=raw_data.get("generic_name"),
                brand_names=raw_data.get("brand_names", []),
                dosages=raw_data.get("dosages", []),
                side_effects=raw_data.get("side_effects", []),
                interactions=raw_data.get("interactions", []),
                indications=raw_data.get("indications", []),
                contraindications=raw_data.get("contraindications", []),
                therapeutic_class=raw_data.get("therapeutic_class"),
                atc_code=raw_data.get("atc_code"),
                regulatory_status=raw_data.get("regulatory_status"),
                language=language
            )
            
            # Validate medication
            if not medication.name:
                self.validation_errors.append({
                    "source": source_id,
                    "error": "Missing medication name",
                    "timestamp": datetime.now().isoformat()
                })
                return None
            
            # Add source attribution
            medication.sources.append({
                "source_id": source_id,
                "added_at": datetime.now().isoformat()
            })
            
            return medication
            
        except Exception as e:
            logger.error(f"Error processing medication data: {e}")
            self.validation_errors.append({
                "source": source_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            return None
    
    def process_case_study(
        self,
        raw_data: Dict[str, Any],
        source_id: str,
        language: str = "en"
    ) -> Optional[CaseStudy]:
        """Process and validate clinical case study"""
        
        try:
            # Generate anonymized case ID
            case_hash = hashlib.sha256(
                f"{source_id}_{raw_data.get('title', '')}_{datetime.now().isoformat()}".encode()
            ).hexdigest()[:12]
            
            case = CaseStudy(
                case_id=f"CASE_{case_hash}",
                medication_names=raw_data.get("medications", []),
                condition=raw_data.get("condition"),
                patient_demographics=raw_data.get("patient_demographics"),
                clinical_outcome=raw_data.get("outcome"),
                adverse_events=raw_data.get("adverse_events", []),
                clinical_notes=raw_data.get("notes"),
                source=source_id,
                source_url=raw_data.get("source_url", ""),
                published_date=raw_data.get("published_date"),
                language=language,
                is_anonymized=True
            )
            
            # Validate case
            if not case.medication_names:
                self.validation_errors.append({
                    "source": source_id,
                    "error": "Case study missing medication information",
                    "timestamp": datetime.now().isoformat()
                })
                return None
            
            return case
            
        except Exception as e:
            logger.error(f"Error processing case study: {e}")
            self.validation_errors.append({
                "source": source_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            return None
    
    def validate_medication_interactions(
        self,
        medication1: str,
        medication2: str,
        interaction_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate and score medication interactions"""
        
        validated = {
            "drug_1": medication1,
            "drug_2": medication2,
            "interaction_type": interaction_data.get("type", "unknown"),
            "severity": interaction_data.get("severity", "unknown"),  # minor, moderate, serious
            "mechanism": interaction_data.get("mechanism", ""),
            "management": interaction_data.get("management", ""),
            "evidence_score": 0.0,
            "validated": False
        }
        
        # Score based on evidence
        severity_weights = {"minor": 0.3, "moderate": 0.6, "serious": 1.0}
        if validated["severity"] in severity_weights:
            validated["evidence_score"] = severity_weights[validated["severity"]]
        
        # Mark as validated if has mechanism and management
        if validated["mechanism"] and validated["management"]:
            validated["validated"] = True
            validated["evidence_score"] = min(1.0, validated["evidence_score"] + 0.2)
        
        return validated
    
    def enrich_with_translation(
        self,
        data: Dict[str, Any],
        target_language: str,
        translator_func=None
    ) -> Dict[str, Any]:
        """Enrich data with translations"""
        
        # If translator function provided, use it
        if translator_func:
            try:
                translated = translator_func(data, target_language)
                data['translations'] = translated
            except Exception as e:
                logger.warning(f"Translation failed: {e}")
        else:
            logger.warning(f"No translator provided for {target_language}")
        
        return data
    
    def anonymize_case_study(self, case: CaseStudy) -> CaseStudy:
        """Ensure case study is properly anonymized"""
        
        # Remove specific dates
        case.published_date = self._anonymize_date(case.published_date)
        
        # Generalize patient demographics
        if case.patient_demographics:
            case.patient_demographics = self._generalize_demographics(case.patient_demographics)
        
        case.is_anonymized = True
        return case
    
    def _anonymize_date(self, date_str: Optional[str]) -> Optional[str]:
        """Anonymize specific dates to month/year"""
        if not date_str:
            return None
        try:
            dt = datetime.fromisoformat(date_str)
            return dt.strftime("%Y-%m")  # Return only month/year
        except:
            return None
    
    def _generalize_demographics(self, demographics: str) -> str:
        """Generalize patient demographics"""
        # Replace specific ages with ranges
        import re
        demographics = re.sub(r'\b\d{2}\b(?=-year-old)', 
                            lambda m: self._age_range(int(m.group())), 
                            demographics)
        return demographics
    
    def _age_range(self, age: int) -> str:
        """Convert specific age to range"""
        ranges = {
            (0, 18): "pediatric",
            (18, 35): "young adult",
            (35, 65): "middle-aged",
            (65, 120): "elderly"
        }
        for (min_age, max_age), label in ranges.items():
            if min_age <= age < max_age:
                return label
        return "adult"
    
    def aggregate_by_source(self, data_list: List[Dict]) -> Dict[str, List]:
        """Aggregate processed data by source"""
        aggregated = {}
        for data in data_list:
            source = data.get("source_id", "unknown")
            if source not in aggregated:
                aggregated[source] = []
            aggregated[source].append(data)
        return aggregated
    
    def generate_quality_report(self) -> Dict[str, Any]:
        """Generate data quality report"""
        
        return {
            "total_records_processed": len(self.processed_data),
            "validation_errors": len(self.validation_errors),
            "error_details": self.validation_errors[-10:],  # Last 10 errors
            "timestamp": datetime.now().isoformat(),
            "success_rate": (
                (len(self.processed_data) / (len(self.processed_data) + len(self.validation_errors)) * 100)
                if (len(self.processed_data) + len(self.validation_errors)) > 0
                else 0
            )
        }


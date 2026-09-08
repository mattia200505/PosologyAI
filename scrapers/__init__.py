"""
Medical Information Scraper Package
Bilingual (EN/FR) medical data extraction and analysis
"""

from .medical_scraper import MedicalScraper
from .source_manager import SourceManager
from .data_processor import DataProcessor

__all__ = ["MedicalScraper", "SourceManager", "DataProcessor"]

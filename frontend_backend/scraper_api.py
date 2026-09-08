"""
Medical Scraper API for Retool Integration
REST API endpoints for triggering and managing scraping jobs
"""

from flask import Blueprint, request, jsonify
from flask_cors import CORS
from typing import Dict, Any
from functools import wraps
import logging
from datetime import datetime
import asyncio
import uuid

import models

from scrapers.medical_scraper import MedicalScraper
from scrapers.source_manager import SourceLanguage, SourceType
from scrapers.data_processor import DataProcessor

logger = logging.getLogger(__name__)

# Create blueprint
scraper_bp = Blueprint('scraper', __name__, url_prefix='/api/scraper')
CORS(scraper_bp)


def admin_required(view):
    """
    Restreint un point d'entrée aux administrateurs.

    La règle d'autorisation est celle de `users.role_required` : identité
    portée par la session signée, rôle relu en base. La réponse, elle, diffère
    volontairement : `role_required` redirige vers l'accueil avec un message
    flash, ce qui convient à une page HTML mais laisse un client d'API devant
    une 302 et du HTML. On rend donc un JSON et le code de statut adéquat,
    401 quand personne n'est authentifié, 403 quand le rôle est insuffisant.

    Ces routes étaient jusqu'ici ouvertes : elles ne s'enregistraient pas,
    faute d'`aiohttp`, et le défaut est resté invisible derrière
    l'avertissement au démarrage.
    """
    @wraps(view)
    def garde(*args, **kwargs):
        from users import current_role, current_user_id

        if not current_user_id():
            return jsonify({'error': 'authentication required'}), 401
        role = current_role()
        if role is None or role < models.User.ROLE_ADMIN:
            return jsonify({'error': 'administrator role required'}), 403
        return view(*args, **kwargs)
    return garde


# In-memory job storage (would use Redis/MongoDB in production)
active_jobs = {}
completed_jobs = {}

class ScraperJob:
    """Manages a single scraping job"""
    
    def __init__(self, job_id: str, job_type: str, parameters: Dict):
        self.job_id = job_id
        self.job_type = job_type
        self.parameters = parameters
        self.status = "pending"  # pending, running, completed, failed
        self.progress = 0
        self.results = []
        self.errors = []
        self.created_at = datetime.now()
        self.started_at = None
        self.completed_at = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status,
            "progress": self.progress,
            "results_count": len(self.results),
            "error_count": len(self.errors),
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None
        }

@scraper_bp.route('/health', methods=['GET'])
@admin_required
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_jobs": len(active_jobs),
        "completed_jobs": len(completed_jobs)
    })

@scraper_bp.route('/sources', methods=['GET'])
@admin_required
def get_available_sources():
    """Get available medical sources"""
    from scrapers.source_manager import SourceManager
    
    manager = SourceManager()
    language = request.args.get('language')
    source_type = request.args.get('type')
    
    # Parse query parameters
    lang_enum = None
    if language == "en":
        lang_enum = SourceLanguage.ENGLISH
    elif language == "fr":
        lang_enum = SourceLanguage.FRENCH
    
    type_enum = None
    if source_type:
        try:
            type_enum = SourceType[source_type.upper()]
        except KeyError:
            pass
    
    sources = manager.get_priority_sources(
        language=lang_enum,
        source_type=type_enum
    )
    
    return jsonify({
        "sources": [
            {
                "id": s.id,
                "name": s.name,
                "url": s.url,
                "language": s.language.value,
                "type": s.source_type.value,
                "priority": s.priority,
                "categories": s.data_categories
            }
            for s in sources
        ]
    })

@scraper_bp.route('/medications/scrape', methods=['POST'])
@admin_required
def scrape_medications():
    """Trigger medication scraping job"""
    
    data = request.get_json()
    medication_name = data.get('medication_name')
    language = data.get('language', 'en')
    
    if not medication_name:
        return jsonify({"error": "Missing medication_name parameter"}), 400
    
    job_id = str(uuid.uuid4())
    job = ScraperJob(
        job_id=job_id,
        job_type="medications",
        parameters={
            "medication_name": medication_name,
            "language": language
        }
    )
    
    active_jobs[job_id] = job
    
    # Run scraping in background
    asyncio.create_task(_run_medication_scrape(job_id, medication_name, language))
    
    return jsonify({
        "job_id": job_id,
        "status": "pending",
        "message": f"Scraping job created for {medication_name}"
    }), 202

@scraper_bp.route('/case-studies/scrape', methods=['POST'])
@admin_required
def scrape_case_studies():
    """Trigger case study scraping job"""
    
    data = request.get_json()
    medication_name = data.get('medication_name')
    condition = data.get('condition')
    language = data.get('language', 'en')
    
    job_id = str(uuid.uuid4())
    job = ScraperJob(
        job_id=job_id,
        job_type="case_studies",
        parameters={
            "medication_name": medication_name,
            "condition": condition,
            "language": language
        }
    )
    
    active_jobs[job_id] = job
    
    asyncio.create_task(_run_case_study_scrape(job_id, medication_name, condition, language))
    
    return jsonify({
        "job_id": job_id,
        "status": "pending",
        "message": "Case study scraping job created"
    }), 202

@scraper_bp.route('/regulatory/alerts', methods=['GET'])
@admin_required
def scrape_regulatory_alerts():
    """Get regulatory alerts and updates"""
    
    language = request.args.get('language', 'en')
    
    job_id = str(uuid.uuid4())
    job = ScraperJob(
        job_id=job_id,
        job_type="regulatory_alerts",
        parameters={"language": language}
    )
    
    active_jobs[job_id] = job
    
    asyncio.create_task(_run_regulatory_scrape(job_id, language))
    
    return jsonify({
        "job_id": job_id,
        "status": "pending"
    }), 202

@scraper_bp.route('/jobs/<job_id>', methods=['GET'])
@admin_required
def get_job_status(job_id):
    """Get status of a scraping job"""
    
    # Check active jobs first
    if job_id in active_jobs:
        job = active_jobs[job_id]
        return jsonify(job.to_dict())
    
    # Check completed jobs
    if job_id in completed_jobs:
        job = completed_jobs[job_id]
        return jsonify({
            **job.to_dict(),
            "results": job.results[:100]  # Return last 100 results
        })
    
    return jsonify({"error": "Job not found"}), 404

@scraper_bp.route('/jobs/<job_id>/results', methods=['GET'])
@admin_required
def get_job_results(job_id):
    """Get full results of a completed job"""
    
    if job_id not in completed_jobs:
        return jsonify({"error": "Job not found or still processing"}), 404
    
    job = completed_jobs[job_id]
    
    if job.status != "completed":
        return jsonify({"error": f"Job status is {job.status}"}), 400
    
    return jsonify({
        "job_id": job_id,
        "status": job.status,
        "results_count": len(job.results),
        "results": job.results,
        "errors": job.errors,
        "completed_at": job.completed_at.isoformat()
    })

@scraper_bp.route('/jobs/active', methods=['GET'])
@admin_required
def list_active_jobs():
    """List all active scraping jobs"""
    
    return jsonify({
        "active_jobs": [
            {
                "job_id": job_id,
                **job.to_dict()
            }
            for job_id, job in active_jobs.items()
        ]
    })

@scraper_bp.route('/jobs/history', methods=['GET'])
@admin_required
def job_history():
    """Get history of completed jobs"""
    
    limit = int(request.args.get('limit', 50))
    
    return jsonify({
        "completed_jobs": [
            job.to_dict()
            for job in list(completed_jobs.values())[-limit:]
        ]
    })

@scraper_bp.route('/validate-interactions', methods=['POST'])
@admin_required
def validate_interactions():
    """Validate medication interactions"""
    
    data = request.get_json()
    drug1 = data.get('drug_1')
    drug2 = data.get('drug_2')
    interaction_data = data.get('interaction', {})
    
    if not drug1 or not drug2:
        return jsonify({"error": "Missing drug_1 or drug_2"}), 400
    
    processor = DataProcessor()
    validated = processor.validate_medication_interactions(
        drug1, drug2, interaction_data
    )
    
    return jsonify(validated)

# Background task functions

async def _run_medication_scrape(job_id: str, medication_name: str, language: str):
    """Background task for medication scraping"""
    
    job = active_jobs[job_id]
    job.status = "running"
    job.started_at = datetime.now()
    
    try:
        scraper = MedicalScraper()
        
        # Parse language
        lang_enum = SourceLanguage.ENGLISH if language == "en" else SourceLanguage.FRENCH
        
        # Run scraping
        results = await scraper.scrape_medications(
            medication_name=medication_name,
            language=lang_enum
        )
        
        # Process results
        processor = DataProcessor()
        job.results = [r.to_dict() for r in results]
        
        job.status = "completed"
        job.completed_at = datetime.now()
        job.progress = 100
        
    except Exception as e:
        logger.error(f"Scraping job {job_id} failed: {e}")
        job.status = "failed"
        job.errors.append(str(e))
        job.completed_at = datetime.now()
    
    finally:
        # Move to completed
        active_jobs.pop(job_id, None)
        completed_jobs[job_id] = job

async def _run_case_study_scrape(job_id: str, medication_name: str, condition: str, language: str):
    """Background task for case study scraping"""
    
    job = active_jobs[job_id]
    job.status = "running"
    job.started_at = datetime.now()
    
    try:
        scraper = MedicalScraper()
        
        lang_enum = SourceLanguage.ENGLISH if language == "en" else SourceLanguage.FRENCH
        
        results = await scraper.scrape_case_studies(
            medication_name=medication_name,
            condition=condition,
            language=lang_enum
        )
        
        job.results = [r.to_dict() for r in results]
        job.status = "completed"
        job.completed_at = datetime.now()
        job.progress = 100
        
    except Exception as e:
        logger.error(f"Case study scraping job {job_id} failed: {e}")
        job.status = "failed"
        job.errors.append(str(e))
        job.completed_at = datetime.now()
    
    finally:
        active_jobs.pop(job_id, None)
        completed_jobs[job_id] = job

async def _run_regulatory_scrape(job_id: str, language: str):
    """Background task for regulatory alerts scraping"""
    
    job = active_jobs[job_id]
    job.status = "running"
    job.started_at = datetime.now()
    
    try:
        scraper = MedicalScraper()
        
        lang_enum = SourceLanguage.ENGLISH if language == "en" else SourceLanguage.FRENCH
        
        results = await scraper.scrape_regulatory_updates(language=lang_enum)
        
        job.results = [r.to_dict() for r in results]
        job.status = "completed"
        job.completed_at = datetime.now()
        job.progress = 100
        
    except Exception as e:
        logger.error(f"Regulatory scraping job {job_id} failed: {e}")
        job.status = "failed"
        job.errors.append(str(e))
        job.completed_at = datetime.now()
    
    finally:
        active_jobs.pop(job_id, None)
        completed_jobs[job_id] = job


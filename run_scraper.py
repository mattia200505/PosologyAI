"""
Medical Scraper API - Standalone Flask App
Run with: python run_scraper.py
"""

import os
import sys

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from flask_cors import CORS

# Create Flask app
app = Flask(__name__)
CORS(app)

# Configure app
app.config['JSON_SORT_KEYS'] = False
app.config['DEBUG'] = True

# Import and register scraper blueprint
try:
    from frontend_backend.scraper_api import scraper_bp
    app.register_blueprint(scraper_bp)
    print("✅ Scraper API Blueprint registered successfully")
except Exception as e:
    print(f"❌ Error loading scraper API: {e}")
    import traceback
    traceback.print_exc()

@app.route('/')
def index():
    """Root endpoint with API information"""
    return {
        "name": "Medical Scraper API",
        "version": "1.0.0",
        "status": "active",
        "docs": "http://localhost:5001/api/scraper/health",
        "endpoints": {
            "health": "GET /api/scraper/health",
            "sources": "GET /api/scraper/sources",
            "medications": "POST /api/scraper/medications/scrape",
            "cases": "POST /api/scraper/case-studies/scrape",
            "alerts": "GET /api/scraper/regulatory/alerts",
            "jobs": "GET /api/scraper/jobs/<id>",
            "results": "GET /api/scraper/jobs/<id>/results"
        }
    }

if __name__ == '__main__':
    print("🚀 Starting Medical Scraper API on port 5001...")
    app.run(host='0.0.0.0', port=5001, debug=True)

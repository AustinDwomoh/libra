from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime
#from services.azalea import Azalea_
from services.db_manager import JobDatabase

#scrape = Azalea_()
app = Flask(__name__)
CORS(app)
@app.route('/', methods=['GET'])
def home():
    """API home endpoint with documentation"""
    return jsonify({
        "message": "Job Scraping API",
        "version": "1.0",
        "endpoints": {
            "GET /": "API documentation",
            "GET /api/jobs": "Get all jobs with optional filters (company, sponsorship, limit)",
            "GET /api/jobs/company/<company_name>": "Get all jobs from a specific company",
            "GET /api/jobs/search/<keyword>": "Search jobs by keyword in title or company",
            "GET /api/jobs/export": "Export all jobs as JSON"
        }
    })


@app.route('/api/jobs', methods=['GET'])
def get_jobs():
    """Get all scraped jobs with optional filtering by company and sponsorship"""
    company = request.args.get('company')
    sponsorship = request.args.get('sponsorship')
    limit = request.args.get('limit', type=int)

    with JobDatabase() as db:
        # Build dynamic query based on filters
        conditions = []
        params = []

        if company:
            conditions.append("company ILIKE %s")
            params.append(f"%{company}%")

        if sponsorship:
            conditions.append("sponsorship = %s")
            params.append(sponsorship)

        # Build query
        if conditions:
            where_clause = " AND ".join(conditions)
            query = f"SELECT * FROM jobs WHERE {where_clause} ORDER BY created_at DESC"
        else:
            query = "SELECT * FROM jobs ORDER BY created_at DESC"

        if limit:
            query += f" LIMIT {limit}"

        db.cursor.execute(query, params)
        jobs = db.cursor.fetchall()

    return jsonify({
        "success": True,
        "count": len(jobs),
        "jobs": jobs
    })


@app.route('/api/jobs/company/<string:company_name>', methods=['GET'])
def get_jobs_by_company(company_name):
    """Get all jobs from a specific company"""
    with JobDatabase() as db:
        jobs = db.get_jobs_by_company(company_name)

    return jsonify({
        "success": True,
        "company": company_name,
        "count": len(jobs),
        "jobs": jobs
    })


@app.route('/api/jobs/search/<string:keyword>', methods=['GET'])
def search_jobs(keyword):
    """Search for jobs by keyword in title or company name"""
    with JobDatabase() as db:
        jobs = db.search_jobs(keyword)

    return jsonify({
        "success": True,
        "keyword": keyword,
        "count": len(jobs),
        "jobs": jobs
    })

@app.route('/api/jobs/sponsor/', methods=['GET'])
def get_jobs_by_sponsorship():
    """Get all jobs by sponsorship status"""
    with JobDatabase() as db:
        jobs = db.get_jobs_with_sponsorship()

    return jsonify({
        "success": True,
        "sponsorship": "likely sponsorship",
        "count": len(jobs),
        "jobs": jobs
    })


# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "message": "Endpoint not found"
    }), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "success": False,
        "message": "Internal server error"
    }), 500


if __name__ == '__main__':
    print("🚀 Job Scraping API Starting...")
    print("📍 API running at: http://localhost:5000")
    print("📖 Read-only API - Job data populated by background scraper")
    print("\nAvailable endpoints:")
    print(" GET / - API documentation")
    print(" GET /api/jobs - Get all jobs (filters: company, sponsorship, limit)")
    print(" GET /api/jobs/company/<name> - Get jobs by company")
    print(" GET /api/jobs/search/<keyword> - Search jobs")
    print(" GET /api/jobs/export - Export all jobs")
    print("\n📝 Example requests:")
    print(' curl "http://localhost:5000/api/jobs?company=Google&sponsorship=Likely%20sponsorship"')
    print(' curl "http://localhost:5000/api/jobs/company/Meta"')
    print(' curl "http://localhost:5000/api/jobs/search/engineer"')
    
    
    app.run(debug=False, host='0.0.0.0', port=5000)

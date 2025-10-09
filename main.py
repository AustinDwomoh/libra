from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from services.db_manager import JobDatabase

app = FastAPI(
    title="Libra - Job Scraping API",
    version="1.0",
    description=(
        "Libra is a FastAPI-powered job scraping API by Austin Dwomoh. "
        "It provides read-only access to scraped job listings with filtering "
        "options for company, sponsorship, and keyword search. "
        "Use /docs for interactive Swagger UI or /redoc for ReDoc documentation."
    )
)


# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    """API home endpoint with documentation"""
    
    return {
        "api": {
            "name": "Libra",
            "version": "1.0",
            "description": "Libra - Job Scraping API powered by FastAPI",
            "author": "Austin Dwomoh",
            "base_url": "/"
        },
        "endpoints": {
            "GET /": "API documentation and metadata",
            "GET /api/jobs": "Retrieve all jobs. Optional query parameters: company, sponsorship, limit",
            "GET /api/jobs/company/{company_name}": "Retrieve all jobs from a specific company",
            "GET /api/jobs/search/{keyword}": "Search jobs by keyword in title or company name",
            "GET /api/jobs/sponsor": "Retrieve all jobs likely to offer visa sponsorship"
        },
        "notes": [
            "All data is read-only and updated by background scrapers.",
            "Query parameters are case-insensitive where applicable.",
            "Use /docs for interactive Swagger UI and /redoc for ReDoc documentation."
        ]
    }


@app.get("/jobs")
def get_jobs(
    company: Optional[str] = Query(None, description="Filter by company name"),
    sponsorship: Optional[str] = Query(None, description="Filter by sponsorship"),
    limit: Optional[int] = Query(None, description="Limit number of results")
):
    """Get all scraped jobs with optional filtering"""
    with JobDatabase() as db:
        conditions = []
        params = []

        if company:
            conditions.append("company ILIKE %s")
            params.append(f"%{company}%")

        if sponsorship:
            conditions.append("sponsorship = %s")
            params.append(sponsorship)

        if conditions:
            where_clause = " AND ".join(conditions)
            query = f"SELECT * FROM jobs WHERE {where_clause} ORDER BY created_at DESC"
        else:
            query = "SELECT * FROM jobs ORDER BY created_at DESC"

        if limit:
            query += f" LIMIT {limit}"

        db.cursor.execute(query, params)
        jobs = db.cursor.fetchall()

    return {"success": True, "count": len(jobs), "jobs": jobs}


@app.get("/jobs/company/{company_name}")
def get_jobs_by_company(company_name: str):
    """Get all jobs from a specific company"""
    with JobDatabase(auto_setup=False) as db:
        jobs = db.get_jobs_by_company(company_name)

    return {"success": True, "company": company_name, "count": len(jobs), "jobs": jobs}


@app.get("/jobs/search/{keyword}")
def search_jobs(keyword: str):
    """Search jobs by keyword in title or company"""
    with JobDatabase(auto_setup=False) as db:
        jobs = db.search_jobs(keyword)

    return {"success": True, "keyword": keyword, "count": len(jobs), "jobs": jobs}


@app.get("/jobs/sponsor")
def get_jobs_by_sponsorship():
    """Get all jobs by sponsorship status"""
    with JobDatabase(auto_setup=False) as db:
        jobs = db.get_jobs_with_sponsorship()

    return {"success": True, "sponsorship": "likely sponsorship", "count": len(jobs), "jobs": jobs}


# Error handling in FastAPI is via exceptions
@app.exception_handler(404)
def not_found(request, exc):
    return JSONResponse(
        status_code=404,
        content={"detail": "Endpoint not found"}
    )

@app.exception_handler(500)
def internal_error(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

#uvicorn main:app --host 0.0.0.0 --port 5000 --reload
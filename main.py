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
            "GET /jobs": "Retrieve jobs with optional query parameters: company, sponsor, search, limit"
        },
        "notes": [
            "All data is read-only and updated by background scrapers.",
            "Query parameters are case-insensitive where applicable.",
            "Use /docs for interactive Swagger UI and /redoc for ReDoc documentation."
        ]
    }


@app.get("/jobs")
def get_jobs(
    limit: Optional[int] = Query(None, description="Limit number of results"),
    company: Optional[str] = Query(None, description="Filter by company name"),
    search: Optional[str] = Query(None, description="Search keyword in title or company"),
    sponsor: Optional[bool] = Query(None, description="Filter by sponsorship availability")
):
    """Get jobs with optional filtering"""
    with JobDatabase(auto_setup=False) as db:
        # Start with base query
        query = "SELECT * FROM jobs WHERE 1=1"
        params = []
        
        # Add filters based on provided parameters
        if company:
            query += " AND company_name LIKE ?"
            params.append(f"%{company}%")
        
        if search:
            query += " AND (title LIKE ? OR company_name LIKE ?)"
            params.append(f"%{search}%")
            params.append(f"%{search}%")
        
        if sponsor is True:
            # Adjust based on how you store sponsorship data
            query += " AND sponsorship = 1"  # or whatever your column is
        
        query += " ORDER BY created_at DESC"
        
        if limit:
            query += f" LIMIT {limit}"
        
        db.cursor.execute(query, params)
        jobs = db.cursor.fetchall()
    
    return {"success": True, "count": len(jobs), "jobs": jobs}

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
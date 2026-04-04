from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from Service.db import JobDatabase


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the DB connection pool once at startup and reuse it across requests."""
    app.state.db = await JobDatabase.create()
    yield
    await app.state.db.pool.close()


app = FastAPI(
    title="Libra - Job Scraping API",
    version="2.0",
    description=(
        "Libra is a FastAPI-powered job scraping API by Austin Dwomoh. "
        "It provides read-only access to scraped job listings with filtering "
        "options for company, sponsorship, and keyword search. "
        "Use /docs for interactive Swagger UI or /redoc for ReDoc documentation."
    ),
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def home():
    """API home endpoint with documentation"""
    return {
        "api": {
            "name": "Libra",
            "version": "2.0",
            "description": "Libra - Job Scraping API powered by FastAPI",
            "author": "Austin Dwomoh",
            "base_url": "/"
        },
        "endpoints": {
            "GET /": "API documentation and metadata",
            "GET /jobs": "Retrieve jobs with optional query parameters: limit(?limit=10)",
            "GET /company/{company_name}": "Get jobs by company name with optional limit",
            "GET /search/{keyword}": "Search jobs by keyword in title",
            "GET /sponsor": "Get all jobs with likely sponsorship"
        },
        "notes": [
            "All data is read-only and updated by background scrapers.",
            "Query parameters are case-insensitive where applicable.",
            "Use /docs for interactive Swagger UI and /redoc for ReDoc documentation."
        ]
    }


@app.get("/jobs")
async def get_jobs(
    request: Request,
    limit: Optional[int] = Query(None, description="Limit number of results"),
):
    """Get all jobs ordered by most recent, with an optional limit."""
    db: JobDatabase = request.app.state.db
    jobs = await db.select("job_list", order_by="created_at DESC", limit=limit)#type: ignore
    return {
        "success": True,
        "params": {"limit": limit},
        "jobs": jobs,
    }


@app.get("/company/{company_name}")
async def get_jobs_by_company(
    company_name: str,
    request: Request,
    limit: Optional[int] = Query(None, description="Limit number of results"),
):
    """Get all jobs from a specific company by name (case-insensitive)."""
    db: JobDatabase = request.app.state.db
    jobs = await db.select(
        "job_list",
        raw_where="company = (SELECT id FROM company WHERE name = $1)",
        raw_params=[company_name.lower()],
        order_by="created_at DESC",
        limit=limit, #type: ignore
    )
    return {
        "success": True,
        "params": {"company_name": company_name, "limit": limit},
        "jobs": jobs,
    }


@app.get("/search/{keyword}")
async def search_jobs(keyword: str, request: Request):
    """Search jobs by keyword in the job title (case-insensitive)."""
    db: JobDatabase = request.app.state.db
    jobs = await db.select(
        "job_list",
        raw_where="lower(title) LIKE $1",
        raw_params=[f"%{keyword.lower()}%"],
        order_by="created_at DESC",
    )
    return {
        "success": True,
        "params": {"keyword": keyword},
        "jobs": jobs,
    }


@app.get("/sponsor")
async def get_jobs_by_sponsorship(request: Request):
    """Get all jobs that are likely to offer visa sponsorship."""
    db: JobDatabase = request.app.state.db
    jobs = await db.select(
        "job_list",
        raw_where="tags->>'sponsorship' = 'true'",
        order_by="created_at DESC",
    )
    return {
        "success": True,
        "params": {"sponsorship": "likely sponsorship"},
        "jobs": jobs,
    }


@app.exception_handler(404)
async def not_found(request, exc):
    return JSONResponse(
        status_code=404,
        content={"success": False, "detail": "Endpoint not found"}
    )


@app.exception_handler(500)
async def internal_error(request, exc):
    return JSONResponse(
        status_code=500,
        content={"success": False, "detail": "Internal server error"}
    )

# uvicorn main:app --host 0.0.0.0 --port 5000 --reload

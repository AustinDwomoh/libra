# Libra - Job Scraping & Sponsorship Tracking System

A comprehensive job scraping system that automatically collects internship listings from SimplifyJobs/Summer2026-Internships and enriches them with H1-B sponsorship information. The system provides a read-only REST API for accessing the job data stored in PostgreSQL.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Setup Instructions](#setup-instructions)
  - [1. PostgreSQL Installation](#1-postgresql-installation)
  - [2. Database Setup](#2-database-setup)
  - [3. Environment Configuration](#3-environment-configuration)
  - [4. Python Dependencies](#4-python-dependencies)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
  - [Scraping Pipeline](#scraping-pipeline)
  - [Sponsorship Matching](#sponsorship-matching)
  - [Database Operations](#database-operations)
- [API Documentation](#api-documentation)
  - [Endpoints](#endpoints)
  - [Data Models](#data-models)
  - [Error Handling](#error-handling)
- [Usage Guide](#usage-guide)
- [Database Management](#database-management)
- [Troubleshooting](#troubleshooting)

---

## Overview

Libra is a job data pipeline that:

1. **Scrapes** internship listings from the Summer2026-Internships GitHub repository
2. **Enriches** job data with H1-B sponsorship information using fuzzy matching
3. **Stores** all data in a PostgreSQL database with automatic timestamp tracking
4. **Serves** data through a RESTful Flask API with filtering capabilities

### Key Features

- 🔄 Automated web scraping from GitHub README markdown tables
- 🎯 Fuzzy company name matching for sponsorship detection (90% threshold)
- 🗄️ PostgreSQL database with UUID primary keys and indexed queries
- 🔍 Full-text search across job titles, companies, locations
- 📊 RESTful API with CORS support for frontend integration
- 🏷️ Automatic tagging of jobs with "Likely sponsorship" or "No record found"

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Repository                        │
│         SimplifyJobs/Summer2026-Internships                 │
│                   (README.md tables)                        │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTP GET
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  Azalea  (azalea.py)                        │
│                                                             │
│  • Fetches README markdown                                  │
│  • Parses HTML tables with BeautifulSoup                    │
│  • Extracts: company, title, location, link                 │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│           SponsorshipDB (assist.py)                         │
│  • Loads H1-B employer data from CSV                        │
│  • Fuzzy matching with RapidFuzz (90% threshold)            │
│  • Tags jobs: "Likely sponsorship" / "No record found"      │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              PostgreSQL Database                            │
│  • UUID primary keys                                        │
│  • Unique constraint on job links                           │
│  • Automatic timestamps (created_at, updated_at)            │
│  • Indexed queries on company and date                      │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                 Flask REST API (main.py)                    │
│  • GET /api/jobs - List/filter jobs                         │
│  • GET /api/jobs/company/<name> - Jobs by company           │
│  • GET /api/jobs/search/<keyword> - Full-text search        │
│  • GET /api/jobs/sponsor - Filter by sponsorship            │
└─────────────────────────────────────────────────────────────┘
```

---

## Setup Instructions

### 1. PostgreSQL Installation

#### Windows

1. Download PostgreSQL 15+ from: https://www.postgresql.org/download/windows/
2. Run the installer and follow the setup wizard
3. **Important**: Remember the password you set for the `postgres` user
4. Default port: 5432
5. Optional: Add `psql` to your PATH for easier command-line access

#### macOS

```bash
brew install postgresql@15
brew services start postgresql@15
```

#### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql  # Auto-start on boot
```

### 2. Database Setup

#### Option A: Interactive Setup

```bash
# Connect to PostgreSQL
psql -U postgres

# Inside psql prompt:
CREATE DATABASE libra;
\c libra
\i resources/schema.sql
\dt  # Verify table was created
\q   # Exit psql
```

#### Option B: Command-Line Setup

```bash
# Create database
psql -U postgres -c "CREATE DATABASE libra;"

# Run schema file
psql -U postgres -d libra -f resources/schema.sql

# Verify setup
psql -U postgres -d libra -c "\dt"
```

#### What the Schema Creates

The `resources/schema.sql` file creates:

1. **`jobs` table** with columns:
   - `id` (UUID, primary key, auto-generated)
   - `company` (TEXT, indexed)
   - `title` (TEXT)
   - `location` (TEXT)
   - `link` (TEXT, unique constraint)
   - `sponsorship` (TEXT)
   - `created_at` (TIMESTAMP, auto-set)
   - `updated_at` (TIMESTAMP, auto-updated)

2. **Indexes** for performance:
   - `idx_jobs_company` on company column
   - `idx_jobs_created_at` on created_at column

3. **Trigger** for automatic timestamp updates:
   - `update_jobs_updated_at` trigger
   - `update_updated_at_column()` function

### 3. Environment Configuration

Create a `.env` file in the project root:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=libra
DB_USER=postgres
DB_PASSWORD=your_password_here
```

**Security Note**: Never commit `.env` to version control. The `.gitignore` file should already exclude it.

### 4. Python Dependencies

```bash
# Activate virtual environment (recommended)
python -m venv libra
source libra/bin/activate  # On Windows: libra\Scripts\activate

# Install all dependencies
pip install -r requirements.txt
```

#### Core Dependencies

- `Flask==3.1.2` - REST API framework
- `flask-cors==6.0.1` - Cross-origin resource sharing
- `psycopg2-binary==2.9.10` - PostgreSQL adapter
- `python-dotenv==1.1.1` - Environment variable management
- `beautifulsoup4==4.14.0` - HTML parsing
- `requests==2.32.5` - HTTP client
- `pandas==2.3.2` - CSV data processing
- `RapidFuzz==3.14.1` - Fuzzy string matching
- `emoji==25.4.16` - Emoji handling and removal

---

## Project Structure

```
libra/
├── main.py                    # Flask API server (entry point)
├── .env                       # Database credentials (not in git)
├── requirements.txt           # Python dependencies
├── README.md                  # This file
│
├── services/
│   ├── azalea.py             # Web scraper (Azalea_ class)
│   ├── db_manager.py           # Database operations (JobDatabase class)
│   └── assist.py             # Sponsorship matching (SponsorshipDB class)
│
└── resources/
    ├── schema.sql            # PostgreSQL table definition
    ├── Employer_info.csv     # H1-B sponsorship data (UTF-16)
    └── scraped_jobs.json     # Cached scraper output
```

### File Responsibilities

#### `services/azalea.py`
The web scraping engine that:
- Fetches README from SimplifyJobs GitHub repository
- Parses markdown tables using BeautifulSoup
- Extracts job data (company, title, location, link)
- Handles continuation rows (↳) for multiple positions per company
- Removes emojis from company names for matching
- Validates job entries before storage
- Saves backup to `scraped_jobs.json`

**Key Class**: `Azalea_`
- `fetch_readme()` - HTTP GET request to GitHub
- `parse_tables()` - BeautifulSoup table parsing
- `tag_sponsorship()` - Add sponsorship information
- `run()` - Main execution pipeline

#### `services/assist.py`
Sponsorship detection system that:
- Loads H1-B employer data from CSV files
- Normalizes company names (lowercase, strip whitespace)
- Performs fuzzy matching using RapidFuzz library
- Returns "Likely sponsorship" or "No record found"

**Key Class**: `SponsorshipDB`
- `_load_csv()` - Auto-detects CSV encoding and separator
- `has_sponsorship()` - Exact match lookup
- `fuzzy_match()` - Fuzzy matching with 90% threshold

#### `services/db_manager.py`
Database abstraction layer with:
- Context manager support (`with JobDatabase() as db`)
- Connection pooling via `get_db_connection()`
- CRUD operations with prepared statements
- Bulk insert with conflict resolution
- Automatic transaction rollback on errors

**Key Class**: `JobDatabase`
- **CREATE**: `insert_job()`, `insert_jobs_bulk()`
- **READ**: `get_all_jobs()`, `get_jobs_by_company()`, `search_jobs()`
- **UPDATE**: `update_job()`
- **DELETE**: `delete_job()`, `delete_all_jobs()`
- **UTILITY**: `count_jobs()`, `recreate_jobs_table()`

#### `main.py`
Flask REST API server with:
- CORS enabled for all origins
- JSON responses with RealDictCursor
- Error handling (404, 500)
- Query parameter filtering
- Read-only endpoints (no POST/PUT/DELETE)

---

## How It Works

### Scraping Pipeline

1. **Fetch README**
   ```
   GET https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md
   ```

2. **Parse Tables**
   - Locate all `<table>` elements
   - Extract rows with `<tr>` and cells with `<td>`
   - Handle multi-position companies (↳ continuation rows)
   - Clean company names (remove emojis)

3. **Extract Links**
   - Priority: Column 3 (application link column)
   - Fallback: Search all cells for `<a href>`
   - Skip internal anchors (`#`) and GitHub links

4. **Validate Jobs**
   - Must have: company, title, location, link
   - Invalid entries logged but skipped

### Sponsorship Matching

The system uses **fuzzy string matching** to handle variations in company names:

```python
# Example matches (90% threshold)
"Google LLC" ✓ matches "Google"
"Meta Platforms, Inc." ✓ matches "Meta"
"Amazon.com Services LLC" ✓ matches "Amazon"
```

**Algorithm**: RapidFuzz's Levenshtein ratio
- Threshold: 90% similarity
- Case-insensitive
- Whitespace normalized

**CSV Loading**:
- Auto-detects encoding: UTF-16, UTF-8, Latin-1, CP1252
- Auto-detects separator: Tab, Comma, Semicolon
- Searches for columns: `EmployerName`, `Employer`, `Employer (Petitioner) Name`

### Database Operations

#### Insert with Conflict Resolution

```python
# Bulk insert with upsert
db.insert_jobs_bulk(jobs)
# ON CONFLICT (link) DO UPDATE
# Updates existing jobs if link already exists
```

#### Context Manager Pattern

```python
# Automatic connection cleanup and rollback on errors
with JobDatabase() as db:
    jobs = db.get_all_jobs()
    # Connection closed automatically
```

#### Timestamp Triggers

```sql
-- updated_at automatically set on every UPDATE
CREATE TRIGGER update_jobs_updated_at
BEFORE UPDATE ON jobs
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

---

## API Documentation

### Base URL
```
http://localhost:5000
```

### Endpoints

#### `GET /`
**Description**: API information and available endpoints

**Response**:
```json
{
  "message": "Job Scraping API",
  "version": "1.0",
  "endpoints": {
    "GET /": "API documentation",
    "GET /api/jobs": "Get all jobs with optional filters",
    "GET /api/jobs/company/<company_name>": "Get jobs by company",
    "GET /api/jobs/search/<keyword>": "Search jobs",
    "GET /api/jobs/sponsor": "Get jobs with sponsorship"
  }
}
```

---

#### `GET /api/jobs`
**Description**: Retrieve all jobs with optional filtering

**Query Parameters**:

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `company` | string | Filter by company (case-insensitive, partial match) | `?company=Google` |
| `sponsorship` | string | Filter by exact sponsorship status | `?sponsorship=Likely%20sponsorship` |
| `limit` | integer | Limit number of results | `?limit=10` |

**Examples**:
```http
GET /api/jobs
GET /api/jobs?company=Meta
GET /api/jobs?sponsorship=Likely%20sponsorship
GET /api/jobs?company=Google&limit=5
```

**Response**:
```json
{
  "success": true,
  "count": 2,
  "jobs": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "company": "google",
      "title": "Software Engineer Intern",
      "location": "New York, NY",
      "link": "https://example.com/job1",
      "sponsorship": "Likely sponsorship",
      "created_at": "2025-01-15T10:30:00",
      "updated_at": "2025-01-15T10:30:00"
    }
  ]
}
```

---

#### `GET /api/jobs/company/<company_name>`
**Description**: Get all jobs from a specific company

**URL Parameters**:
- `company_name` (string, required): Company name to filter by

**Examples**:
```http
GET /api/jobs/company/Google
GET /api/jobs/company/Meta
```

**Response**:
```json
{
  "success": true,
  "company": "Google",
  "count": 3,
  "jobs": [...]
}
```

---

#### `GET /api/jobs/search/<keyword>`
**Description**: Search jobs by keyword in title, company, location, or sponsorship

**URL Parameters**:
- `keyword` (string, required): Search term

**Examples**:
```http
GET /api/jobs/search/engineer
GET /api/jobs/search/python
GET /api/jobs/search/remote
```

**Implementation**:
```sql
SELECT * FROM jobs
WHERE title ILIKE '%keyword%'
   OR company ILIKE '%keyword%'
   OR location ILIKE '%keyword%'
   OR sponsorship ILIKE '%keyword%'
ORDER BY created_at DESC;
```

**Response**:
```json
{
  "success": true,
  "keyword": "engineer",
  "count": 5,
  "jobs": [...]
}
```

---

#### `GET /api/jobs/sponsor/`
**Description**: Get all jobs with "Likely sponsorship" status

**Response**:
```json
{
  "success": true,
  "sponsorship": "likely sponsorship",
  "count": 42,
  "jobs": [...]
}
```

---

### Data Models

#### Job Object

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique identifier (auto-generated) |
| `company` | string | Company name (lowercase, no emojis) |
| `title` | string | Job title/position |
| `location` | string | Job location(s) |
| `link` | string | Application URL (unique) |
| `sponsorship` | string | "Likely sponsorship" or "No record found" |
| `created_at` | timestamp | First insertion time (auto-set) |
| `updated_at` | timestamp | Last update time (auto-updated) |

---

### Error Handling

All errors return JSON with `success: false`:

```json
{
  "success": false,
  "message": "Error description"
}
```

**Status Codes**:

| Code | Description |
|------|-------------|
| `200 OK` | Request successful |
| `400 Bad Request` | Invalid request parameters |
| `404 Not Found` | Endpoint not found |
| `500 Internal Server Error` | Database or server error |

---

## Usage Guide

### Running the Scraper

```python
from services.azalea import Azalea_

scraper = Azalea_()
stats = scraper.run(use_fuzzy=True)

print(f"Parsed: {stats['parsed']} jobs")
print(f"Inserted: {stats['inserted']} jobs")
```

**Output**:
```
INFO - Fetching README from https://raw.githubusercontent.com/...
INFO - Successfully fetched README (125000 characters)
INFO - Parsing job tables...
INFO - Found 3 tables to parse
INFO - Parsed 500 valid job entries
INFO - Loading sponsorship database...
INFO - Tagging 500 jobs with sponsorship info...
INFO - Sponsorship tagging complete: 120/500 with likely sponsorship
INFO - Saved 500 jobs to resources/scraped_jobs.json
INFO - Database now contains 500 total jobs
```

### Starting the API Server

```bash
python main.py
```

**Output**:
```
🚀 Job Scraping API Starting...
📍 API running at: http://localhost:5000
📖 Read-only API - Job data populated by background scraper

Available endpoints:
 GET / - API documentation
 GET /api/jobs - Get all jobs (filters: company, sponsorship, limit)
 GET /api/jobs/company/<name> - Get jobs by company
 GET /api/jobs/search/<keyword> - Search jobs
 GET /api/jobs/export - Export all jobs

📝 Example requests:
 curl "http://localhost:5000/api/jobs?company=Google"
 curl "http://localhost:5000/api/jobs/company/Meta"
 curl "http://localhost:5000/api/jobs/search/engineer"
```

### Making API Requests

#### cURL Examples

```bash
# Get all jobs
curl "http://localhost:5000/api/jobs"

# Filter by company
curl "http://localhost:5000/api/jobs?company=Google"

# Filter by company AND sponsorship
curl "http://localhost:5000/api/jobs?company=Meta&sponsorship=Likely%20sponsorship"

# Limit results
curl "http://localhost:5000/api/jobs?limit=20"

# Get jobs by company
curl "http://localhost:5000/api/jobs/company/Google"

# Search jobs
curl "http://localhost:5000/api/jobs/search/engineer"

# Get sponsored jobs
curl "http://localhost:5000/api/jobs/sponsor/"
```

#### Python Examples

```python
import requests

# Get all jobs
response = requests.get("http://localhost:5000/api/jobs")
jobs = response.json()['jobs']

# Filter by company
params = {'company': 'Google', 'limit': 10}
response = requests.get("http://localhost:5000/api/jobs", params=params)
```

#### JavaScript Examples

```javascript
// Fetch all jobs
fetch('http://localhost:5000/api/jobs')
  .then(res => res.json())
  .then(data => console.log(data.jobs));

// Filter by company
fetch('http://localhost:5000/api/jobs?company=Meta')
  .then(res => res.json())
  .then(data => console.log(`Found ${data.count} jobs`));
```

---

## Database Management

### Useful PostgreSQL Commands

```bash
# Connect to database
psql -U postgres -d libra

# Inside psql:

# List all tables
\dt

# Describe jobs table
\d jobs

# View all records
SELECT * FROM jobs;

# Count total jobs
SELECT COUNT(*) FROM jobs;

# Count jobs by company
SELECT company, COUNT(*) as count
FROM jobs
GROUP BY company
ORDER BY count DESC
LIMIT 10;

# View sponsored jobs
SELECT company, title, location
FROM jobs
WHERE sponsorship = 'Likely sponsorship';

# Recent jobs
SELECT company, title, created_at
FROM jobs
ORDER BY created_at DESC
LIMIT 10;

# Exit psql
\q
```

### Database Maintenance

#### Recreate Table from Scratch

```python
from services.db_manager import JobDatabase

with JobDatabase() as db:
    db.recreate_jobs_table()
    print("Table recreated successfully")
```

#### Refresh All Jobs (Drop + Recreate + Insert)

```python
from services.azalea import Azalea_
from services.db_manager import JobDatabase

# Scrape fresh data
scraper = Azalea_()
scraper.fetch_readme()
scraper.parse_tables()

# Drop table, recreate, and insert
with JobDatabase() as db:
    result = db.refresh_all_jobs(scraper.jobs)
    print(f"Inserted {result['inserted']} jobs")
```

#### Delete All Jobs (Keep Table Structure)

```python
with JobDatabase() as db:
    deleted = db.delete_all_jobs()
    print(f"Deleted {deleted} jobs")
```

### Backup and Restore

#### Backup Database

```bash
# Backup entire database
pg_dump -U postgres libra > libra_backup.sql

# Backup just the jobs table
pg_dump -U postgres -t jobs libra > jobs_backup.sql
```

#### Restore Database

```bash
# Restore from backup
psql -U postgres libra < libra_backup.sql
```

---

## Troubleshooting

### Database Connection Issues

**Problem**: `psycopg2.OperationalError: could not connect to server`

**Solutions**:
1. Verify PostgreSQL is running:
   ```bash
   # Windows: Check Services app
   # macOS: brew services list
   # Linux: sudo systemctl status postgresql
   ```

2. Check `.env` credentials:
   ```bash
   cat .env  # Verify DB_PASSWORD matches postgres user password
   ```

3. Test connection manually:
   ```bash
   psql -U postgres -d libra
   ```

---

### CSV Encoding Issues

**Problem**: `UnicodeDecodeError` when loading `Employer_info.csv`

**Solution**: The CSV is UTF-16 encoded. The code auto-detects this:
```python
# services/assist.py handles multiple encodings
for encoding in ['utf-16', 'utf-8', 'latin-1', 'cp1252']:
    try:
        df = pd.read_csv(path, encoding=encoding)
        break
    except:
        continue
```

To manually verify encoding:
```bash
file -i resources/Employer_info.csv
# Output: charset=utf-16le
```

---

### Scraping Failures

**Problem**: Scraper returns 0 jobs

**Debugging Steps**:

1. Check README URL is accessible:
   ```bash
   curl -I https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md
   ```

2. Verify table structure hasn't changed:
   ```python
   scraper = Azalea_()
   scraper.fetch_readme()

   from bs4 import BeautifulSoup
   soup = BeautifulSoup(scraper.readme_text, "html.parser")
   tables = soup.find_all("table")
   print(f"Found {len(tables)} tables")
   ```

3. Check logs for parsing errors:
   ```python
   # Enable debug logging
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

---

### API Returns Empty Results

**Problem**: `GET /api/jobs` returns `count: 0`

**Debugging**:

1. Check database has data:
   ```bash
   psql -U postgres -d libra -c "SELECT COUNT(*) FROM jobs;"
   ```

2. Verify API is querying correct database:
   ```python
   # In main.py, temporarily add:
   with JobDatabase() as db:
       print(f"Database connection test: {db.count_jobs()} jobs")
   ```

3. Check for transaction issues:
   ```python
   # Ensure scraper commits transactions
   with JobDatabase() as db:
       db.insert_jobs_bulk(jobs)
       # Context manager auto-commits unless error occurs
   ```

---

### Port Already in Use

**Problem**: `OSError: [Errno 48] Address already in use`

**Solutions**:

```bash
# Find process using port 5000
# macOS/Linux:
lsof -i :5000

# Windows:
netstat -ano | findstr :5000

# Kill the process
kill -9 <PID>  # macOS/Linux
taskkill /PID <PID> /F  # Windows

# Or use a different port
# In main.py:
app.run(debug=False, host='0.0.0.0', port=8080)
```

---

### Fuzzy Matching Too Strict/Loose

**Problem**: Sponsorship matching misses companies or matches incorrectly

**Solutions**:

1. Adjust fuzzy threshold (default: 90):
   ```python
   # In services/azalea.py, modify Config class
   class Config:
       FUZZY_THRESHOLD = 85  # More lenient (80-89)
       # or
       FUZZY_THRESHOLD = 95  # More strict (90-100)
   ```

2. Test specific matches:
   ```python
   from services.assist import SponsorshipDB
   from rapidfuzz import fuzz

   db = SponsorshipDB(csv_paths=["resources/Employer_info.csv"])

   # Test a specific company
   company = "Google LLC"
   match = db.fuzzy_match(company, threshold=90)
   print(f"{company}: {match}")

   # See exact ratio
   for employer in list(db.employers)[:10]:
       ratio = fuzz.ratio(employer, company.lower())
       print(f"{employer}: {ratio}%")
   ```

---

## Advanced Configuration

### Custom Scraping URL

```python
# Scrape from a different repository
scraper = Azalea_(url="https://raw.githubusercontent.com/other/repo/main/README.md")
scraper.run()
```

### Scheduled Scraping

Using `cron` (Linux/macOS):
```bash
# Run scraper every day at 2 AM
0 2 * * * cd /path/to/libra && /path/to/libra/bin/python -c "from services.azalea import Azalea_; Azalea_().run()"
```

Using Windows Task Scheduler:
```powershell
# Create a batch file: scrape.bat
cd C:\path\to\libra
C:\path\to\libra\Scripts\python.exe -c "from services.azalea import Azalea_; Azalea_().run()"
```

### Production Deployment

**Using Gunicorn** (recommended for production):
```bash
pip install gunicorn

# Run with 4 worker processes
gunicorn -w 4 -b 0.0.0.0:5000 main:app
```

**Environment Variables for Production**:
```bash
export FLASK_ENV=production
export DB_HOST=your-db-host.com
export DB_PASSWORD=secure-password
```

---

## Contributing

When adding new features:

1. Update `schema.sql` if database schema changes
2. Update API documentation in this README
3. Add error handling and logging
4. Test with `pytest` (add tests in `tests/` directory)
5. Update requirements.txt: `pip freeze > requirements.txt`

---

## License

This project is for educational and personal use. Job data sourced from SimplifyJobs/Summer2026-Internships repository. H1-B sponsorship data sourced from publicly available USCIS records.

---

## Support

For issues:
1. Check the [Troubleshooting](#troubleshooting) section
2. Verify environment configuration (`.env` file)
3. Check PostgreSQL logs: `tail -f /var/log/postgresql/postgresql-15-main.log`
4. Enable debug logging in Python code

---

**Last Updated**: January 2025
**Version**: 1.0

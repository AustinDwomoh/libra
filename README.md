<!--
Docify-style README for Libra
This file is structured for readability and easy consumption by static doc generators.
-->

# Libra

> Job scraping and sponsorship detection API(v2)

<p align="center">
  <img src="./logo.svg" alt="Libra logo" width="240" />
</p>

---

## Overview

Libra is a small FastAPI-based service that exposes scraped internship/job listings and tags them with likely H1-B sponsorship data. The project contains scrapers, a lightweight DB layer, and a read-only REST API for querying results.

This README is written in a Docify-friendly layout and includes a quickstart, API reference, and a detailed file-explanation section.

---

## Current State
- This is for the v2 only 
- Swicthing from the dependency on the CSV from the USCIS to using the description from the apply links
- The other issues is understanding the and extrating data from the description
  > The options were regex and LLM extractions but am against having to keep paying for such a service in this low stakes project. Will research and develop somethign better but then I will build without the extractions and get version two up and working

---

## API Reference

Base URL: `http://libra.austindwomoh.xyz`

### GET /

Returns API metadata and available endpoints.

Response (200):

```json
{
  "api": {
    "name": "Libra",
    "version": "1.0",
    "description": "Libra - Job Scraping API powered by FastAPI",
    "author": "Austin Dwomoh",
    "base_url": "/"
  },
  "endpoints": {
    "GET /": "API documentation and metadata",
    "GET /jobs": "Retrieve jobs with optional query parameters: limit(?limit=10)",
    "GET /company/{company_name}": "Get jobs by company name with optional limit",
    "GET /search/{keyword}": "Search jobs by keyword in title or company",
    "GET /sponsor": "Get all jobs with likely sponsorship"
  },
  "notes": [
    "All data is read-only and updated by background scrapers.",
    "Query parameters are case-insensitive where applicable.",
    "Use /docs for interactive Swagger UI and /redoc for ReDoc documentation."
  ]
}
```

### GET /jobs

Query parameters:

- `limit` (optional): integer limit on returned rows

Example:
`GET /jobs?&limit=2`

Response (200):

```json
{
  "success": true,
  "params": {
    "limit": 4
  },
  "jobs": [
    {
      "id": "dcf8edc2-05b4-456c-b24e-b27b9ee20ee8",
      "company": "spectrum control",
      "title": "Engineering Intern/Co-op",
      "location": "Philadelphia, PA",
      "link": "https://spectrumcontrol.wd1.myworkdayjobs.com/spectrumcontrol/job/Philadelphia-PA/Engineering-Co-Op_JR101305?utm_source=Simplify&ref=Simplify",
      "sponsorship": "No record found",
      "source": "simplify",
      "remote": false,
      "date_posted": null,
      "description": null,
      "tags": [],
      "created_at": "2026-03-10T11:02:53.371494",
      "updated_at": "2026-03-10T11:02:53.371494"
    },
    {
      "id": "d0c43e5b-3bf6-4031-82d4-f35f702d94de",
      "company": "amentum",
      "title": "Software Programmer Intern",
      "location": "Detroit, MI",
      "link": "https://pae.wd1.myworkdayjobs.com/en-US/amentum_careers/job/US-MI-Detroit/Software-Programmer-Intern_R0156070?utm_source=Simplify&ref=Simplify",
      "sponsorship": "No record found",
      "source": "simplify",
      "remote": false,
      "date_posted": null,
      "description": null,
      "tags": [],
      "created_at": "2026-03-10T11:02:53.371494",
      "updated_at": "2026-03-10T11:02:53.371494"
    }
  ]
}
```

### GET /ompany/{company_name}

Return jobs filtered by company name (exact match path param). Example:
`GET /company/walmart`

> company name must be lower case

```json
{
  "success": true,
  "params": {
    "company_name": "walmart",
    "limit": null
  },
  "jobs": [
    {
      "id": "9a55263c-2bce-4ac4-b565-945e01c235af",
      "company": "walmart",
      "title": "Software Engineer 2",
      "location": "Bentonville, ARSunnyvale, CA",
      "link": "https://walmart.wd5.myworkdayjobs.com/WalmartExternal/job/Bentonville-AR/XMLNAME-2026-Summer-Intern--Software-Engineering-II--Bentonville-_R-2354856?utm_source=Simplify&ref=Simplify",
      "sponsorship": "No record found",
      "source": "simplify",
      "remote": false,
      "date_posted": null,
      "description": null,
      "tags": [],
      "created_at": "2026-01-08T14:31:12.947092",
      "updated_at": "2026-01-28T04:21:08.332309"
    },
    {
      "id": "4360bd4c-e4c0-4c0a-9b51-334f6f2fc365",
      "company": "walmart",
      "title": "Intern Software Engineer 2 - Software Engineer",
      "location": "Sunnyvale, CA",
      "link": "https://walmart.wd5.myworkdayjobs.com/WalmartExternal/job/Sunnyvale-CA/XMLNAME-2026-Summer-Intern--Software-Engineer-II_R-2349390?utm_source=Simplify&ref=Simplify",
      "sponsorship": "No record found",
      "source": "simplify",
      "remote": false,
      "date_posted": null,
      "description": null,
      "tags": [],
      "created_at": "2026-01-06T20:54:01.542547",
      "updated_at": "2026-01-06T23:19:06.082396"
    }
  ]
}
```

### GET /search/{keyword}

Full-text-ish search across title and company.

```json
{
  "success": true,
  "params": {
    "keyword": "walmart"
  },
  "jobs": [
    {
      "id": "9a55263c-2bce-4ac4-b565-945e01c235af",
      "company": "walmart",
      "title": "Software Engineer 2",
      "location": "Bentonville, ARSunnyvale, CA",
      "link": "https://walmart.wd5.myworkdayjobs.com/WalmartExternal/job/Bentonville-AR/XMLNAME-2026-Summer-Intern--Software-Engineering-II--Bentonville-_R-2354856?utm_source=Simplify&ref=Simplify",
      "sponsorship": "No record found",
      "source": "simplify",
      "remote": false,
      "date_posted": null,
      "description": null,
      "tags": [],
      "created_at": "2026-01-08T14:31:12.947092",
      "updated_at": "2026-01-28T04:21:08.332309"
    }
  ]
}
```

### GET /sponsor

Return jobs that are likely to offer sponsorship.

```json
{
  "success": true,
  "params": {
    "sponsorship": "likely sponsorship"
  },
  "jobs": [
    {
      "id": "ed0b2104-93ae-42c2-a221-84ed553f0fbb",
      "company": "copart",
      "title": "Software Engineering Intern 🎓",
      "location": "Dallas, TX",
      "link": "https://copart.wd12.myworkdayjobs.com/copart/job/Dallas-TX---Headquarters/Software-Engineering-Intern_JR107699?utm_source=Simplify&ref=Simplify",
      "sponsorship": "Likely sponsorship",
      "source": "simplify",
      "remote": false,
      "date_posted": null,
      "description": null,
      "tags": [],
      "created_at": "2026-03-10T11:02:53.371494",
      "updated_at": "2026-03-10T11:02:53.371494"
    },
    {
      "id": "ad024357-b96b-4ba9-a56f-4ed1fda9c3b2",
      "company": "copart",
      "title": "Software Engineer Intern",
      "location": "Dallas, TX",
      "link": "https://copart.wd12.myworkdayjobs.com/copart/job/Dallas-TX---Headquarters/Software-Engineering-Intern_JR107700?utm_source=Simplify&ref=Simplify",
      "sponsorship": "Likely sponsorship",
      "source": "simplify",
      "remote": false,
      "date_posted": null,
      "description": null,
      "tags": [],
      "created_at": "2026-03-10T11:02:53.371494",
      "updated_at": "2026-03-10T11:02:53.371494"
    }
  ]
}
```

---

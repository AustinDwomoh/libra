"""
constants.py - Centralized constants and enums for the job scraping system
"""
from enum import Enum
from typing import Final


class PositionType(Enum):
    """Job position types"""
    INTERN = "intern"
    FULLTIME = "fulltime"
    BOTH = "both"
    HYBRID = "hybrid"
    OTHER = "other"


class DatePosted(Enum):
    """Date filter options for job searches"""
    ALL = "all"
    TODAY = "today"
    THREE_DAYS = "3days"
    WEEK = "week"
    MONTH = "month"


class JobSource(Enum):
    """Available job data sources"""
    SIMPLIFY = "simplify"
    JSEARCH = "jsearch"
    REMOTEOK = "remoteok"


class EmploymentType(Enum):
    """Employment type constants from APIs"""
    INTERN = "INTERN"
    FULLTIME = "FULLTIME"


class SponsorshipStatus(Enum):
    """Sponsorship status values"""
    LIKELY = "Likely sponsorship"
    NO_RECORD = "No record found"


# Database field names
class DBFields:
    """Database column names"""
    ID: Final = "id"
    COMPANY: Final = "company"
    TITLE: Final = "title"
    LOCATION: Final = "location"
    LINK: Final = "link"
    SPONSORSHIP: Final = "sponsorship"
    SOURCE: Final = "source"
    REMOTE: Final = "remote"
    DATE_POSTED: Final = "date_posted"
    DESCRIPTION: Final = "description"
    TAGS: Final = "tags"
    CREATED_AT: Final = "created_at"
    UPDATED_AT: Final = "updated_at"
    
    @classmethod
    def updatable_fields(cls) -> list[str]:
        """Returns list of fields that can be updated"""
        return [
            cls.COMPANY, cls.TITLE, cls.LOCATION, cls.LINK,
            cls.SPONSORSHIP, cls.SOURCE, cls.REMOTE,
            cls.DATE_POSTED, cls.DESCRIPTION, cls.TAGS
        ]


# CSV parsing constants
class CSVConfig:
    """CSV parsing configuration"""
    ENCODINGS: Final = ["utf-16", "utf-8", "latin-1", "cp1252"]
    SEPARATORS: Final = ["\t", ",", ";"]
    EMPLOYER_COLUMNS: Final = [
        "EmployerName",
        "Employer",
        "Employer_Name",
        "CompanyName",
        "Employer (Petitioner) Name",
    ]
    MIN_CASES_DEFAULT: Final = 3


# JSearch API constants
class JSearchConfig:
    """JSearch API configuration"""
    DEFAULT_CATEGORIES: Final = ["software", "data science", "marketing"]
    DEFAULT_NUM_PAGES: Final = "10"
    DEFAULT_RETRY_COUNT: Final = 3
    RATE_LIMIT_WAIT_MULTIPLIER: Final = 5
    RATE_LIMIT_DELAY: Final = 2.0
    RETRY_DELAY: Final = 2
    
    
class HTTPStatus:
    """HTTP status codes"""
    OK: Final = 200
    UNAUTHORIZED: Final = 401
    FORBIDDEN: Final = 403
    TOO_MANY_REQUESTS: Final = 429


# Search query templates
class SearchQueries:
    """Search query templates"""
    INTERN_SUFFIX: Final = "intern"
    FULLTIME_SUFFIX: Final = "entry level"
    DEFAULT_QUERY: Final = "developer"


# Job validation constants
class JobValidation:
    """Job validation rules"""
    MIN_TITLE_LENGTH: Final = 1
    MIN_COMPANY_LENGTH: Final = 1
    EXCLUDED_DOMAINS: Final = ["github.com"]
    CONTINUATION_MARKER: Final = "↳"


# Fuzzy matching constants
class FuzzyMatchConfig:
    """Fuzzy matching configuration"""
    DEFAULT_THRESHOLD: Final = 90
    NORMALIZATION_REMOVE: Final = [",", ".", "inc", "llc", "corp"]


# File paths
class FilePaths:
    """Default file paths"""
    SCRAPED_JOBS_JSON: Final = "resources/scraped_jobs.json"
    JSEARCH_RAW_JOBS: Final = "jsearch_raw_jobs.json"
    JSEARCH_JOBS: Final = "jsearch_jobs.json"
    SPONSOR_CACHE: Final = "cache/sponsors.json"


# Logging messages
class LogMessages:
    """Standardized log message templates"""
    
    @staticmethod
    def fetch_start(source: str, position_type: str, date_posted: str) -> str:
        return f"FETCHING FROM: {source.upper()} ({position_type}, posted: {date_posted})"
    
    @staticmethod
    def jobs_found(count: int, query: str) -> str:
        return f"Found {count} positions for '{query}'"
    
    @staticmethod
    def deduplication_result(original: int, unique: int) -> str:
        duplicates = original - unique
        return f"Deduplication: {original} → {unique} jobs ({duplicates} duplicates removed)"
    
    @staticmethod
    def sponsorship_tagged(tagged: int, total: int) -> str:
        return f"Sponsorship tagging complete: {tagged}/{total} with likely sponsorship"
    
    @staticmethod
    def bulk_insert_complete(count: int) -> str:
        return f"Bulk insert completed. {count} jobs processed."


# Statistics keys
class StatsKeys:
    """Keys for statistics dictionary"""
    SIMPLIFY: Final = "simplify"
    JSEARCH: Final = "jsearch"
    REMOTEOK: Final = "remoteok"
    TOTAL_FETCHED: Final = "total_fetched"
    UNIQUE_JOBS: Final = "unique_jobs"
    INSERTED: Final = "inserted"
    WITH_SPONSORSHIP: Final = "with_sponsorship"
    ERRORS: Final = "errors"
    POSITION_TYPE: Final = "position_type"


# Default values
class Defaults:
    """Default values used across the system"""
    UNKNOWN_COMPANY: Final = "Unknown"
    UNKNOWN_LOCATION: Final = "Unknown"
    LOCATION_NOT_SPECIFIED: Final = "Not specified"
    EMPTY_HIGHLIGHTS: Final = {"general": []}
    DEFAULT_INDUSTRY: Final = None
    DEFAULT_SPONSORSHIP: Final = False


# Company validation
class CompanyValidation:
    """Company validation constants"""
    MIN_NAME_LENGTH: Final = 1
    MAX_URL_TIMEOUT: Final = 5
    NORMALIZATION_TERMS: Final = [",", ".", "inc", "llc", "corp", "corporation", "limited"]


# Simplify scraping constants
class SimplifyConfig:
    """Simplify scraper configuration"""
    CONTINUATION_MARKER: Final = "↳"
    MIN_TABLE_COLUMNS: Final = 3
    EXCLUDED_LINK_PREFIXES: Final = ["#"]
    EXCLUDED_LINK_DOMAINS: Final = ["github.com"]
    

# Visa/Sponsorship constants
class VisaConfig:
    """Visa and sponsorship related constants"""
    VISA_CLASS_COLUMN: Final = "VisaClass"
    CASE_STATUS_COLUMN: Final = "CaseStatus"
    H1B_PATTERN: Final = "H-1B"
    APPROVED_PATTERN: Final = "Approved|Certified"
    MIN_SPONSORSHIP_CASES: Final = 3
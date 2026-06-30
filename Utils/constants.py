"""
constants.py - Centralized constants and enums for the job scraping system
"""

from enum import Enum
from typing import Final, List, Dict
import json,re,os,logging
from bs4 import BeautifulSoup
from dotenv import load_dotenv
load_dotenv()

class PositionType(Enum):
    """Job position types"""
    INTERN = "intern"
    FULLTIME = "fulltime"
    PARTIME = "part-time"
    REMOTE = "remote"
    HYBRID = "hybrid"
    OTHER = "other"



class JobSource(Enum):
    """Available job data sources"""

    SIMPLIFY = "simplify"
    JSEARCH = "jsearch"
    REMOTEOK = "remoteok"

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
    PARTTIME_SUFFIX: Final = "part-time"
    REMOTE_SUFFIX: Final = "remote"
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
    JSEARCH_RAW_JOBS: Final = "resources/jsearch_raw_jobs.json"
    JSEARCH_JOBS: Final = "resources/jsearch_jobs.json"
    REMOTEOK_RAW: Final = "resources/remoteok_raw.json"
    REMOTEOK_BEFORE_JOBS: Final = "resources/remoteok_before_jobs.json"
    REMOTEOK_INTERNSHIPS: Final = "resources/remoteok_internships.json"
    SPONSOR_CACHE: Final = "cache/sponsors.json"


# Logging messages
class LogMessages:
    """Standardized log message templates"""

    @staticmethod
    def fetch_start(source: str, position_type: str, date_posted: str) -> str:
        return (
            f"FETCHING FROM: {source.upper()} ({position_type}, posted: {date_posted})"
        )

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


# Simplify scraping constant
class SimplifyConfig:
    """Simplify scraper configuration"""

    CONTINUATION_MARKER: Final = "↳"
    MIN_TABLE_COLUMNS: Final = 3
    EXCLUDED_LINK_PREFIXES: Final = ["#"]
    EXCLUDED_LINK_DOMAINS: Final = ["github.com"]

class DatePosted(Enum):
    """Date filter options for job searches"""
    ALL = "all"
    TODAY = "today"
    THREE_DAYS = "3days"
    WEEK = "week"
    MONTH = "month"


class Config:
    DEFAULT_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md"
    FUZZY_THRESHOLD = 90
    REQUEST_TIMEOUT = 30
    #GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    #GOOGLE_CX = os.getenv("GOOGLE_CX")
    JSEARCH_API_URL = "https://api.openwebninja.com/jsearch/search"
    REMOTEOK= "https://remoteok.com/api"
    J_SEARCH_API_KEY = os.getenv("JSearch_API_Key")
    logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True,
)
    logger = logging.getLogger(__name__)
    GEMINI_KEY = os.getenv("GEMINI_KEY")
    DB_HOST = os.getenv("DB_HOST")
    DB_NAME = os.getenv("DB_NAME")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_PORT = os.getenv("DB_PORT", 5432)
    DISCLAIMER_TEXT = "Data provided is for informational purposes only. We do not guarantee job availability or sponsorship status. Always verify details with the employer directly."
    DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")

    @classmethod
    def save_to_json(cls, jobs: List[Dict], filepath: str = FilePaths.SCRAPED_JOBS_JSON):
        """Save jobs to JSON file for backup/debugging"""
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(jobs, f, indent=2, ensure_ascii=False)
            cls.logger.info(f"✓ Saved {len(jobs)} jobs to {filepath}")
        except Exception as e:
            cls.logger.warning(f"Could not save jobs to JSON: {e}")
           
    @staticmethod
    def strip_html(text: str) -> str:
        return BeautifulSoup(text, "html.parser").get_text(separator=" ").strip()

    @staticmethod
    def clean_ws(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def is_missing(value) -> bool:
        """True if a field value should be treated as unfilled."""
        if value is None:
            return True
        if isinstance(value, str) and value.strip() in ("", "Unknown", "other", "unknown"):
            return True
        if isinstance(value, list) and (len(value) == 0 or all(v is None for v in value)):
            return True
        if isinstance(value, dict) and len(value) == 0:
            return True
        return False


    @staticmethod
    def _norm_amount(s: str) -> float:
        s = s.replace(",", "").strip()
        return float(s[:-1]) * 1000 if s.lower().endswith("k") else float(s)
    
    
    
    # ---------------------------------------------------------------------------- #
    #                             HARD CODED CONSTANTS                             #
    # ---------------------------------------------------------------------------- #


class LLMConstants:
    """Constants related to LLM processing"""
    # scrape_apply_url already caps scraped text at 10000 chars, so there's no
    # point truncating further here — the text is already plain (HTML-stripped)
    # by the time it reaches us. 10000 chars is roughly 2500 tokens, which fits
    # comfortably inside both Groq's context window and Ollama's num_ctx=8192
    # setting (leaving headroom for the prompt template + JSON response).
    _MAX_PROMPT_CHARS = 10000
   
   
    _LLM_PROMPT = """Extract structured data from this job posting.
            Return ONLY valid JSON, no markdown, no explanation.

            Schema:
            {{
            "title": string or null,
            "location": string or null,
            "is_remote": true | false | null,
            "role_type": "full-time" | "part-time" | "contract" | "internship" | "freelance" | "other" | null,
            "pay_range": [min_number, max_number] or [min_number, null] or null,
            "description": string or null,
            "tags": {{
                "experience_years": string or null,
                "skill_0": string,
                "skill_1": string
                ... up to 10 hard skills as skill_0, skill_1, etc.
            }} or null,
            "job_expired": true | false
            }}

            Rules:
            - pay_range must be a 2-element array: [min, max]. Use null for max if only one value.
            Convert shorthand: 80k -> 80000. Return null if no salary info at all.
            - is_remote: true if fully remote, false if on-site or hybrid, null if unclear
            - role_type: default "other" if not determinable
            - tags: experience_years as "5+" or "3-5", plus top hard/technical skills only
            - location: city/country only, null if not mentioned
            - description: clean plain-text summary of the role (2-4 sentences). null if not enough info.
            - job_expired: set to true if the page text contains phrases like "this job is no longer available",
            "position has been filled", "listing has expired", "job not found", "no longer accepting",
            or if the page is clearly a redirect/error/login wall with no actual job content.
            If expired, set description to "This listing is no longer available." and null out all other fields
            you cannot confirm.

            IMPORTANT — only extract from the actual job posting content:
            - Ignore site navigation, headers, footers, cookie banners, and login prompts
            - Ignore generic employer branding or "about us" boilerplate unless it describes this specific role
            - If the scraped text is mostly page chrome with no real job details, treat fields as null rather
            than guessing from surrounding content

            Already known (do not override):
            {known}

            Job posting:
            {text}
    """
    
    # Canonical role types we're willing to store. Anything else gets mapped via
    # keyword sniffing, or falls back to "other" rather than being stored verbatim.
    _VALID_ROLE_TYPES = {"full-time", "part-time", "contract", "internship", "freelance", "other"}

    _ROLE_TYPE_KEYWORDS = (
        # order matters — more specific terms checked first
        (re.compile(r"intern(?:ship)?", re.IGNORECASE), "internship"),
        (re.compile(r"part[\s-]?time", re.IGNORECASE), "part-time"),
        (re.compile(r"contract(?:or)?|temp(?:orary)?", re.IGNORECASE), "contract"),
        (re.compile(r"freelance", re.IGNORECASE), "freelance"),
        (re.compile(r"full[\s-]?time", re.IGNORECASE), "full-time"),
    )
    
    
    _MAX_TAGS = 11  # experience_years + up to 10 skills, matches the prompt schema

    
    _TEXT_FIELD_LIMITS = {"title": 200, "location": 100, "description": 1000}




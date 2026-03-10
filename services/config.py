
import json
import os,logging
import re
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from typing import List, Dict

from services.constants import FilePaths
load_dotenv()
class Config:
    DEFAULT_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md"
    FUZZY_THRESHOLD = 90
    REQUEST_TIMEOUT = 30
    #GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    #GOOGLE_CX = os.getenv("GOOGLE_CX")
    JSEARCH_API_URL = "https://api.openwebninja.com/jsearch/search"
    REMOTEOK= "https://remoteok.com/api"
    J_SEARCH_API_KEY = os.getenv("JSearch_API_Key")
    logging.basicConfig(level=logging.INFO,format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)
    GEMINI_KEY = os.getenv("GEMINI_KEY")
    DB_HOST = os.getenv("DB_HOST")
    DB_NAME = os.getenv("DB_NAME")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_PORT = os.getenv("DB_PORT", 5432)
    DISCLAIMER_TEXT = "Data provided is for informational purposes only. We do not guarantee job availability or sponsorship status. Always verify details with the employer directly."
    DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

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

import os,logging
from dotenv import load_dotenv
load_dotenv()
class Config:
    DEFAULT_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md"
    SPONSORSHIP_CSV = "resources/Employer_info.csv"
    FUZZY_THRESHOLD = 90
    REQUEST_TIMEOUT = 10
    JSEARCH_API_URL = "https://api.openwebninja.com/jsearch/search"
    #REMOTEOK_API_URL = "https://remoteok.com/api"
    J_SEARCH_API_KEY = None #os.getenv("JSearch_API_Key")
    logging.basicConfig(level=logging.INFO,format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)
    DB_HOST = os.getenv("DB_HOST")
    DB_NAME = os.getenv("DB_NAME")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_PORT = os.getenv("DB_PORT", 5432)
    DISCLAIMER_TEXT = "Data provided is for informational purposes only. We do not guarantee job availability or sponsorship status. Always verify details with the employer directly."
    DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")
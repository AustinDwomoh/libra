
from ast import Dict
from services.companies import Job,Company


class Cache:
    """Simple in-memory cache for storing job data during runtime."""
    
    def __init__(self):
        self.job_cache: Dict[str, Job] = {}
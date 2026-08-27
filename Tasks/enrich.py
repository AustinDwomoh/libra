import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Utils.constants import Config
import requests
from Utils.models import Job
from Refine.refine import enrich_unenriched_jobs
from Utils.notify import notify_discord
from Service.db import JobDatabase

async def main():
    await enrich_unenriched_jobs()
    notify_discord("Enrichment process completed successfully.", file_path="logs/enrich.log")
    db = await JobDatabase.create()
    columns = ["title", "location", "is_remote", "description", "apply_url", "role_type", "pay_range", "source", "tags"]
    
if __name__ == "__main__":
    asyncio.run(main())
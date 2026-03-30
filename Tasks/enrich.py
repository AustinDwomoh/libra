import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Refine.refine import enrich_unenriched_jobs

async def main():
    await enrich_unenriched_jobs()

if __name__ == "__main__":
    asyncio.run(main())
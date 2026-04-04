import asyncio
import sys
import os

from Utils.notify import notify_discord

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Service.azalea import Azalea
from Utils.constants import PositionType

async def main():
    azalea = Azalea()
    await azalea.run(position_type=PositionType.INTERN, save_json=False)
    #await azalea.run(position_type=PositionType.FULLTIME, save_json=False)
    notify_discord("Scraping process completed successfully.", file_path="logs/scrape.log")

if __name__ == "__main__":
    asyncio.run(main())
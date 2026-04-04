import os

import requests
from Utils.constants import Config

def notify_discord(message: str, file_path: str = ''):
    webhook_url = Config.DISCORD_WEBHOOK
    if not webhook_url:
        Config.logger.warning("No Discord webhook found. Skipping.")
        return

    try:
        if file_path:
            with open(file_path, "rb") as f:
                response = requests.post(
                    webhook_url,
                    data={"content": message},        # message goes in data=
                    files={"file": (os.path.basename(file_path), f)}  # file goes in files=
                )
        else:
            response = requests.post(webhook_url, json={"content": message})
        
        response.raise_for_status()
    except Exception as e:
        Config.logger.error(f"Failed to send Discord notification: {e}")

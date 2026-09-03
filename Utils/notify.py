import os,  requests, json
from Utils.constants import Config
from Utils.run_logging import get_logger

logger = get_logger(__name__)

def notify_discord(message: str = '', file_path: str = '', embed: dict = None): #type: ignore
    webhook_url = Config.DISCORD_WEBHOOK
    if not webhook_url:
        logger.warning("No Discord webhook found. Skipping.")
        return

    payload = {}
    if message:
        payload["content"] = message
    if embed:
        payload["embeds"] = [embed]

    try:
        if file_path:
            with open(file_path, "rb") as f:
                response = requests.post(
                    webhook_url,
                    data={"payload_json": json.dumps(payload)}, #type: ignore
                    files={"file": (os.path.basename(file_path), f)}
                )
        else:
            response = requests.post(webhook_url, json=payload)

        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to send Discord notification: {e}")
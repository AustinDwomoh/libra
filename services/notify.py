import requests
from services.config import Config

def notify_discord(message: str):
    webhook_url = Config.DISCORD_WEBHOOK
    if not webhook_url:
        print("⚠️ No Discord webhook found in environment (DISCORD_WEBHOOK). Skipping notification.")
        return

    payload = {"content": message}
    try:
        response = requests.post(webhook_url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ Failed to send Discord notification: {e}")

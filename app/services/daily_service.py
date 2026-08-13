import logging
import os

import requests
from flask import current_app
logger = logging.getLogger(__name__)

DAILY_API_URL = "https://api.daily.co/v1"

class DailyService:
    @staticmethod
    def _get_api_key():
        return (current_app.config.get('DAILY_API_KEY') or os.environ.get('DAILY_API_KEY') or '').strip()

    @staticmethod
    def _get_headers():
        api_key = DailyService._get_api_key()
        if not api_key:
            logger.error("DAILY_API_KEY is not set in environment variables")
            raise ValueError("Daily API key is not configured")
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    @staticmethod
    def get_or_create_room(room_name: str) -> str:
        """
        Creates a private room in Daily or returns its URL if it already exists.
        Returns the room_url.
        """
        headers = DailyService._get_headers()
        
        # Check if room already exists
        check_url = f"{DAILY_API_URL}/rooms/{room_name}"
        try:
            resp = requests.get(check_url, headers=headers, timeout=5)
            if resp.status_code == 200:
                room_url = (resp.json() or {}).get("url")
                if room_url:
                    return room_url
                logger.error("Daily returned an existing room without URL: %s", room_name)
                raise RuntimeError("Daily room response did not include a URL")
        except requests.RequestException as e:
            logger.warning(f"Error checking Daily room {room_name}: {e}")
            # Continue to try creating it if check fails (might be 404)
            pass

        # Create the room
        create_url = f"{DAILY_API_URL}/rooms"
        payload = {
            "name": room_name,
            "privacy": "private",
            "properties": {
                "enable_chat": True,
                "enable_screenshare": True,
            }
        }
        
        try:
            resp = requests.post(create_url, headers=headers, json=payload, timeout=5)
            if resp.status_code in (200, 201):
                room_url = (resp.json() or {}).get("url")
                if room_url:
                    return room_url
                logger.error("Daily created a room without URL: %s", room_name)
                raise RuntimeError("Daily room response did not include a URL")
            elif resp.status_code == 400 and "already exists" in resp.text:
                # In case of race condition, check again
                resp = requests.get(check_url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    room_url = (resp.json() or {}).get("url")
                    if room_url:
                        return room_url
            
            logger.error("Daily room creation failed for %s (HTTP %s)", room_name, resp.status_code)
            raise RuntimeError("Failed to create video room")
            
        except requests.RequestException as e:
            logger.error(f"Request exception creating Daily room {room_name}: {e}")
            raise RuntimeError("Failed to connect to video provider")

    @staticmethod
    def create_meeting_token(room_name: str, user_name: str, is_owner: bool) -> str:
        """
        Creates a meeting token scoped to the room.
        """
        headers = DailyService._get_headers()
        create_url = f"{DAILY_API_URL}/meeting-tokens"
        
        payload = {
            "properties": {
                "room_name": room_name,
                "is_owner": is_owner,
                "user_name": user_name
            }
        }
        
        try:
            resp = requests.post(create_url, headers=headers, json=payload, timeout=5)
            if resp.status_code in (200, 201):
                token = (resp.json() or {}).get("token")
                if token:
                    return token
                logger.error("Daily created a meeting token without token value for %s", room_name)
                raise RuntimeError("Daily meeting-token response did not include a token")
            logger.error("Daily meeting-token creation failed for %s (HTTP %s)", room_name, resp.status_code)
            raise RuntimeError("Failed to create meeting token")
        except requests.RequestException as e:
            logger.error(f"Request exception creating meeting token for {room_name}: {e}")
            raise RuntimeError("Failed to connect to video provider")

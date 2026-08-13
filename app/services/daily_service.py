import logging
import os

import requests
from flask import current_app
logger = logging.getLogger(__name__)

class DailyService:
    @staticmethod
    def _get_api_key():
        return (current_app.config.get('DAILY_API_KEY') or os.environ.get('DAILY_API_KEY') or '').strip()

    @staticmethod
    def _get_api_url():
        url = (current_app.config.get('DAILY_API_URL') or os.environ.get('DAILY_API_URL') or 'https://api.daily.co/v1').strip()
        return url.rstrip('/')

    @staticmethod
    def _get_proxies():
        proxy = (current_app.config.get('DAILY_PROXY') or os.environ.get('DAILY_PROXY') or os.environ.get('HTTPS_PROXY') or '').strip()
        if proxy:
            return {'http': proxy, 'https': proxy}
        return None

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

    @classmethod
    def get_or_create_room(cls, room_name: str) -> str:
        """
        Creates a private room in Daily or returns its URL if it already exists.
        Returns the room_url.
        """
        headers = cls._get_headers()
        base_url = cls._get_api_url()
        proxies = cls._get_proxies()
        
        # Check if room already exists
        check_url = f"{base_url}/rooms/{room_name}"
        try:
            resp = requests.get(check_url, headers=headers, proxies=proxies, timeout=5)
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
        create_url = f"{base_url}/rooms"
        payload = {
            "name": room_name,
            "privacy": "private",
            "properties": {
                "enable_chat": True,
                "enable_screenshare": True,
            }
        }
        
        try:
            resp = requests.post(create_url, headers=headers, json=payload, proxies=proxies, timeout=5)
            if resp.status_code in (200, 201):
                room_url = (resp.json() or {}).get("url")
                if room_url:
                    return room_url
                logger.error("Daily created a room without URL: %s", room_name)
                raise RuntimeError("Daily room response did not include a URL")
            elif resp.status_code == 400 and "already exists" in resp.text:
                # In case of race condition, check again
                resp = requests.get(check_url, headers=headers, proxies=proxies, timeout=5)
                if resp.status_code == 200:
                    room_url = (resp.json() or {}).get("url")
                    if room_url:
                        return room_url
            
            logger.error("Daily room creation failed for %s (HTTP %s)", room_name, resp.status_code)
            raise RuntimeError("Failed to create video room")
            
        except requests.RequestException as e:
            logger.error(f"Request exception creating Daily room {room_name}: {e}")
            raise RuntimeError("Failed to connect to video provider")

    @classmethod
    def create_meeting_token(cls, room_name: str, user_name: str, is_owner: bool) -> str:
        """
        Creates a meeting token scoped to the room.
        """
        headers = cls._get_headers()
        base_url = cls._get_api_url()
        proxies = cls._get_proxies()
        create_url = f"{base_url}/meeting-tokens"
        
        payload = {
            "properties": {
                "room_name": room_name,
                "is_owner": is_owner,
                "user_name": user_name
            }
        }
        
        try:
            resp = requests.post(create_url, headers=headers, json=payload, proxies=proxies, timeout=5)
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

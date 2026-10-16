"""
Service for self-hosted LiveKit WebRTC video integration in BooStudy.
Handles LiveKit JWT access token generation and backend server-to-server admin APIs.
"""
import os
import time
import json
import logging
from typing import Optional, Dict, Any, Tuple
import requests

logger = logging.getLogger(__name__)


class LiveKitService:
    @staticmethod
    def get_url(request_host: Optional[str] = None) -> str:
        """Get the LiveKit server URL (e.g., ws://localhost:7880 or wss://livekit.boostudy.ru)."""
        env_url = os.environ.get('LIVEKIT_URL')
        if env_url:
            return env_url.rstrip('/')
        if request_host:
            host_clean = request_host.split(':')[0]
            if host_clean and host_clean != '0.0.0.0':
                return f"ws://{host_clean}:7880"
        return 'ws://localhost:7880'

    @staticmethod
    def get_http_url() -> str:
        """Get the HTTP/HTTPS URL corresponding to LiveKit server for Twirp admin API calls."""
        ws_url = LiveKitService.get_url()
        if ws_url.startswith('wss://'):
            return 'https://' + ws_url[6:]
        elif ws_url.startswith('ws://'):
            return 'http://' + ws_url[5:]
        return ws_url

    @staticmethod
    def get_api_key() -> str:
        return os.environ.get('LIVEKIT_API_KEY', 'devkey')

    @staticmethod
    def get_api_secret() -> str:
        return os.environ.get('LIVEKIT_API_SECRET', 'secretdevsecret1234567890abcdef1234567890')

    @staticmethod
    def get_mode() -> str:
        """Get current LiveKit deployment mode: 'disabled', 'pilot', or 'enabled'."""
        return os.environ.get('LIVEKIT_MODE', 'pilot').strip().lower()

    @staticmethod
    def is_enabled_for_user(user, lesson=None) -> bool:
        """
        Server-side gating for LiveKit video calls.
        - 'disabled' / 'off' / 'false': Completely disabled.
        - 'pilot' / 'test': Enabled ONLY for:
            1. Creator or SuperAdmin users (user.is_creator() or user.is_admin())
            2. User IDs explicitly listed in LIVEKIT_PILOT_USER_IDS env var
            3. In a lesson where the teacher is creator/admin or listed in LIVEKIT_PILOT_USER_IDS
            4. In pytest test suite (current_app.config.get('TESTING'))
        - 'enabled' / 'all' / 'true': Enabled for all users in production.
        URL query parameters CANNOT bypass this gating.
        """
        try:
            from flask import current_app
            if current_app and current_app.config.get('TESTING'):
                return True
        except Exception:
            pass

        mode = LiveKitService.get_mode()
        if mode in ('disabled', 'off', 'false', '0'):
            return False
        if mode in ('enabled', 'all', 'true', '1'):
            return True
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        if getattr(user, 'is_creator', lambda: False)() or getattr(user, 'is_admin', lambda: False)():
            return True
        pilot_ids = [s.strip() for s in os.environ.get('LIVEKIT_PILOT_USER_IDS', '').split(',') if s.strip()]
        user_id_str = str(getattr(user, 'id', ''))
        if user_id_str and user_id_str in pilot_ids:
            return True
        if lesson:
            student = getattr(lesson, 'student', None)
            teacher_id = getattr(student, 'teacher_id', None) if student else None
            if teacher_id and str(teacher_id) in pilot_ids:
                return True
            teacher_user = getattr(student, 'teacher', None) if student else None
            if teacher_user:
                u = getattr(teacher_user, 'user', None) or teacher_user
                if getattr(u, 'is_creator', lambda: False)() or getattr(u, 'is_admin', lambda: False)():
                    return True
        return False

    @classmethod
    def create_token(
        cls,
        room_name: str,
        identity: str,
        name: str,
        is_teacher: bool = False,
        valid_seconds: int = 21600,  # 6 hours default
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate a LiveKit JWT access token for joining a video room.
        Follows LiveKit standard token claims format:
        https://docs.livekit.io/home/server/generating-tokens/
        """
        now = int(time.time())
        api_key = cls.get_api_key()
        api_secret = cls.get_api_secret()

        video_grants = {
            'room': room_name,
            'roomJoin': True,
            'canPublish': True,
            'canSubscribe': True,
            'canPublishData': True,
            'canPublishSources': [
                'camera',
                'microphone',
                'screen_share',
                'screen_share_audio'
            ],
            'roomAdmin': bool(is_teacher),
            'roomRecord': False,
            'hidden': False
        }

        payload = {
            'iss': api_key,
            'sub': str(identity),
            'name': str(name),
            'iat': now,
            'nbf': now - 5,
            'exp': now + max(60, valid_seconds),
            'video': video_grants
        }

        if metadata:
            payload['metadata'] = json.dumps(metadata, ensure_ascii=False)

        return cls._encode_jwt(payload, api_secret)

    @staticmethod
    def _encode_jwt(payload: Dict[str, Any], secret: str) -> str:
        """Encode a JWT using HS256 with standard library (zero external dependencies)."""
        import base64
        import hmac
        import hashlib
        header = {'alg': 'HS256', 'typ': 'JWT'}
        b64_h = base64.urlsafe_b64encode(json.dumps(header, separators=(',', ':')).encode('utf-8')).decode('ascii').rstrip('=')
        b64_p = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).decode('ascii').rstrip('=')
        signing_input = f"{b64_h}.{b64_p}"
        sig = hmac.new(secret.encode('utf-8'), signing_input.encode('utf-8'), hashlib.sha256).digest()
        b64_sig = base64.urlsafe_b64encode(sig).decode('ascii').rstrip('=')
        return f"{signing_input}.{b64_sig}"

    @classmethod
    def create_admin_token(cls, room_name: str, valid_seconds: int = 60) -> str:
        """Generate a short-lived admin token for server-to-server twirp calls."""
        now = int(time.time())
        api_key = cls.get_api_key()
        api_secret = cls.get_api_secret()

        payload = {
            'iss': api_key,
            'sub': 'boostudy-server-admin',
            'iat': now,
            'nbf': now - 5,
            'exp': now + max(30, valid_seconds),
            'video': {
                'room': room_name,
                'roomAdmin': True,
                'roomCreate': True,
                'roomList': True
            }
        }
        return cls._encode_jwt(payload, api_secret)

    @classmethod
    def admin_mute_participant(
        cls,
        room_name: str,
        identity: str,
        track_sid: str,
        muted: bool = True
    ) -> Tuple[bool, str]:
        """Admin API call to mute a participant's published track."""
        url = f"{cls.get_http_url()}/twirp/livekit.RoomService/MutePublishedTrack"
        headers = {
            'Authorization': f"Bearer {cls.create_admin_token(room_name)}",
            'Content-Type': 'application/json'
        }
        body = {
            'room': room_name,
            'identity': identity,
            'track_sid': track_sid,
            'muted': bool(muted)
        }
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=5)
            if resp.status_code == 200:
                return True, "Успешно"
            return False, f"Ошибка LiveKit ({resp.status_code}): {resp.text}"
        except Exception as e:
            logger.warning("LiveKit admin_mute_participant failed: %s", e)
            return False, f"Сетевая ошибка при связи с LiveKit: {str(e)}"

    @classmethod
    def admin_remove_participant(cls, room_name: str, identity: str) -> Tuple[bool, str]:
        """Admin API call to kick/remove a participant from the room."""
        url = f"{cls.get_http_url()}/twirp/livekit.RoomService/RemoveParticipant"
        headers = {
            'Authorization': f"Bearer {cls.create_admin_token(room_name)}",
            'Content-Type': 'application/json'
        }
        body = {
            'room': room_name,
            'identity': identity
        }
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=5)
            if resp.status_code == 200:
                return True, "Участник отключён"
            return False, f"Ошибка LiveKit ({resp.status_code}): {resp.text}"
        except Exception as e:
            logger.warning("LiveKit admin_remove_participant failed: %s", e)
            return False, f"Сетевая ошибка при связи с LiveKit: {str(e)}"

    @classmethod
    def admin_delete_room(cls, room_name: str) -> Tuple[bool, str]:
        """Admin API call to terminate/end a room for everyone."""
        url = f"{cls.get_http_url()}/twirp/livekit.RoomService/DeleteRoom"
        headers = {
            'Authorization': f"Bearer {cls.create_admin_token(room_name)}",
            'Content-Type': 'application/json'
        }
        body = {'room': room_name}
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=5)
            if resp.status_code == 200:
                return True, "Комната завершена"
            return False, f"Ошибка LiveKit ({resp.status_code}): {resp.text}"
        except Exception as e:
            logger.warning("LiveKit admin_delete_room failed: %s", e)
            return False, f"Сетевая ошибка при связи с LiveKit: {str(e)}"

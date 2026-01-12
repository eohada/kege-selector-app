"""
Менеджер окружений для удаленной админки
Управляет выбором и переключением между production и sandbox
"""
import os
import requests
import logging
from typing import Dict, Optional, Tuple
from flask import session, current_app

logger = logging.getLogger(__name__)

# Конфигурация окружений
ENVIRONMENTS = {
    'production': {
        'name': 'Production',
        'url': os.environ.get('PRODUCTION_URL', ''),
        'token': os.environ.get('PRODUCTION_ADMIN_TOKEN', ''),
        'description': 'Основное рабочее окружение'
    },
    'sandbox': {
        'name': 'Sandbox',
        'url': os.environ.get('SANDBOX_URL', ''),
        'token': os.environ.get('SANDBOX_ADMIN_TOKEN', ''),
        'description': 'Тестовое окружение'
    }
}


def get_current_environment() -> str:
    """Получить текущее выбранное окружение из сессии"""
    return session.get('remote_admin_environment', 'production')


def set_current_environment(env: str) -> bool:
    """Установить текущее окружение в сессию"""
    if env in ENVIRONMENTS:
        session['remote_admin_environment'] = env
        session.permanent = True
        return True
    return False


def get_environment_config(env: Optional[str] = None) -> Dict:
    """Получить конфигурацию окружения"""
    if env is None:
        env = get_current_environment()
    
    return ENVIRONMENTS.get(env, {})


def is_environment_configured(env: Optional[str] = None) -> bool:
    """Проверить, настроено ли окружение"""
    config = get_environment_config(env)
    return bool(config.get('url') and config.get('token'))


def make_remote_request(method: str, path: str, payload: Optional[Dict] = None, env: Optional[str] = None) -> requests.Response:
    """
    Выполнить запрос к удаленному API окружения
    
    Args:
        method: HTTP метод (GET, POST, etc.)
        path: Путь API (начинается с /)
        payload: Тело запроса для POST/PUT
        env: Окружение (если None, используется текущее из сессии)
    
    Returns:
        Response объект requests
    """
    config = get_environment_config(env)
    base_url = config.get('url', '').rstrip('/')
    token = config.get('token', '')
    
    if not base_url or not token:
        raise RuntimeError(f'Environment {env or get_current_environment()} is not configured')
    
    url = f"{base_url}{path}"
    headers = {
        'X-Admin-Token': token,
        'User-Agent': 'Remote-Admin/1.0',
        'Content-Type': 'application/json'
    }
    timeout = 10
    
    if method.upper() == 'GET':
        return requests.get(url, headers=headers, timeout=timeout)
    elif method.upper() == 'POST':
        return requests.post(url, headers=headers, json=(payload or {}), timeout=timeout)
    elif method.upper() == 'PUT':
        return requests.put(url, headers=headers, json=(payload or {}), timeout=timeout)
    elif method.upper() == 'DELETE':
        return requests.delete(url, headers=headers, timeout=timeout)
    else:
        raise ValueError(f'Unsupported HTTP method: {method}')


def get_environment_status(env: str) -> Dict:
    """Получить статус окружения (доступность, статистика)"""
    config = get_environment_config(env)
    
    if not is_environment_configured(env):
        return {
            'configured': False,
            'available': False,
            'error': 'Environment not configured'
        }
    
    try:
        resp = make_remote_request('GET', '/internal/remote-admin/status', env=env)
        if resp.status_code == 200:
            data = resp.json()
            return {
                'configured': True,
                'available': True,
                'status': data.get('status', 'unknown'),
                'stats': data.get('stats', {})
            }
        else:
            return {
                'configured': True,
                'available': False,
                'error': f'HTTP {resp.status_code}'
            }
    except Exception as e:
        logger.error(f"Error checking environment {env} status: {e}")
        return {
            'configured': True,
            'available': False,
            'error': str(e)
        }


def get_all_environments_status() -> Dict[str, Dict]:
    """Получить статус всех окружений"""
    return {
        env: get_environment_status(env)
        for env in ENVIRONMENTS.keys()
    }

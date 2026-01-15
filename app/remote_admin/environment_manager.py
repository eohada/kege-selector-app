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

# Конфигурация окружений - динамически загружается из переменных окружения
def _load_environments() -> Dict:
    """Загрузить конфигурацию окружений из переменных окружения"""
    envs = {}
    
    # Production окружение
    prod_url = os.environ.get('PRODUCTION_URL', '').strip()
    prod_token = os.environ.get('PRODUCTION_ADMIN_TOKEN', '').strip()
    if prod_url or prod_token:
        envs['production'] = {
            'name': 'Production',
            'url': prod_url,
            'token': prod_token,
            'description': 'Основное рабочее окружение'
        }
    
    # Sandbox окружение
    sandbox_url = os.environ.get('SANDBOX_URL', '').strip()
    sandbox_token = os.environ.get('SANDBOX_ADMIN_TOKEN', '').strip()
    if sandbox_url or sandbox_token:
        envs['sandbox'] = {
            'name': 'Sandbox',
            'url': sandbox_url,
            'token': sandbox_token,
            'description': 'Тестовое окружение'
        }
    
    # Admin окружение (новое отдельное окружение для удаленной админки)
    admin_url = os.environ.get('ADMIN_URL', '').strip()
    admin_token = os.environ.get('ADMIN_ADMIN_TOKEN', '').strip()
    if admin_url or admin_token:
        envs['admin'] = {
            'name': 'Admin',
            'url': admin_url,
            'token': admin_token,
            'description': 'Окружение удаленной админки'
        }
    
    # Поддержка произвольных окружений через переменные вида ENV_<NAME>_URL и ENV_<NAME>_TOKEN
    # Например: ENV_STAGING_URL и ENV_STAGING_TOKEN создадут окружение 'staging'
    env_vars = {}
    for key, value in os.environ.items():
        if key.startswith('ENV_') and key.endswith('_URL'):
            env_name = key[4:-4].lower()  # ENV_STAGING_URL -> staging
            if env_name not in envs:
                env_vars[env_name] = {'url': value.strip()}
        elif key.startswith('ENV_') and key.endswith('_TOKEN'):
            env_name = key[4:-6].lower()  # ENV_STAGING_TOKEN -> staging
            if env_name not in env_vars:
                env_vars[env_name] = {}
            env_vars[env_name]['token'] = value.strip()
    
    # Добавляем произвольные окружения
    for env_name, config in env_vars.items():
        if config.get('url') or config.get('token'):
            envs[env_name] = {
                'name': env_name.capitalize(),
                'url': config.get('url', ''),
                'token': config.get('token', ''),
                'description': f'Окружение {env_name}'
            }
    
    return envs


# Глобальный словарь окружений (обновляется при каждом обращении)
def get_environments() -> Dict:
    """Получить актуальный список окружений"""
    return _load_environments()


def get_current_environment() -> str:
    """Получить текущее выбранное окружение из сессии"""
    envs = get_environments()
    default_env = 'admin' if 'admin' in envs else (list(envs.keys())[0] if envs else 'production')
    return session.get('remote_admin_environment', default_env)


def set_current_environment(env: str) -> bool:
    """Установить текущее окружение в сессию"""
    envs = get_environments()
    if env in envs:
        session['remote_admin_environment'] = env
        session.permanent = True
        return True
    return False


def get_environment_config(env: Optional[str] = None) -> Dict:
    """Получить конфигурацию окружения"""
    if env is None:
        env = get_current_environment()
    
    envs = get_environments()
    return envs.get(env, {})


def is_environment_configured(env: Optional[str] = None) -> bool:
    """Проверить, настроено ли окружение"""
    config = get_environment_config(env)
    return bool(config.get('url') and config.get('token'))


def make_remote_request(method: str, path: str, payload: Optional[Dict] = None, env: Optional[str] = None) -> requests.Response:
    """
    Выполнить запрос к удаленному API окружения
    """
    if env is None:
        env = get_current_environment()
        
    config = get_environment_config(env)
    base_url = config.get('url', '').rstrip('/')
    token = config.get('token', '')
    
    if not base_url or not token:
        # Вместо RuntimeError возвращаем мок-ответ с ошибкой, чтобы не валить приложение 500-й
        logger.warning(f"Environment {env} is not configured correctly")
        mock_resp = requests.Response()
        mock_resp.status_code = 503
        mock_resp._content = b'{"error": "Environment not configured"}'
        return mock_resp
    
    url = f"{base_url}{path}"
    headers = {
        'X-Admin-Token': token,
        'User-Agent': 'Remote-Admin/1.0',
        'Content-Type': 'application/json'
    }
    timeout = 5 # Уменьшаем таймаут до 5 секунд
    
    try:
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
    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed to {url}: {e}")
        mock_resp = requests.Response()
        mock_resp.status_code = 502
        mock_resp._content = f'{{"error": "Connection failed: {str(e)}"}}'.encode('utf-8')
        return mock_resp


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
        # Используем отдельный таймаут для проверки статуса
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
    envs = get_environments()
    return {
        env: get_environment_status(env)
        for env in envs.keys()
    }

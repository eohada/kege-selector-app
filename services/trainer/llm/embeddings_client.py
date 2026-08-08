"""
Клиент GigaChat Embeddings для RAG.

Использует GigaChat API embeddings (model Embeddings или Embeddings-2).
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def get_embeddings(texts: list[str], model: str = 'Embeddings') -> list[list[float]]:
    """
    Получить эмбеддинги для списка текстов через GigaChat API.

    Args:
        texts: список строк для эмбеддинга
        model: 'Embeddings', 'Embeddings-2' или 'EmbeddingsGigaR'

    Returns:
        список векторов (каждый — list[float])

    Raises:
        RuntimeError: если нет credentials или API ошибка
    """
    creds = (os.environ.get('GIGACHAT_CREDENTIALS') or '').strip()
    if not creds:
        raise RuntimeError('GIGACHAT_CREDENTIALS не задан')

    try:
        from gigachat import GigaChat
    except ImportError as e:
        raise RuntimeError(f'Установите gigachat: pip install gigachat. {e}') from e

    verify_env = (os.environ.get('GIGACHAT_VERIFY_SSL_CERTS') or 'true').strip().lower()
    verify_ssl = verify_env not in ('0', 'false', 'no')
    ca_bundle = (os.environ.get('GIGACHAT_CA_BUNDLE_FILE') or '').strip() or None
    scope = (os.environ.get('GIGACHAT_SCOPE') or 'GIGACHAT_API_PERS').strip()
    timeout = float(os.environ.get('TRAINER_LLM_TIMEOUT_SECONDS', '30'))

    kwargs: dict[str, Any] = {
        'credentials': creds,
        'scope': scope,
        'verify_ssl_certs': verify_ssl,
        'timeout': timeout,
    }
    if ca_bundle:
        kwargs['ca_bundle_file'] = ca_bundle

    # Ограничение: API принимает до N строк за раз (обычно ~100)
    batch_size = 32
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        if not batch:
            continue
        try:
            with GigaChat(**kwargs) as giga:
                response = giga.embeddings(batch, model=model)
        except Exception as e:
            logger.warning('GigaChat embeddings error: %s', str(e)[:300])
            raise RuntimeError(f'gigachat_embeddings_error: {e}') from e

        # Парсим ответ: response.data — список {embedding: [...], index: N}
        data = getattr(response, 'data', None) or []
        items = sorted(data, key=lambda x: getattr(x, 'index', 0)) if data else []
        for item in items:
            emb = getattr(item, 'embedding', None)
            all_embeddings.append(list(emb) if emb is not None else [])

    return all_embeddings

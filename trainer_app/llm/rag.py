"""
RAG для подсказок: поиск похожих примеров в индексе эталонных подсказок.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# Путь к индексу ChromaDB (relative to project root)
_INDEX_PATH: str | None = None
_COLLECTION_NAME = 'hints'


def _get_index_path() -> str:
    global _INDEX_PATH
    if _INDEX_PATH is None:
        base = os.environ.get('RAG_HINTS_INDEX_PATH', '').strip()
        if base:
            _INDEX_PATH = os.path.abspath(base)
        else:
            # trainer_app/llm/rag.py -> project_root/data/rag_hints
            _INDEX_PATH = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'rag_hints')
            )
    return _INDEX_PATH


def _strip_html(s: str) -> str:
    s = (s or '').strip()
    if not s:
        return ''
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:2000]


def retrieve_similar_hints(task_text: str, hint_level: int | None = None, k: int = 3) -> list[str]:
    """
    Ищет похожие подсказки в RAG-индексе по тексту задачи.

    Args:
        task_text: условие задачи (HTML или plain text)
        hint_level: уровень подсказки (1, 2, 3) — пока не фильтруем, индекс общий
        k: количество ближайших примеров

    Returns:
        список текстов подсказок (в порядке убывания релевантности)
    """
    if not task_text or len(_strip_html(task_text)) < 10:
        return []

    index_path = _get_index_path()
    if not os.path.exists(index_path):
        logger.debug('RAG index not found: %s', index_path)
        return []

    creds = (os.environ.get('GIGACHAT_CREDENTIALS') or '').strip()
    if not creds:
        logger.debug('GIGACHAT_CREDENTIALS not set, skip RAG')
        return []

    try:
        import chromadb
        from trainer_app.llm.embeddings_client import get_embeddings
    except ImportError as e:
        logger.warning('RAG imports failed: %s', e)
        return []

    try:
        client = chromadb.PersistentClient(path=index_path)
        collection = client.get_collection(name=_COLLECTION_NAME)
    except Exception as e:
        logger.warning('RAG collection load failed: %s', e)
        return []

    query_text = _strip_html(task_text)
    if len(query_text) < 10:
        return []

    try:
        query_embeddings = get_embeddings([query_text])
    except Exception as e:
        logger.warning('RAG embeddings failed: %s', str(e)[:200])
        return []

    if not query_embeddings:
        return []

    try:
        results = collection.query(
            query_embeddings=query_embeddings,
            n_results=min(k, collection.count()),
            include=['metadatas'],
        )
    except Exception as e:
        logger.warning('RAG query failed: %s', e)
        return []

    metas = results.get('metadatas') or []
    if not metas or not metas[0]:
        return []

    hints = []
    for m in metas[0]:
        if isinstance(m, dict) and m.get('hint'):
            hints.append(str(m['hint']).strip())
    return hints[:k]


def get_rag_examples_prompt(task_text: str, k: int = 3) -> str:
    """
    Возвращает строку для добавления в system prompt с примерами подсказок из RAG.
    Если RAG недоступен или пуст — возвращает пустую строку.
    """
    hints = retrieve_similar_hints(task_text, k=k)
    if not hints:
        return ''
    lines = ['Примеры подсказок из эталонов (стиль, на который ориентируйся):']
    for i, h in enumerate(hints, 1):
        lines.append(f'  {i}. {h}')
    return '\n'.join(lines)

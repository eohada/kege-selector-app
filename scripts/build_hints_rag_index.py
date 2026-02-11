#!/usr/bin/env python3
"""
Скрипт построения RAG-индекса подсказок для тренажёра.

Читает train_hints.jsonl, получает эмбеддинги через GigaChat Embeddings,
сохраняет в ChromaDB (persistent).

Требуется: GIGACHAT_CREDENTIALS в окружении.

Запуск:
  python scripts/build_hints_rag_index.py [--input exports/train_hints.jsonl] [--index data/rag_hints]
"""
import sys
import os
import json
import argparse
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DEFAULT_INPUT = os.path.join(REPO_ROOT, 'exports', 'train_hints.jsonl')
DEFAULT_INDEX = os.path.join(REPO_ROOT, 'data', 'rag_hints')


def _strip_html(s: str) -> str:
    import re
    s = (s or '').strip()
    if not s:
        return ''
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:2000]  # ограничение для эмбеддинга


def load_hint_samples(path: str) -> list[dict]:
    """Загружает сэмплы из JSONL."""
    samples = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                samples.append(data)
            except json.JSONDecodeError as e:
                logger.warning('Skip invalid JSON: %s', e)
    return samples


def main():
    parser = argparse.ArgumentParser(description='Построение RAG-индекса подсказок')
    parser.add_argument('--input', default=DEFAULT_INPUT, help='Путь к train_hints.jsonl')
    parser.add_argument('--index', default=DEFAULT_INDEX, help='Каталог для ChromaDB')
    parser.add_argument('--batch-size', type=int, default=20, help='Размер батча для embeddings')
    parser.add_argument('--collection', default='hints', help='Имя коллекции ChromaDB')
    args = parser.parse_args()

    input_path = os.path.abspath(args.input)
    index_path = os.path.abspath(args.index)

    if not os.path.exists(input_path):
        logger.error('Файл не найден: %s', input_path)
        logger.info('Сначала выполните: python scripts/export_training_data.py --output-dir exports')
        sys.exit(1)

    creds = (os.environ.get('GIGACHAT_CREDENTIALS') or '').strip()
    if not creds:
        logger.error('GIGACHAT_CREDENTIALS не задан. Задайте переменную окружения.')
        sys.exit(1)

    samples = load_hint_samples(input_path)
    logger.info('Загружено сэмплов: %d', len(samples))

    # Извлекаем поля для индекса
    documents = []
    metadatas = []
    for i, sample in enumerate(samples):
        msgs = sample.get('messages', [])
        if not msgs:
            continue
        user_content = ''
        assistant_content = ''
        for m in msgs:
            role = (m.get('role') or '').strip().lower()
            content = (m.get('content') or '').strip()
            if role == 'user':
                user_content = content
            elif role == 'assistant':
                assistant_content = content
        if not user_content or not assistant_content:
            continue
        # Текст для поиска: условие задачи (из user) — ищем по нему
        doc_text = _strip_html(user_content)
        if len(doc_text) < 20:
            continue
        documents.append(doc_text)
        metadatas.append({
            'hint': assistant_content[:1500],
            'idx': i,
        })

    logger.info('Документов для индексации: %d', len(documents))
    if not documents:
        logger.error('Нет документов для индексации')
        sys.exit(1)

    # Эмбеддинги через GigaChat
    from trainer_app.llm.embeddings_client import get_embeddings

    embeddings_list = []
    batch_size = args.batch_size
    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        logger.info('Embeddings batch %d-%d / %d', i, min(i + batch_size, len(documents)), len(documents))
        try:
            embs = get_embeddings(batch)
            embeddings_list.extend(embs)
        except Exception as e:
            logger.error('Ошибка embeddings: %s', e)
            sys.exit(1)

    if len(embeddings_list) != len(documents):
        logger.error('Несоответствие количества эмбеддингов: %d != %d', len(embeddings_list), len(documents))
        sys.exit(1)

    # Сохраняем в ChromaDB
    import chromadb

    os.makedirs(index_path, exist_ok=True)
    client = chromadb.PersistentClient(path=index_path)
    collection_name = args.collection
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.create_collection(name=collection_name, metadata={'description': 'hints RAG'})
    ids = [f'hint_{i}' for i in range(len(documents))]
    collection.add(ids=ids, embeddings=embeddings_list, documents=documents, metadatas=metadatas)
    logger.info('Индекс сохранён: %s (%d записей)', index_path, len(documents))
    print(f'\n[OK] RAG-индекс готов: {index_path}')

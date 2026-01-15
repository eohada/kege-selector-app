"""
Модели данных для хранения репортов и их статусов
"""
import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict
from pathlib import Path


class ReportDatabase:
    """Класс для работы с базой данных репортов"""
    
    def __init__(self, db_path: str = "data/reports.db"):
        """
        Инициализация базы данных
        
        Args:
            db_path: Путь к файлу базы данных SQLite
        """
        # Создаем директорию, если её нет
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Создание таблиц в базе данных, если их нет"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица репортов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT UNIQUE NOT NULL,
                numeric_id INTEGER,  -- Числовой ID для удобства (будет равен id)
                group_message_id INTEGER NOT NULL,
                group_chat_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                author_username TEXT,
                author_first_name TEXT,
                tag TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                admin_message_id INTEGER,
                admin_chat_id INTEGER
            )
        """)
        
        # Добавляем колонку numeric_id, если её нет (для существующих БД)
        try:
            cursor.execute("ALTER TABLE reports ADD COLUMN numeric_id INTEGER")
            # Заполняем numeric_id значениями из id для существующих записей
            cursor.execute("UPDATE reports SET numeric_id = id WHERE numeric_id IS NULL")
        except sqlite3.OperationalError:
            # Колонка уже существует, ничего не делаем
            pass
        
        # Индекс для быстрого поиска по статусу
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_status ON reports(status)
        """)
        
        # Индекс для поиска по тегу
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tag ON reports(tag)
        """)
        
        conn.commit()
        conn.close()
    
    def add_report(
        self,
        report_id: str,
        group_message_id: int,
        group_chat_id: int,
        author_id: int,
        author_username: Optional[str],
        author_first_name: Optional[str],
        tag: str,
        content: str
    ) -> bool:
        """
        Добавление нового репорта в базу данных
        
        Args:
            report_id: Уникальный идентификатор репорта
            group_message_id: ID сообщения в группе
            group_chat_id: ID чата группы
            author_id: ID автора сообщения
            author_username: Username автора
            author_first_name: Имя автора
            tag: Тег репорта (#BUG, #UIFIX, #FEATURE)
            content: Текст репорта
            
        Returns:
            True если репорт добавлен, False если уже существует
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO reports 
                (report_id, group_message_id, group_chat_id, author_id, 
                 author_username, author_first_name, tag, content, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new')
            """, (
                report_id, group_message_id, group_chat_id, author_id,
                author_username, author_first_name, tag, content
            ))
            # Обновляем numeric_id значением из id
            cursor.execute("UPDATE reports SET numeric_id = id WHERE report_id = ?", (report_id,))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Репорт уже существует
            return False
        finally:
            conn.close()
    
    def update_status(
        self,
        report_id: str,
        status: str,
        admin_message_id: Optional[int] = None,
        admin_chat_id: Optional[int] = None
    ) -> bool:
        """
        Обновление статуса репорта
        
        Args:
            report_id: Идентификатор репорта
            status: Новый статус (new, in_progress, resolved, rejected)
            admin_message_id: ID сообщения в личке админа
            admin_chat_id: ID чата админа
            
        Returns:
            True если обновлено успешно
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE reports 
            SET status = ?, updated_at = CURRENT_TIMESTAMP,
                admin_message_id = COALESCE(?, admin_message_id),
                admin_chat_id = COALESCE(?, admin_chat_id)
            WHERE report_id = ?
        """, (status, admin_message_id, admin_chat_id, report_id))
        
        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return updated
    
    def get_report(self, report_id: str) -> Optional[Dict]:
        """
        Получение репорта по ID
        
        Args:
            report_id: Идентификатор репорта
            
        Returns:
            Словарь с данными репорта или None
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM reports WHERE report_id = ?", (report_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def get_reports_by_status(self, status: str) -> List[Dict]:
        """
        Получение всех репортов с определенным статусом
        
        Args:
            status: Статус для фильтрации
            
        Returns:
            Список словарей с данными репортов
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM reports WHERE status = ? ORDER BY created_at DESC", (status,))
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_report_by_numeric_id(self, numeric_id: int) -> Optional[Dict]:
        """
        Получение репорта по числовому ID
        
        Args:
            numeric_id: Числовой идентификатор репорта
            
        Returns:
            Словарь с данными репорта или None
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM reports WHERE numeric_id = ? OR id = ?", (numeric_id, numeric_id))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def get_all_reports(self, tag: Optional[str] = None, status: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[Dict]:
        """
        Получение списка репортов с фильтрацией
        
        Args:
            tag: Фильтр по тегу (опционально)
            status: Фильтр по статусу (опционально)
            limit: Максимальное количество репортов
            offset: Смещение для пагинации
            
        Returns:
            Список словарей с данными репортов
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Формируем запрос с фильтрами
        query = "SELECT * FROM reports WHERE 1=1"
        params = []
        
        if tag:
            query += " AND tag = ?"
            params.append(tag)
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def count_reports(self, tag: Optional[str] = None, status: Optional[str] = None) -> int:
        """
        Подсчет количества репортов с фильтрацией
        
        Args:
            tag: Фильтр по тегу (опционально)
            status: Фильтр по статусу (опционально)
            
        Returns:
            Количество репортов
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = "SELECT COUNT(*) FROM reports WHERE 1=1"
        params = []
        
        if tag:
            query += " AND tag = ?"
            params.append(tag)
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        cursor.execute(query, params)
        count = cursor.fetchone()[0]
        conn.close()
        
        return count
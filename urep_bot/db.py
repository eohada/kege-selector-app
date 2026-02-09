"""
Подключение к базе данных.
"""
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from urep_bot.config import DATABASE_URL

logger = logging.getLogger(__name__)

engine = None
Session = None


def init_db():
    """Инициализация подключения к БД."""
    global engine, Session
    
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL не задан")
    
    db_url = DATABASE_URL
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    
    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_recycle=300,
        echo=False
    )
    
    Session = scoped_session(sessionmaker(bind=engine))
    
    logger.info("Database connection initialized")
    return engine


def get_session():
    """Получить сессию БД."""
    if Session is None:
        init_db()
    return Session()


def close_session(session):
    """Закрыть сессию."""
    try:
        session.close()
    except Exception as e:
        logger.warning(f"Error closing session: {e}")

"""
Подключение к базе данных.
"""
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from urep_bot.config import DATABASE_URL, DEMO_DATABASE_URL

logger = logging.getLogger(__name__)

engine = None
Session = None
demo_engine = None
DemoSession = None


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


def init_demo_db():
    """Инициализация подключения к DEMO-БД (для реф.кодов демо)."""
    global demo_engine, DemoSession

    if not DEMO_DATABASE_URL:
        raise ValueError("DEMO_DATABASE_URL не задан")

    db_url = DEMO_DATABASE_URL
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)

    demo_engine = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_recycle=300,
        echo=False
    )
    DemoSession = scoped_session(sessionmaker(bind=demo_engine))
    logger.info("Demo database connection initialized")
    return demo_engine


def get_session():
    """Получить сессию БД."""
    if Session is None:
        init_db()
    return Session()


def get_demo_session():
    """Получить сессию DEMO-БД (для реф.кодов демо)."""
    if DemoSession is None:
        init_demo_db()
    return DemoSession()


def close_session(session):
    """Закрыть сессию."""
    try:
        session.close()
    except Exception as e:
        logger.warning(f"Error closing session: {e}")


def close_demo_session(session):
    """Закрыть сессию DEMO-БД."""
    try:
        session.close()
    except Exception as e:
        logger.warning(f"Error closing demo session: {e}")

import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import settings

log = logging.getLogger(__name__)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


_ADDITIVE_MIGRATIONS: list[tuple[str, str, str]] = [
    # (table, column, sqlite_column_def)
    ("trade_suggestions", "hit_rate", "FLOAT"),
    ("trade_suggestions", "hit_rate_sample", "INTEGER"),
]


def _apply_additive_migrations() -> None:
    """Idempotently add new columns to existing tables. SQLite ALTER TABLE does
    not support IF NOT EXISTS, so we introspect first.
    """
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, column, ddl in _ADDITIVE_MIGRATIONS:
            if not inspector.has_table(table):
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            if column in existing:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            log.info("db: added column %s.%s", table, column)


def init_db() -> None:
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _apply_additive_migrations()

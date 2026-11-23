"""User storage.

Locally (no DATABASE_URL) a SQLite file `local.db` is used.
In production set DATABASE_URL to a Postgres connection string
(e.g. from Neon). Render's own disk is wiped on every deploy,
so users must live in an external database.
"""

import os
from pathlib import Path

from sqlalchemy import (
    Column, DateTime, Integer, MetaData, String, Table,
    create_engine, func, insert, select, update,
)


def _database_url():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///" + str(Path(__file__).parent / "local.db")
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


engine = create_engine(_database_url(), pool_pre_ping=True)
metadata = MetaData()

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("google_sub", String(255), unique=True, nullable=False),
    Column("email", String(255), nullable=False),
    Column("name", String(100), nullable=False),
    Column("institution", String(150)),
    Column("study_year", String(30)),
    Column("degree_id", String(50)),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)


def init():
    metadata.create_all(engine)


def get_user(user_id):
    with engine.connect() as conn:
        row = conn.execute(select(users).where(users.c.id == user_id)).mappings().first()
    return dict(row) if row else None


def upsert_google_user(sub, email, name):
    """Find the user by Google account id, creating it on first sign-in."""
    with engine.begin() as conn:
        row = conn.execute(select(users.c.id).where(users.c.google_sub == sub)).first()
        if row:
            conn.execute(update(users).where(users.c.id == row.id).values(email=email, name=name))
            return row.id
        result = conn.execute(insert(users).values(google_sub=sub, email=email, name=name))
        return result.inserted_primary_key[0]


def update_profile(user_id, institution, study_year, degree_id):
    with engine.begin() as conn:
        conn.execute(
            update(users).where(users.c.id == user_id).values(
                institution=institution, study_year=study_year, degree_id=degree_id
            )
        )

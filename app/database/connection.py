from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from pgvector.psycopg import register_vector

from app.config import DATABASE_URL


def require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("Thiếu DATABASE_URL trong file .env")
    return DATABASE_URL


@contextmanager
def database_connection() -> Iterator[Connection]:
    with psycopg.connect(require_database_url(), row_factory=dict_row) as connection:
        register_vector(connection)
        yield connection

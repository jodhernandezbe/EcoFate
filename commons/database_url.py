"""PostgreSQL URL spellings: one URL, written for SQLAlchemy or for libpq (psycopg).

Pure string handling: no I/O, no connection, nothing read from the environment.
"""

from __future__ import annotations

_SQLALCHEMY_SCHEME = "postgresql+psycopg://"
_LIBPQ_SCHEME = "postgresql://"
_ACCEPTED_SCHEMES = ("postgresql+psycopg://", "postgresql://", "postgres://")


def _tail(url: str) -> str:
    """The URL without its scheme; raises ``ValueError`` for anything but a PostgreSQL URL."""
    for scheme in _ACCEPTED_SCHEMES:
        if url.startswith(scheme):
            return url[len(scheme) :]
    raise ValueError("The database URL must start with postgresql:// or postgresql+psycopg://")


def sqlalchemy_url(url: str) -> str:
    """The URL with the ``postgresql+psycopg`` scheme SQLAlchemy needs for psycopg 3."""
    return _SQLALCHEMY_SCHEME + _tail(url)


def libpq_url(url: str) -> str:
    """The URL with the plain ``postgresql`` scheme that psycopg's own pool understands."""
    return _LIBPQ_SCHEME + _tail(url)

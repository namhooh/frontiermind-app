"""
Database connection management with connection pooling.

Provides thread-safe connection pooling for PostgreSQL database access.
Uses psycopg2 connection pool for efficient resource management.
"""

import os
import logging
from contextlib import contextmanager
from typing import Optional

import psycopg2
from psycopg2 import pool, sql
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Global connection pool
_connection_pool: Optional[pool.ThreadedConnectionPool] = None


def init_connection_pool(
    min_connections: int = 1,
    max_connections: int = 5,  # Reduced from 10 to 5 for Supabase pooler
    database_url: Optional[str] = None
) -> None:
    """
    Initialize the database connection pool.

    Args:
        min_connections: Minimum number of connections to maintain
        max_connections: Maximum number of connections allowed
        database_url: PostgreSQL connection string (defaults to DATABASE_URL env var)

    Raises:
        ValueError: If DATABASE_URL not provided and not in environment
        psycopg2.Error: If connection pool cannot be created
    """
    global _connection_pool

    if _connection_pool is not None:
        logger.warning("Connection pool already initialized")
        return

    db_url = database_url or os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError(
            "DATABASE_URL not found. Set it in .env file or pass as parameter."
        )

    try:
        # Add SSL and timeout parameters for Supabase
        db_url_with_params = db_url
        if '?' not in db_url:
            db_url_with_params += '?'
        else:
            db_url_with_params += '&'

        # Add critical Supabase connection parameters
        db_url_with_params += 'sslmode=require&connect_timeout=10'

        _connection_pool = pool.ThreadedConnectionPool(
            min_connections,
            max_connections,
            db_url_with_params,
            # Critical timeout and keepalive settings for Supabase
            keepalives=1,                # Enable TCP keepalives
            keepalives_idle=30,          # Start keepalives after 30s idle
            keepalives_interval=10,      # Send keepalive every 10s
            keepalives_count=5,          # Retry 5 times before giving up
            options='-c statement_timeout=60000'  # 60 second query timeout
        )
        logger.info(
            f"Database connection pool initialized with Supabase optimizations: "
            f"min={min_connections}, max={max_connections}"
        )
    except psycopg2.Error as e:
        logger.error(f"Failed to create connection pool: {e}")
        raise


def close_connection_pool() -> None:
    """
    Close all connections in the pool and cleanup resources.

    Should be called when application shuts down.
    """
    global _connection_pool

    if _connection_pool is not None:
        _connection_pool.closeall()
        _connection_pool = None
        logger.info("Database connection pool closed")


@contextmanager
def get_db_connection(dict_cursor: bool = True):
    """
    Get a database connection from the pool (context manager).

    Usage:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM contract")
                results = cursor.fetchall()

    Args:
        dict_cursor: If True, use RealDictCursor to return rows as dictionaries

    Yields:
        psycopg2.connection: Database connection

    Raises:
        RuntimeError: If connection pool not initialized
        psycopg2.Error: If database operation fails
    """
    if _connection_pool is None:
        raise RuntimeError(
            "Connection pool not initialized. Call init_connection_pool() first."
        )

    conn = None
    try:
        conn = _connection_pool.getconn()

        # VALIDATE CONNECTION IS ALIVE - prevents stale connection errors
        try:
            conn.isolation_level  # Quick check if connection is alive
        except Exception:
            # Connection is dead, close it and get a fresh one
            logger.warning("Stale connection detected, getting fresh connection")
            _connection_pool.putconn(conn, close=True)
            conn = _connection_pool.getconn()

        # Set cursor factory for dict results if requested
        if dict_cursor:
            original_factory = conn.cursor_factory
            conn.cursor_factory = RealDictCursor

        yield conn

        # Commit transaction on success
        conn.commit()

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database operation failed: {e}")
        raise

    finally:
        if dict_cursor and conn:
            conn.cursor_factory = original_factory

        if conn:
            _connection_pool.putconn(conn)


def execute_query(query: str, params: Optional[tuple] = None, fetch: bool = True):
    """
    Execute a single query and return results.

    Convenience method for simple queries without explicit connection management.

    Args:
        query: SQL query string
        params: Query parameters (for parameterized queries)
        fetch: If True, fetch and return results; if False, just execute

    Returns:
        List of result rows (as dicts) if fetch=True, otherwise None

    Raises:
        RuntimeError: If connection pool not initialized
        psycopg2.Error: If query execution fails
    """
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            if fetch:
                return cursor.fetchall()
            return None


def health_check() -> bool:
    """
    Check if database connection is healthy.

    Returns:
        True if database is accessible, False otherwise
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                return result is not None
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False

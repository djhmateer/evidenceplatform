import json
import logging
import os
import threading
from contextlib import contextmanager
from typing import Literal

import mysql
import mysql.connector
from dotenv import load_dotenv

load_dotenv()
USER = os.getenv("DB_USER")
PASSWORD = os.getenv("DB_PASS")
DB_NAME = os.getenv("DB_NAME")
DB_PORT = os.getenv("DB_PORT")
DB_HOST = os.getenv("DB_HOST")

logger = logging.getLogger(__name__)

cnx_pool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name="connections", pool_size=20,
    pool_reset_session=True,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME,
    user=USER,
    password=PASSWORD
)


class DbError(Exception):
    """Raised when a database query fails."""
    pass


# Thread-local storage for transaction batching — each thread gets its own connection.
_local = threading.local()


@contextmanager
def transaction_batch():
    """
    Context manager for batching multiple queries into a single transaction.
    Commits only once at the end instead of after every query.

    Usage:
        with db.transaction_batch():
            db.execute_query(...)  # No commit
            db.execute_query(...)  # No commit
            db.execute_query(...)  # No commit
        # Commits here when exiting the context

    This can provide 5-10x speedup for bulk insert operations.
    Nested calls reuse the same connection (inner batch is a no-op boundary).
    Thread-safe: each thread maintains its own connection via threading.local().
    """
    if getattr(_local, "connection", None) is not None:
        # Already in a batch on this thread — nested call, just yield through.
        yield
        return

    cnx = cnx_pool.get_connection()
    cnx.autocommit = False
    _local.connection = cnx
    try:
        yield
        cnx.commit()
    except Exception:
        cnx.rollback()
        raise
    finally:
        _local.connection = None
        cnx.close()


def in_transaction_batch() -> bool:
    """True when the calling thread is inside a transaction_batch() context."""
    return getattr(_local, "connection", None) is not None


def batch_insert(table: str, columns: list, rows: list) -> list:
    """
    Perform a single multi-row INSERT and return the list of auto-increment IDs.
    IDs are guaranteed consecutive for a single INSERT statement in InnoDB.
    Must be called inside a transaction_batch() context.
    """
    if not rows:
        return []
    cnx = getattr(_local, "connection", None)
    if cnx is None:
        raise RuntimeError("batch_insert must be called inside a transaction_batch() context")
    n = len(rows)
    cols_sql = ', '.join(f'`{c}`' for c in columns)
    row_ph = '(' + ', '.join(['%s'] * len(columns)) + ')'
    values_sql = ', '.join([row_ph] * n)
    query = f'INSERT INTO `{table}` ({cols_sql}) VALUES {values_sql}'
    flat_args = [val for row in rows for val in row]
    cursor = cnx.cursor(buffered=True)
    try:
        cursor.execute(query, flat_args)
        first_id = cursor.lastrowid
        return list(range(first_id, first_id + n))
    except mysql.connector.Error as err:
        logger.error("batch_insert failed: %s\nTable: %s\nColumns: %s", err, table, columns)
        raise DbError(str(err)) from err
    finally:
        cursor.close()


def execute_query(query, args, return_type: Literal["single_row", "rows", "id", "none", "rowcount", "debug"] = "rows", timeout_ms: int | None = None):
    if getattr(_local, "connection", None) is not None:
        # Reuse the open transaction connection on this thread.
        return _execute_query_on_connection(_local.connection, query, args, return_type, commit=False, timeout_ms=timeout_ms)

    cnx = cnx_pool.get_connection()
    try:
        return _execute_query_on_connection(cnx, query, args, return_type, commit=True, timeout_ms=timeout_ms)
    finally:
        cnx.close()


def _execute_query_on_connection(cnx, query, args, return_type, commit=True, timeout_ms: int | None = None):
    """Internal function to execute query on a given connection."""
    if timeout_ms is not None:
        stripped = query.lstrip()
        if stripped[:6].upper() == "SELECT":
            query = stripped[:6] + f" /*+ MAX_EXECUTION_TIME({int(timeout_ms)}) */" + stripped[6:]
    cursor = cnx.cursor(buffered=True)
    try:
        cursor.execute(query, args)
        if return_type == "single_row":
            return select_result(cursor)
        if return_type == "rows":
            return select_results(cursor)
        if return_type == "debug":
            return cursor.statement
        if return_type == "id":
            last_row_id = cursor.lastrowid
            if not last_row_id:
                return False
            return last_row_id
        if return_type == "none":
            return True
        if return_type == "rowcount":
            return cursor.rowcount
        return None
    except mysql.connector.Error as err:
        if err.errno == 3024:
            raise TimeoutError(f"Query timed out after {timeout_ms}ms") from err
        logger.error("DB query failed: %s\nQuery: %s\nArgs: %s", err, query, json.dumps(args, default=str))
        raise DbError(str(err)) from err
    finally:
        cursor.close()
        if commit:
            cnx.commit()


def select_results(cursor):
    data = cursor.fetchall()
    columns = [i[0] for i in cursor.description]
    if not data:
        return []
    results = [{columns[i]: row[i] for i in range(len(columns))} for row in data]
    return results


def select_result(cursor):
    data = cursor.fetchone()
    columns = [i[0] for i in cursor.description]
    if not data:
        return None
    results = {columns[i]: data[i] for i in range(len(columns))}
    return results

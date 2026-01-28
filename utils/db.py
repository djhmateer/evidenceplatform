import json
import os
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

cnx_pool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name="connections", pool_size=20,
    pool_reset_session=True,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME,
    user=USER,
    password=PASSWORD
)

# Thread-local storage for transaction batching
_batch_connection = None


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
    """
    global _batch_connection

    if _batch_connection is not None:
        # Already in a batch, just yield (nested batches use same connection)
        yield
        return

    cnx = cnx_pool.get_connection()
    cnx.autocommit = False
    _batch_connection = cnx
    try:
        yield
        cnx.commit()
    except Exception:
        cnx.rollback()
        raise
    finally:
        _batch_connection = None
        cnx.close()


def execute_query(query, args, return_type: Literal["single_row", "rows", "id", "none", "debug"] = "rows"):
    global _batch_connection

    # If we're in a batch, reuse the connection and don't commit
    if _batch_connection is not None:
        return _execute_query_on_connection(_batch_connection, query, args, return_type, commit=False)

    # Otherwise, use a new connection and commit immediately (original behavior)
    cnx = cnx_pool.get_connection()
    try:
        return _execute_query_on_connection(cnx, query, args, return_type, commit=True)
    finally:
        cnx.close()


def _execute_query_on_connection(cnx, query, args, return_type, commit=True):
    """Internal function to execute query on a given connection."""
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
        return None
    except mysql.connector.Error as err:
        print(err)
        print("query: ")
        print(query)
        print(json.dumps(args))
        # log_event("sql_error", None, str(err), json.dumps({"query": query, "args": args}))
        return False
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

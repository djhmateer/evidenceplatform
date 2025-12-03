import json
import os
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


def execute_query(query, args, return_type: Literal["single_row", "rows", "id", "none", "debug"] = "rows"):
    cnx = cnx_pool.get_connection()
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
        try:
            cursor.close()
            cnx.commit()
            cnx.close()
        except mysql.connector.Error as err:
            print(err)


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

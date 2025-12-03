from typing import Literal, Optional

from utils import db


def log_event(event_type: Literal["server_call", "sql_error", "scraping_error", "scraping_progress", "unknown_error",  "unauthorized_access", "login_attempt"],
              user_id: Optional[int], details: str, args: Optional[str]):
    return db.execute_query(
        '''
        INSERT INTO error_log (event_type, user_id, details, args) 
        VALUES (%(event_type)s, %(user_id)s, %(details)s, %(args)s);
        '''
        , {"event_type": event_type, "user_id": user_id, "details": details, "args": args}, "id"
    )

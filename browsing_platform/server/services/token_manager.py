import string
from datetime import timedelta, datetime
from secrets import choice
from typing import Optional

from pydantic import BaseModel

from utils import db

TOKEN_LENGTH = 30
TOKEN_EXPIRY = timedelta(days=30)

class Token(BaseModel):
    id: Optional[int]
    user_id: int
    token: str
    admin: Optional[int]
    create_date: datetime
    last_use: datetime


def generate_token() -> str:
    """Generate a random token string of TOKEN_LENGTH characters."""
    return ''.join(choice(string.ascii_letters + string.digits) for _ in range(TOKEN_LENGTH))


class TokenPermissions(BaseModel):
    valid: bool
    admin: bool
    user_id: Optional[int]


def check_token(token: Optional[str]) -> TokenPermissions:
    try:
        if not token:
            return TokenPermissions(valid=False, admin=False, user_id=None)
        token_check = db.execute_query(
            '''SELECT token.*, u.admin, u.id as user_id FROM token JOIN user AS u ON token.user_id = u.id
            WHERE token = %(token)s'''
            , {"token": token}, "single_row"
        )
        if token_check is None:
            return TokenPermissions(valid=False, admin=False, user_id=None)
        else:
            token = Token(**token_check)
            if token.last_use > datetime.now() - TOKEN_EXPIRY:
                return TokenPermissions(valid=True, admin=(token.admin ==1), user_id=token.user_id)
            return TokenPermissions(valid=False, admin=False, user_id=None)
    except Exception:
        return TokenPermissions(valid=False, admin=False, user_id=None)


def remove_token(token: str):
    db.execute_query(
        '''DELETE FROM token
        WHERE token = %(token)s'''
        , {"token": token}, "none"
    )
    return True

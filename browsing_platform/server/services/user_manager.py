from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from browsing_platform.server.services.password_authenticator import set_user_password
from utils import db


class User(BaseModel):
    id: Optional[int] = None
    create_date: Optional[datetime] = None
    update_date: Optional[datetime] = None
    email: str
    locked: Optional[bool] = False
    password_hash: Optional[str] = None
    password_alg: Optional[str] = None
    password_set_at: Optional[datetime] = None
    last_password_failure: Optional[datetime] = None
    force_pwd_reset: Optional[bool] = False
    last_login: Optional[datetime] = None
    login_attempts: Optional[int] = 0
    admin: Optional[bool] = False
    password_to_set: Optional[str] = None


def get_user_by_email(email: str):
    user: Optional[User] = db.execute_query(
        '''SELECT * FROM user WHERE email = %(email)s''',
        {"email": email}, "single_row"
    )
    return user


def get_user(user_id: int) -> User:
    user_row = db.execute_query(
        '''SELECT * FROM user WHERE id = %(id)s''',
        {"id": user_id}, "single_row"
    )
    if user_row is None:
        raise Exception("user not found")
    return User(**user_row)


def update_user(item: User):
    db.execute_query(
        '''UPDATE user SET
         email = %(email)s, admin = %(admin)s, locked = %(locked)s
        WHERE id = %(id)s''',
        {
            "id": item.id,
            "email": item.email,
            "admin": item.admin,
            "locked": item.locked,
        }, "none"
    )
    if item.password_to_set and len(item.password_to_set):
        set_user_password(item.id, item.password_to_set)
    if not item.locked:
        db.execute_query(
            '''UPDATE user SET login_attempts = 0 WHERE id = %(id)s''',
            {"id": item.id}, "none"
        )
    else:
        db.execute_query(
            '''DELETE FROM token WHERE user_id = %(id)s''',
            {"id": item.id}, "none"
        )
    return item.id


def insert_user(item: User):
    new_id = db.execute_query(
        '''INSERT INTO
         user (`email`, `admin`, `locked`) 
         VALUES (%(email)s, %(admin)s, %(locked)s)''',
        {
            "email": item.email,
            "admin": item.admin,
            "locked": item.locked,
        }, "id"
    )
    if item.password_to_set and len(item.password_to_set):
        set_user_password(new_id, item.password_to_set)
    return new_id


def delete_user(item_id: int):
    db.execute_query(
        '''DELETE FROM user WHERE id = %(id)s''',
        {"id": item_id}, "none"
    )
    db.execute_query(
        '''DELETE FROM token WHERE user_id = %(id)s''',
        {"id": item_id}, "none"
    )
    return item_id

from typing import Optional

from argon2 import PasswordHasher, exceptions as argon_exc

from browsing_platform.server.services.event_logger import log_event
from browsing_platform.server.services.token_manager import generate_token
from utils import db

# Tuned Argon2id parameters (adjust memory/time for your infra)
_ph = PasswordHasher(
    time_cost=2,
    memory_cost=19456,  # ~19 MB
    parallelism=1,
    hash_len=32,
    salt_len=16
)

def hash_password(password: str) -> tuple[str, str]:
    if len(password) < 12 or len(password) > 512:
        raise ValueError("Password length invalid (12-512 chars required)")

    h = _ph.hash(password)
    return h, "argon2id"

def verify_password(stored_hash: str, provided: str) -> bool:
    try:
        _ph.verify(stored_hash, provided)
        if _ph.check_needs_rehash(stored_hash):
            # Optional: return flag so caller re-saves upgraded hash
            pass
        return True
    except argon_exc.VerifyMismatchError:
        return False
    except argon_exc.InvalidHash:
        return False

def set_user_password(user_id: int, new_password: str):
    h, alg = hash_password(new_password)
    db.execute_query(
        """UPDATE user
           SET password_hash=%(h)s,
               password_alg=%(alg)s,
               password_set_at=NOW(),
               login_attempts=0,
               force_pwd_reset=0
           WHERE id=%(uid)s""",
        {"h": h, "alg": alg, "uid": user_id},
        "none"
    )

def login_with_password(email: str, password: str, max_failures: int = 10) -> Optional[int]:
    user = db.execute_query(
        "SELECT * FROM user WHERE email=%(e)s",
        {"e": email},
        "single_row"
    )
    token = generate_token()
    if not user:
        # a fake verify to equalize timing
        verify_password(
            "$argon2id$v=19$m=65536,t=3,p=4$abcdefghijklmnopqrstuv$01234567890123456789012345678901",
            password
        )
        raise Exception("error - couldn't login")
    if user["locked"]:
        raise Exception("Error - too many failed login attempts. Please ask the system admin to unlock your user.")
    if not user["password_hash"]:
        raise Exception("error - couldn't login")

    ok = verify_password(user["password_hash"], password)
    if ok:
        db.execute_query(
            "UPDATE user SET login_attempts=0, last_login=NOW() WHERE id=%(id)s",
            {"id": user["id"]},
            "none"
        )
        db.execute_query(
            '''INSERT INTO token (user_id, token) VALUES (%(user_id)s, %(token)s)'''
            , {"user_id": user["id"], "token": token}, "id"
        )
        log_event(
            "login_attempt", None,
            "{'success': true}",
            "{'email': " + email + "}"
        )
        return {"token": token, "permissions": user["admin"]}
    else:
        db.execute_query(
            """UPDATE user
               SET login_attempts = login_attempts + 1,
                   last_pwd_failure = NOW(),
                   locked = CASE WHEN login_attempts + 1 >= %(maxf)s THEN 1 ELSE locked END
               WHERE id=%(id)s""",
            {"id": user["id"], "maxf": max_failures},
            "none"
        )
        raise Exception("error - couldn't login")


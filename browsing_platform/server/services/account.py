import json
from typing import Any, Optional

from browsing_platform.server.services.annotation import Annotation
from extractors.entity_types import Account
from utils import db


def account_exists(account_id: int) -> bool:
    return db.execute_query(
        "SELECT id FROM account WHERE id = %(id)s",
        {"id": account_id},
        return_type="single_row"
    ) is not None


def get_account_data_by_id(account_id: int) -> tuple[bool, Any]:
    """Returns (True, data) if the account exists, (False, None) if not found."""
    row = db.execute_query(
        "SELECT data FROM account WHERE id = %(id)s",
        {"id": account_id},
        return_type="single_row"
    )
    if row is None:
        return False, None
    data = row["data"]
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = None
    return True, data


_ACCOUNT_COLS = "id, id_on_platform, url_suffix, platform, identifiers, display_name, bio, data, url_parts, create_date"
_ACCOUNT_COLS_NO_DATA = "id, id_on_platform, url_suffix, platform, identifiers, display_name, bio, NULL AS data, url_parts, create_date"


def get_account_by_id(account_id: int, include_data: bool = True) -> Optional[Account]:
    cols = _ACCOUNT_COLS if include_data else _ACCOUNT_COLS_NO_DATA
    account = db.execute_query(
        f"SELECT {cols} FROM account WHERE id = %(id)s",
        {"id": account_id},
        return_type="single_row"
    )
    if account is None:
        return None
    return Account(**account)


def get_account_by_platform_id(platform_id: str, include_data: bool = True) -> Optional[Account]:
    cols = _ACCOUNT_COLS if include_data else _ACCOUNT_COLS_NO_DATA
    row = db.execute_query(
        f"SELECT {cols} FROM account WHERE id_on_platform = %(pid)s LIMIT 1",
        {"pid": platform_id},
        return_type="single_row"
    )
    return Account(**row) if row else None


def get_account_by_url(url: str, include_data: bool = True) -> Optional[Account]:
    cols = _ACCOUNT_COLS if include_data else _ACCOUNT_COLS_NO_DATA
    # Several live rows can share a handle (a pk-less stub beside the pk-holder,
    # or a recycled username) — prefer the pk-holder, then the oldest row.
    row = db.execute_query(
        f"""SELECT {cols} FROM account WHERE url_suffix = %(url)s
            ORDER BY (id_on_platform IS NULL), id LIMIT 1""",
        {"url": url},
        return_type="single_row"
    )
    return Account(**row) if row else None


def annotate_account(account_id: int, annotation: Annotation) -> None:
    with db.transaction_batch():
        # Clear associated tags
        db.execute_query(
            """DELETE FROM account_tag WHERE account_id = %(id)s""",
            {"id": account_id},
            return_type="none"
        )
        # Add new tags with per-assignment notes
        for tag in (annotation.tags or []):
            db.execute_query(
                """INSERT INTO account_tag (account_id, tag_id, notes) VALUES (%(account_id)s, %(tag_id)s, %(notes)s)""",
                {"account_id": account_id, "tag_id": tag.id, "notes": tag.notes},
                return_type="none"
            )
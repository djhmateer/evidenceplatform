from typing import Optional

from browsing_platform.server.services.annotation import Annotation
from extractors.entity_types import Account
from utils import db


def get_account_by_id(account_id: int) -> Optional[Account]:
    account = db.execute_query(
        """SELECT * FROM account WHERE id = %(id)s""",
        {"id": account_id},
        return_type="single_row"
    )
    if account is None:
        return None
    return Account(**account)


def annotate_account(account_id: int, annotation: Annotation) -> None:
    # Set notes field
    db.execute_query(
        """UPDATE account SET notes = %(notes)s WHERE id = %(id)s""",
        {"id": account_id, "notes": annotation.notes},
        return_type="none"
    )
    # Clear associated tags
    db.execute_query(
        """DELETE FROM account_tag WHERE account_id = %(id)s""",
        {"id": account_id},
        return_type="none"
    )
    # Add new tags
    for tag_id in annotation.tags:
        db.execute_query(
            """INSERT INTO account_tag (account_id, tag_id) VALUES (%(account_id)s, %(tag_id)s)""",
            {"account_id": account_id, "tag_id": tag_id},
            return_type="none"
        )
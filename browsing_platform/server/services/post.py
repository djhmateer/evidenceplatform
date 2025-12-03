from typing import Optional

from browsing_platform.server.services.annotation import Annotation
from extractors.entity_types import Account, Post
from utils import db


def get_post_by_id(post_id: int) -> Optional[Post]:
    row = db.execute_query(
        """SELECT * FROM post WHERE id = %(id)s""",
        {"id": post_id},
        return_type="single_row"
    )
    if row is None:
        return None
    return Post(**row)


def get_posts_by_accounts(accounts: list[Account]) -> list[Post]:
    if not accounts or len(accounts) == 0:
        return []
    query_args = {f"account_id_{i}": f"{account.id}" for i, account in enumerate(accounts)}
    query_in_clause = ', '.join([f"%(account_id_{i})s" for i in range(len(accounts))])
    posts = db.execute_query(
        f"""SELECT * FROM post WHERE account_id IN ({query_in_clause})""",
        query_args,
        return_type="rows"
    )
    return [Post(**p) for p in posts]

def annotate_post(post_id: int, annotation: Annotation) -> None:
    # Set notes field
    db.execute_query(
        """UPDATE post SET notes = %(notes)s WHERE id = %(id)s""",
        {"id": post_id, "notes": annotation.notes},
        return_type="none"
    )
    # Clear associated tags
    db.execute_query(
        """DELETE FROM post_tag WHERE post_id = %(id)s""",
        {"id": post_id},
        return_type="none"
    )
    # Add new tags
    for tag_id in annotation.tags:
        db.execute_query(
            """INSERT INTO post_tag (post_id, tag_id) VALUES (%(post_id)s, %(tag_id)s)""",
            {"post_id": post_id, "tag_id": tag_id},
            return_type="none"
        )
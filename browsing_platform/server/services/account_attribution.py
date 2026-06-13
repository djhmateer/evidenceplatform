from typing import Optional
from utils import db


def _uncertain_count(main_table: str, fk_col: str, archive_table: str,
                     archive_fk_col: str, archive_pk_col: str, account_id: int) -> dict:
    """Returns {total, uncertain} for one affiliation type.

    'uncertain' means every archive record for that entity observed the account
    by username only (archive_pk_col IS NULL in all sessions), which is the
    ambiguous case when the username is contested.
    """
    row = (db.execute_query(
        f"""SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN NOT EXISTS (
                    SELECT 1 FROM `{archive_table}` a
                    WHERE a.`{archive_fk_col}` = m.id
                      AND a.`{archive_pk_col}` IS NOT NULL
                ) THEN 1 ELSE 0 END) AS uncertain
            FROM `{main_table}` m
            WHERE m.`{fk_col}` = %(id)s""",
        {"id": account_id},
        return_type="single_row"
    ) or {})
    return {"total": row.get("total", 0) or 0, "uncertain": row.get("uncertain", 0) or 0}


def get_attribution_report(account_id: int) -> Optional[dict]:
    """Check whether affiliations attributed to this account are verifiable.

    An affiliation (comment, like, tag) is 'uncertain' when every archive session
    that observed the affiliated entity identified the account by username only —
    not by its platform pk. If another account (A') also holds the same username,
    the affiliation could genuinely belong to A'.

    Returns None if the account does not exist.
    """
    row = db.execute_query(
        "SELECT id, url_suffix, id_on_platform, display_name FROM account WHERE id = %(id)s",
        {"id": account_id},
        return_type="single_row"
    )
    if not row:
        return None

    url_suffix = row["url_suffix"]

    if not url_suffix:
        return {
            "account_id": account_id,
            "url_suffix": None,
            "contested": False,
            "contesting_accounts": [],
            "uncertain_affiliations": {},
            "note": "Account has no username — no ambiguity possible.",
        }

    contesters = db.execute_query(
        """SELECT id, id_on_platform, url_suffix, display_name
           FROM account
           WHERE url_suffix = %(url_suffix)s
             AND id_on_platform IS NOT NULL
             AND merged_into_account_id IS NULL
             AND id != %(account_id)s""",
        {"url_suffix": url_suffix, "account_id": account_id},
        return_type="rows"
    ) or []

    if not contesters:
        return {
            "account_id": account_id,
            "url_suffix": url_suffix,
            "contested": False,
            "contesting_accounts": [],
            "uncertain_affiliations": {},
            "note": "Username is not contested — affiliations are fully verifiable.",
        }

    uncertain_affiliations = {
        "posts_authored": _uncertain_count(
            "post", "account_id", "post_archive", "canonical_id", "account_id_on_platform", account_id
        ),
        "comments": _uncertain_count(
            "comment", "account_id", "comment_archive", "canonical_id", "account_id_on_platform", account_id
        ),
        "post_likes": _uncertain_count(
            "post_like", "account_id", "post_like_archive", "canonical_id", "account_id_on_platform", account_id
        ),
        "tagged_in_posts": _uncertain_count(
            "tagged_account", "tagged_account_id", "tagged_account_archive", "canonical_id",
            "tagged_account_id_on_platform", account_id
        ),
    }

    total_uncertain = sum(v["uncertain"] for v in uncertain_affiliations.values())
    contester_handles = ", ".join(
        c["url_suffix"] or f"id={c['id']}" for c in contesters
    )
    if total_uncertain == 0:
        note = (
            f"Username '{url_suffix}' is also held by: {contester_handles}. "
            f"However, all affiliations for this account were verified via platform pk in at least one session."
        )
    else:
        note = (
            f"Username '{url_suffix}' is also held by: {contester_handles}. "
            f"{total_uncertain} affiliated entities were attributed via username match only and could "
            f"belong to any of the contesting accounts."
        )

    return {
        "account_id": account_id,
        "url_suffix": url_suffix,
        "contested": True,
        "contesting_accounts": [
            {
                "id": c["id"],
                "id_on_platform": c["id_on_platform"],
                "url_suffix": c["url_suffix"],
                "display_name": c["display_name"],
            }
            for c in contesters
        ],
        "uncertain_affiliations": uncertain_affiliations,
        "note": note,
    }

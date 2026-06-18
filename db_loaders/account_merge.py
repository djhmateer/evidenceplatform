"""
Soft-merge for canonical account rows that describe the same real-world profile.

Why merging exists: many Instagram payloads (mentions, captions, comment
authors, tags) identify an account ONLY by username, so a username-only stub
row is sometimes created before the account's pk is ever observed. When a
later observation carries both (pk, username), the platform has asserted that
the stub and the pk-holder are one profile, and they must be folded together —
otherwise community detection and the browsing UI see two half-profiles.

Why merging is SOFT: internal account ids appear in browsing-platform URLs
cited by external researchers, so a merged row is never deleted. It becomes a
tombstone: every child row and provenance record is re-pointed to the keeper,
its identity and content fields are cleared (so no intake lookup or search can
ever match it again), and merged_into_account_id is set so the read path can
serve the keeper for stale citations. Tombstones are inert by construction —
code that is unaware of them sees an empty row, never wrong data.

A merge only ever folds a row into a keeper when their pks don't conflict; two
rows holding DIFFERENT pks are provably distinct accounts and are refused.
Keepers are never tombstones, so merge chains cannot grow: any chain left by
out-of-order operations is path-compressed at merge time. Every merge is
recorded in account_merge_log with a snapshot of the tombstoned row's fields,
so a wrong merge can be audited and unwound (V032-style: detach + re-extract).

Merges are triggered only by the ingestion pipeline (auto_merge_shadowed_stubs)
and by migrations — the browsing-platform API is read-only over archived
entities and exposes no merge endpoint. (The account_merge_log 'manual' source
is reserved for operator-run scripts.)

All write helpers must run inside db.transaction_batch() so a merge is atomic
with the operation that triggered it.
"""

import json
import logging
from typing import Optional

from utils import db

logger = logging.getLogger(__name__)

# Tables with a plain FK to account(id): straight re-point, no collisions.
SIMPLE_FK_REPOINTS = [
    ("post", "account_id"),
    ("media", "account_id"),
    ("comment", "account_id"),
    ("post_like", "account_id"),
    ("tagged_account", "tagged_account_id"),
    ("account_relation", "follower_account_id"),
    ("account_relation", "followed_account_id"),
]

# account_archive columns backfilled onto the keeper's row when the keeper and
# the merged row both hold a row for the same archive_session (the identity
# columns id / create_date / canonical_id / archive_session_id never move).
_ARCHIVE_COLS = ["id_on_platform", "url_suffix", "display_name", "bio", "data", "platform"]

# Canonical scalar columns resolved keeper-first on merge (id_on_platform,
# url_suffix and identifiers get dedicated handling).
_CANONICAL_COLS = ["display_name", "bio", "data", "url_parts", "platform"]

# Fields of the merged row preserved in account_merge_log before tombstoning.
_SNAPSHOT_COLS = ["id_on_platform", "url_suffix", "identifiers", "display_name",
                  "bio", "data", "url_parts", "platform", "post_count"]

# SQL counterpart of is_valid_identifier (see V032 for the sentinels' origin).
REAL_HANDLE_SQL = "({col} IS NOT NULL AND {col} != '' AND TRIM(TRAILING '/' FROM {col}) != 'None')"


def is_valid_identifier(value) -> bool:
    """Return False for null-like values that must not be used as entity-match keys.

    Null-like means: Python None, empty string, or the literal string 'None' /
    'None/' which is the f-string artifact of formatting a Python None value
    (a past bug left these in the DB — see V032). Matching multiple distinct
    entities on a shared null-like identifier would incorrectly merge them.
    """
    return bool(value) and str(value).rstrip('/') != 'None'


def resolve_account_redirect(account_id: int) -> int:
    """Follow merged_into_account_id to the live account. Chains are
    path-compressed at merge time, so more than one hop indicates an
    interrupted compression — follow defensively, never loop."""
    seen = set()
    while account_id not in seen:
        seen.add(account_id)
        row = db.execute_query(
            "SELECT merged_into_account_id FROM account WHERE id = %(id)s",
            {"id": account_id},
            return_type="single_row"
        )
        if row is None or row["merged_into_account_id"] is None:
            return account_id
        account_id = row["merged_into_account_id"]
    return account_id


def merge_account_into(
        keeper_id: int,
        merged_id: int,
        source: str,
        archive_session_id: Optional[int] = None,
        user_id: Optional[int] = None,
) -> None:
    """Fold account `merged_id` into `keeper_id` and tombstone it.

    source: 'intake_auto' | 'migration' | 'manual' (account_merge_log enum).
    Raises ValueError on identity conflicts; the caller decides how to surface
    them. Must be called inside db.transaction_batch().
    """
    if not db.in_transaction_batch():
        raise RuntimeError("merge_account_into must run inside db.transaction_batch()")
    if keeper_id == merged_id:
        raise ValueError("Cannot merge an account into itself")

    rows = db.execute_query(
        f"""SELECT id, merged_into_account_id, {', '.join(f'`{c}`' for c in _SNAPSHOT_COLS)}
            FROM account WHERE id IN (%s, %s)""",
        [keeper_id, merged_id],
        return_type="rows"
    ) or []
    by_id = {r["id"]: r for r in rows}
    keeper, merged = by_id.get(keeper_id), by_id.get(merged_id)
    if keeper is None or merged is None:
        raise ValueError(f"Account not found (keeper={keeper_id}, merged={merged_id})")
    if keeper["merged_into_account_id"] is not None:
        raise ValueError(f"Keeper account {keeper_id} is itself merged into "
                         f"{keeper['merged_into_account_id']} — resolve the redirect first")
    if merged["merged_into_account_id"] is not None:
        raise ValueError(f"Account {merged_id} is already merged into {merged['merged_into_account_id']}")
    if keeper["id_on_platform"] and merged["id_on_platform"] \
            and keeper["id_on_platform"] != merged["id_on_platform"]:
        raise ValueError(
            f"Refusing to merge: accounts {keeper_id} and {merged_id} hold different platform ids "
            f"({keeper['id_on_platform']!r} vs {merged['id_on_platform']!r}) — they are distinct profiles"
        )

    _repoint_account_archives(keeper_id, merged_id)

    for table, col in SIMPLE_FK_REPOINTS:
        db.execute_query(
            f"UPDATE `{table}` SET `{col}` = %(keeper)s WHERE `{col}` = %(merged)s",
            {"keeper": keeper_id, "merged": merged_id},
            return_type="none"
        )

    _repoint_account_tags(keeper_id, merged_id)

    db.execute_query(
        "UPDATE entity_share_link SET entity_id = %(keeper)s WHERE entity = 'account' AND entity_id = %(merged)s",
        {"keeper": keeper_id, "merged": merged_id},
        return_type="none"
    )

    # Path compression: tombstones already pointing at the merged row follow it.
    db.execute_query(
        "UPDATE account SET merged_into_account_id = %(keeper)s WHERE merged_into_account_id = %(merged)s",
        {"keeper": keeper_id, "merged": merged_id},
        return_type="none"
    )

    _synthesize_keeper(keeper, merged)

    # Tombstone: clear every matchable/searchable field so the row is inert.
    # identifiers stay as a forensic remnant (not used by any lookup).
    db.execute_query(
        """UPDATE account
           SET merged_into_account_id = %(keeper)s,
               id_on_platform = NULL, url_suffix = NULL, display_name = NULL,
               bio = NULL, data = NULL, url_parts = NULL, post_count = 0
           WHERE id = %(merged)s""",
        {"keeper": keeper_id, "merged": merged_id},
        return_type="none"
    )

    snapshot = {col: merged[col] for col in _SNAPSHOT_COLS}
    db.execute_query(
        """INSERT INTO account_merge_log
               (keeper_account_id, merged_account_id, source, archive_session_id, user_id, merged_snapshot)
           VALUES (%(keeper)s, %(merged)s, %(source)s, %(session)s, %(user)s, %(snapshot)s)""",
        {
            "keeper": keeper_id,
            "merged": merged_id,
            "source": source,
            "session": archive_session_id,
            "user": user_id,
            "snapshot": json.dumps(snapshot, default=str),
        },
        return_type="none"
    )
    logger.info(f"Merged account {merged_id} into {keeper_id} (source={source})")


def _repoint_account_archives(keeper_id: int, merged_id: int) -> None:
    """Move the merged row's provenance onto the keeper. When both hold a row
    for the same archive_session (uq_account_archive_canonical_session), the
    keeper's row survives, backfilled from the merged row's for any column it
    is missing — both rows describe the same account in the same session."""
    cols_sql = ', '.join(f'`{c}`' for c in _ARCHIVE_COLS)
    keeper_rows = db.execute_query(
        f"SELECT id, archive_session_id, {cols_sql} FROM account_archive WHERE canonical_id = %(id)s",
        {"id": keeper_id},
        return_type="rows"
    ) or []
    keeper_by_session = {r["archive_session_id"]: r for r in keeper_rows
                         if r["archive_session_id"] is not None}
    merged_rows = db.execute_query(
        f"SELECT id, archive_session_id, {cols_sql} FROM account_archive WHERE canonical_id = %(id)s ORDER BY id",
        {"id": merged_id},
        return_type="rows"
    ) or []
    for row in merged_rows:
        session_id = row["archive_session_id"]
        keeper_row = keeper_by_session.get(session_id) if session_id is not None else None
        if keeper_row is None:
            db.execute_query(
                "UPDATE account_archive SET canonical_id = %(keeper)s WHERE id = %(id)s",
                {"keeper": keeper_id, "id": row["id"]},
                return_type="none"
            )
            if session_id is not None:
                keeper_by_session[session_id] = row
        else:
            fill = {c: row[c] for c in _ARCHIVE_COLS
                    if keeper_row[c] is None and row[c] is not None}
            if fill:
                set_sql = ', '.join(f"`{c}` = %({c})s" for c in fill)
                db.execute_query(
                    f"UPDATE account_archive SET {set_sql} WHERE id = %(id)s",
                    {**fill, "id": keeper_row["id"]},
                    return_type="none"
                )
            db.execute_query(
                "DELETE FROM account_archive WHERE id = %(id)s",
                {"id": row["id"]},
                return_type="none"
            )


def _repoint_account_tags(keeper_id: int, merged_id: int) -> None:
    """Re-point account_tag rows respecting UNIQUE(account_id, tag_id): a tag
    the keeper already carries keeps the keeper's row (and notes)."""
    merged_tags = db.execute_query(
        "SELECT id, tag_id FROM account_tag WHERE account_id = %(id)s ORDER BY id",
        {"id": merged_id},
        return_type="rows"
    ) or []
    if not merged_tags:
        return
    keeper_tag_rows = db.execute_query(
        "SELECT tag_id FROM account_tag WHERE account_id = %(id)s",
        {"id": keeper_id},
        return_type="rows"
    ) or []
    keeper_tags = {r["tag_id"] for r in keeper_tag_rows}
    for row in merged_tags:
        if row["tag_id"] in keeper_tags:
            db.execute_query("DELETE FROM account_tag WHERE id = %(id)s", {"id": row["id"]}, return_type="none")
        else:
            db.execute_query(
                "UPDATE account_tag SET account_id = %(keeper)s WHERE id = %(id)s",
                {"keeper": keeper_id, "id": row["id"]},
                return_type="none"
            )
            keeper_tags.add(row["tag_id"])


def _synthesize_keeper(keeper: dict, merged: dict) -> None:
    """Recompute the keeper's canonical fields from both rows and the merged
    provenance: identifiers are the union of both histories, url_suffix is the
    most recently observed handle (it is defined as 'newest known value'), the
    pk and scalar fields resolve keeper-first, post_count is recounted."""
    def parse_identifiers(raw) -> list:
        if not raw:
            return []
        return json.loads(raw) if isinstance(raw, str) else list(raw)

    identifiers = parse_identifiers(keeper["identifiers"])
    for ident in parse_identifiers(merged["identifiers"]):
        if ident not in identifiers:
            identifiers.append(ident)

    pk = keeper["id_on_platform"] or merged["id_on_platform"]

    newest = db.execute_query(
        f"""SELECT aa.url_suffix
            FROM account_archive aa
            LEFT JOIN archive_session s ON s.id = aa.archive_session_id
            WHERE aa.canonical_id = %(id)s
              AND {REAL_HANDLE_SQL.format(col='aa.url_suffix')}
            ORDER BY COALESCE(s.archiving_timestamp, s.create_date, aa.create_date) DESC, aa.id DESC
            LIMIT 1""",
        {"id": keeper["id"]},
        return_type="single_row"
    )
    if newest:
        url_suffix = newest["url_suffix"]
    elif is_valid_identifier(keeper["url_suffix"]):
        url_suffix = keeper["url_suffix"]
    elif is_valid_identifier(merged["url_suffix"]):
        url_suffix = merged["url_suffix"]
    else:
        url_suffix = None

    if pk and f"id_{pk}" not in identifiers:
        identifiers.append(f"id_{pk}")
    for handle in (keeper["url_suffix"], merged["url_suffix"], url_suffix):
        if is_valid_identifier(handle) and f"url_{handle}" not in identifiers:
            identifiers.append(f"url_{handle}")

    scalars = {col: keeper[col] if keeper[col] not in (None, "") else merged[col]
               for col in _CANONICAL_COLS}
    set_sql = ', '.join(f"`{c}` = %({c})s" for c in _CANONICAL_COLS)
    db.execute_query(
        f"""UPDATE account
            SET id_on_platform = %(pk)s,
                url_suffix = %(url_suffix)s,
                identifiers = %(identifiers)s,
                {set_sql},
                post_count = (SELECT COUNT(*) FROM post WHERE account_id = %(id)s)
            WHERE id = %(id)s""",
        {
            "id": keeper["id"],
            "pk": pk,
            "url_suffix": url_suffix,
            "identifiers": json.dumps(identifiers),
            **scalars,
        },
        return_type="none"
    )


def auto_merge_shadowed_stubs(accounts: list, archive_session_id: Optional[int]) -> int:
    """Intake hook: an extracted account carrying BOTH (pk, username) is a
    platform assertion that the username belongs to that pk. If the pk already
    has a canonical row AND a pk-less stub holds the username, the stub is the
    same profile observed through a username-only context (mention, tag,
    story) — merge it into the pk-holder before canonical matching runs.

    Stubs whose pk-holder does not exist yet are NOT touched: regular matching
    enriches them in place (the stub IS the account's row, no duplicate ever
    forms). Rows holding a different pk are never candidates (pk-less filter).

    Returns the number of merges performed.
    """
    bindings: dict = {}  # username -> set of pks asserted for it in this batch
    for a in accounts:
        if a.id_on_platform and is_valid_identifier(a.url_suffix):
            bindings.setdefault(a.url_suffix, set()).add(a.id_on_platform)
    if not bindings:
        return 0

    urls = list(bindings)
    pks = list({pk for pk_set in bindings.values() for pk in pk_set})
    ph_urls = ','.join(['%s'] * len(urls))
    ph_pks = ','.join(['%s'] * len(pks))
    holder_rows = db.execute_query(
        f"""SELECT id, id_on_platform FROM account
            WHERE id_on_platform IN ({ph_pks}) AND merged_into_account_id IS NULL""",
        pks,
        return_type="rows"
    ) or []
    holder_by_pk = {r["id_on_platform"]: r["id"] for r in holder_rows}
    stub_rows = db.execute_query(
        f"""SELECT id, url_suffix FROM account
            WHERE url_suffix IN ({ph_urls}) AND id_on_platform IS NULL
              AND merged_into_account_id IS NULL""",
        urls,
        return_type="rows"
    ) or []
    stubs_by_url: dict = {}
    for r in stub_rows:
        stubs_by_url.setdefault(r["url_suffix"], []).append(r["id"])

    merged_count = 0
    for url, pk_set in bindings.items():
        if len(pk_set) != 1:
            # Two pks claiming one username inside a single archive — ambiguous,
            # leave the rows alone rather than guess.
            logger.warning(f"Username {url!r} bound to multiple pks in one archive: {sorted(pk_set)}")
            continue
        holder_id = holder_by_pk.get(next(iter(pk_set)))
        if holder_id is None:
            continue
        for stub_id in stubs_by_url.get(url, []):
            if stub_id != holder_id:
                merge_account_into(holder_id, stub_id, source="intake_auto",
                                   archive_session_id=archive_session_id)
                merged_count += 1
    if merged_count:
        logger.info(f"Auto-merged {merged_count} username stub(s) into their pk-holder accounts")
    return merged_count

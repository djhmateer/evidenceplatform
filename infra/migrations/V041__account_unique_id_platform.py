"""
V041 — Make entity identity per-platform: (id_on_platform | url_suffix) + platform

ROOT CAUSE
----------
The archiver was Instagram-only; the threads-support branch added Threads.
Instagram and Threads are both Meta products and SHARE the same numeric
user-id (`pk`) space — a person's IG account and their Threads account carry
the *same* pk. Entities already carry a `platform` field, but every
identity-matching layer (in-memory dedup, canonical lookup, FK resolution,
soft-merge) matched purely on id_on_platform / url_suffix with no platform
predicate, and the DB enforced a GLOBAL UNIQUE(id_on_platform) on account
(V038). Consequently a person's IG and Threads profiles could not coexist as
separate rows and were conflated.

INTENDED INVARIANT
------------------
Two entities are the same only if they share an identifier AND the same
platform. IG and Threads identities for one person are kept as distinct rows.

WHAT THIS MIGRATION DOES
------------------------
  1. Backfill platform = 'instagram' on every NULL-platform row of account,
     post, media and comment. All pre-Threads data is Instagram, so this is a
     safe widening; it also lets every matching layer key strictly on
     (platform, identifier) with no NULL-platform ambiguity.
  2. Refuse (abort) if, after backfill, any live row group already violates the
     composite uniqueness about to be enforced — these would be pre-existing
     bugs, not something this migration should silently merge away.
  3. Replace account's single-column UNIQUE(id_on_platform) with a composite
     UNIQUE(id_on_platform, platform), keeping the index NAME so create_db.sql,
     V038's _index_exists check and this migration all converge.
  4. Add composite UNIQUE constraints that did not exist before:
       post    UNIQUE (id_on_platform, platform)   — post identity is the pk
       media   UNIQUE (url_suffix, platform)        — media identity is the
               filename; id_on_platform is the parent post's pk, shared by
               carousel siblings, so it is NOT a unique key for media
       comment UNIQUE (id_on_platform, platform)

NULL handling: MySQL treats NULLs as distinct in a unique index, so pk-less
account stubs (id_on_platform IS NULL) and url-less / id-less rows never
collide — exactly as before. The `platform` column stays NULLable; the backfill
plus the required `platform` field on the entity models guarantee non-null on
every row that participates in a composite index.

V038 is left untouched: it is already applied, and on a fresh DB it runs on
empty data (its pk-spans-two-platforms guard never fires). This migration
supersedes its single-column constraint.

Uses utils.db (like V038); the runner's final commit over `cnx` is a no-op.
"""

from utils import db

# Composite uniques to enforce. (table, index_name, "col1, col2").
# account reuses the V038/create_db.sql name so the object converges.
_COMPOSITE_UNIQUES = [
    ("account", "uq_account_id_on_platform", "id_on_platform, platform"),
    ("post", "uq_post_id_on_platform_platform", "id_on_platform, platform"),
    ("media", "uq_media_url_suffix_platform", "url_suffix, platform"),
    ("comment", "uq_comment_id_on_platform_platform", "id_on_platform, platform"),
]

# The single-column account unique added by V038 / create_db.sql, replaced here.
_OLD_ACCOUNT_UNIQUE = "uq_account_id_on_platform"

# Per-table pre-check: the identifier column whose (col, platform) pair must be
# unique among live rows before its constraint is created.
_PRECHECK_IDENTIFIER = {
    "account": "id_on_platform",
    "post": "id_on_platform",
    "media": "url_suffix",
    "comment": "id_on_platform",
}


def _index_exists(table: str, index_name: str) -> bool:
    row = db.execute_query(
        """SELECT COUNT(*) AS n FROM information_schema.statistics
           WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s""",
        [table, index_name],
        return_type="single_row"
    )
    return row["n"] > 0


def _backfill_platform() -> None:
    for table in ("account", "post", "media", "comment"):
        affected = db.execute_query(
            f"SELECT COUNT(*) AS n FROM `{table}` WHERE platform IS NULL",
            [],
            return_type="single_row"
        )["n"]
        db.execute_query(
            f"UPDATE `{table}` SET platform = 'instagram' WHERE platform IS NULL",
            [],
            return_type="none"
        )
        print(f"    V041: backfilled platform='instagram' on {affected} `{table}` row(s)")


def _abort_on_violation(table: str, identifier: str) -> None:
    """Refuse to add a composite unique if live rows already violate it."""
    where_extra = ""
    if table == "account":
        # tombstones hold a NULL identifier and are exempt anyway, but be explicit
        where_extra = "AND merged_into_account_id IS NULL"
    dup = db.execute_query(
        f"""SELECT COUNT(*) AS n FROM (
                SELECT {identifier}, platform FROM `{table}`
                WHERE {identifier} IS NOT NULL {where_extra}
                GROUP BY {identifier}, platform HAVING COUNT(*) > 1
            ) d""",
        [],
        return_type="single_row"
    )["n"]
    if dup:
        raise RuntimeError(
            f"V041: {dup} ({identifier}, platform) group(s) in `{table}` already hold "
            f">1 live row — these are pre-existing duplicates that must be resolved "
            f"before UNIQUE({identifier}, platform) can be enforced."
        )


def run(cnx):
    # ------------------------------------------------------------------ #
    # Step 1: backfill platform on all single-platform legacy data.
    # ------------------------------------------------------------------ #
    _backfill_platform()

    # ------------------------------------------------------------------ #
    # Step 2: refuse if the new composite uniqueness is already violated.
    # ------------------------------------------------------------------ #
    for table, identifier in _PRECHECK_IDENTIFIER.items():
        _abort_on_violation(table, identifier)

    # ------------------------------------------------------------------ #
    # Step 3: drop the old single-column account unique (same name reused
    #          by the composite below) so the ALTER can recreate it.
    # ------------------------------------------------------------------ #
    if _index_exists("account", _OLD_ACCOUNT_UNIQUE):
        db.execute_query(f"DROP INDEX {_OLD_ACCOUNT_UNIQUE} ON account", [], return_type="none")
        print(f"    V041: dropped single-column index '{_OLD_ACCOUNT_UNIQUE}'")

    # ------------------------------------------------------------------ #
    # Step 4: add every composite UNIQUE (idempotent by index name).
    # ------------------------------------------------------------------ #
    for table, index_name, cols in _COMPOSITE_UNIQUES:
        if _index_exists(table, index_name):
            print(f"    V041: composite unique '{index_name}' already present on `{table}` — skipping")
            continue
        db.execute_query(
            f"ALTER TABLE `{table}` ADD CONSTRAINT {index_name} UNIQUE ({cols})",
            [],
            return_type="none"
        )
        print(f"    V041: added UNIQUE({cols}) '{index_name}' on `{table}`")

    print("    V041: done")

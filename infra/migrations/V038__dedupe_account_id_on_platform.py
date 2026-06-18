"""
V038 — De-duplicate account rows sharing an id_on_platform and enforce
UNIQUE(id_on_platform)

ROOT CAUSE
----------
db_intake matched extracted accounts to existing canonicals URL-FIRST
(batch_get_canonicals_url_and_id returned `by_url.get(...) or by_id.get(...)`,
and get_canonical_account used `WHERE url = X OR id_on_platform = Y LIMIT 1`,
which has no defined row preference). Instagram usernames are mutable; the pk
(id_on_platform) is not. The losing sequence:

  1. Account A is ingested with (pk=X, username=U1).
  2. The user renames to U2 on the platform.
  3. A session observes only the username U2 (e.g. a stories page) — no pk.
     No canonical matches, so a pk-less stub B (url_suffix=U2) is created.
     (Detectable in the wild: B's identifiers list starts with 'url_…',
     proving it was born without a pk.)
  4. A later session observes BOTH (pk=X, username=U2). The url match on B
     shadows the pk match on A, and reconciliation fills B.id_on_platform=X.
     Two canonical rows now hold pk X.

Nothing at the DB level prevented this: account.id_on_platform carried only a
plain index. The code-side fixes ship alongside this migration: id-priority
matching in db_intake, and the soft-merge mechanism (V037 +
db_loaders/account_merge.py) that folds a username stub into its pk-holder the
moment an observation proves they are one profile.

WHAT THIS MIGRATION DOES
------------------------
For every id_on_platform held by more than one account row, the lowest id is
the keeper (the original registration; its id is what external citations are
most likely to reference) and each other row is soft-merged into it via
db_loaders.account_merge.merge_account_into:

  * all child rows and provenance re-pointed to the keeper (account_archive
    session collisions backfill the keeper's row, account_tag respects its
    UNIQUE pair constraint, entity_share_link rows follow);
  * the keeper's identifiers/url_suffix/scalars re-synthesized (url_suffix =
    most recently observed handle), post_count recounted;
  * the duplicate becomes a TOMBSTONE (merged_into_account_id = keeper) — its
    id keeps resolving on the browsing platform, so cited URLs never break;
  * the merge is recorded in account_merge_log (source='migration').

Then UNIQUE(id_on_platform) is added so the bug cannot recur at the DB level
(tombstones hold NULL and are exempt), and the now-redundant plain index is
dropped. NULL id_on_platform rows are untouched — NULL is the legitimate shape
of a username-only stub.

DELIBERATELY NOT DONE
---------------------
  * No UNIQUE constraint on account.url_suffix: usernames are recycled on the
    platform, so two DISTINCT accounts (different pks) can legitimately hold
    the same handle at different times. Remaining same-url groups are
    reported, not merged: a pk-less stub sharing a url with a pk-holder is
    PROBABLY the same account, but only a session observing (pk, username)
    together proves it — the intake auto-merge handles exactly that moment.
  * post / comment id_on_platform duplicates are detected and reported but not
    fixed — none are expected (posts are never ingested without a pk).

The constraint is global rather than per-platform, matching the code's
matching semantics (canonical lookups never filter on platform). A group whose
rows disagree on a non-null platform is refused.

This migration uses utils.db (the merge service's connection handling) rather
than the runner-provided cnx; the runner's final commit is a no-op.
"""

from db_loaders.account_merge import merge_account_into, REAL_HANDLE_SQL
from utils import db

_UNIQUE_NAME = "uq_account_id_on_platform"
_OLD_INDEX_NAME = "account_id_on_platform_index"


def _index_exists(table: str, index_name: str) -> bool:
    row = db.execute_query(
        """SELECT COUNT(*) AS n FROM information_schema.statistics
           WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s""",
        [table, index_name],
        return_type="single_row"
    )
    return row["n"] > 0


def _report_residual_duplicates() -> None:
    """Diagnostics only — surface duplicate shapes this migration deliberately
    does not fix, so they can be handled if they ever materialise."""
    for table in ("post", "comment"):
        row = db.execute_query(
            f"""SELECT COUNT(*) AS n FROM (
                    SELECT id_on_platform FROM `{table}`
                    WHERE id_on_platform IS NOT NULL
                    GROUP BY id_on_platform HAVING COUNT(*) > 1
                ) d""",
            [],
            return_type="single_row"
        )
        if row["n"]:
            print(f"    V038: WARNING — {row['n']} duplicate id_on_platform group(s) in `{table}` "
                  f"(not fixed by this migration; investigate separately)")

    row = db.execute_query(
        f"""SELECT COUNT(*) AS n FROM (
                SELECT url_suffix FROM account
                WHERE {REAL_HANDLE_SQL.format(col='url_suffix')} AND merged_into_account_id IS NULL
                GROUP BY url_suffix HAVING COUNT(*) > 1
            ) d""",
        [],
        return_type="single_row"
    )
    if row["n"]:
        print(f"    V038: note — {row['n']} url_suffix group(s) still shared by multiple live rows "
              f"(pk-less stubs or recycled usernames; the intake auto-merge folds a stub into its "
              f"pk-holder when a session proves the binding)")


def run(cnx):
    # ---------------------------------------------------------------------- #
    # Step 0a: collation safety (same rationale as V036). Instagram pks are
    #          numeric today, but id_on_platform is a varchar that other
    #          platforms may fill with cased ids; grouping and the UNIQUE
    #          constraint use the column's case-insensitive collation. If any
    #          collation-group folds >1 binary-distinct value, refuse rather
    #          than merge two distinct identities.
    # ---------------------------------------------------------------------- #
    folded = db.execute_query(
        """SELECT id_on_platform, COUNT(DISTINCT BINARY id_on_platform) AS variants
           FROM account
           WHERE id_on_platform IS NOT NULL
           GROUP BY id_on_platform
           HAVING variants > 1""",
        [],
        return_type="rows"
    ) or []
    if folded:
        sample = ", ".join(repr(r["id_on_platform"]) for r in folded[:10])
        raise RuntimeError(
            f"V038: {len(folded)} id_on_platform value(s) collide only under the column's "
            f"case-insensitive collation, e.g. {sample}. These are distinct identifiers — "
            f"merging them would conflate distinct accounts. Switch account.id_on_platform "
            f"to a case-sensitive collation (e.g. utf8mb4_bin) and re-run."
        )

    # ---------------------------------------------------------------------- #
    # Step 0b: refuse groups whose rows disagree on a non-null platform —
    #          same pk on two platforms is two identities, not a duplicate.
    # ---------------------------------------------------------------------- #
    conflicted = db.execute_query(
        """SELECT id_on_platform, COUNT(DISTINCT platform) AS platforms
           FROM account
           WHERE id_on_platform IS NOT NULL AND platform IS NOT NULL
           GROUP BY id_on_platform
           HAVING platforms > 1""",
        [],
        return_type="rows"
    ) or []
    if conflicted:
        sample = ", ".join(repr(r["id_on_platform"]) for r in conflicted[:10])
        raise RuntimeError(
            f"V038: {len(conflicted)} id_on_platform value(s) span multiple platforms, "
            f"e.g. {sample}. These are distinct identities; this migration (and a global "
            f"UNIQUE(id_on_platform)) cannot proceed while they coexist."
        )

    # ---------------------------------------------------------------------- #
    # Step 1: soft-merge every duplicate-pk group, atomically.
    # ---------------------------------------------------------------------- #
    dup_rows = db.execute_query(
        """SELECT id_on_platform FROM account
           WHERE id_on_platform IS NOT NULL
           GROUP BY id_on_platform HAVING COUNT(*) > 1""",
        [],
        return_type="rows"
    ) or []
    dup_pks = [r["id_on_platform"] for r in dup_rows]
    print(f"    V038: {len(dup_pks)} id_on_platform value(s) with duplicate account rows")

    merged_total = 0
    with db.transaction_batch():
        for pk in dup_pks:
            rows = db.execute_query(
                "SELECT id FROM account WHERE id_on_platform = %s ORDER BY id",
                [pk],
                return_type="rows"
            )
            ids = [r["id"] for r in rows]
            keeper, dups = ids[0], ids[1:]
            for dup in dups:
                merge_account_into(keeper, dup, source="migration")
                merged_total += 1
            print(f"      pk {pk}: kept account {keeper}, tombstoned {dups}")
    print(f"    V038: tombstoned {merged_total} duplicate account row(s)")

    # ---------------------------------------------------------------------- #
    # Step 2: verify no non-null duplicates remain before constraining.
    # ---------------------------------------------------------------------- #
    remaining = db.execute_query(
        """SELECT COUNT(*) AS n FROM (
               SELECT id_on_platform FROM account
               WHERE id_on_platform IS NOT NULL
               GROUP BY id_on_platform HAVING COUNT(*) > 1
           ) d""",
        [],
        return_type="single_row"
    )["n"]
    if remaining:
        raise RuntimeError(
            f"V038: {remaining} duplicate id_on_platform group(s) still present "
            f"after de-duplication — aborting before adding UNIQUE constraint."
        )

    # ---------------------------------------------------------------------- #
    # Step 3: enforce uniqueness at the DB level (the real backstop).
    # ---------------------------------------------------------------------- #
    if _index_exists("account", _UNIQUE_NAME):
        print(f"    V038: unique index '{_UNIQUE_NAME}' already present — skipping")
    else:
        db.execute_query(
            f"ALTER TABLE account ADD CONSTRAINT {_UNIQUE_NAME} UNIQUE (id_on_platform)",
            [],
            return_type="none"
        )
        print(f"    V038: added UNIQUE constraint '{_UNIQUE_NAME}' on account.id_on_platform")

    # ---------------------------------------------------------------------- #
    # Step 4: drop the now-redundant plain index, if still present.
    # ---------------------------------------------------------------------- #
    if _index_exists("account", _OLD_INDEX_NAME):
        db.execute_query(f"DROP INDEX {_OLD_INDEX_NAME} ON account", [], return_type="none")
        print(f"    V038: dropped redundant index '{_OLD_INDEX_NAME}'")

    # ---------------------------------------------------------------------- #
    # Step 5: report residual duplicate shapes (no changes).
    # ---------------------------------------------------------------------- #
    _report_residual_duplicates()

    print("    V038: done")

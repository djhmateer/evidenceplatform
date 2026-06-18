"""
V036 — De-duplicate archive_session rows and enforce UNIQUE(external_id)

ROOT CAUSE
----------
register_archives() (db_loaders/archives_db_loader.py) built its "already
registered" set with a LIMIT/OFFSET paginated SELECT that had NO ORDER BY.
MySQL gives no stable row order across pages without ORDER BY, so once the
local_har/local_wacz session count passed _REGISTER_FETCH_BATCH (5000), pages
overlapped/skipped and some already-registered external_ids were dropped from
the set. Those archives were then treated as new and re-INSERTed. Because
archive_session.external_id carried only a PLAIN (non-unique) index, the
duplicate INSERT succeeded silently, producing a second archive_session row
with the SAME external_id but a NEW id.

The new id breaks the (canonical_id, archive_session_id) provenance key that
db_intake relies on (uq_*_canonical_session, V007): re-extraction against the
new id INSERTs a fresh set of *_archive rows instead of overriding the
originals, leaving duplicate provenance and an orphaned session row.

Canonical entities (account/post/media) and account.post_count are NOT
corrupted: post_count is recomputed from the de-duplicated `post` table, and
canonical rows are de-duplicated by identity. Only the *_archive provenance
rows and the surplus archive_session rows are duplicated. So the fix is a pure
merge — no re-extraction is required.

WHAT THIS MIGRATION DOES
------------------------
For every external_id that maps to more than one archive_session row:
  * KEEPER = the lowest id in the group. The original registration; its id is
    referenced by browsing-platform URLs and external citations, so it is never
    deleted (internal auto-increment ids are load-bearing).
  * For each of the 7 *_archive tables (the only tables FK'd to
    archive_session) the provenance rows on duplicate sessions are merged onto
    the keeper. For any canonical_id, only the row on the LOWEST session id in
    the group survives — collisions (the normal case: same archive, same HAR,
    re-extracted) are deleted to respect uq_*_canonical_session; rows for
    canonicals the keeper never saw are re-pointed, preserving their provenance.
    NULL-canonical rows are always re-pointed (UNIQUE permits multiple NULLs).
  * The keeper is backfilled from the richest duplicate for any parse/extract
    column it is missing, and its incorporation_status is upgraded to the most
    advanced status in the group, so no extracted data is lost in the rare case
    where a duplicate — not the keeper — was the row that got parsed/extracted.
  * The duplicate archive_session rows are deleted.

Then a UNIQUE constraint is added on archive_session.external_id so the bug can
never recur at the DB level, and the now-redundant plain index is dropped. SQL
NULL external_ids are left untouched — UNIQUE permits multiple NULLs.
"""

# The only tables with a FK to archive_session(id); each carries the
# uq_*_canonical_session unique constraint (canonical_id, archive_session_id).
CHILD_TABLES = [
    "account_archive",
    "account_relation_archive",
    "comment_archive",
    "media_archive",
    "post_archive",
    "post_like_archive",
    "tagged_account_archive",
]

# Parse/extract columns backfilled onto the keeper from the richest duplicate
# wherever the keeper's own value is NULL. (id/create_date/external_id/
# source_type/archive_location are identity columns and never copied.)
_BACKFILL_COLS = [
    "structures", "metadata", "attachments", "summary_html",
    "parse_algorithm_version", "extract_algorithm_version",
    "archived_url_suffix", "archived_url_parts", "archiving_timestamp",
    "notes", "platform",
]

_STATUS_RANK = {
    "done": 4, "parsed": 3, "extract_failed": 2, "parse_failed": 1, "pending": 0,
}

_UNIQUE_NAME = "uq_archive_session_external_id"
_OLD_INDEX_NAME = "archive_session_external_id_index"


def _index_exists(cur, table: str, index_name: str) -> bool:
    cur.execute(
        """SELECT COUNT(*) FROM information_schema.statistics
           WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s""",
        (table, index_name),
    )
    return cur.fetchone()[0] > 0


def _backfill_keeper(cur, keeper: int, dups: list, status_by_id: dict) -> None:
    """Fill any parse/extract column the keeper is missing from the richest
    duplicate, and upgrade the keeper's status to the best in the group. All
    rows in a group share one archive on disk, so their parse output is
    equivalent; this only matters when a duplicate (not the keeper) was the row
    that actually got parsed/extracted."""
    cols_sql = ", ".join(f"`{c}`" for c in _BACKFILL_COLS)
    cur.execute(f"SELECT {cols_sql} FROM archive_session WHERE id = %s", (keeper,))
    keeper_vals = list(cur.fetchone())
    missing = [c for c, v in zip(_BACKFILL_COLS, keeper_vals) if v is None]

    if missing:
        dups_sorted = sorted(
            dups, key=lambda i: _STATUS_RANK.get(status_by_id[i], -1), reverse=True
        )
        sel = ", ".join(f"`{c}`" for c in missing)
        ph = ",".join(["%s"] * len(dups_sorted))
        cur.execute(
            f"SELECT id, {sel} FROM archive_session WHERE id IN ({ph})", dups_sorted
        )
        dup_rows = {r[0]: r[1:] for r in cur.fetchall()}
        fill = {}
        for idx, col in enumerate(missing):
            for did in dups_sorted:
                val = dup_rows[did][idx]
                if val is not None:
                    fill[col] = val
                    break
        if fill:
            set_sql = ", ".join(f"`{c}` = %s" for c in fill)
            cur.execute(
                f"UPDATE archive_session SET {set_sql} WHERE id = %s",
                list(fill.values()) + [keeper],
            )

    best_status = max(
        (status_by_id[i] for i in [keeper] + dups),
        key=lambda s: _STATUS_RANK.get(s, -1),
    )
    if _STATUS_RANK.get(best_status, -1) > _STATUS_RANK.get(status_by_id[keeper], -1):
        cur.execute(
            "UPDATE archive_session SET incorporation_status = %s WHERE id = %s",
            (best_status, keeper),
        )


def run(cnx):
    # Buffered: _backfill_keeper issues single-row fetchone() lookups between
    # executes; an unbuffered cursor would raise "Unread result found".
    cur = cnx.cursor(buffered=True)
    try:
        # ------------------------------------------------------------------ #
        # Step 0: collation safety. external_id is a case-sensitive identifier
        #         (it embeds a filesystem path: 'har-<dir>'/'wacz-<dir>'/'aa-N').
        #         Grouping and the UNIQUE constraint use the COLUMN's collation;
        #         under a case/accent-insensitive collation two binary-distinct
        #         external_ids would be treated as equal — which would merge two
        #         DISTINCT archives here, or make ADD CONSTRAINT reject a legit
        #         pair. BINARY makes the comparison charset/collation-agnostic.
        #         If any collation-group folds >1 binary-distinct value, refuse to
        #         proceed rather than silently destroy a distinct archive.
        # ------------------------------------------------------------------ #
        cur.execute(
            """SELECT external_id, COUNT(DISTINCT BINARY external_id) AS variants
               FROM archive_session
               WHERE external_id IS NOT NULL
               GROUP BY external_id
               HAVING variants > 1"""
        )
        folded = cur.fetchall()
        if folded:
            sample = ", ".join(repr(r[0]) for r in folded[:10])
            raise RuntimeError(
                f"V036: {len(folded)} external_id value(s) collide only under the "
                f"column's collation (case/accent-insensitive), e.g. {sample}. "
                f"These are distinct identifiers, not duplicates — merging them "
                f"would destroy a distinct archive, and a UNIQUE constraint cannot "
                f"be added while they coexist. Switch archive_session.external_id "
                f"to a case-sensitive collation (e.g. utf8mb4_bin) and re-run."
            )

        # ------------------------------------------------------------------ #
        # Step 1: find external_ids that map to more than one session.
        # ------------------------------------------------------------------ #
        cur.execute(
            """SELECT external_id FROM archive_session
               WHERE external_id IS NOT NULL
               GROUP BY external_id HAVING COUNT(*) > 1"""
        )
        dup_external_ids = [row[0] for row in cur.fetchall()]
        print(f"    V036: {len(dup_external_ids)} external_id(s) with duplicate session rows")

        repointed = deleted_children = deleted_sessions = 0

        for ext_id in dup_external_ids:
            cur.execute(
                "SELECT id, incorporation_status FROM archive_session "
                "WHERE external_id = %s ORDER BY id",
                (ext_id,),
            )
            rows = cur.fetchall()
            ids = [r[0] for r in rows]
            status_by_id = {r[0]: r[1] for r in rows}
            keeper = ids[0]          # lowest id — the originally-registered, cited id
            dups = ids[1:]

            ph_group = ",".join(["%s"] * len(ids))
            ph_dups = ",".join(["%s"] * len(dups))

            for t in CHILD_TABLES:
                # Per canonical_id keep only the row on the LOWEST session id in
                # the group: delete a duplicate's row when another row in the
                # same group has the same canonical and a smaller session id.
                # (Handles both dup-vs-keeper and dup-vs-dup collisions. NULL
                # canonical_id never matches, so those rows are left for re-point.)
                cur.execute(
                    f"""DELETE d FROM `{t}` d
                        JOIN `{t}` e
                          ON e.canonical_id = d.canonical_id
                         AND e.archive_session_id IN ({ph_group})
                         AND e.archive_session_id < d.archive_session_id
                        WHERE d.archive_session_id IN ({ph_dups})""",
                    ids + dups,
                )
                deleted_children += cur.rowcount
                # Re-point the survivors onto the keeper — no collision remains.
                cur.execute(
                    f"UPDATE `{t}` SET archive_session_id = %s "
                    f"WHERE archive_session_id IN ({ph_dups})",
                    [keeper] + dups,
                )
                repointed += cur.rowcount

            _backfill_keeper(cur, keeper, dups, status_by_id)

            cur.execute(f"DELETE FROM archive_session WHERE id IN ({ph_dups})", dups)
            deleted_sessions += cur.rowcount
            print(f"      {ext_id}: kept {keeper}, merged + deleted {dups}")

        print(
            f"    V036: re-pointed {repointed} provenance row(s), "
            f"deleted {deleted_children} colliding provenance row(s), "
            f"deleted {deleted_sessions} duplicate session(s)"
        )

        # ------------------------------------------------------------------ #
        # Step 2: verify no non-null duplicates remain before constraining.
        # ------------------------------------------------------------------ #
        cur.execute(
            """SELECT COUNT(*) FROM (
                   SELECT external_id FROM archive_session
                   WHERE external_id IS NOT NULL
                   GROUP BY external_id HAVING COUNT(*) > 1
               ) d"""
        )
        remaining = cur.fetchone()[0]
        if remaining:
            raise RuntimeError(
                f"V036: {remaining} duplicate external_id group(s) still present "
                f"after de-duplication — aborting before adding UNIQUE constraint."
            )

        # ------------------------------------------------------------------ #
        # Step 3: enforce uniqueness at the DB level (the real bug fix).
        # ------------------------------------------------------------------ #
        if _index_exists(cur, "archive_session", _UNIQUE_NAME):
            print(f"    V036: unique index '{_UNIQUE_NAME}' already present — skipping")
        else:
            cur.execute(
                f"ALTER TABLE archive_session "
                f"ADD CONSTRAINT {_UNIQUE_NAME} UNIQUE (external_id)"
            )
            print(f"    V036: added UNIQUE constraint '{_UNIQUE_NAME}' on external_id")

        # ------------------------------------------------------------------ #
        # Step 4: drop the now-redundant plain index, if it is still present.
        # ------------------------------------------------------------------ #
        if _index_exists(cur, "archive_session", _OLD_INDEX_NAME):
            cur.execute(f"DROP INDEX {_OLD_INDEX_NAME} ON archive_session")
            print(f"    V036: dropped redundant index '{_OLD_INDEX_NAME}'")

        cnx.commit()
        print("    V036: done")
    finally:
        cur.close()

"""
V032 — Reset (in place) the canonical accounts contaminated by the 'None' merge bug

A past bug formatted a missing username as "None/" — stored as "None" after
normalize_url_suffix strips the trailing slash. Distinct usernameless accounts
then collided on that shared sentinel and merged into one canonical. V020 tried
to clean this but matched only the literal 'None/', so it missed the rows stored
as "None".

Two shapes of contamination survive in the DB:

  * "Pure" sentinel canonical — account.url_suffix is still '', 'None', or
    'None/'. It is the merge magnet itself.

  * "Promoted" canonical — its url_suffix was later OVERWRITTEN with a real
    username when a new archiving session re-observed one of the merged accounts
    (joined on a shared id_on_platform) and reconciliation preferred the real
    value. The canonical now LOOKS valid (real username, 'url_None' kept in the
    identifiers history) but still holds dozens of OTHER accounts' posts, and its
    per-session account_archive rows still carry the 'None' sentinel.

Detecting contamination by the canonical's url_suffix alone would miss the
promoted case. So we detect it by the per-session account_archive rows — those
still say 'None' regardless of what happened to the canonical row.

This migration RESETS each contaminated canonical IN PLACE and never deletes a
canonical row (their internal ids are referenced by the browsing platform and
external citations):

  1. Identify contaminated canonicals: those that own a sentinel account_archive
     row, plus any whose own url_suffix is a sentinel.
  2. Detach every child FK (post / media / comment / post_like / tagged_account)
     pointing at them, so re-extraction re-attaches each entity to its CORRECT
     account and the post_count sync recomputes each canonical from scratch.
  3. Delete the sentinel account_archive provenance rows (foreign-account data
     wrongly attributed to these canonicals); legitimate rows are kept.
  4. Clear a sentinel value off the canonical row itself (-> NULL). NULL is the
     legitimate id-only shape and is never a merge key; a promoted canonical
     already holds a real username and is left untouched.
  5. Re-queue every contributing session to 'parsed'. On re-extraction: the
     legitimately-owned account re-attaches its posts and re-synthesizes the
     canonical's metadata from only its surviving (correct) archive rows, while
     each wrongly-merged account is rebuilt as its own canonical.

SQL NULL is never treated as a sentinel — a NULL url_suffix is the legitimate
shape of an id-only account and must be preserved.

NOTE: between this migration and the next extraction run, the detached posts are
temporarily account-less (account_id = NULL), exactly as with V020. Run the
extraction pipeline promptly afterwards. Sessions whose HAR is unavailable will
not re-attach until they can be re-extracted.
"""


def _sentinel(col: str) -> str:
    """Match the non-NULL null-like url_suffix values the bug produced: the empty
    string, 'None', or 'None/' (trailing slash stripped to 'None'). SQL NULL is
    deliberately excluded — it is the legitimate shape of an id-only account."""
    return f"({col} = '' OR TRIM(TRAILING '/' FROM {col}) = 'None')"


def run(cnx):
    cur = cnx.cursor()
    try:
        # ------------------------------------------------------------------ #
        # Step 1: Identify contaminated canonical accounts.
        #   (a) any canonical that owns a sentinel account_archive row, and
        #   (b) any canonical whose own url_suffix is still a sentinel.
        # ------------------------------------------------------------------ #
        cur.execute(
            f"""SELECT DISTINCT canonical_id FROM account_archive
                WHERE {_sentinel('url_suffix')} AND canonical_id IS NOT NULL"""
        )
        contaminated = {row[0] for row in cur.fetchall()}

        cur.execute(f"SELECT id FROM account WHERE {_sentinel('url_suffix')}")
        contaminated.update(row[0] for row in cur.fetchall())

        if not contaminated:
            print("    V032: no contaminated canonical accounts found — nothing to do")
            return

        ids = list(contaminated)
        ph = ','.join(['%s'] * len(ids))
        print(f"    V032: {len(ids)} contaminated canonical account(s)")

        # ------------------------------------------------------------------ #
        # Step 2: Collect every 'done' session that contributed ANY archive row
        #         to a contaminated canonical (sentinel OR legit) — BEFORE we
        #         delete any rows. Includes the session that supplied the real
        #         username, so its re-extraction re-synthesizes clean metadata.
        # ------------------------------------------------------------------ #
        cur.execute(
            f"""SELECT DISTINCT aa.archive_session_id
                FROM account_archive aa
                JOIN archive_session s ON s.id = aa.archive_session_id
                WHERE aa.canonical_id IN ({ph})
                  AND s.incorporation_status = 'done'""",
            ids,
        )
        sessions = [row[0] for row in cur.fetchall()]
        print(f"    V032: {len(sessions)} contributing session(s) will be reset to 'parsed'")

        # ------------------------------------------------------------------ #
        # Step 3: Detach all child FK references to the contaminated canonicals.
        #         Re-extraction re-attaches each entity to its correct account;
        #         nulling first guarantees the post_count sync recomputes these
        #         canonicals from scratch (no carry-over of mis-merged counts).
        #         account_tag.account_id is NOT NULL but the canonical row
        #         survives, so its tags stay FK-valid and are left in place.
        # ------------------------------------------------------------------ #
        for table, col in [
            ('post', 'account_id'),
            ('media', 'account_id'),
            ('comment', 'account_id'),
            ('post_like', 'account_id'),
            ('tagged_account', 'tagged_account_id'),
        ]:
            cur.execute(
                f"UPDATE `{table}` SET `{col}` = NULL WHERE `{col}` IN ({ph})",
                ids,
            )

        # The detach above leaves every contaminated canonical with zero posts,
        # so reset the denormalized post_count to match. Re-extraction's
        # per-session sync re-inflates it as the legitimately-owned posts
        # re-attach; a pure shell that nothing re-attaches to correctly stays at
        # 0. (Without this the sync — which only touches accounts whose posts are
        # re-observed — would never revisit such a shell, leaving its old
        # inflated count, which drives the post_count search filters, forever.)
        cur.execute(f"UPDATE account SET post_count = 0 WHERE id IN ({ph})", ids)

        # ------------------------------------------------------------------ #
        # Step 4: Delete the sentinel account_archive rows (the 'None'/'' rows
        #         carrying foreign-account data). Legit non-sentinel rows stay,
        #         so a promoted canonical retains the row it re-synthesizes from.
        # ------------------------------------------------------------------ #
        cur.execute(f"DELETE FROM account_archive WHERE {_sentinel('url_suffix')}")
        print(f"    V032: deleted {cur.rowcount} sentinel account_archive row(s)")

        # ------------------------------------------------------------------ #
        # Step 5: Clear the sentinel value off the canonical row itself (-> NULL).
        #         Promoted canonicals hold a real username and are not matched.
        # ------------------------------------------------------------------ #
        cur.execute(f"UPDATE account SET url_suffix = NULL WHERE {_sentinel('url_suffix')}")
        print(f"    V032: nulled url_suffix on {cur.rowcount} canonical account(s)")

        # ------------------------------------------------------------------ #
        # Step 6: Re-queue the contributing sessions for re-extraction.
        # ------------------------------------------------------------------ #
        if sessions:
            ph_s = ','.join(['%s'] * len(sessions))
            cur.execute(
                f"""UPDATE archive_session
                    SET incorporation_status = 'parsed'
                    WHERE id IN ({ph_s})
                      AND incorporation_status = 'done'""",
                sessions,
            )
            print(f"    V032: reset {cur.rowcount} session(s) to 'parsed'")

        # ------------------------------------------------------------------ #
        # Step 7: Report (do NOT delete) canonicals left as empty shells — no
        #         id_on_platform to re-attach to and no surviving archive rows.
        #         These are pure garbage magnets; prune separately if desired.
        # ------------------------------------------------------------------ #
        cur.execute(
            f"""SELECT COUNT(*) FROM account a
                WHERE a.id IN ({ph})
                  AND a.id_on_platform IS NULL
                  AND NOT EXISTS (SELECT 1 FROM account_archive aa WHERE aa.canonical_id = a.id)""",
            ids,
        )
        shells = cur.fetchone()[0]
        if shells:
            print(f"    V032: {shells} canonical(s) will remain as empty shells "
                  f"(NULL id_on_platform, no archive rows) — prune separately if desired")

        cnx.commit()
        print("    V032: done")

    finally:
        cur.close()

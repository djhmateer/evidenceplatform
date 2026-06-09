"""
V035 — Make share-link attachment access conservative by default

Sets include_screen_recordings and include_har to 0 on all existing rows in
entity_share_link. Previously these defaulted to 1 (include), which exposed
HAR files and screen recordings to recipients unless explicitly disabled.
Link sharing should be conservative by default: minimal attachment access
unless the owner opts in.
"""


def _column_exists(cur, table, column):
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
        (table, column),
    )
    return cur.fetchone()[0] > 0


def run(cnx):
    cur = cnx.cursor()
    try:
        if not _column_exists(cur, "entity_share_link", "include_screen_recordings") \
                or not _column_exists(cur, "entity_share_link", "include_har"):
            print("    entity_share_link: attachment-access columns missing, skipping")
            return

        cur.execute(
            "UPDATE entity_share_link "
            "SET include_screen_recordings = 0, include_har = 0"
        )
        print(f"    entity_share_link: reset attachment access to minimal on {cur.rowcount} rows")
        cnx.commit()
    finally:
        cur.close()

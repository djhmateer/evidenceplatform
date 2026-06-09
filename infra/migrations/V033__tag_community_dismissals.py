"""
V033 — Add tag.community_dismissals

A nullable JSON column on `tag` holding the list of candidate accounts the user
has dismissed from the community-detection candidates list while the page was in
tag-bound mode for this tag. Each entry is {id, url_suffix, display_name}. The
list is per-tag only — the tag hierarchy is intentionally not consulted.
"""


def run(cnx):
    cur = cnx.cursor()
    try:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() "
            "  AND table_name = 'tag' AND column_name = 'community_dismissals'",
        )
        if cur.fetchone()[0] > 0:
            print("    tag.community_dismissals: already exists, skipping")
        else:
            print("    tag.community_dismissals: adding ...", flush=True)
            cur.execute(
                "ALTER TABLE tag ADD COLUMN community_dismissals JSON NULL "
                "COMMENT 'Per-tag community-detection candidate dismissals: "
                "[{id, url_suffix, display_name}]'"
            )
            print("    tag.community_dismissals: added")

        cnx.commit()
    finally:
        cur.close()

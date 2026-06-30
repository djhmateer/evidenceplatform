"""
V044 — Collapse the 'media_part' tag-type affinity into 'media'.

A MediaPart now shares its parent media's tag set: there is no separate
'media_part' affinity, and the backend validates a part's tags against the
'media' affinity (services/annotation.validate_tags_entity_affinity). Any
existing tag_type that listed 'media_part' in its entity_affinity JSON must be
rewritten so it keeps working — otherwise a type that listed only 'media_part'
would suddenly reject both media and media-part assignments.

For each affected tag_type we replace 'media_part' with 'media' and de-duplicate
the resulting list (preserving order).
"""

import json


def run(cnx):
    cur = cnx.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, entity_affinity FROM tag_type WHERE entity_affinity IS NOT NULL"
        )
        rows = cur.fetchall()
        updated = 0
        for row in rows:
            ea = row["entity_affinity"]
            if isinstance(ea, str):
                try:
                    ea = json.loads(ea)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not isinstance(ea, list) or "media_part" not in ea:
                continue
            # Replace media_part -> media, then dedup preserving order.
            mapped = ["media" if v == "media_part" else v for v in ea]
            seen = set()
            deduped = []
            for v in mapped:
                if v not in seen:
                    seen.add(v)
                    deduped.append(v)
            cur.execute(
                "UPDATE tag_type SET entity_affinity = %s WHERE id = %s",
                (json.dumps(deduped), row["id"]),
            )
            updated += 1
        cnx.commit()
        print(f"    V044: rewrote media_part affinity on {updated} tag_type(s)")
    finally:
        cur.close()

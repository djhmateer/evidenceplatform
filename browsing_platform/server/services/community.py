import json
from typing import Callable, Optional

from pydantic import BaseModel

from browsing_platform.server.services.media import get_media_thumbnail_path
from browsing_platform.server.services.search import SearchResultTransform, Thumbnail, sign_thumbnail_path
from browsing_platform.server.services.tag import ITagWithType
from browsing_platform.server.services.tag_management import IQuickAccessTypeDropdown, ITagHierarchyEntry
from utils import db

TOP_N = 50
SUGGESTED_RELATION_TYPE = 'suggested'
DEFAULT_TIE_WEIGHTS: dict[str, float] = {
    'follow': 1.0,
    'suggested': 0.0,
    'like': 1.0,
    'comment': 1.0,
    'tag': 1.0,
}


class TieWeights(BaseModel):
    follow: float = DEFAULT_TIE_WEIGHTS['follow']
    suggested: float = DEFAULT_TIE_WEIGHTS['suggested']
    like: float = DEFAULT_TIE_WEIGHTS['like']
    comment: float = DEFAULT_TIE_WEIGHTS['comment']
    tag: float = DEFAULT_TIE_WEIGHTS['tag']


class CommunityCandidatesRequest(BaseModel):
    kernel_ids: list[int]
    excluded_ids: list[int] = []
    weights: TieWeights = TieWeights()


class CandidateAccount(BaseModel):
    id: int
    url_suffix: Optional[str] = None
    display_name: Optional[str] = None
    bio: Optional[str] = None
    is_verified: Optional[bool] = None
    score: float
    kernel_connections: int
    thumbnails: list[Thumbnail] = []
    media_count: int = 0
    follower_count: int = 0
    following_count: int = 0
    post_count: int = 0


class CommunityCandidatesResponse(BaseModel):
    candidates: list[CandidateAccount]


class TagKernelAccount(BaseModel):
    id: int
    url_suffix: Optional[str] = None
    display_name: Optional[str] = None
    bio: Optional[str] = None
    thumbnails: list[Thumbnail] = []
    media_count: int = 0
    applied_tags: list[ITagWithType] = []


class DismissedAccount(BaseModel):
    id: int
    url_suffix: Optional[str] = None
    display_name: Optional[str] = None


class TagDismissalsRequest(BaseModel):
    dismissals: list[DismissedAccount] = []


class TagKernelResponse(BaseModel):
    accounts: list[TagKernelAccount]
    dropdown: IQuickAccessTypeDropdown
    dismissals: list[DismissedAccount] = []


def _parse_is_verified(data) -> Optional[bool]:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return None
    if isinstance(data, dict):
        v = data.get('is_verified')
        if isinstance(v, bool):
            return v
    return None


def _weight_args(weights: TieWeights) -> dict:
    return {
        "follow_w": weights.follow,
        "suggested_w": weights.suggested,
        "like_w": weights.like,
        "comment_w": weights.comment,
        "tag_w": weights.tag,
        "suggested_type": SUGGESTED_RELATION_TYPE,
    }


def _build_score_sql(k_in: str, cand_pred: Callable[[str], str], limited: bool) -> str:
    """Build the tie-scoring query shared by candidate and kernel scoring.

    ``cand_pred(col)`` produces the predicate restricting the *candidate* side of
    each tie: ``NOT IN (excluded)`` when ranking external candidates, or
    ``IN (kernel)`` when scoring kernel members against one another. The two
    GROUP BY stages run entirely in MySQL; only the result rows reach Python.
    """
    limit_clause = "\n        LIMIT %(top_n)s" if limited else ""
    return f"""
        WITH ties AS (
            -- follow: kernel member is the follower
            SELECT ar.followed_account_id AS candidate_id,
                   ar.follower_account_id AS kernel_id,
                   %(follow_w)s           AS weight
            FROM account_relation ar
            WHERE ar.follower_account_id IN ({k_in})
              AND {cand_pred('ar.followed_account_id')}
              AND (ar.relation_type IS NULL OR ar.relation_type != %(suggested_type)s)

            UNION ALL

            -- follow: kernel member is the followed account
            SELECT ar.follower_account_id AS candidate_id,
                   ar.followed_account_id AS kernel_id,
                   %(follow_w)s           AS weight
            FROM account_relation ar
            WHERE ar.followed_account_id IN ({k_in})
              AND {cand_pred('ar.follower_account_id')}
              AND (ar.relation_type IS NULL OR ar.relation_type != %(suggested_type)s)

            UNION ALL

            -- suggested: kernel member is follower_account_id
            SELECT ar.followed_account_id, ar.follower_account_id, %(suggested_w)s
            FROM account_relation ar
            WHERE ar.follower_account_id IN ({k_in})
              AND {cand_pred('ar.followed_account_id')}
              AND ar.relation_type = %(suggested_type)s

            UNION ALL

            -- suggested: kernel member is followed_account_id
            SELECT ar.follower_account_id, ar.followed_account_id, %(suggested_w)s
            FROM account_relation ar
            WHERE ar.followed_account_id IN ({k_in})
              AND {cand_pred('ar.follower_account_id')}
              AND ar.relation_type = %(suggested_type)s

            UNION ALL

            -- like: kernel member authored the liked post
            SELECT pl.account_id, p.account_id, %(like_w)s
            FROM post_like pl
            JOIN post p ON pl.post_id = p.id
            WHERE p.account_id IN ({k_in})
              AND pl.account_id IS NOT NULL
              AND {cand_pred('pl.account_id')}

            UNION ALL

            -- like: kernel member liked someone else's post
            SELECT p.account_id, pl.account_id, %(like_w)s
            FROM post_like pl
            JOIN post p ON pl.post_id = p.id
            WHERE pl.account_id IN ({k_in})
              AND p.account_id IS NOT NULL
              AND {cand_pred('p.account_id')}

            UNION ALL

            -- comment: kernel member authored the commented post
            SELECT c.account_id, p.account_id, %(comment_w)s
            FROM comment c
            JOIN post p ON c.post_id = p.id
            WHERE p.account_id IN ({k_in})
              AND c.account_id IS NOT NULL
              AND {cand_pred('c.account_id')}

            UNION ALL

            -- comment: kernel member left the comment
            SELECT p.account_id, c.account_id, %(comment_w)s
            FROM comment c
            JOIN post p ON c.post_id = p.id
            WHERE c.account_id IN ({k_in})
              AND p.account_id IS NOT NULL
              AND {cand_pred('p.account_id')}

            UNION ALL

            -- tag: kernel member tagged someone in a post
            SELECT ta.tagged_account_id, p.account_id, %(tag_w)s
            FROM tagged_account ta
            JOIN post p ON ta.post_id = p.id
            WHERE p.account_id IN ({k_in})
              AND ta.tagged_account_id IS NOT NULL
              AND {cand_pred('ta.tagged_account_id')}

            UNION ALL

            -- tag: kernel member tagged someone in media
            SELECT ta.tagged_account_id, m.account_id, %(tag_w)s
            FROM tagged_account ta
            JOIN media m ON ta.media_id = m.id
            WHERE m.account_id IN ({k_in})
              AND ta.tagged_account_id IS NOT NULL
              AND {cand_pred('ta.tagged_account_id')}

            UNION ALL

            -- tag: kernel member was tagged in a post
            SELECT p.account_id, ta.tagged_account_id, %(tag_w)s
            FROM tagged_account ta
            JOIN post p ON ta.post_id = p.id
            WHERE ta.tagged_account_id IN ({k_in})
              AND p.account_id IS NOT NULL
              AND {cand_pred('p.account_id')}

            UNION ALL

            -- tag: kernel member was tagged in media
            SELECT m.account_id, ta.tagged_account_id, %(tag_w)s
            FROM tagged_account ta
            JOIN media m ON ta.media_id = m.id
            WHERE ta.tagged_account_id IN ({k_in})
              AND m.account_id IS NOT NULL
              AND {cand_pred('m.account_id')}
        ),
        pair_strength AS (
            SELECT candidate_id, kernel_id, MAX(weight) AS strength
            FROM ties
            WHERE candidate_id != kernel_id
            GROUP BY candidate_id, kernel_id
        ),
        candidate_scores AS (
            SELECT candidate_id,
                   SUM(strength)             AS score,
                   COUNT(DISTINCT kernel_id) AS kernel_connections
            FROM pair_strength
            GROUP BY candidate_id
            HAVING score > 0
        )
        SELECT candidate_id, score, kernel_connections
        FROM candidate_scores
        ORDER BY score DESC{limit_clause}
        """


def _parse_score_rows(score_rows) -> tuple[list[int], dict[int, float], dict[int, int]]:
    ids: list[int] = []
    score_map: dict[int, float] = {}
    connections_map: dict[int, int] = {}
    for row in score_rows:
        cid = row["candidate_id"]
        ids.append(cid)
        score_map[cid] = row["score"]
        connections_map[cid] = row["kernel_connections"]
    return ids, score_map, connections_map


def _hydrate_accounts(
        ids: list[int],
        score_map: dict[int, float],
        connections_map: dict[int, int],
        transform: Optional[SearchResultTransform] = None,
) -> list[CandidateAccount]:
    """Build ``CandidateAccount`` objects for every id, preserving the given order.

    Accounts absent from ``score_map``/``connections_map`` default to a score and
    connection count of 0 (so kernel members with no internal ties still appear).
    """
    if not ids:
        return []

    cand_args = {f"c_{i}": cid for i, cid in enumerate(ids)}
    cand_in = ", ".join(f"%(c_{i})s" for i in range(len(ids)))

    account_rows = db.execute_query(  # nosec B608
        f"SELECT id, url_suffix, display_name, bio, data, post_count FROM account WHERE id IN ({cand_in})",
        cand_args,
        return_type="rows",
    )
    account_map = {r["id"]: r for r in account_rows}

    # Scraped relation counts (real follows only — 'suggested' relations excluded).
    # Both directions in one batched pass: followers = account is the followed
    # party, following = account is the follower.
    relation_rows = db.execute_query(  # nosec B608
        f"""SELECT account_id, direction, COUNT(*) AS cnt FROM (
                SELECT followed_account_id AS account_id, 'followers' AS direction
                FROM account_relation
                WHERE followed_account_id IN ({cand_in})
                  AND (relation_type IS NULL OR relation_type != %(suggested_type)s)
                UNION ALL
                SELECT follower_account_id AS account_id, 'following' AS direction
                FROM account_relation
                WHERE follower_account_id IN ({cand_in})
                  AND (relation_type IS NULL OR relation_type != %(suggested_type)s)
            ) r
            GROUP BY account_id, direction""",
        {**cand_args, "suggested_type": SUGGESTED_RELATION_TYPE},
        return_type="rows",
    )
    follower_map: dict[int, int] = {}
    following_map: dict[int, int] = {}
    for r in relation_rows:
        if r["direction"] == "followers":
            follower_map[r["account_id"]] = r["cnt"]
        else:
            following_map[r["account_id"]] = r["cnt"]

    thumb_rows = db.execute_query(  # nosec B608
        f"""SELECT account_id, thumbnail_path, local_url, aspect_ratio, media_count
            FROM (
                SELECT account_id, thumbnail_path, local_url, aspect_ratio,
                       COUNT(*) OVER (PARTITION BY account_id) AS media_count,
                       ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY publication_date DESC) AS rn
                FROM media
                WHERE account_id IN ({cand_in})
                  AND local_url IS NOT NULL
            ) ranked
            WHERE rn <= 8""",
        cand_args,
        return_type="rows",
    )

    thumb_map: dict[int, list[Thumbnail]] = {}
    media_count_map: dict[int, int] = {}
    should_sign = transform is not None and transform.access_token is not None
    for t in thumb_rows:
        aid = t["account_id"]
        media_count_map[aid] = t["media_count"]
        src = get_media_thumbnail_path(t["thumbnail_path"], t["local_url"])
        if src:
            if should_sign:
                src = sign_thumbnail_path(src, transform)
            thumb_map.setdefault(aid, []).append(Thumbnail(src=src, aspect_ratio=t.get("aspect_ratio")))

    candidates = []
    for cid in ids:
        acct = account_map.get(cid)
        if not acct:
            continue
        candidates.append(CandidateAccount(
            id=cid,
            url_suffix=acct.get("url_suffix"),
            display_name=acct.get("display_name"),
            bio=acct.get("bio"),
            is_verified=_parse_is_verified(acct.get("data")),
            score=score_map.get(cid, 0),
            kernel_connections=connections_map.get(cid, 0),
            thumbnails=thumb_map.get(cid, []),
            media_count=media_count_map.get(cid, 0),
            follower_count=follower_map.get(cid, 0),
            following_count=following_map.get(cid, 0),
            post_count=acct.get("post_count") or 0,
        ))

    return candidates


def compute_candidates(
        req: CommunityCandidatesRequest,
        transform: Optional[SearchResultTransform] = None,
) -> CommunityCandidatesResponse:
    if not req.kernel_ids:
        return CommunityCandidatesResponse(candidates=[])

    kernel_ids = req.kernel_ids
    all_excluded = list(set(kernel_ids) | set(req.excluded_ids))

    k_args = {f"k_{i}": kid for i, kid in enumerate(kernel_ids)}
    k_in = ", ".join(f"%(k_{i})s" for i in range(len(kernel_ids)))
    ex_args = {f"ex_{i}": eid for i, eid in enumerate(all_excluded)}
    ex_in = ", ".join(f"%(ex_{i})s" for i in range(len(all_excluded)))

    query_args = {**k_args, **ex_args, **_weight_args(req.weights), "top_n": TOP_N}

    score_rows = db.execute_query(  # nosec B608 - k_in / ex_in contain only %(key)s placeholders
        _build_score_sql(k_in, lambda col: f"{col} NOT IN ({ex_in})", limited=True),
        query_args,
        return_type="rows",
    )

    if not score_rows:
        return CommunityCandidatesResponse(candidates=[])

    top_ids, score_map, connections_map = _parse_score_rows(score_rows)
    return CommunityCandidatesResponse(
        candidates=_hydrate_accounts(top_ids, score_map, connections_map, transform),
    )


def compute_kernel_scores(
        req: CommunityCandidatesRequest,
        transform: Optional[SearchResultTransform] = None,
) -> CommunityCandidatesResponse:
    """Score each kernel member by its tie strength to the *other* kernel members.

    Reuses the optimized batched scoring of ``compute_candidates`` (the candidate
    side is restricted to the kernel rather than excluded from it), so every
    member's score is produced by a single query rather than O(n) per-account
    queries. Every kernel id is hydrated, including members with no internal ties
    (score 0). ``req.excluded_ids`` is ignored in this mode.
    """
    if not req.kernel_ids:
        return CommunityCandidatesResponse(candidates=[])

    kernel_ids = req.kernel_ids
    k_args = {f"k_{i}": kid for i, kid in enumerate(kernel_ids)}
    k_in = ", ".join(f"%(k_{i})s" for i in range(len(kernel_ids)))

    query_args = {**k_args, **_weight_args(req.weights)}

    score_rows = db.execute_query(  # nosec B608 - k_in contains only %(key)s placeholders
        _build_score_sql(k_in, lambda col: f"{col} IN ({k_in})", limited=False),
        query_args,
        return_type="rows",
    )

    _, score_map, connections_map = _parse_score_rows(score_rows)
    return CommunityCandidatesResponse(
        candidates=_hydrate_accounts(kernel_ids, score_map, connections_map, transform),
    )


# ── Tag-based kernel helpers ──────────────────────────────────────────────────

_TAG_COLS = """
    t.id, t.name, t.description, t.tag_type_id,
    tt.name AS tag_type_name,
    tt.description AS tag_type_description,
    tt.notes AS tag_type_notes,
    tt.entity_affinity AS tag_type_entity_affinity
"""


def get_community_tag_dropdown(tag_id: int) -> IQuickAccessTypeDropdown:
    """Return an IQuickAccessTypeDropdown for the tag and all its descendants."""
    tag_rows = db.execute_query(  # nosec B608
        f"""WITH RECURSIVE tag_desc AS (
                SELECT id FROM tag WHERE id = %(tag_id)s
                UNION ALL
                SELECT th.sub_tag_id FROM tag_hierarchy th
                JOIN tag_desc td ON th.super_tag_id = td.id
            )
            SELECT {_TAG_COLS}
            FROM tag_desc td
            JOIN tag t ON t.id = td.id
            LEFT JOIN tag_type tt ON t.tag_type_id = tt.id""",
        {"tag_id": tag_id},
        return_type="rows",
    )
    if not tag_rows:
        return IQuickAccessTypeDropdown(type_id=tag_id, type_name="", tags=[], hierarchy=[])

    tag_id_set = {r["id"] for r in tag_rows}

    if len(tag_id_set) > 1:
        h_ids = list(tag_id_set)
        h_args = {f"h_{i}": tid for i, tid in enumerate(h_ids)}
        h_in = ", ".join(f"%(h_{i})s" for i in range(len(h_ids)))
        hierarchy_rows = db.execute_query(  # nosec B608
            f"SELECT super_tag_id, sub_tag_id FROM tag_hierarchy WHERE super_tag_id IN ({h_in}) AND sub_tag_id IN ({h_in})",
            h_args,
            return_type="rows",
        )
    else:
        hierarchy_rows = []

    return IQuickAccessTypeDropdown(
        type_id=tag_id,
        type_name=None,
        tags=[ITagWithType(**row) for row in tag_rows],
        hierarchy=[ITagHierarchyEntry(super_tag_id=h["super_tag_id"], sub_tag_id=h["sub_tag_id"]) for h in hierarchy_rows],
    )


def get_tag_dismissals(tag_id: int) -> list[DismissedAccount]:
    """Return the candidate dismissals saved for this tag (its own list only).

    The tag hierarchy is intentionally not consulted — each tag keeps its own
    dismissal list (see the community detection page for the rationale).
    """
    row = db.execute_query(
        "SELECT community_dismissals FROM tag WHERE id = %(tag_id)s",
        {"tag_id": tag_id},
        return_type="single_row",
    )
    if not row:
        return []
    raw = row.get("community_dismissals")
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    dismissals: list[DismissedAccount] = []
    for item in raw:
        if isinstance(item, dict) and item.get("id") is not None:
            dismissals.append(DismissedAccount(
                id=item["id"],
                url_suffix=item.get("url_suffix"),
                display_name=item.get("display_name"),
            ))
    return dismissals


def set_tag_dismissals(tag_id: int, dismissals: list[DismissedAccount]) -> None:
    """Overwrite the tag's saved candidate dismissals with the given list."""
    payload = json.dumps([d.model_dump() for d in dismissals])
    db.execute_query(
        "UPDATE tag SET community_dismissals = %(payload)s WHERE id = %(tag_id)s",
        {"payload": payload, "tag_id": tag_id},
        return_type="none",
    )


def get_tag_kernel_accounts(
        tag_id: int,
        transform: Optional[SearchResultTransform] = None,
) -> TagKernelResponse:
    """Return all accounts tagged with tag_id or any of its descendants, with applied tags."""
    dropdown = get_community_tag_dropdown(tag_id)
    dismissals = get_tag_dismissals(tag_id)

    if not dropdown.tags:
        return TagKernelResponse(accounts=[], dropdown=dropdown, dismissals=dismissals)

    tag_by_id: dict[int, ITagWithType] = {t.id: t for t in dropdown.tags}
    d_args = {f"d_{i}": tid for i, tid in enumerate(tag_by_id)}
    d_in = ", ".join(f"%(d_{i})s" for i in range(len(tag_by_id)))

    tag_account_rows = db.execute_query(  # nosec B608
        f"SELECT account_id, tag_id FROM account_tag WHERE tag_id IN ({d_in})",
        d_args,
        return_type="rows",
    )
    if not tag_account_rows:
        return TagKernelResponse(accounts=[], dropdown=dropdown, dismissals=dismissals)

    applied_tags_map: dict[int, list[ITagWithType]] = {}
    for r in tag_account_rows:
        tag = tag_by_id.get(r["tag_id"])
        if tag:
            applied_tags_map.setdefault(r["account_id"], []).append(tag)

    account_ids = list(applied_tags_map.keys())
    cand_args = {f"c_{i}": aid for i, aid in enumerate(account_ids)}
    cand_in = ", ".join(f"%(c_{i})s" for i in range(len(account_ids)))

    account_rows = db.execute_query(  # nosec B608
        f"SELECT id, url_suffix, display_name, bio FROM account WHERE id IN ({cand_in})",
        cand_args,
        return_type="rows",
    )
    account_map = {r["id"]: r for r in account_rows}

    thumb_rows = db.execute_query(  # nosec B608
        f"""SELECT account_id, thumbnail_path, local_url, aspect_ratio, media_count
            FROM (
                SELECT account_id, thumbnail_path, local_url, aspect_ratio,
                       COUNT(*) OVER (PARTITION BY account_id) AS media_count,
                       ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY publication_date DESC) AS rn
                FROM media
                WHERE account_id IN ({cand_in})
                  AND local_url IS NOT NULL
            ) ranked
            WHERE rn <= 8""",
        cand_args,
        return_type="rows",
    )

    thumb_map: dict[int, list[Thumbnail]] = {}
    media_count_map: dict[int, int] = {}
    should_sign = transform is not None and transform.access_token is not None
    for t in thumb_rows:
        aid = t["account_id"]
        media_count_map[aid] = t["media_count"]
        src = get_media_thumbnail_path(t["thumbnail_path"], t["local_url"])
        if src:
            if should_sign:
                src = sign_thumbnail_path(src, transform)
            thumb_map.setdefault(aid, []).append(Thumbnail(src=src, aspect_ratio=t.get("aspect_ratio")))

    accounts = []
    for aid in account_ids:
        acct = account_map.get(aid)
        if not acct:
            continue
        accounts.append(TagKernelAccount(
            id=aid,
            url_suffix=acct.get("url_suffix"),
            display_name=acct.get("display_name"),
            bio=acct.get("bio"),
            thumbnails=thumb_map.get(aid, []),
            media_count=media_count_map.get(aid, 0),
            applied_tags=applied_tags_map[aid],
        ))

    return TagKernelResponse(accounts=accounts, dropdown=dropdown, dismissals=dismissals)

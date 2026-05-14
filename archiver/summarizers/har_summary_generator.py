import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from extractors.entity_types import (
    AccountAndAssociatedEntities, PostAndAssociatedEntities, ExtractedEntitiesNested,
    MediaAndAssociatedEntities, Comment, Like, TaggedAccount, AccountRelation
)
from extractors.extract_photos import PhotoAcquisitionConfig
from extractors.extract_videos import VideoAcquisitionConfig
from extractors.structures_to_entities import extract_entities_from_har, nest_entities_from_archive_session


def generate_stylesheet() -> str:
    return """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
    --ig-gradient: linear-gradient(45deg, #833ab4, #fd1d1d, #fcb045);
    --bg: #eef1f5;
    --surface: #ffffff;
    --surface-2: #f8fafc;
    --surface-3: #f1f5f9;
    --border: #e2e8f0;
    --border-strong: #cbd5e1;
    --text-primary: #0f172a;
    --text-secondary: #475569;
    --text-muted: #64748b;
    --text-link: #1d4ed8;
    --accent: #833ab4;
    --radius: 14px;
    --radius-sm: 8px;
    --shadow-sm: 0 1px 2px rgba(15,23,42,0.04), 0 1px 1px rgba(15,23,42,0.03);
    --shadow: 0 1px 3px rgba(15,23,42,0.06), 0 8px 24px rgba(15,23,42,0.05);
}

html { scrollbar-color: #cbd5e1 transparent; scrollbar-width: thin; }

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, Roboto, sans-serif;
    font-size: 15px;
    background: var(--bg);
    color: var(--text-primary);
    line-height: 1.55;
    padding: 0;
    min-height: 100vh;
}

.page {
    max-width: 960px;
    margin: 0 auto;
    padding: 24px 20px 96px;
}

.summary-title {
    font-size: 20px;
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 20px;
    padding: 16px 22px;
    background: var(--surface);
    border-radius: var(--radius);
    border: 1px solid var(--border);
    box-shadow: var(--shadow);
    position: sticky;
    top: 12px;
    z-index: 20;
    overflow: hidden;
    backdrop-filter: saturate(140%) blur(8px);
}
.summary-title::before {
    content: '';
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 4px;
    background: var(--ig-gradient);
}
.summary-counts {
    display: block;
    margin-top: 6px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary);
    letter-spacing: 0.04em;
    text-transform: uppercase;
}

.section-title {
    font-size: 12px;
    font-weight: 700;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin: 28px 4px 10px;
}

/* ── Account card ─────────────────────────────────── */
.account-card {
    background: var(--surface);
    border-radius: var(--radius);
    border: 1px solid var(--border);
    box-shadow: var(--shadow);
    margin-bottom: 18px;
    overflow: hidden;
}

.account-header {
    display: flex;
    align-items: flex-start;
    gap: 14px;
    padding: 18px 22px;
    border-bottom: 1px solid var(--border);
}

.account-avatar {
    width: 52px; height: 52px;
    border-radius: 50%;
    background: var(--ig-gradient);
    display: flex; align-items: center; justify-content: center;
    font-size: 22px; font-weight: 700;
    color: #fff;
    flex-shrink: 0;
    letter-spacing: -0.5px;
    text-transform: uppercase;
}

.account-info { flex: 1; min-width: 0; }

.account-username {
    font-size: 16px; font-weight: 700;
    color: var(--text-primary);
    text-decoration: none;
    display: block;
    margin-bottom: 2px;
}
.account-username:hover { text-decoration: underline; }

.account-display-name {
    font-size: 14px; color: var(--text-secondary);
    margin-bottom: 4px;
}

.account-bio {
    font-size: 13px; color: var(--text-secondary);
    white-space: pre-line;
}

.account-stats { display: flex; gap: 8px; flex-shrink: 0; }

.stat-badge {
    background: var(--ig-gradient);
    color: #fff;
    font-size: 12px; font-weight: 600;
    padding: 4px 10px;
    border-radius: 20px;
    white-space: nowrap;
}

/* ── Relations ───────────────────────────────────── */
.relations-list {
    display: flex; flex-direction: column; gap: 2px;
}

.relation-item {
    display: flex; align-items: center; gap: 8px;
    padding: 6px 0;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
}
.relation-item:last-child { border-bottom: none; }

.relation-type {
    font-size: 11px; font-weight: 600;
    background: var(--surface-3);
    padding: 2px 8px; border-radius: 10px;
    color: var(--text-secondary);
    flex-shrink: 0;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

.relation-name { font-weight: 600; color: var(--text-primary); }

.relation-url {
    color: var(--text-link);
    text-decoration: none;
    font-size: 12px;
    font-family: 'Courier New', Courier, monospace;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.relation-url:hover { text-decoration: underline; }

.account-posts { padding: 4px 22px 18px; }

.account-posts-label {
    font-size: 11px; font-weight: 700;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 14px 0 10px;
}

/* ── Post card ───────────────────────────────────── */
.post-card {
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    margin-bottom: 14px;
    overflow: hidden;
    background: var(--surface-2);
    box-shadow: var(--shadow-sm);
}

.post-header { padding: 14px 16px 10px; }

.post-meta {
    display: flex; align-items: center; flex-wrap: wrap;
    gap: 8px; margin-bottom: 8px;
}

.post-date {
    font-size: 12px; color: var(--text-secondary);
    font-variant-numeric: tabular-nums;
}

.post-url-chip {
    font-family: ui-monospace, "SF Mono", "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
    background: var(--surface-3);
    color: var(--text-link);
    padding: 3px 9px; border-radius: 6px;
    text-decoration: none;
    white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
    max-width: 360px;
    display: inline-block;
    border: 1px solid var(--border);
}
.post-url-chip:hover { background: var(--surface); border-color: var(--border-strong); }

.post-caption {
    font-size: 14px; color: var(--text-primary);
    line-height: 1.5;
    overflow: hidden;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
}
.post-caption.expanded { -webkit-line-clamp: unset; }

.caption-toggle {
    font-size: 12px; color: var(--text-link);
    cursor: pointer; background: none; border: none;
    padding: 4px 0;
    display: inline-block;
    margin-top: 2px;
}
.caption-toggle:hover { text-decoration: underline; }

/* ── Media grid ──────────────────────────────────── */
.post-media-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 12px;
    align-items: start;
    padding: 0 16px 14px;
}

.media-item {
    display: flex; flex-direction: column;
    gap: 8px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px;
}

.media-preview {
    width: 100%;
    height: auto;
    max-height: 520px;
    object-fit: contain;
    border-radius: 6px;
    display: block;
    background: #0b0d12;
}
video.media-preview, audio.media-preview { width: 100%; height: auto; }
audio.media-preview { background: var(--surface-3); }

.media-actions {
    display: flex; gap: 6px; flex-wrap: wrap;
    align-items: center;
}

.download-btn {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 6px 14px;
    background: var(--ig-gradient);
    color: #fff;
    font-size: 12px; font-weight: 600;
    text-decoration: none;
    border-radius: 6px;
    transition: opacity 0.15s, transform 0.15s;
    white-space: nowrap;
}
.download-btn:hover { opacity: 0.9; transform: translateY(-1px); }

/* ── Collapsible sections ────────────────────────── */
.collapsible-section { border-top: 1px solid var(--border); }

.collapsible-header {
    display: flex; align-items: center; justify-content: space-between;
    width: 100%;
    padding: 11px 16px;
    cursor: pointer;
    user-select: none;
    font-size: 13px; font-weight: 600;
    color: var(--text-secondary);
    background: transparent;
    border: 0;
    text-align: left;
    font-family: inherit;
    transition: background 0.15s, color 0.15s;
}
.collapsible-header:hover { background: var(--surface-3); color: var(--text-primary); }
.collapsible-header:focus-visible {
    outline: 2px solid var(--text-link);
    outline-offset: -2px;
}

.collapsible-indicator {
    display: inline-flex;
    align-items: center; justify-content: center;
    width: 20px; height: 20px;
    border-radius: 50%;
    background: var(--surface-3);
    color: var(--text-secondary);
    font-size: 14px; font-weight: 700;
    line-height: 1;
    transition: background 0.15s, color 0.15s;
}
.collapsible-indicator::before { content: "+"; }
.collapsible-header.open .collapsible-indicator { background: var(--text-secondary); color: #fff; }
.collapsible-header.open .collapsible-indicator::before { content: "−"; }

.collapsible-body { display: none; padding: 10px 16px 14px; }
.collapsible-body.open { display: block; }

/* JSON data — de-emphasized via size + surface, NOT contrast */
.json-collapsible .collapsible-header {
    font-size: 11px;
    color: var(--text-muted);
    font-weight: 600;
    padding: 8px 16px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.json-collapsible .collapsible-header:hover { color: var(--text-secondary); }
.json-collapsible .collapsible-body {
    font-family: ui-monospace, "SF Mono", "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    color: var(--text-secondary);
    white-space: pre-wrap; word-break: break-all;
    background: var(--surface-2);
    border-top: 1px solid var(--border);
    max-height: 320px; overflow: auto;
    padding: 10px 16px 12px;
    line-height: 1.5;
}

/* ── Comments ────────────────────────────────────── */
.comments-list { display: flex; flex-direction: column; gap: 6px; }

.comment-item {
    border-left: 3px solid var(--border);
    padding: 9px 12px;
    border-radius: 0 6px 6px 0;
    transition: border-color 0.15s, background 0.15s;
    background: var(--surface);
}
.comment-item:hover { border-left-color: var(--accent); background: var(--surface-2); }
.comment-item.reply {
    margin-left: 24px;
    border-left-color: var(--border-strong);
}

.comment-meta { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }

.comment-author {
    font-size: 13px; font-weight: 600;
    color: var(--text-primary);
    text-decoration: none;
}
.comment-author:hover { text-decoration: underline; }

.comment-date { font-size: 11px; color: var(--text-secondary); }

.comment-text {
    font-size: 13px; color: var(--text-primary);
    margin-top: 4px; line-height: 1.4;
}

/* ── Likes ───────────────────────────────────────── */
.likes-grid { display: flex; flex-wrap: wrap; gap: 6px; }

.like-pill {
    background: var(--surface-3);
    color: var(--text-primary);
    font-size: 13px;
    padding: 4px 12px;
    border-radius: 20px;
    text-decoration: none;
    transition: background 0.15s;
    white-space: nowrap;
    border: 1px solid var(--border);
}
.like-pill:hover { background: var(--surface); border-color: var(--border-strong); }

/* ── Tagged accounts ─────────────────────────────── */
.tagged-grid { display: flex; flex-wrap: wrap; gap: 6px; }

.tagged-chip {
    background: linear-gradient(45deg, rgba(131,58,180,0.08), rgba(252,176,69,0.08));
    color: #833ab4;
    font-size: 13px; font-weight: 600;
    padding: 4px 12px;
    border-radius: 20px;
    text-decoration: none;
    border: 1px solid rgba(131,58,180,0.18);
    white-space: nowrap;
}
.tagged-chip:hover {
    background: linear-gradient(45deg, rgba(131,58,180,0.16), rgba(252,176,69,0.16));
}

/* ── Metadata table ──────────────────────────────── */
.metadata-section {
    background: var(--surface);
    border-radius: var(--radius);
    border: 1px solid var(--border);
    box-shadow: var(--shadow);
    overflow: hidden;
    margin-top: 28px;
}
.metadata-section > .section-title {
    margin: 0;
    padding: 16px 20px 10px;
    background: var(--surface);
}

.metadata-section table { width: 100%; border-collapse: collapse; }
.metadata-section th, .metadata-section td {
    text-align: left;
    padding: 9px 16px;
    font-size: 13px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
    color: var(--text-primary);
}
.metadata-section th {
    background: var(--surface-2);
    font-weight: 600; color: var(--text-secondary);
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em;
    width: 28%;
    white-space: nowrap;
}
.metadata-section tr:last-child td, .metadata-section tr:last-child th { border-bottom: none; }
.metadata-section tr:hover td { background: var(--surface-2); }

.metadata-section ul { list-style: disc; padding-left: 20px; margin: 4px 0; }
.metadata-section li { margin-bottom: 2px; font-size: 13px; }

/* ── Scrollbars (visible) ──────────────────────────── */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: var(--border-strong);
    border-radius: 6px;
    border: 2px solid transparent;
    background-clip: padding-box;
}
::-webkit-scrollbar-thumb:hover { background: #94a3b8; background-clip: padding-box; }
::-webkit-scrollbar-corner { background: transparent; }

/* ── Back-to-top ───────────────────────────────────── */
.back-to-top {
    position: fixed;
    right: 24px; bottom: 24px;
    width: 44px; height: 44px;
    border-radius: 50%;
    background: var(--surface);
    color: var(--text-primary);
    border: 1px solid var(--border);
    box-shadow: var(--shadow);
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; font-weight: 700;
    text-decoration: none;
    transition: transform 0.15s, box-shadow 0.15s;
    z-index: 30;
}
.back-to-top:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(15,23,42,0.12), 0 12px 32px rgba(15,23,42,0.08);
}

@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { transition: none !important; animation: none !important; }
}

@media print {
    body { background: #fff; }
    .page { max-width: none; padding: 0; }
    .summary-title { position: static; box-shadow: none; }
    .back-to-top { display: none; }
    .account-card, .post-card, .metadata-section {
        box-shadow: none;
        page-break-inside: avoid;
    }
    .collapsible-body { display: block !important; max-height: none !important; }
    .collapsible-indicator { display: none; }
    .json-collapsible .collapsible-body { overflow: visible; }
}
"""


def generate_scripts() -> str:
    return """
document.querySelectorAll('.collapsible-header').forEach(function(header) {
    header.addEventListener('click', function() {
        var opened = this.classList.toggle('open');
        this.setAttribute('aria-expanded', opened ? 'true' : 'false');
        var body = this.nextElementSibling;
        if (body) body.classList.toggle('open');
    });
});

document.querySelectorAll('.post-caption').forEach(function(caption) {
    var lineHeight = parseInt(window.getComputedStyle(caption).lineHeight) || 21;
    if (caption.scrollHeight > lineHeight * 3 + 4) {
        var btn = document.createElement('button');
        btn.className = 'caption-toggle';
        btn.textContent = 'See more';
        btn.addEventListener('click', function() {
            caption.classList.toggle('expanded');
            btn.textContent = caption.classList.contains('expanded') ? 'See less' : 'See more';
        });
        caption.parentNode.insertBefore(btn, caption.nextSibling);
    }
});
"""


def _make_collapsible(header_text: str, body_tag: Tag, soup: BeautifulSoup,
                      extra_class: str = "", start_open: bool = False) -> Tag:
    section = soup.new_tag("div")
    section['class'] = f"collapsible-section {extra_class}".strip()

    header = soup.new_tag("button", type="button")
    header['class'] = f"collapsible-header {'open' if start_open else ''}".strip()
    header['aria-expanded'] = 'true' if start_open else 'false'

    label = soup.new_tag("span")
    label['class'] = "collapsible-label"
    label.string = header_text
    indicator = soup.new_tag("span")
    indicator['class'] = "collapsible-indicator"

    header.append(label)
    header.append(indicator)
    section.append(header)

    wrapper = soup.new_tag("div")
    wrapper['class'] = f"collapsible-body {'open' if start_open else ''}".strip()
    wrapper.append(body_tag)
    section.append(wrapper)

    return section


def _make_json_collapsible(data: Any, soup: BeautifulSoup) -> Tag:
    body = soup.new_tag("pre")
    body.string = json.dumps(data, ensure_ascii=False, default=str)
    return _make_collapsible("raw data", body, soup, extra_class="json-collapsible")


def summarize_comments(comments: list[Comment], soup: BeautifulSoup) -> Tag:
    sorted_comments = sorted(comments, key=lambda c: c.publication_date or 0)
    top_level = [c for c in sorted_comments if not c.parent_comment_id_on_platform]
    replies: dict = {}
    for c in sorted_comments:
        if c.parent_comment_id_on_platform:
            replies.setdefault(c.parent_comment_id_on_platform, []).append(c)

    container = soup.new_tag("div")
    container['class'] = "comments-list"

    def render_comment(cmt: Comment, is_reply: bool = False) -> Tag:
        item = soup.new_tag("div")
        item['class'] = "comment-item reply" if is_reply else "comment-item"

        meta = soup.new_tag("div")
        meta['class'] = "comment-meta"

        name = cmt.account_display_name or cmt.account_url_suffix or "Unknown"
        if cmt.account_url:
            author = soup.new_tag("a", href=str(cmt.account_url))
        else:
            author = soup.new_tag("span")
        author['class'] = "comment-author"
        author.string = f"@{name}"
        meta.append(author)

        if cmt.publication_date:
            date_span = soup.new_tag("span")
            date_span['class'] = "comment-date"
            date_span.string = cmt.publication_date.strftime("%Y-%m-%d %H:%M")
            meta.append(date_span)

        item.append(meta)

        if cmt.text:
            text_div = soup.new_tag("div")
            text_div['class'] = "comment-text"
            text_div.string = cmt.text
            item.append(text_div)

        return item

    rendered_parent_ids = set()
    for comment in top_level:
        container.append(render_comment(comment))
        rendered_parent_ids.add(comment.id_on_platform)
        for reply in replies.get(comment.id_on_platform or '', []):
            container.append(render_comment(reply, is_reply=True))

    for parent_id, reply_list in replies.items():
        if parent_id not in rendered_parent_ids:
            for reply in reply_list:
                container.append(render_comment(reply))

    return container


def summarize_likes(likes: list[Like], soup: BeautifulSoup) -> Tag:
    grid = soup.new_tag("div")
    grid['class'] = "likes-grid"
    for like in likes:
        name = like.account_display_name or like.account_url_suffix or "Unknown"
        if like.account_url:
            pill = soup.new_tag("a", href=str(like.account_url))
        else:
            pill = soup.new_tag("span")
        pill['class'] = "like-pill"
        pill.string = f"@{name}"
        grid.append(pill)
    return grid


def summarize_tagged_accounts(tagged_accounts: list[TaggedAccount], soup: BeautifulSoup) -> Tag:
    grid = soup.new_tag("div")
    grid['class'] = "tagged-grid"
    for tagged in tagged_accounts:
        name = tagged.tagged_account_display_name or tagged.tagged_account_url_suffix or "Unknown"
        url = tagged.tagged_account_url
        if url:
            chip = soup.new_tag("a", href=url)
        else:
            chip = soup.new_tag("span")
        chip['class'] = "tagged-chip"
        chip.string = f"@{name}"
        grid.append(chip)
    return grid


def summarize_account_relations(account_relations: list[AccountRelation], soup: BeautifulSoup) -> Tag:
    container = soup.new_tag("div")
    container['class'] = "relations-list"
    for relation in account_relations:
        item = soup.new_tag("div")
        item['class'] = "relation-item"

        if relation.relation_type:
            badge = soup.new_tag("span")
            badge['class'] = "relation-type"
            badge.string = relation.relation_type
            item.append(badge)

        follower_name = relation.follower_account_display_name or relation.follower_account_url_suffix
        followed_name = relation.followed_account_display_name or relation.followed_account_url_suffix
        display = follower_name or followed_name or "Unknown"
        url = relation.follower_account_url or relation.followed_account_url

        name_span = soup.new_tag("span")
        name_span['class'] = "relation-name"
        name_span.string = display
        item.append(name_span)

        if url:
            url_link = soup.new_tag("a", href=url)
            url_link['class'] = "relation-url"
            url_link.string = url
            item.append(url_link)

        container.append(item)
    return container


def summarize_media(media: MediaAndAssociatedEntities, soup: BeautifulSoup) -> Tag:
    item = soup.new_tag("div")
    item['class'] = "media-item"

    if media.media_type == "image":
        preview = soup.new_tag("img", src=media.local_url, loading="lazy")
    elif media.media_type == "video":
        preview = soup.new_tag("video", src=media.local_url, controls="true", preload="metadata")
    elif media.media_type == "audio":
        preview = soup.new_tag("audio", src=media.local_url, controls="true", preload="metadata")
    else:
        preview = soup.new_tag("span")
        preview.string = "Unsupported media"
    preview['class'] = "media-preview"
    item.append(preview)

    actions = soup.new_tag("div")
    actions['class'] = "media-actions"
    download = soup.new_tag("a", href=media.local_url, download="true")
    download['class'] = "download-btn"
    download.string = "↓ Download"
    actions.append(download)
    item.append(actions)

    if media.data is not None:
        item.append(_make_json_collapsible(media.data, soup))

    return item


def summarize_post(post: PostAndAssociatedEntities, soup: BeautifulSoup) -> Tag:
    card = soup.new_tag("div")
    card['class'] = "post-card"

    # Header: meta + caption
    header = soup.new_tag("div")
    header['class'] = "post-header"

    meta = soup.new_tag("div")
    meta['class'] = "post-meta"

    if post.publication_date:
        date_span = soup.new_tag("span")
        date_span['class'] = "post-date"
        date_span.string = post.publication_date.strftime("%Y-%m-%d %H:%M")
        meta.append(date_span)

    if post.url:
        url_chip = soup.new_tag("a", href=post.url)
        url_chip['class'] = "post-url-chip"
        url_chip.string = post.url
        meta.append(url_chip)

    header.append(meta)

    if post.caption and post.caption.strip():
        caption_div = soup.new_tag("div")
        caption_div['class'] = "post-caption"
        caption_div.string = post.caption.strip()
        header.append(caption_div)

    card.append(header)

    # Media grid
    if post.post_media:
        media_grid = soup.new_tag("div")
        media_grid['class'] = "post-media-grid"
        for media in post.post_media:
            media_grid.append(summarize_media(media, soup))
        card.append(media_grid)

    # Comments
    if post.post_comments:
        n = len(post.post_comments)
        body = summarize_comments(post.post_comments, soup)
        card.append(_make_collapsible(
            f"💬 Comments ({n})", body, soup,
            start_open=(n <= 5)
        ))

    # Likes
    if post.post_likes:
        n = len(post.post_likes)
        body = summarize_likes(post.post_likes, soup)
        card.append(_make_collapsible(f"❤️ Likes ({n})", body, soup))

    # Tagged accounts
    if post.post_tagged_accounts:
        n = len(post.post_tagged_accounts)
        body = summarize_tagged_accounts(post.post_tagged_accounts, soup)
        card.append(_make_collapsible(f"🏷️ Tagged ({n})", body, soup))

    # Raw data (de-emphasized)
    card.append(_make_json_collapsible(post.data, soup))

    return card


def summarize_account(account: AccountAndAssociatedEntities, soup: BeautifulSoup) -> Tag:
    card = soup.new_tag("div")
    card['class'] = "account-card"

    # Header row
    header = soup.new_tag("div")
    header['class'] = "account-header"

    avatar = soup.new_tag("div")
    avatar['class'] = "account-avatar"
    initial = (account.url_suffix or "?")[0]
    avatar.string = initial

    info = soup.new_tag("div")
    info['class'] = "account-info"

    username_tag = soup.new_tag("a", href=account.url or "#")
    username_tag['class'] = "account-username"
    username_tag.string = f"@{account.url_suffix}" if account.url_suffix else account.url or "Unknown"
    info.append(username_tag)

    if account.display_name:
        dn = soup.new_tag("div")
        dn['class'] = "account-display-name"
        dn.string = account.display_name
        info.append(dn)

    if account.bio:
        bio = soup.new_tag("div")
        bio['class'] = "account-bio"
        bio.string = account.bio
        info.append(bio)

    stats = soup.new_tag("div")
    stats['class'] = "account-stats"
    n_posts = len(account.account_posts)
    if n_posts:
        badge = soup.new_tag("span")
        badge['class'] = "stat-badge"
        badge.string = f"{n_posts} post{'s' if n_posts != 1 else ''}"
        stats.append(badge)

    header.append(avatar)
    header.append(info)
    header.append(stats)
    card.append(header)

    # Raw JSON data
    card.append(_make_json_collapsible(account.data, soup))

    # Related accounts
    if account.account_relations:
        n = len(account.account_relations)
        body = summarize_account_relations(account.account_relations, soup)
        card.append(_make_collapsible(f"👥 Related Accounts ({n})", body, soup))

    # Posts
    if account.account_posts:
        posts_block = soup.new_tag("div")
        posts_block['class'] = "account-posts"
        label = soup.new_tag("div")
        label['class'] = "account-posts-label"
        label.string = "Posts"
        posts_block.append(label)
        account.account_posts.sort(key=lambda p: p.publication_date or 0, reverse=True)
        for post in account.account_posts:
            posts_block.append(summarize_post(post, soup))
        card.append(posts_block)

    return card


def filter_out_empty_entities(nested_entities: ExtractedEntitiesNested) -> None:
    nested_entities.media = [m for m in nested_entities.media if m.local_url]
    for p in nested_entities.posts:
        p.post_media = [m for m in p.post_media if m.local_url]
    nested_entities.posts = [
        p for p in nested_entities.posts
        if p.post_media or (p.caption and p.caption.strip())
    ]
    for a in nested_entities.accounts:
        for p in a.account_posts:
            p.post_media = [m for m in p.post_media if m.local_url]
        a.account_posts = [
            p for p in a.account_posts
            if p.post_media or (p.caption and p.caption.strip())
        ]
    nested_entities.accounts = [a for a in nested_entities.accounts if a.account_posts]


def summarize_nested_entities(nested_entities: ExtractedEntitiesNested, metadata: dict) -> str:
    filter_out_empty_entities(nested_entities)
    page_title = f"Archive Summary — {metadata.get('archiving_start_timestamp', 'Unknown Date')}"
    soup = BeautifulSoup(
        f"<html><head><meta charset='utf-8'><title>{page_title}</title></head><body></body></html>",
        "html.parser"
    )
    style_tag = soup.new_tag("style")
    style_tag.string = generate_stylesheet()
    soup.head.append(style_tag)

    body = soup.body

    page = soup.new_tag("div")
    page['class'] = "page"
    body.append(page)

    title = soup.new_tag("h1", id="top")
    title['class'] = "summary-title"
    title_label = soup.new_tag("span")
    title_label.string = page_title
    title.append(title_label)

    n_accounts = len(nested_entities.accounts)
    n_posts = sum(len(a.account_posts) for a in nested_entities.accounts) + len(nested_entities.posts)
    n_media = (
        sum(len(p.post_media) for a in nested_entities.accounts for p in a.account_posts)
        + sum(len(p.post_media) for p in nested_entities.posts)
        + len(nested_entities.media)
    )
    counts = soup.new_tag("span")
    counts['class'] = "summary-counts"
    counts.string = f"{n_accounts} accounts · {n_posts} posts · {n_media} media"
    title.append(counts)
    page.append(title)

    if nested_entities.accounts:
        section = soup.new_tag("div")
        section['class'] = "accounts-section"
        lbl = soup.new_tag("div")
        lbl['class'] = "section-title"
        lbl.string = f"Accounts ({n_accounts})"
        section.append(lbl)
        for account in nested_entities.accounts:
            section.append(summarize_account(account, soup))
        page.append(section)

    if nested_entities.posts:
        section = soup.new_tag("div")
        section['class'] = "orphaned-posts-section"
        lbl = soup.new_tag("div")
        lbl['class'] = "section-title"
        lbl.string = f"Additional Posts ({len(nested_entities.posts)})"
        section.append(lbl)
        for post in nested_entities.posts:
            section.append(summarize_post(post, soup))
        page.append(section)

    if nested_entities.media:
        section = soup.new_tag("div")
        section['class'] = "orphaned-media-section"
        lbl = soup.new_tag("div")
        lbl['class'] = "section-title"
        lbl.string = f"Additional Media ({len(nested_entities.media)})"
        section.append(lbl)
        grid = soup.new_tag("div")
        grid['class'] = "post-media-grid"
        for media in nested_entities.media:
            grid.append(summarize_media(media, soup))
        section.append(grid)
        page.append(section)

    # Metadata
    meta_section = soup.new_tag("div")
    meta_section['class'] = "metadata-section"
    lbl = soup.new_tag("div")
    lbl['class'] = "section-title"
    lbl.string = "Archive Metadata"
    meta_section.append(lbl)
    meta_section.append(_generate_table_rec(metadata, soup))
    page.append(meta_section)

    back_to_top = soup.new_tag("a", href="#top")
    back_to_top['class'] = "back-to-top"
    back_to_top['aria-label'] = "Back to top"
    back_to_top.string = "↑"
    body.append(back_to_top)

    # Scripts
    script_tag = soup.new_tag("script")
    script_tag.string = generate_scripts()
    body.append(script_tag)

    return str(soup)


def _generate_table_rec(data: Any, soup: BeautifulSoup) -> Tag:
    if isinstance(data, dict):
        table = soup.new_tag("table")
        for k, v in data.items():
            row = soup.new_tag("tr")
            th = soup.new_tag("th")
            th.string = str(k)
            td = soup.new_tag("td")
            td.append(_generate_table_rec(v, soup))
            row.append(th)
            row.append(td)
            table.append(row)
        return table
    elif isinstance(data, list):
        ul = soup.new_tag("ul")
        for item in data:
            li = soup.new_tag("li")
            li.append(_generate_table_rec(item, soup))
            ul.append(li)
        return ul
    else:
        span = soup.new_tag("span")
        span.string = str(data)
        return span


def generate_entities_summary(
        har_path: Path,
        archive_dir: Path,
        metadata: dict,
        video_acquisition_config: VideoAcquisitionConfig = VideoAcquisitionConfig(
            download_missing=True, download_media_not_in_structures=True, download_unfetched_media=True,
            download_full_versions_of_fetched_media=True, download_highest_quality_assets_from_structures=True
        ),
        photo_acquisition_config: PhotoAcquisitionConfig = PhotoAcquisitionConfig(
            download_missing=True, download_media_not_in_structures=True, download_unfetched_media=True,
            download_highest_quality_assets_from_structures=True
        )
):
    flattened_entities = extract_entities_from_har(har_path, video_acquisition_config, photo_acquisition_config)
    nested_entities = nest_entities_from_archive_session(flattened_entities)
    html = summarize_nested_entities(nested_entities, metadata)
    archive_dir_str = archive_dir.as_posix()
    html = html.replace(archive_dir_str, ".")
    if metadata.get("profile_name"):
        html = html.replace(metadata["profile_name"], "[ANONYMIZED]")
    if metadata.get("signature"):
        html = html.replace(metadata["signature"], "[ANONYMIZED]")
    if metadata.get("my_ip"):
        html = html.replace(metadata["my_ip"], "[ANONYMIZED]")

    out_path = archive_dir / "entities_summary.html"
    print("Writing entities summary to", out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


def manual_entities_summary_generation():
    har_file = input("Input path to HAR file: ")
    har_file = har_file.strip().strip('"').strip("'")
    har_path = Path(har_file)
    archive_dir = Path(har_path).parent
    metadata_path = archive_dir / "metadata.json"
    metadata = {}
    if metadata_path.exists():
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
    generate_entities_summary(
        har_path,
        archive_dir,
        metadata,
        VideoAcquisitionConfig(
            download_missing=True,
            download_media_not_in_structures=False,
            download_unfetched_media=False,
            download_full_versions_of_fetched_media=False,
            download_highest_quality_assets_from_structures=False
        ),
        PhotoAcquisitionConfig(
            download_missing=True,
            download_media_not_in_structures=False,
            download_unfetched_media=False,
            download_highest_quality_assets_from_structures=False
        )
    )


if __name__ == '__main__':
    manual_entities_summary_generation()

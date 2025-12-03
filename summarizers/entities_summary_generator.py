import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from extractors.entity_types import AccountAndAssociatedEntities, PostAndAssociatedEntities, ExtractedEntitiesNested, \
    MediaAndAssociatedEntities
from extractors.extract_photos import PhotoAcquisitionConfig
from extractors.extract_videos import VideoAcquisitionConfig
from extractors.structures_to_entities import extract_entities_from_har, nest_entities_from_archive_session


def generate_collapsible_section(header: Tag, body: Tag, soup: BeautifulSoup) -> Tag:
    section = soup.new_tag("div")
    section['class'] = "collapsible-section"
    header['class'] = "collapsible-header"
    header[
        'onclick'] = "this.nextElementSibling.style.display = (this.nextElementSibling.style.display === 'none' ? 'block' : 'none');"
    section.append(header)
    section.append(body)
    return section


def generate_table_rec(data: Any, soup: BeautifulSoup) -> Tag:
    if isinstance(data, dict):
        table = soup.new_tag("table", border="1", cellpadding="4", cellspacing="0")
        for k, v in data.items():
            row = soup.new_tag("tr")
            key_cell = soup.new_tag("td")
            key_cell.string = str(k)
            key_cell['style'] = "font-weight: bold;"
            value_cell = soup.new_tag("td")
            value_cell.append(generate_table_rec(v, soup))
            row.append(key_cell)
            row.append(value_cell)
            table.append(row)
        return table
    elif isinstance(data, list):
        ul = soup.new_tag("ul")
        for item in data:
            li = soup.new_tag("li")
            li.append(generate_table_rec(item, soup))
            ul.append(li)
        return ul
    else:
        leaf = soup.new_tag("span")
        leaf.string = str(data)
        return leaf


def summarize_media(media: MediaAndAssociatedEntities, soup: BeautifulSoup) -> Tag:
    container = soup.new_tag("div")
    container['class'] = "media-container"
    # Preview element
    if media.media_type == "image":
        preview = soup.new_tag("img", src=media.local_url)
        preview['class'] = "media-preview media-image"
    elif media.media_type == "audio":
        preview = soup.new_tag("audio", src=media.local_url, controls="true")
        preview['class'] = "media-preview media-audio"
    elif media.media_type == "video":
        preview = soup.new_tag("video", src=media.local_url, controls="true")
        preview['class'] = "media-preview media-video"
    else:
        preview = soup.new_tag("span")
        preview['class'] = "media-preview media-unsupported"
        preview.string = "Unsupported media type"
    container.append(preview)

    details = soup.new_tag("div")
    details['class'] = "media-details"
    # Download button
    download_link = soup.new_tag("a", href=media.local_url, download="true")
    download_link['class'] = "media-download-link"
    download_link.string = "Download"
    details.append(download_link)

    # URL display
    # url_tag = soup.new_tag("div")
    # url_tag['class'] = "media-url"
    # url_tag.string = f"URL: {media.url}"
    # details.append(url_tag)

    # JSON printout
    full_data = json.dumps(media.data, ensure_ascii=False, default=str)
    json_header = soup.new_tag("div")
    json_header['class'] = "collapsible-header"
    json_header.string = "data"
    json_body = soup.new_tag("pre")
    json_body['class'] = "collapsible-body"
    json_body['style'] = "display: none;"
    json_body.string = full_data
    collapsible_json = generate_collapsible_section(json_header, json_body, soup)
    details.append(collapsible_json)

    container.append(details)

    return container


def summarize_post(post: PostAndAssociatedEntities, soup: BeautifulSoup) -> Tag:
    container = soup.new_tag("div")
    container['class'] = "post-container"

    # Left: Post details
    details = soup.new_tag("div")
    details['class'] = "post-details"
    detail_url = soup.new_tag("div")
    detail_url['class'] = "post-url"
    detail_url.string = f"URL: {post.url}"
    details.append(detail_url)

    # detail_account_url = soup.new_tag("div")
    # detail_account_url['class'] = "post-account-url"
    # detail_account_url.string = f"Account URL: {post.post.account_url}"
    # details.append(detail_account_url)

    detail_pub_date = soup.new_tag("div")
    detail_pub_date['class'] = "post-publication-date"
    detail_pub_date.string = f"Publication Date: {post.publication_date}"
    details.append(detail_pub_date)

    detail_caption = soup.new_tag("div")
    detail_caption['class'] = "post-caption"
    detail_caption.string = f"Caption: {post.caption}"
    details.append(detail_caption)

    json_header = soup.new_tag("div")
    json_header['class'] = "collapsible-header"
    json_header.string = "data"
    json_body = soup.new_tag("pre")
    json_body['class'] = "collapsible-body"
    json_body['style'] = "display: none;"
    json_body.string = json.dumps(post.data, ensure_ascii=False, default=str)
    collapsible_json = generate_collapsible_section(json_header, json_body, soup)
    details.append(collapsible_json)

    container.append(details)

    # Right: Media items
    media_box = soup.new_tag("div")
    media_box['class'] = "post-media-box"
    for media in post.post_media:
        media_tag = summarize_media(media, soup)
        media_box.append(media_tag)
    container.append(media_box)

    return container


def summarize_account(account: AccountAndAssociatedEntities, soup: BeautifulSoup) -> Tag:
    container = soup.new_tag("div")
    container['class'] = "account-container"

    # Top section: Account details
    details = soup.new_tag("div")
    details['class'] = "account-details"
    detail_url = soup.new_tag("div")
    detail_url['class'] = "account-url"
    detail_url.string = f"Url: {account.url}"
    details.append(detail_url)

    detail_display_name = soup.new_tag("div")
    detail_display_name['class'] = "account-display-name"
    detail_display_name.string = f"Display Name: {account.display_name or ''}"
    details.append(detail_display_name)

    detail_bio = soup.new_tag("div")
    detail_bio['class'] = "account-bio"
    detail_bio.string = f"Bio: {account.bio or ''}"
    details.append(detail_bio)

    json_header = soup.new_tag("div")
    json_header['class'] = "collapsible-header"
    json_header.string = "data"
    json_body = soup.new_tag("pre")
    json_body['class'] = "collapsible-body"
    json_body['style'] = "display: none;"
    json_body.string = json.dumps(account.data, ensure_ascii=False, default=str)
    collapsible_json = generate_collapsible_section(json_header, json_body, soup)
    details.append(collapsible_json)

    container.append(details)

    # Bottom section: Posts
    posts_section = soup.new_tag("div")
    posts_section['class'] = "account-posts-section"
    account.account_posts.sort(key=lambda x: x.publication_date, reverse=True)
    for post in account.account_posts:
        post_tag = summarize_post(post, soup)
        posts_section.append(post_tag)
    container.append(posts_section)

    return container


def generate_stylesheet() -> str:
    return """
    body {
        font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
        margin: 0;
        background-color: #f4f6fa;
        color: #222;
        line-height: 1.6;
        padding: 32px;
        min-height: 100vh;
    }
    .summary-title {
        text-align: center;
        color: #07000a;
        font-size: 2.2rem;
        margin: 32px 0 24px 0;
        font-weight: 800;
        letter-spacing: 0.02em;
        text-shadow: 0 2px 8px rgba(26,35,126,0.08);
    }
    h2 {
        font-size: 1.3rem;
        color: #2563eb;
        margin: 24px 0 12px 0;
        font-weight: 700;
        letter-spacing: 0.01em;
        border-bottom: 1px solid #e3e8ee;
        padding-bottom: 4px;
    }
    .collapsible-section {
        margin-bottom: 18px;
        background: #fff;
        border-radius: 10px;
        box-shadow: 0 2px 12px rgba(0,0,0,0.07);
        overflow: hidden;
        transition: box-shadow 0.2s;
        border: 1px solid #e3e8ee;
    }
    .collapsible-section:hover {
        box-shadow: 0 6px 18px rgba(0,0,0,0.13);
    }
    .collapsible-header {
        padding: 14px 20px;
        cursor: pointer;
        color: #1a237e;
        font-size: 1.08rem;
        font-weight: 700;
        border: none;
        outline: none;
        user-select: none;
        position: relative;
        background: linear-gradient(90deg, #f7f9fb 0%, #e3e8ee 100%);
        transition: background 0.2s;
    }
    .collapsible-header:hover {
        background: linear-gradient(90deg, #e3e8ee 0%, #f7f9fb 100%);
    }
    .collapsible-header::after {
        content: "▼";
        position: absolute;
        right: 20px;
        top: 50%;
        transform: translateY(-50%) rotate(0deg);
        transition: transform 0.2s;
        font-size: 1.1rem;
        color: #2563eb;
    }
    .collapsible-header.active::after {
        transform: translateY(-50%) rotate(-180deg);
    }
    .collapsible-body {
        padding: 14px 20px;
        display: none;
        background: #f3f6fa;
        font-size: 1rem;
        white-space: pre-wrap;
        word-break: break-word;
        border-radius: 0 0 10px 10px;
        border-top: 1px solid #e3e8ee;
        color: #263238;
    }
    .media-container, .post-container, .account-container {
        padding: 18px 22px;
        background: #fff;
        border-radius: 8px;
        margin-bottom: 16px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        overflow-wrap: anywhere;
        border: 1px solid #e3e8ee;
        transition: box-shadow 0.2s;
    }
    .media-container:hover, .post-container:hover, .account-container:hover {
        box-shadow: 0 6px 18px rgba(0,0,0,0.13);
    }
    .media-preview {
        width: 240px;
        max-width: 100%;
        height: auto;
        border-radius: 6px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.09);
        margin-bottom: 10px;
        display: block;
        border: 1px solid #e3e8ee;
        background: #f7f9fb;
    }
    .media-download-link {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin-top: 8px;
    color: #fff;
    background: linear-gradient(90deg, #2563eb 0%, #1e40af 100%);
    font-weight: 600;
    text-decoration: none;
    border: none;
    border-radius: 6px;
    box-shadow: 0 2px 8px rgba(37,99,235,0.08);
    font-size: 1rem;
    padding: 8px 20px;
    transition: background 0.2s, box-shadow 0.2s, color 0.2s;
    cursor: pointer;
    width: auto;
    min-width: 100px;
    max-width: 220px;
    white-space: nowrap;
}
.media-download-link:hover {
    background: linear-gradient(90deg, #1e40af 0%, #2563eb 100%);
    color: #e3e8ee;
    box-shadow: 0 4px 16px rgba(37,99,235,0.13);
}
    .post-media-box {
        display: flex;
        flex-direction: row;
        flex-wrap: wrap;
        width: 100%;
        gap: 16px;
        margin-top: 10px;
    }
    .account-container {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }
    .account-details, .post-details, .media-details {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }
    table {
        border-collapse: collapse;
        width: 100%;
        margin-top: 8px;
        background: #f7f9fb;
        border-radius: 6px;
        overflow: hidden;
        box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    }
    th, td {
        border: 1px solid #e3e8ee;
        padding: 8px 12px;
        text-align: left;
        font-size: 0.98rem;
    }
    th {
        background: #e3e8ee;
        font-weight: 700;
        color: #1a237e;
    }
    tr:nth-child(even) {
        background: #f3f6fa;
    }
    ul {
        padding-left: 20px;
        margin: 8px 0;
    }
    li {
        margin-bottom: 4px;
        font-size: 0.98rem;
    }
    ::-webkit-scrollbar {
        width: 10px;
        background: #e3e8ee;
        border-radius: 5px;
    }
    ::-webkit-scrollbar-thumb {
        background: #0b1717;
        border-radius: 5px;
    }
    """


def filter_out_empty_entities(nested_entities: ExtractedEntitiesNested) -> None:
    # Filter out media items with no local_url
    # Filter out posts with no media or caption
    # Filter out accounts with no posts
    filtered_media = [m for m in nested_entities.media if m.local_url]
    nested_entities.media = filtered_media
    for p in nested_entities.posts:
        filtered_post_media = [m for m in p.post_media if m.local_url]
        p.post_media = filtered_post_media
    filtered_posts = [p for p in nested_entities.posts if len(p.post_media) or (p.caption and len(p.caption.strip()))]
    nested_entities.posts = filtered_posts
    for a in nested_entities.accounts:
        for p in a.account_posts:
            filtered_post_media = [m for m in p.post_media if m.local_url]
            p.post_media = filtered_post_media
        filtered_posts = [p for p in a.account_posts if len(p.post_media) or (p.caption and len(p.caption.strip()))]
        a.account_posts = filtered_posts
    filtered_accounts = [a for a in nested_entities.accounts if len(a.account_posts)]
    nested_entities.accounts = filtered_accounts


def summarize_nested_entities(nested_entities: ExtractedEntitiesNested, metadata: dict) -> str:
    filter_out_empty_entities(nested_entities)
    page_title = f"Summary of Entities Extracted from Archiving Session {metadata.get('archiving_start_timestamp', 'Unknown Date')}"
    soup = BeautifulSoup(f"<html><head><title>{page_title}</title></head><body></body></html>", "html.parser")
    # Attach stylesheet to head
    style_tag = soup.new_tag("style")
    style_tag.string = generate_stylesheet()
    soup.head.append(style_tag)
    body = soup.body
    title = soup.new_tag("h1")
    title['class'] = "summary-title"
    title.string = page_title
    body.append(title)
    if len(nested_entities.accounts) > 0:
        accounts_section = soup.new_tag("div")
        accounts_section['class'] = "accounts-section"
        accounts_title = soup.new_tag("h2")
        accounts_title['class'] = "accounts-title"
        accounts_title.string = "Accounts"
        accounts_section.append(accounts_title)
        for account in nested_entities.accounts:
            account_tag = summarize_account(account, soup)
            accounts_section.append(account_tag)
        body.append(accounts_section)
    if len(nested_entities.posts) > 0:
        orphaned_posts_section = soup.new_tag("div")
        orphaned_posts_section['class'] = "orphaned-posts-section"
        orphaned_posts_title = soup.new_tag("h2")
        orphaned_posts_title['class'] = "orphaned-posts-title"
        orphaned_posts_title.string = "Additional Posts"
        orphaned_posts_section.append(orphaned_posts_title)
        for post in nested_entities.posts:
            post_tag = summarize_post(post, soup)
            orphaned_posts_section.append(post_tag)
        body.append(orphaned_posts_section)
    if len(nested_entities.media) > 0:
        orphaned_media_section = soup.new_tag("div")
        orphaned_media_section['class'] = "orphaned-media-section"
        orphaned_media_title = soup.new_tag("h2")
        orphaned_media_title['class'] = "orphaned-media-title"
        orphaned_media_title.string = "Additional Media"
        orphaned_media_section.append(orphaned_media_title)
        for media in nested_entities.media:
            media_tag = summarize_media(media, soup)
            orphaned_media_section.append(media_tag)
        body.append(orphaned_media_section)

    # Add metadata section
    metadata_section = soup.new_tag("div")
    metadata_section['class'] = "metadata-section"
    metadata_title = soup.new_tag("h2")
    metadata_title['class'] = "metadata-title"
    metadata_title.string = "Archive Metadata"
    metadata_section.append(metadata_title)
    metadata_section.append(generate_table_rec(metadata, soup))
    body.append(metadata_section)

    return str(soup)


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
    # replace absolute paths under archive_dir with relative paths
    archive_dir_str = archive_dir.as_posix()
    html = html.replace(archive_dir_str, ".")
    if metadata.get("profile_name", None):
        html = html.replace(metadata["profile_name"], "[ANONYMIZED]")
    if metadata.get("signature", None):
        html = html.replace(metadata["signature"], "[ANONYMIZED]")
    if metadata.get("my_ip", None):
        html = html.replace(metadata["my_ip"], "[ANONYMIZED]")

    print("Writing entities summary to", archive_dir / "entities_summary.html")
    with open(archive_dir / "entities_summary.html", "w", encoding="utf-8") as f:
        f.write(html)


def manual_entities_summary_generation():
    # Provide the path to your .har file and desired output folder
    har_file = input("Input path to HAR file: ")  # Replace with your actual HAR file
    # Strip leading and trailing whitespace as well as " " or " from the input
    har_file = har_file.strip().strip('"').strip("'")
    har_path = Path(har_file)
    archive_dir = Path(har_path).parent
    metadata_path = archive_dir / "metadata.json"
    metadata = {}
    if metadata_path.exists():
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
    download_full_video = False
    # download_full_video = input("Download full videos? (yes/no, default: yes): ").strip().lower()
    # if download_full_video in ["yes", "y", ""]:
    #    download_full_video = True
    # else:
    #    download_full_video = False
    generate_entities_summary(
        har_path,
        archive_dir,
        metadata,
        VideoAcquisitionConfig(
            download_missing=True,
            download_media_not_in_structures=False,
            download_unfetched_media=True,
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

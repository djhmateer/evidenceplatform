import json
from pathlib import Path

from extractors.structures_extraction import StructureType, structures_from_har


def generate_summary(har_path: Path, archive_dir: Path, metadata: dict, download_full_video: bool = True) -> str:
    videos = [] #acquire_videos(har_path, archive_dir / "videos", download_full_versions_of_fetched_media=download_full_video)
    photos = [] #acquire_photos(har_path, archive_dir / "photos")
    structures = structures_from_har(har_path)

    html = """<!DOCTYPE html>
<html>
<head>
    <title>Instagram Archive Summary</title>
    <style>
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            margin: 0 auto;
            padding: 32px 16px;
            background: #f7f9fb;
            color: #222;
        }
        h1, h2, h3 {
            color: #1a1a1a;
            font-weight: 600;
            margin-bottom: 0.5em;
        }
        h1 {
            font-size: 2.2em;
            margin-top: 0.2em;
        }
        .warning {
            color: #C00;
            font-weight: bold;
        }
        h2 {
            font-size: 1.5em;
            margin-top: 2em;
        }
        h3 {
            font-size: 1.15em;
            margin-top: 1.5em;
        }
        .container {
            display: flex;
            flex-wrap: wrap;
            gap: 18px;
            margin-bottom: 2em;
        }
        .media-item {
            background: #fff;
            margin: 0;
            padding: 18px 18px 12px 18px;
            border: 1px solid #e3e8ee;
            border-radius: 10px;
            box-shadow: 0 2px 8px 0 rgba(60,72,88,0.07);
            width: 340px;
            display: flex;
            flex-direction: column;
            align-items: center;
            transition: box-shadow 0.2s;
        }
        .media-item:hover {
            box-shadow: 0 4px 16px 0 rgba(60,72,88,0.13);
        }
        .media-item img, .media-item video {
            max-width: 100%;
            max-height: 260px;
            border-radius: 6px;
            margin-bottom: 10px;
            background: #f0f0f0;
        }
        .metadata {
            margin-top: 8px;
            font-size: 0.97em;
            width: 100%;
        }
        .metadata p {
            margin: 4px 0;
        }
        .metadata-value {
            background: #eaf6ff;
            border-radius: 4px;
            padding: 2px 6px;
            user-select: all;
            cursor: pointer;
            overflow-wrap: break-word;
            word-break: break-word;
            white-space: pre-wrap;
            color: #0a3d62;
            font-family: 'Fira Mono', 'Consolas', monospace;
        }
        .structure-item {
            margin-bottom: 18px;
            padding: 18px 18px 10px 18px;
            border: 1px solid #e3e8ee;
            border-radius: 10px;
            background: #fafdff;
            box-shadow: 0 1px 4px 0 rgba(60,72,88,0.04);
            max-width: 100%;
            overflow-x: auto;
        }
        /* Nested structure table styling */
        .structure-item table {
            border-collapse: collapse;
            margin: 0;
            font-size: 0.98em;
        }
        .structure-item table td, .structure-item table th {
            border: 1px solid #c7d0db;
            padding: 4px 8px;
            margin: 0;
            vertical-align: top;
        }
        .structure-item table tr {
            background: #fff;
        }
        .structure-item table tr:nth-child(even) {
            background: #f3f8fb;
        }
        .structure-item ul {
            margin: 0 0 0 18px;
            padding: 0;
        }
        @media (max-width: 800px) {
            .container {
                flex-direction: column;
                gap: 10px;
            }
            .media-item, .structure-item {
                width: 100%;
            }
        }
    </style>
</head>
<body>
    <h1>Instagram Archive Summary <span class='warning'>WARNING: NOT FULLY ANONYMIZED, ACCOUNT DETAILS MIGHT LEAK! DO NOT SHARE PUBLICLY OR WITH COURT!!!</span></h1>"""


    # Add videos
    html += f"""<h2>Videos ({len(videos)})</h2>
        <div class="container">"""
    for video in videos:
        try:
            # Use video.location if available, otherwise the first local file
            video_path = video.location if video.location else video.local_files[0]
            video_path = Path(video_path)
            video_path_relative = video_path.relative_to(archive_dir)
            html += f"""
                <div class="media-item">
                    <video controls>
                        <source src="{video_path_relative.as_posix()}" type="video/mp4">
                        Your browser does not support the video tag.
                    </video>
                    <div class="metadata">
                        <p><strong>Asset ID:</strong> <span class="metadata-value">{video.xpv_asset_id}</span></p>
                        <p><strong>Tracks ({len(video.fetched_tracks)}):</strong></p>
                        {"".join(f'<p class="metadata-value">{track}</p>' for track in video.fetched_tracks.keys())}
                    </div>
                </div>"""
        except Exception as e:
            print(f"Error printing summary for video {video.xpv_asset_id}: {e}")
            continue

    html += """</div>"""

    html += f"""<h2>Photos ({len(photos)})</h2>
        <div class="container">"""

    # Add photos
    for photo in photos:
        if photo.local_files:  # Check if there are any local files
            photo_path = photo.local_files[0]  # Use first file path
            photo_path = Path(photo_path)
            photo_path_relative = photo_path.relative_to(archive_dir)
            html += f"""
                <div class="media-item">
                    <img src="{photo_path_relative.as_posix()}" alt="Instagram Photo">
                    <div class="metadata">
                        <p><strong>URL:</strong> <span class="metadata-value">{photo.url}</span></p>
                        <p><strong>Filename:</strong> <span class="metadata-value">{photo.filename}</span></p>
                        <p><strong>Extension:</strong> <span class="metadata-value">{photo.extension}</span></p>
                        <p><strong>Asset ID:</strong> <span class="metadata-value">{photo.xpv_asset_id if photo.xpv_asset_id else 'N/A'}</span></p>
                    </div>
                </div>"""

    html += f"""
        </div>"""

    # Add structures
    html += f"""<h2>Structures</h2>
        <div class="container">"""
    for i, structure in enumerate(structures):
        html += f"""
            <div class="structure-item">
                <h3>Structure {i + 1}</h3>
                <pre>{str(structure.__class__.__name__)}</pre>
                <div class="metadata">
                    {_format_structure_data(structure)}
                </div>
            </div>"""

    html += f"""</div>"""

    # Add metadata
    html += f"""<h2>Session Metadata</h2>
    <div class="metadata">{render_table(metadata)}</div>"""


    html += """</body>
    </html>"""
    with open(archive_dir / "summary.html", 'w', encoding='utf-8') as f:
        f.write(html)
    with open(archive_dir / "summary_anonymized_researchers.html", 'w', encoding='utf-8') as f:
        anon_html = html
        if metadata.get("profile_name", None):
            anon_html = anon_html.replace(metadata["profile_name"], "[ANONYMIZED]")
        if metadata.get("signature", None):
            anon_html = anon_html.replace(metadata["signature"], "[ANONYMIZED]")
        if metadata.get("my_ip", None):
            anon_html = anon_html.replace(metadata["my_ip"], "[ANONYMIZED]")
        anon_html = anon_html.replace("<h1>Instagram Archive Summary", """<h1>Instagram Archive Summary (Partially Anonymized)""")
        f.write(anon_html)


def render_table(data):
    if isinstance(data, dict):
        rows = ""
        for k, v in data.items():
            rows += f"<tr><td><strong>{k}</strong></td><td>{render_table(v)}</td></tr>"
        return f"<table border='1' cellpadding='4' cellspacing='0'>{rows}</table>"
    elif isinstance(data, list):
        items = "".join(f"<li>{render_table(item)}</li>" for item in data)
        return f"<ul>{items}</ul>"
    else:
        return str(data)


def _format_structure_data(structure: StructureType) -> str:
        """
        Recursively formats a nested dict or object as an HTML table.
        """
        def to_dict(obj):
            # Try model_dump (pydantic), then __dict__, else fallback to str
            if hasattr(obj, "model_dump"):
                return obj.model_dump(mode="json", warnings=False)
            elif hasattr(obj, "__dict__"):
                return {k: to_dict(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
            elif isinstance(obj, (list, tuple)):
                return [to_dict(i) for i in obj]
            else:
                return obj

        structure_dict = to_dict(structure)
        return render_table(structure_dict)


def manual_summary_generation():
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
    download_full_video = input("Download full videos? (yes/no, default: yes): ").strip().lower()
    if download_full_video in ["yes", "y", ""]:
        download_full_video = True
    else:
        download_full_video = False
    generate_summary(har_path, archive_dir, metadata, download_full_video=download_full_video)


if __name__ == '__main__':
    manual_summary_generation()

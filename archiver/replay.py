import asyncio
import os
from pathlib import Path

from har2warc.har2warc import har2warc


async def generate_warc(archive_name):
    archives_dir = Path("../archives")
    archive_path = archives_dir / archive_name

    if not archive_path.exists() or not (archive_path / "archive.har").exists():
        print(f"Archive '{archive_name}' not found or missing 'archive.har' file.")
        return

    har_file = archive_path / "archive.har"
    warc_file = archive_path / "archive.warc.gz"
    har2warc(str(har_file), str(warc_file))
    print(f"WARC file generated at: {warc_file}")


if __name__ == "__main__":
    archive_name_arg = os.getenv("ARCHIVE_NAME")
    if not archive_name_arg:
        archive_name_arg = input("Enter the name of the archived page: ")

    asyncio.run(generate_warc(archive_name_arg))
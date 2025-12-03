import subprocess

from db_loaders.db_intake import ROOT_ARCHIVES

# Your keywords (case-insensitive)
KEYWORDS = ["daniel_abramov3", "danielabramov1718"]

def find_matching_archives():
    """Find all archives where metadata.json contains at least one keyword."""
    matching = []
    for entry in ROOT_ARCHIVES.iterdir():
        if entry.is_dir():
            meta_path = entry / "metadata.json"
            if meta_path.exists():
                try:
                    data = meta_path.read_text(encoding="utf-8").lower()
                    if any(kw.lower() in data for kw in KEYWORDS):
                        matching.append(entry)
                except Exception as e:
                    print(f"Could not read {meta_path}: {e}")
    return matching

def open_in_explorer(paths):
    """Open an Explorer window for each path, pre-selecting the folder."""
    for p in paths:
        subprocess.Popen(["explorer.exe", "/select,", str(p)])

if __name__ == "__main__":
    matches = find_matching_archives()
    if matches:
        print(f"Found {len(matches)} matching archives. Opening Explorer windows...")
        open_in_explorer(matches)
    else:
        print("No matching archives found.")

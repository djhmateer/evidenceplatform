"""
Sidecar cleanup: remove `.manifest.json` / `.par2` siblings whose primary asset
file is gone. Run on a directory at the start of acquisition and again before
sealing — keeps `manifests.json` from committing to nonexistent files when a
user has deleted assets from `videos/` or `photos/` by hand.
"""

from pathlib import Path


def prune_orphan_sidecars(directory: Path) -> list[Path]:
    """
    For every `<name>.manifest.json` in `directory`, if the primary asset file
    at `directory / <name>` does not exist, delete that manifest plus the
    matching PAR2 sidecars (`<name>.par2` index + any `<name>.vol*.par2`
    recovery volumes) and any OpenTimestamps proof (`<name>.manifest.json.ots`).

    Returns the list of paths that were actually deleted.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []

    removed: list[Path] = []
    for manifest_path in directory.glob("*.manifest.json"):
        asset_name = manifest_path.name[: -len(".manifest.json")]
        asset_path = directory / asset_name
        if asset_path.exists():
            continue
        candidates = [
            manifest_path,
            manifest_path.with_suffix(manifest_path.suffix + ".ots"),
            directory / f"{asset_name}.par2",
            *directory.glob(f"{asset_name}.vol*.par2"),
            *directory.glob(f"{asset_name}*.par2"),
        ]
        seen: set[Path] = set()
        for c in candidates:
            if c in seen or not c.exists():
                seen.add(c)
                continue
            seen.add(c)
            try:
                c.unlink()
                removed.append(c)
            except Exception as e:
                print(f"⚠️  Could not delete orphan sidecar {c}: {e}")
    return removed

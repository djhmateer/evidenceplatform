"""
Thin subprocess wrapper around the par2cmdline CLI (`par2`).

PAR2 generates Reed-Solomon recovery files that can detect AND repair bitrot
up to a configurable redundancy budget. We use it as the recovery layer next
to chunked SHA-256 manifests.

The CLI is located via PATH first, then a project-local fallback file
(utils/integrity/par2_location.txt) following the same pattern as
utils/opentimestamps/timestamper_opentimestamps.py.
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

try:
    from root_anchor import ROOT_DIR
except Exception:
    ROOT_DIR = Path.cwd()

PAR2_LOCATION_FILE = Path(ROOT_DIR) / "utils" / "integrity" / "par2_location.txt"

DEFAULT_REDUNDANCY_PCT = 20


class Par2NotFoundError(RuntimeError):
    pass


def _exe_name() -> str:
    return "par2.exe" if os.name == "nt" else "par2"


def find_par2_executable() -> Optional[Path]:
    found = shutil.which("par2")
    if found:
        return Path(found)
    if PAR2_LOCATION_FILE.exists():
        try:
            stored = PAR2_LOCATION_FILE.read_text(encoding="utf-8").strip()
            if stored:
                candidate = Path(stored)
                if candidate.is_file():
                    return candidate
                exe_in_dir = candidate / _exe_name()
                if exe_in_dir.is_file():
                    return exe_in_dir
        except Exception:
            pass
    # Project-local install dir (mirrors utils/ffmpeg pattern). Walk recursively
    # because the par2cmdline-turbo zip extracts into a versioned subdirectory.
    local_dir = Path(ROOT_DIR) / "utils" / "par2"
    if local_dir.is_dir():
        exe_name = _exe_name()
        for root, _dirs, files in os.walk(local_dir):
            if exe_name in files:
                return Path(root) / exe_name
    scripts_dir = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")
    candidate = scripts_dir / _exe_name()
    if candidate.exists():
        return candidate
    return None


def ensure_par2_on_path() -> Path:
    exe = find_par2_executable()
    if exe is None:
        raise Par2NotFoundError(
            "Could not locate the `par2` executable. Install par2cmdline-turbo "
            "(https://github.com/animetosho/par2cmdline-turbo) and put `par2.exe` "
            "on PATH, or save the directory containing it to "
            f"{PAR2_LOCATION_FILE}.\n"
            "On Windows: `winget install Animetosho.par2cmdline-turbo` (then restart shell), "
            "or extract the release zip and point the location file at it."
        )
    par2_dir = exe.parent
    if str(par2_dir) not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = str(par2_dir) + os.pathsep + os.environ.get("PATH", "")
    return exe


def create_recovery(
    path: Path,
    redundancy_pct: int = DEFAULT_REDUNDANCY_PCT,
) -> list[Path]:
    """
    Generate PAR2 recovery files for `path` at the given redundancy %.

    Returns the list of `.par2` files produced (relative paths beside `path`).
    Raises Par2NotFoundError or subprocess.CalledProcessError on failure.
    """
    exe = ensure_par2_on_path()
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Cannot create PAR2 recovery for missing file: {path}")

    par2_index = path.with_suffix(path.suffix + ".par2")
    # `-n1` collapses recovery data into a single volume file. Combined with the
    # par2 index file this gives the par2cmdline minimum of 2 files per asset.
    cmd = [
        str(exe),
        "create",
        f"-r{int(redundancy_pct)}",
        "-n1",
        "-q",
        "-q",
        "--",
        str(par2_index),
        str(path),
    ]
    subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        cwd=str(path.parent),
    )

    produced = sorted(path.parent.glob(path.name + "*.par2"))
    return produced


def index_file_for(path: Path) -> Path:
    path = Path(path)
    return path.with_suffix(path.suffix + ".par2")


def hash_par2_index(par2_index: Path) -> str:
    return hashlib.sha256(Path(par2_index).read_bytes()).hexdigest()


def verify_recovery(par2_index: Path) -> bool:
    exe = ensure_par2_on_path()
    cmd = [str(exe), "verify", "-q", "-q", "--", str(par2_index)]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(par2_index).parent))
    return result.returncode == 0


def repair(par2_index: Path) -> bool:
    exe = ensure_par2_on_path()
    cmd = [str(exe), "repair", "-q", "-q", "--", str(par2_index)]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(par2_index).parent))
    return result.returncode == 0

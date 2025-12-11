#!/usr/bin/env python3
"""Extract all .tar.zst files in /mnt/c/temp"""

import subprocess
from pathlib import Path

zst_dir = Path("/mnt/c/temp/1source/1todo")

# **HERE** rename all .zst files to .tar.zst if needed
for zst_file in zst_dir.glob("*.zst"):
    if not zst_file.name.endswith(".tar.zst"):
        new_name = zst_file.with_suffix(".tar.zst")
        print(f"Renaming: {zst_file.name} to {new_name.name}")
        zst_file.rename(new_name)

for tar_zst_file in zst_dir.glob("*.tar.zst"):
    print(f"Extracting: {tar_zst_file.name}")
    subprocess.run(["tar", "--zstd", "-xf", str(tar_zst_file), "-C", str(zst_dir)], check=True)
    print(f"  Done: {tar_zst_file.name}")

import os
import pathlib

directory = pathlib.Path("/mnt/c/Users/djhma/Downloads")

for file in directory.iterdir():
    if file.is_file() and file.suffix == ".zst":
        # Skip files that already have .tar.zst
        if file.name.endswith(".tar.zst"):
            continue
        
        new_name = file.with_suffix("")  # remove .zst
        new_name = new_name.with_suffix(".tar.zst")  # add .tar.zst
        
        print(f"Renaming: {file.name} → {new_name.name}")
        # file.rename(new_name)

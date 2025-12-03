import os
import tarfile
from pathlib import Path
from typing import Optional
from zipfile import ZipFile, ZIP_DEFLATED

import zstandard as zstd

from root_anchor import ROOT_DIR

BATCH_SIZE_LIMIT = 10000 * 1024 * 1024


def get_size_bytes(start_path: Path):
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(start_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            # skip if it is symbolic link
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)

    return total_size


def package_archives_zip():
    root_archives = Path(ROOT_DIR) / "archives"
    archive_dirs = [d for d in root_archives.iterdir() if d.is_dir()]

    root_zips = Path(ROOT_DIR) / "packaged_archives"
    packaged_list_path = root_zips / "packaged_list.txt"
    if packaged_list_path.exists():
        with packaged_list_path.open("r", encoding="utf-8") as f:
            already_packaged = set(line.strip() for line in f if line.strip())
    else:
        already_packaged = set()
    batch_counter_path = root_zips / "batch_counter.txt"
    if batch_counter_path.exists():
        with batch_counter_path.open("r", encoding="utf-8") as f:
            batch_counter = int(f.readline().strip())
    else:
        batch_counter = 0

    to_archive: list[Path] = [a for a in archive_dirs if a.name not in already_packaged]
    current_batch: list[Path] = []
    current_batch_size = 0
    for i in range(len(to_archive)):
        a = to_archive[i]
        print(f"processing {a.name}")
        a_size = get_size_bytes(a)
        print(f"size of {a.name} = {a_size}")
        current_batch.append(a)
        current_batch_size += a_size
        if current_batch_size >= BATCH_SIZE_LIMIT or i == (len(to_archive) - 1):
            print("starting new zip batch")
            with ZipFile(root_zips / f'batch_{batch_counter}.zip', 'w', compresslevel=9, compression=ZIP_DEFLATED) as myzip:
                for p in current_batch:
                    print(f"adding {p.name}")
                    for root, dirs, files in os.walk(p):
                        for file in files:
                            file_path = os.path.join(root, file)
                            # Calculate the relative path within the zip archive
                            arcname = os.path.relpath(file_path, p)
                            myzip.write(file_path, arcname=os.path.join(p.name, arcname))
            batch_counter += 1
            with batch_counter_path.open("w", encoding="utf-8") as f:
                f.write(str(batch_counter))
            with packaged_list_path.open("a", encoding="utf-8") as f:
                f.writelines([p.name + "\n" for p in current_batch])
            current_batch = []
            current_batch_size = 0


def package_archives_zstd():
    root_archives = Path(ROOT_DIR) / "archives"
    archive_dirs = [d for d in root_archives.iterdir() if d.is_dir()]

    root_zips = Path(ROOT_DIR) / "packaged_archives"
    packaged_list_path = root_zips / "packaged_list_zstd.txt"
    if packaged_list_path.exists():
        with packaged_list_path.open("r", encoding="utf-8") as f:
            already_packaged = set(line.strip() for line in f if line.strip())
    else:
        already_packaged = set()
    batch_counter_path = root_zips / "batch_counter_zstd.txt"
    if batch_counter_path.exists():
        with batch_counter_path.open("r", encoding="utf-8") as f:
            batch_counter = int(f.readline().strip())
    else:
        batch_counter = 0

    to_archive: list[Path] = [a for a in archive_dirs if a.name not in already_packaged]
    current_batch: list[Path] = []
    current_batch_size = 0
    for i in range(len(to_archive)):
        a = to_archive[i]
        print(f"processing {a.name}")
        a_size = get_size_bytes(a)
        print(f"size of {a.name} = {a_size}")
        current_batch.append(a)
        current_batch_size += a_size
        if current_batch_size >= BATCH_SIZE_LIMIT or i == (len(to_archive) - 1):
            print("starting new zstd batch")
            with (root_zips / f'batch_{batch_counter}.tar').open('wb') as tar_file:
                with tarfile.open(fileobj=tar_file, mode='w') as tar:
                    for p in current_batch:
                        print(f"adding {p.name}")
                        tar.add(p, arcname=p.name)
            print(f"Created tar file for batch {batch_counter} with size {os.path.getsize(root_zips / f'batch_{batch_counter}.tar')} bytes")
            with (root_zips / f'batch_{batch_counter}.tar').open('rb') as tar_file:
                cctx = zstd.ZstdCompressor(level=22)
                with (root_zips / f'batch_{batch_counter}.zst').open('wb') as zst_file:
                    print(f"Compressing batch {batch_counter} to zstd")
                    cctx.copy_stream(tar_file, zst_file)
            os.remove(root_zips / f'batch_{batch_counter}.tar')
            batch_counter += 1
            with batch_counter_path.open("w", encoding="utf-8") as f:
                f.write(str(batch_counter))
            with packaged_list_path.open("a", encoding="utf-8") as f:
                f.writelines([p.name + "\n" for p in current_batch])
            current_batch = []
            current_batch_size = 0


def decompress_zst(zstd_file: Path, output_dir: Optional[Path]):
    if output_dir is None:
        output_dir = zstd_file.parent
    """Decompress a zstd file to the specified output directory."""
    with zstd.open(zstd_file, 'rb') as f:
        with open(output_dir / zstd_file.with_suffix('').name, 'wb') as out_f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                out_f.write(chunk)
    print(f"Decompressed {zstd_file.name} to {output_dir}")


if __name__ == "__main__":
    package_archives_zstd()
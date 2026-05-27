import os
import tarfile
import shutil
from pathlib import Path
from typing import Optional

import zstandard as zstd

from root_anchor import ROOT_DIR
from utils.integrity.par2 import create_recovery

BATCH_SIZE_LIMIT = 6000 * 1024 * 1024


def get_size_bytes(start_path: Path):
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(start_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            # skip if it is symbolic link
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)

    return total_size


def package_archives_zstd(max_batches: int = 0):
    root_archives = Path(ROOT_DIR) / "archives"
    archive_dirs = [d for d in root_archives.iterdir() if d.is_dir()]

    root_zips = Path(ROOT_DIR) / "utils" / "data_transfers" / "packaged_archives"
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

    to_archive: list[Path] = sorted(
        [a for a in archive_dirs if a.name not in already_packaged],
        key=lambda p: p.stat().st_ctime,
    )
    current_batch: list[Path] = []
    current_batch_size = 0
    batches_created = 0
    for i in range(len(to_archive)):
        a = to_archive[i]
        print(f"processing {a.name}")
        a_size = get_size_bytes(a)
        print(f"size of {a.name} = {a_size}")
        current_batch.append(a)
        current_batch_size += a_size
        if current_batch_size >= BATCH_SIZE_LIMIT or i == (len(to_archive) - 1):
            print("starting new zstd batch")
            tar_path = root_zips / f'batch_{batch_counter}.tar'
            zst_path = root_zips / f'batch_{batch_counter}.tar.zst'
            bundle_path = root_zips / f'batch_{batch_counter}_with_par2.tar'
            with tar_path.open('wb') as tar_file:
                with tarfile.open(fileobj=tar_file, mode='w') as tar:
                    for p in current_batch:
                        print(f"adding {p.name}")
                        tar.add(p, arcname=p.name)
            print(f"Created tar file for batch {batch_counter} with size {os.path.getsize(tar_path)} bytes")
            with tar_path.open('rb') as tar_file:
                cctx = zstd.ZstdCompressor(level=22)
                with zst_path.open('wb') as zst_file:
                    print(f"Compressing batch {batch_counter} to zstd")
                    cctx.copy_stream(tar_file, zst_file)
            os.remove(tar_path)

            print(f"Generating PAR2 recovery for batch {batch_counter} (10% redundancy)")
            par2_files = create_recovery(zst_path, redundancy_pct=10)

            print(f"Bundling {zst_path.name} + {len(par2_files)} par2 files into {bundle_path.name}")
            with tarfile.open(bundle_path, mode='w') as bundle:
                bundle.add(zst_path, arcname=zst_path.name)
                for p in par2_files:
                    bundle.add(p, arcname=p.name)

            os.remove(zst_path)
            for p in par2_files:
                os.remove(p)

            batch_counter += 1
            batches_created += 1
            with batch_counter_path.open("w", encoding="utf-8") as f:
                f.write(str(batch_counter))
            with packaged_list_path.open("a", encoding="utf-8") as f:
                f.writelines([p.name + "\n" for p in current_batch])
            current_batch = []
            current_batch_size = 0
            if max_batches and batches_created >= max_batches:
                return


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


def clean_already_packaged_archives_zstd():
    root_archives = Path(ROOT_DIR) / "archives"
    archive_dirs = [d for d in root_archives.iterdir() if d.is_dir()]

    root_zips = Path(ROOT_DIR) / "utils" / "data_transfers" / "packaged_archives"
    packaged_list_path = root_zips / "packaged_list_zstd.txt"
    if packaged_list_path.exists():
        with packaged_list_path.open("r", encoding="utf-8") as f:
            already_packaged = set(line.strip() for line in f if line.strip())
    else:
        already_packaged = set()

    already_archived: list[Path] = [a for a in archive_dirs if a.name in already_packaged]

    pre_deletion_staging = root_archives / "pre_deletion_staging"
    if not os.path.exists(pre_deletion_staging):
        os.makedirs(pre_deletion_staging)

    for a in already_archived:
        shutil.move(a, pre_deletion_staging)

    if os.name == "nt":
        os.startfile(pre_deletion_staging)


if __name__ == "__main__":
    raw = input("How many batches to create? (0 or empty = all, 'clean' = move already-packaged archives to staging) ").strip()
    if raw.lower() == "clean":
        clean_already_packaged_archives_zstd()
    else:
        max_batches = int(raw) if raw else 0
        package_archives_zstd(max_batches=max_batches)
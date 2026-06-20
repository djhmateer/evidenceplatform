#!/usr/bin/env python3
"""
Database migration runner.

Usage:
    uv run infra/migrate.py
    uv run infra/migrate.py --one-at-a-time

Pending migrations are listed and you are prompted to choose a starting
version.  Migrations before the chosen version are recorded as applied
(skipped) so they are never re-run.  This is the bootstrap path for
existing installations whose schema is already partially or fully up to
date.

Migration files live in migrations/ at the project root and follow the
naming convention:

    V{NNN}__{description}.sql   — SQL migration; may contain multiple
                                  statements separated by semicolons
    V{NNN}__{description}.py    — Python migration; must expose run(cnx)
                                  where cnx is a mysql.connector connection.
                                  The runner commits after run() returns;
                                  raise an exception to abort.

Each applied migration is recorded in the schema_migration table with its
version number.  Migrations are never re-applied.
"""

import importlib.util
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class _Tee:
    """Write to both a file and the original stream."""

    def __init__(self, stream, path: Path):
        self._stream = stream
        self._file = path.open("a", encoding="utf-8", buffering=1)

    def write(self, data):
        self._stream.write(data)
        self._file.write(data)

    def flush(self):
        self._stream.flush()
        self._file.flush()

    def fileno(self):
        return self._stream.fileno()

    def close(self):
        self._file.close()

from utils import db as db_utils  # noqa: E402

MIGRATIONS_DIR = ROOT / "infra" / "migrations"

_CREATE_MIGRATION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version     INT          NOT NULL PRIMARY KEY,
    description VARCHAR(200) NOT NULL,
    applied_at  DATETIME     DEFAULT CURRENT_TIMESTAMP NOT NULL
) ENGINE = InnoDB
"""


# ---------------------------------------------------------------------------
# Internal helpers — all take a raw mysql.connector connection
# ---------------------------------------------------------------------------

def _ensure_migration_table(cnx):
    cur = cnx.cursor()
    try:
        cur.execute(_CREATE_MIGRATION_TABLE)
        cnx.commit()
    finally:
        cur.close()


def _get_applied_versions(cnx) -> set[int]:
    cur = cnx.cursor()
    try:
        cur.execute("SELECT version FROM schema_migration")
        return {row[0] for row in cur.fetchall()}
    finally:
        cur.close()


def _record_version(cnx, version: int, description: str):
    cur = cnx.cursor()
    try:
        cur.execute(
            "INSERT INTO schema_migration (version, description) VALUES (%s, %s)",
            (version, description),
        )
        cnx.commit()
    finally:
        cur.close()


def _parse_filename(path: Path) -> tuple[int, str] | None:
    """V001__some_description.sql → (1, 'some description'), or None if unrecognised."""
    stem = path.stem
    if not stem.startswith("V"):
        return None
    parts = stem.split("__", 1)
    if len(parts) != 2:
        return None
    try:
        version = int(parts[0][1:])
        description = parts[1].replace("_", " ")
        return version, description
    except ValueError:
        return None


def _strip_line_comments(sql: str) -> str:
    """Drop full-line ``--`` comments so semicolons inside them can't split a
    statement. Lines whose first non-whitespace characters are ``--`` are
    removed entirely; everything else (including ``comment '...'`` clauses) is
    left untouched."""
    return "\n".join(
        line for line in sql.splitlines()
        if not line.lstrip().startswith("--")
    )


def _apply_sql(cnx, path: Path):
    sql = _strip_line_comments(path.read_text(encoding="utf-8"))
    cur = cnx.cursor()
    try:
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        cnx.commit()
    finally:
        cur.close()


def _apply_python(cnx, path: Path):
    spec = importlib.util.spec_from_file_location("migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "run"):
        raise AttributeError(f"{path.name} must expose a run(cnx) function")
    module.run(cnx)
    cnx.commit()


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run_pending_migrations(one_at_a_time: bool = False):
    cnx = db_utils.cnx_pool.get_connection()
    try:
        _ensure_migration_table(cnx)
        applied = _get_applied_versions(cnx)

        candidates: list[tuple[int, str, Path]] = []
        for path in MIGRATIONS_DIR.iterdir():
            if path.suffix not in (".sql", ".py"):
                continue
            parsed = _parse_filename(path)
            if parsed is None:
                print(f"  [SKIP] Unrecognised filename: {path.name}")
                continue
            candidates.append((parsed[0], parsed[1], path))

        candidates.sort(key=lambda x: x[0])
        pending = [(v, d, p) for v, d, p in candidates if v not in applied]

        if not pending:
            print("Database is up to date — no pending migrations.")
            return

        print("Pending migrations:")
        for v, d, _ in pending:
            print(f"  V{v:03d}  {d}")
        print()

        valid_versions = [v for v, _, _ in pending]

        if one_at_a_time:
            answer = input(
                f"Run which single migration? (only this one will apply) "
                f"[{valid_versions[0]}–{valid_versions[-1]}]: "
            ).strip()
        else:
            answer = input(
                f"Start from which version? "
                f"[{valid_versions[0]}–{valid_versions[-1]}, default={valid_versions[0]}]: "
            ).strip()

        if answer == "" and not one_at_a_time:
            start_version = valid_versions[0]
        else:
            try:
                start_version = int(answer)
            except ValueError:
                print("Invalid input — expected a version number.")
                sys.exit(1)
            if start_version not in valid_versions:
                print(f"V{start_version:03d} is not in the pending list.")
                sys.exit(1)

        stop_version = start_version if one_at_a_time else None

        skipped = 0
        applied_count = 0
        for version, description, path in pending:
            if stop_version is not None and version > stop_version:
                break
            if version < start_version:
                _record_version(cnx, version, description)
                print(f"  Skipped  V{version:03d}: {description}")
                skipped += 1
                continue

            print(f"  Applying V{version:03d}: {description} ...", flush=True)
            t_start = time.perf_counter()
            try:
                if path.suffix == ".sql":
                    _apply_sql(cnx, path)
                else:
                    _apply_python(cnx, path)
                _record_version(cnx, version, description)
                elapsed = time.perf_counter() - t_start
                print(f"  V{version:03d} done ({elapsed:.1f}s).")
                applied_count += 1
            except Exception as e:
                elapsed = time.perf_counter() - t_start
                print(f"  V{version:03d} FAILED after {elapsed:.1f}s.\n  Error: {e}")
                print("  Stopping. Fix the migration and re-run.")
                sys.exit(1)

        parts = []
        if skipped:
            parts.append(f"{skipped} skipped")
        if applied_count:
            parts.append(f"{applied_count} applied")
        print(f"\n{', '.join(parts)}.")
    finally:
        cnx.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run database migrations.")
    parser.add_argument("--one-at-a-time", action="store_true",
                        help="Prompt for a single version to run, then stop.")
    args = parser.parse_args()

    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"migrate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    tee = _Tee(sys.stdout, log_path)
    sys.stdout = tee
    print(f"Logging to {log_path}", flush=True)

    tee_err = _Tee(sys.stderr, log_path)
    sys.stderr = tee_err

    try:
        run_pending_migrations(one_at_a_time=args.one_at_a_time)
    finally:
        sys.stdout = tee._stream
        sys.stderr = tee_err._stream
        tee.close()
        tee_err.close()

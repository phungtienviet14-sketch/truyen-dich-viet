"""Consistent SQLite snapshots via the backup API; never overwrite live files."""

import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path


def backup_database(source: Path, destination: Path) -> Path:
    source, destination = source.resolve(), destination.resolve()
    if source == destination:
        raise ValueError("Source and destination must differ")
    if not source.is_file():
        raise FileNotFoundError("Source database does not exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as origin:
            with closing(sqlite3.connect(destination)) as snapshot:
                origin.backup(snapshot)
                if snapshot.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise sqlite3.DatabaseError("Snapshot integrity check failed")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def restore_database(source: Path, destination: Path) -> Path:
    """Restore to a NEW path; operator must stop web/worker before swapping files."""
    return backup_database(source, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--restore", action="store_true")
    parser.add_argument("--if-exists", action="store_true", help="Skip an absent source on first deploy")
    args = parser.parse_args()
    if args.if_exists and not args.source.exists():
        print("No database yet; initial deployment needs no snapshot.")
        return 0
    operation = restore_database if args.restore else backup_database
    try:
        operation(args.source, args.destination)
    except (OSError, ValueError, sqlite3.DatabaseError) as error:
        parser.exit(1, f"Snapshot failed ({type(error).__name__}); source was not modified.\n")
    print("Snapshot created and integrity checked. Source was not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

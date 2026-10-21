import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path


def connect_readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=30)


def check(path):
    with closing(connect_readonly(path)) as database:
        if database.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed")


def copy_database(source, destination):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("Backup destination must differ from source")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".sqlite-backup-", dir=destination.parent)
    os.close(descriptor)
    try:
        with closing(connect_readonly(source)) as reader, closing(sqlite3.connect(temporary)) as writer:
            reader.backup(writer, pages=256, sleep=0.05)
        check(temporary)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def verify_restore(source):
    check(source)
    with tempfile.TemporaryDirectory(prefix="logiops-restore-") as directory:
        restored = Path(directory) / "restored.sqlite3"
        copy_database(source, restored)
        check(restored)
    data = Path(source).read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("source", type=Path)
    backup.add_argument("destination", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("source", type=Path)
    args = parser.parse_args()
    if args.command == "backup":
        copy_database(args.source, args.destination)
    print(json.dumps(verify_restore(args.destination if args.command == "backup" else args.source)))


if __name__ == "__main__":
    main()

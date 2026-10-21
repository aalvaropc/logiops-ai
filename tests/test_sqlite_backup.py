import sqlite3

import pytest

from scripts.sqlite_backup import copy_database, verify_restore


def test_online_backup_includes_committed_wal_and_restores(tmp_path):
    source, backup = tmp_path / "live.sqlite3", tmp_path / "backup.sqlite3"
    with sqlite3.connect(source) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE audit (value TEXT)")
        writer.execute("INSERT INTO audit VALUES ('committed')")
        writer.commit()
        writer.execute("INSERT INTO audit VALUES ('pending')")
        copy_database(source, backup)
        assert source.with_name("live.sqlite3-wal").exists()
    with sqlite3.connect(backup) as restored:
        assert restored.execute("SELECT value FROM audit").fetchall() == [("committed",)]
    assert verify_restore(backup)["bytes"] > 0
    assert backup.stat().st_mode & 0o777 == 0o600


def test_failed_backup_preserves_previous_destination(tmp_path):
    source, backup = tmp_path / "bad.sqlite3", tmp_path / "backup.sqlite3"
    source.write_bytes(b"not a database")
    backup.write_bytes(b"previous backup")
    with pytest.raises(sqlite3.DatabaseError):
        copy_database(source, backup)
    assert backup.read_bytes() == b"previous backup"
    assert list(tmp_path.glob(".sqlite-backup-*")) == []

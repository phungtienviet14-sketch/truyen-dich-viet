import sqlite3
from pathlib import Path

import pytest

from scripts.backup_sqlite import backup_database, restore_database
from scripts.oracle_preflight import read_profile, run_readonly


def test_backup_includes_committed_wal_and_preserves_source(tmp_path):
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE stories (title TEXT)")
        connection.execute("INSERT INTO stories VALUES ('Truyện Việt')")
        connection.commit()
        backup = backup_database(source, tmp_path / "backup.db")
        with sqlite3.connect(backup) as restored:
            assert restored.execute("SELECT title FROM stories").fetchone()[0] == "Truyện Việt"
        assert connection.execute("SELECT count(*) FROM stories").fetchone()[0] == 1


def test_backup_refuses_overwrite_missing_and_same_path(tmp_path):
    source = tmp_path / "source.db"
    with pytest.raises(FileNotFoundError):
        backup_database(source, tmp_path / "backup.db")
    sqlite3.connect(source).close()
    with pytest.raises(ValueError):
        backup_database(source, source)
    target = tmp_path / "exists.db"
    target.write_text("preserve")
    with pytest.raises(FileExistsError):
        backup_database(source, target)
    assert target.read_text() == "preserve"


def test_restore_requires_new_destination_and_rejects_corrupt_backup(tmp_path):
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE stories (id INTEGER)")
    restored = restore_database(source, tmp_path / "restored.db")
    assert restored.exists()
    with pytest.raises(FileExistsError):
        restore_database(source, restored)
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        restore_database(broken, tmp_path / "bad-restore.db")
    assert not (tmp_path / "bad-restore.db").exists()


def test_profile_does_not_require_or_read_private_key(tmp_path):
    config = tmp_path / "config"
    config.write_text("[TRUYEN]\nregion=ap-singapore-1\ntenancy=ocid1.tenancy.oc1..example\nsecurity_token_file=private-token\nkey_file=private-key\n")
    profile = read_profile(config, "TRUYEN")
    assert profile == {"region": "ap-singapore-1", "tenancy": "ocid1.tenancy.oc1..example"}
    with pytest.raises(ValueError, match="profile"):
        read_profile(config, "MISSING")


def test_readonly_cli_rejects_mutation_before_subprocess():
    with pytest.raises(ValueError, match="read-only"):
        run_readonly("oci", Path("config"), "TRUYEN", ["compute", "instance", "launch"])


def test_readonly_cli_hides_provider_errors(monkeypatch):
    import subprocess

    def fail(*args, **kwargs):
        assert kwargs["shell"] is False
        raise subprocess.CalledProcessError(1, args[0], stderr="private-key-detail")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(RuntimeError) as error:
        run_readonly("oci", Path("config"), "TRUYEN", ["iam", "region-subscription", "list"])
    assert "private-key-detail" not in str(error.value)

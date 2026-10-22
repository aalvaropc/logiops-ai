import os
import re
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

import pytest

import scripts.deploy_ec2 as deploy
from scripts.sqlite_backup import copy_database

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra" / "amazon"


def heredoc(template, name):
    body = re.search(rf"<<'{name}'\n(.*?)\n{name}\n", template, re.S).group(1)
    return body.replace("$$", "$")


def run_script(script, tmp_path, *args, env=None):
    path = tmp_path / "script.sh"
    path.write_text(script)
    return subprocess.run(["bash", str(path), *args], capture_output=True, text=True, env={"PATH": os.environ["PATH"], **(env or {})})


def reset_gate(tmp_path, age_seconds):
    marker = tmp_path / "paused"
    script = heredoc((INFRA / "recovery.sh.tftpl").read_text(), "GATE").replace("/etc/logiops-reset-paused", str(marker))
    if age_seconds is not None:
        marker.touch()
        stamp = time.time() - age_seconds
        os.utime(marker, (stamp, stamp))
    return run_script(script, tmp_path)


def test_the_reset_pause_marker_expires_after_thirty_hours(tmp_path):
    assert reset_gate(tmp_path, None).returncode == 0
    fresh = reset_gate(tmp_path, 3600)
    assert fresh.returncode == 1 and "Reset skipped" in fresh.stdout
    assert reset_gate(tmp_path, 30 * 3600 - 60).returncode == 1
    forgotten = reset_gate(tmp_path, 30 * 3600)
    assert forgotten.returncode == 0 and "resetting" in forgotten.stdout
    assert reset_gate(tmp_path, -3600).returncode == 0


def test_the_reset_unit_is_gated_and_installation_fails_without_it():
    template = (INFRA / "recovery.sh.tftpl").read_text()
    assert "ExecCondition=/usr/local/sbin/logiops-reset-gate" in template and "ConditionPathExists" not in template
    assert template.index("test -f /etc/systemd/system/logiops-reset.service ||") < template.index("pause.conf")
    assert "exit 1" in template.split("test -f /etc/systemd/system/logiops-reset.service ||")[1].split("\n")[0]


def test_missing_reset_unit_leaves_the_installation_untouched(tmp_path):
    template = (INFRA / "recovery.sh.tftpl").read_text()
    for directory in ("/usr/local", "/etc", "/var/lib"):
        template = template.replace(directory, str(tmp_path / "host" / directory.lstrip("/")))
    result = run_script(template, tmp_path)
    assert result.returncode == 1
    assert "logiops-reset.service is not installed" in result.stderr
    assert not (tmp_path / "host").exists()


@pytest.mark.parametrize("sidecar", ["wal", "shm"])
def test_permission_cleanup_does_not_follow_a_sidecar_symlink(tmp_path, sidecar):
    database = tmp_path / "database.sqlite3"
    database.touch()
    target = tmp_path / "outside-the-database"
    target.write_text("protected")
    database.with_name(f"{database.name}-{sidecar}").symlink_to(target)
    backup = heredoc((INFRA / "recovery.sh.tftpl").read_text(), "BACKUP")
    cleanup = backup[backup.index("restore_owner() {"):backup.index("\ntrap ")]
    before = target.stat()
    time.sleep(0.02)
    result = run_script(f'database="{database}"\n{cleanup}\nrestore_owner\n', tmp_path)
    assert result.returncode == 0, result.stderr
    assert target.stat().st_ctime_ns == before.st_ctime_ns
    assert target.read_text() == "protected"


def predeploy(tmp_path, attempts_failing, env=None, installed=True):
    deployment = (INFRA / "deploy.sh.tftpl").read_text()
    block = deployment[deployment.index("if test -f /var/lib/logiops/logiops.sqlite3; then"):deployment.index("token=$(")]
    backup = tmp_path / "logiops-backup"
    counter = tmp_path / "count"
    counter.write_text("0")
    backup.write_text(f'#!/usr/bin/env bash\nn=$(( $(cat {counter}) + 1 )); echo $n > {counter}\n[ "$n" -gt {attempts_failing} ]\n')
    backup.chmod(0o755)
    (tmp_path / "logiops.sqlite3").touch()
    script = block.replace("$$", "$").replace("/var/lib/logiops/logiops.sqlite3", str(tmp_path / "logiops.sqlite3")).replace("/usr/local/sbin/logiops-backup", str(backup if installed else tmp_path / "missing")).replace("sleep 10", ":")
    result = run_script(script + "\necho continued\n", tmp_path, env=env)
    return result, int(counter.read_text())


def test_a_flaky_backup_is_retried_and_the_deploy_continues(tmp_path):
    result, calls = predeploy(tmp_path, attempts_failing=2)
    assert result.returncode == 0 and "continued" in result.stdout and calls == 3


def test_a_backup_that_keeps_failing_stops_the_deploy_with_a_reason(tmp_path):
    result, calls = predeploy(tmp_path, attempts_failing=99)
    assert result.returncode == 1 and "continued" not in result.stdout and calls == 3
    assert "no verified pre-deploy backup" in result.stderr


def test_an_environment_override_cannot_bypass_a_failed_backup(tmp_path):
    result, _ = predeploy(tmp_path, attempts_failing=99, env={"LOGIOPS_ACCEPT_NO_RECOVERY_POINT": "yes"})
    assert result.returncode == 1 and "continued" not in result.stdout


def test_a_missing_backup_hook_stops_the_deploy(tmp_path):
    result, calls = predeploy(tmp_path, attempts_failing=0, installed=False)
    assert result.returncode == 1 and calls == 0 and "install_recovery.py" in result.stderr


def test_the_remote_deploy_always_checks_the_recovery_hook():
    plain = deploy.deploy_command("s3://b/releases/d.tar.gz", "d", "h", "s")
    assert plain.index("test -x /usr/local/sbin/logiops-backup") < plain.index("logiops-deploy s3://")
    assert "LOGIOPS_ACCEPT_NO_RECOVERY_POINT" not in plain


def test_snapshots_expire_with_their_versions_and_delete_markers_and_the_role_stays_narrow():
    backup = (INFRA / "backup.tf").read_text()
    assert "expiration { days = 7 }" in backup and "noncurrent_version_expiration { noncurrent_days = 7 }" in backup
    assert "expiration { expired_object_delete_marker = true }" in backup
    policy = backup.split('resource "aws_iam_role_policy" "backups"')[1].split("locals {")[0]
    assert 'Action   = ["s3:PutObject", "s3:GetObject", "s3:AbortMultipartUpload"]' in policy
    assert '"${aws_s3_bucket.backups.arn}/snapshots/*"' in policy and "s3:*" not in policy and '"*"' not in policy


def test_a_backup_completes_while_another_process_keeps_writing(tmp_path):
    source, backup = tmp_path / "live.sqlite3", tmp_path / "backup.sqlite3"
    with sqlite3.connect(source) as setup:
        setup.execute("PRAGMA journal_mode=WAL")
        setup.execute("CREATE TABLE audit (id INTEGER PRIMARY KEY, value TEXT)")
        setup.executemany("INSERT INTO audit (value) VALUES (?)", [("x" * 900,)] * 30000)
    stop = threading.Event()

    def write():
        with sqlite3.connect(source, timeout=30) as writer:
            while not stop.is_set():
                writer.execute("INSERT INTO audit (value) VALUES ('y')")
                writer.commit()

    writer_thread = threading.Thread(target=write, daemon=True)
    copier = threading.Thread(target=copy_database, args=(source, backup), daemon=True)
    writer_thread.start()
    copier.start()
    copier.join(15)
    stop.set()
    assert not copier.is_alive(), "the backup restarted on every write and never finished"
    with sqlite3.connect(backup) as restored:
        assert restored.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


def test_the_rendered_user_data_stays_under_the_16_kb_instance_limit():
    parts = [INFRA / "bootstrap.sh.tftpl", INFRA / "recovery.sh.tftpl", INFRA / "deploy.sh.tftpl", ROOT / "scripts" / "sqlite_backup.py"]
    assert sum(len(part.read_bytes()) for part in parts) < 15000

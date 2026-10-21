import json
import sys
import tarfile

import pytest

import scripts.deploy_ec2 as deploy


def test_archive_metadata_and_hash_are_repeatable():
    first, first_hash = deploy.package("a" * 40)
    second, second_hash = deploy.package("a" * 40)
    assert first_hash == second_hash
    with tarfile.open(second, "r:gz") as archive:
        assert json.load(archive.extractfile("release.json")) == {"commit": "a" * 40}


def test_preview_and_package_only_cannot_bypass_a_dirty_checkout(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["deploy", "--package-only", "--allow-unmerged"])
    monkeypatch.setattr(deploy, "release_dirty", lambda: True)
    with pytest.raises(SystemExit, match="clean commit"):
        deploy.main()

import sqlite3
import threading

import pytest

from logiops.scenario import INCIDENT_IDS, INCIDENTS, KIND_LABELS, PLAYBOOKS, incident_ids, reset_registry
from logiops.service import LogiOpsService
from tests.test_scenario_atomicity import pack_incident


@pytest.fixture(autouse=True)
def registry():
    reset_registry()
    yield
    reset_registry()


def test_a_failed_seed_rolls_back_every_incident_and_can_be_retried(tmp_path, monkeypatch):
    service = LogiOpsService(tmp_path / "rollback.sqlite3")
    seed = LogiOpsService._seed
    second = pack_incident(id="SHIP-471")
    second["orders"][0]["id"] = "ORD-471"
    pack = {"version": 1, "incidents": [pack_incident(), second]}

    def fail(cls, connection, incident_id, *args, **kwargs):
        seed(connection, incident_id, *args, **kwargs)
        if incident_id == "SHIP-471":
            raise sqlite3.OperationalError("simulated write failure")

    monkeypatch.setattr(LogiOpsService, "_seed", classmethod(fail))
    with pytest.raises(sqlite3.OperationalError):
        service.register_pack(pack)
    assert incident_ids() == INCIDENT_IDS
    assert "SHIP-470" not in PLAYBOOKS and "SHIP-471" not in INCIDENTS
    assert "port_strike" not in KIND_LABELS
    with sqlite3.connect(service.db_path) as connection:
        assert {row[0] for row in connection.execute("SELECT incident_id FROM snapshot")} == set(INCIDENT_IDS)
        assert connection.execute("SELECT COUNT(*) FROM events WHERE incident_id IN ('SHIP-470', 'SHIP-471')").fetchone()[0] == 0
    monkeypatch.setattr(LogiOpsService, "_seed", classmethod(seed.__func__))
    assert service.register_pack(pack) == ["SHIP-470", "SHIP-471"]
    assert service.get("SHIP-471")["source_version"] == 1


@pytest.mark.parametrize("fail", [False, True])
def test_a_reader_can_scan_while_a_pack_is_being_seeded(tmp_path, monkeypatch, fail):
    service = LogiOpsService(tmp_path / "visibility.sqlite3")
    seed = LogiOpsService._seed
    writing, release = threading.Event(), threading.Event()
    errors = []

    def pause(cls, connection, incident_id, *args, **kwargs):
        seed(connection, incident_id, *args, **kwargs)
        writing.set()
        if not release.wait(5):
            raise TimeoutError("the reader did not release the writer")
        if fail:
            raise sqlite3.OperationalError("simulated write failure")

    def write():
        try:
            service.register_pack({"version": 1, "incidents": [pack_incident()]})
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(LogiOpsService, "_seed", classmethod(pause))
    writer = threading.Thread(target=write)
    writer.start()
    try:
        assert writing.wait(5)
        assert incident_ids() == INCIDENT_IDS
        assert len(service.list_incidents()) == len(INCIDENT_IDS)
        with sqlite3.connect(service.db_path) as connection:
            assert {row[0] for row in connection.execute("SELECT incident_id FROM snapshot")} == set(INCIDENT_IDS)
    finally:
        release.set()
        writer.join(5)
    assert not writer.is_alive()
    assert len(errors) == int(fail)
    if fail:
        assert isinstance(errors[0], sqlite3.OperationalError)
        assert incident_ids() == INCIDENT_IDS
    else:
        assert incident_ids() == (*INCIDENT_IDS, "SHIP-470")
        assert service.get("SHIP-470")["state"]["incident_id"] == "SHIP-470"

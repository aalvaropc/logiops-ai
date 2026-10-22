import threading
import time
from copy import deepcopy
from datetime import date

import pytest

from logiops import scenario
from logiops.scenario import (
    INCIDENTS, KIND_LABELS, PLAYBOOKS, ScenarioPackError, builtin_incidents, register_pack, reset_registry, seed_state,
)


def pack_incident(**changes):
    definition = builtin_incidents()[0]
    definition.update(id="SHIP-470", kind="port_strike", kind_label="Port strike")
    definition["orders"][0]["id"] = "ORD-470"
    for path, value in changes.items():
        target = definition
        keys = path.split(".")
        for key in keys[:-1]:
            target = target[int(key)] if key.isdigit() else target[key]
        target[int(keys[-1]) if keys[-1].isdigit() else keys[-1]] = value
    return definition


@pytest.mark.parametrize("change", [
    {"orders.0.priority": {}},
    {"options.0.sources": [{}]},
    {"options.0.sources": [[]]},
    {"shipment": []},
    {"inventory": []},
    {"carriers": []},
    {"options": [None]},
    {"shipment.original_eta": "2026-10-12-05:00"},
])
def test_nested_bad_types_do_not_register_any_part_of_a_pack(change):
    good = pack_incident()
    bad = pack_incident(id="SHIP-471", **change)
    bad["orders"][0]["id"] = "ORD-471"
    before = deepcopy((INCIDENTS, PLAYBOOKS, KIND_LABELS))
    try:
        with pytest.raises(ScenarioPackError):
            register_pack({"version": 1, "incidents": [good, bad]})
        assert (INCIDENTS, PLAYBOOKS, KIND_LABELS) == before
    finally:
        reset_registry()


def test_duplicates_inside_a_pack_are_validated_before_commit():
    before = deepcopy((INCIDENTS, PLAYBOOKS, KIND_LABELS))
    with pytest.raises(ScenarioPackError, match="already registered"):
        register_pack({"version": 1, "incidents": [pack_incident(), pack_incident()]})
    assert (INCIDENTS, PLAYBOOKS, KIND_LABELS) == before


def test_concurrent_registrations_of_one_id_register_it_once(monkeypatch):
    checked = scenario._problems

    def slow(*args, **kwargs):
        found = checked(*args, **kwargs)
        time.sleep(0.2)
        return found

    monkeypatch.setattr(scenario, "_problems", slow)
    outcomes = []

    def attempt():
        try:
            outcomes.append(register_pack({"version": 1, "incidents": [pack_incident()]}))
        except ScenarioPackError as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(type(item).__name__ for item in outcomes) == ["ScenarioPackError", "list"]
        assert "already registered" in str(next(item for item in outcomes if isinstance(item, ScenarioPackError)))
    finally:
        reset_registry()


def test_an_incident_is_visible_only_after_its_playbook_and_kind_label(monkeypatch):
    seen = []

    class Revealing(dict):
        def update(self, *args, **kwargs):
            seen.append(("SHIP-470" in scenario.PLAYBOOKS, "port_strike" in scenario.KIND_LABELS))
            super().update(*args, **kwargs)

    for name in ("INCIDENTS", "PLAYBOOKS", "KIND_LABELS"):
        monkeypatch.setattr(scenario, name, Revealing(getattr(scenario, name)))
    register_pack({"version": 1, "incidents": [pack_incident()]})
    assert seen[-1] == (True, True) and len(seen) == 3


def test_text_that_looks_like_a_timestamp_does_not_break_seeding():
    definition = pack_incident(title="2026-10-12T14:00 strike", **{"orders.0.customer": "2026-10-12T14:00:00-05:00 Harbor"})
    definition["shipment"]["disruption"] = "2026-10-12T14:00 the port is closed"
    try:
        register_pack({"version": 1, "incidents": [definition]})
        state = seed_state("SHIP-470", date(2026, 10, 22))
        assert state["title"] == "2026-10-12T14:00 strike"
        assert state["orders"][0]["customer"] == "2026-10-12T14:00:00-05:00 Harbor"
        assert state["shipment"]["disruption"] == "2026-10-12T14:00 the port is closed"
        assert state["shipment"]["original_eta"].startswith("2026-10-22T14:00:00")
    finally:
        reset_registry()


@pytest.mark.parametrize("moment", ["1999-12-31T23:59:00-05:00", "2100-01-01T00:00:00-05:00", "9999-12-31T23:59:00-05:00"])
def test_a_timestamp_the_scenario_clock_cannot_move_is_rejected(moment):
    before = deepcopy((INCIDENTS, PLAYBOOKS, KIND_LABELS))
    try:
        with pytest.raises(ScenarioPackError, match="original_eta"):
            register_pack({"version": 1, "incidents": [pack_incident(**{"shipment.original_eta": moment})]})
        assert (INCIDENTS, PLAYBOOKS, KIND_LABELS) == before
    finally:
        reset_registry()

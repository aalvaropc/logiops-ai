from copy import deepcopy

import pytest

from logiops.scenario import INCIDENTS, KIND_LABELS, PLAYBOOKS, ScenarioPackError, builtin_incidents, register_pack, reset_registry


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
])
def test_nested_bad_types_do_not_register_any_part_of_a_pack(change):
    good = pack_incident()
    bad = pack_incident(id="SHIP-471", **change)
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

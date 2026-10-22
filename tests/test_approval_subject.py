from logiops.service import LogiOpsService


def test_approval_records_optional_subject_without_changing_idempotence(tmp_path):
    service = LogiOpsService(tmp_path / "subject.sqlite3")
    plan = service.investigate("SHIP-421")[0]
    first = service.approve("SHIP-421", plan["id"], plan["source_version"], "Judge", approved_subject="user-123")
    again = service.approve("SHIP-421", plan["id"], plan["source_version"], "Other", approved_subject="user-456")
    assert first == again
    events = [item for item in service.get("SHIP-421")["events"] if item["name"] == "plan_approved"]
    assert len(events) == 1
    assert events[0]["data"]["approved_subject"] == "user-123"

from datetime import date

from scripts.audit_dependencies import problems


def test_dependency_exceptions_are_narrow_and_expire():
    report = {"dependencies": [{"name": "example", "version": "1", "vulns": [{"id": "CVE-X", "aliases": ["GHSA-X"]}]}]}
    exception = {"package": "example", "version": "1", "id": "GHSA-X", "reason": "Unaffected call path", "url": "https://github.com/advisories/GHSA-X", "expires": "2026-10-25"}
    assert problems(report, [], date(2026, 10, 21))
    assert problems(report, [exception], date(2026, 10, 21)) == []
    assert problems(report, [{**exception, "version": "2"}], date(2026, 10, 21))
    assert problems(report, [exception], date(2026, 10, 25))


def test_a_skipped_dependency_and_a_distant_expiry_fail_the_audit():
    skipped = {"dependencies": [{"name": "example", "skip_reason": "Dependency not found on PyPI"}]}
    assert problems(skipped, [], date(2026, 10, 21))
    exception = {"package": "example", "version": "1", "id": "GHSA-X", "reason": "Unaffected call path", "url": "https://github.com/advisories/GHSA-X"}
    assert problems({"dependencies": []}, [{**exception, "expires": "2026-12-31"}], date(2026, 10, 21)) == []
    assert problems({"dependencies": []}, [{**exception, "expires": "2027-12-31"}], date(2026, 10, 21))

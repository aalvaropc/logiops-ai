from datetime import date

from scripts.audit_dependencies import problems


def test_dependency_exceptions_are_narrow_and_expire():
    report = {"dependencies": [{"name": "example", "version": "1", "vulns": [{"id": "CVE-X", "aliases": ["GHSA-X"]}]}]}
    exception = {"package": "example", "version": "1", "id": "GHSA-X", "reason": "Unaffected call path", "url": "https://github.com/advisories/GHSA-X", "expires": "2026-10-25"}
    assert problems(report, [], date(2026, 10, 21))
    assert problems(report, [exception], date(2026, 10, 21)) == []
    assert problems(report, [{**exception, "version": "2"}], date(2026, 10, 21))
    assert problems(report, [exception], date(2026, 10, 25))

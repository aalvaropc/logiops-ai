import json
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_EXCEPTION_DAYS = 90


def problems(report, exceptions, today=None):
    today = today or date.today()
    errors = []
    allowed = set()
    for item in exceptions:
        if not item.get("reason") or not str(item.get("url", "")).startswith("https://"):
            errors.append(f"Exception needs a reason and advisory URL: {item}")
        elif date.fromisoformat(item["expires"]) <= today:
            errors.append(f"Expired exception: {item['id']}")
        elif date.fromisoformat(item["expires"]) > today + timedelta(days=MAX_EXCEPTION_DAYS):
            errors.append(f"Exception {item['id']} expires more than {MAX_EXCEPTION_DAYS} days from now")
        else:
            allowed.add((item["package"], item["version"], item["id"]))
    for dependency in report["dependencies"]:
        if "skip_reason" in dependency:
            errors.append(f"{dependency['name']} was not audited: {dependency['skip_reason']}")
        for vulnerability in dependency.get("vulns", []):
            ids = {vulnerability["id"], *vulnerability.get("aliases", [])}
            if not any((dependency["name"], dependency["version"], identifier) in allowed for identifier in ids):
                errors.append(f"{dependency['name']}=={dependency['version']}: {vulnerability['id']}")
    return errors


def main():
    with tempfile.TemporaryDirectory() as directory:
        requirements = Path(directory) / "requirements.txt"
        report = Path(directory) / "audit.json"
        with requirements.open("w") as output:
            subprocess.run(["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-annotate", "--no-header", "--quiet"], cwd=ROOT, stdout=output, check=True)
        audited = subprocess.run([
            "uvx", "--from", "pip-audit==2.10.1", "pip-audit", "--no-deps", "--disable-pip",
            "--requirement", str(requirements), "--format", "json", "--output", str(report),
        ], capture_output=True, text=True)
        if audited.returncode not in (0, 1) or not report.is_file():
            raise RuntimeError(f"Dependency audit did not complete: {audited.stderr}")
        errors = problems(json.loads(report.read_text()), json.loads((ROOT / "security/dependency-exceptions.json").read_text())["exceptions"])
        if errors:
            raise SystemExit("\n".join(errors))
        print("Production dependency audit passed")


if __name__ == "__main__":
    main()

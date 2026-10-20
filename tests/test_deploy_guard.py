"""Only main is deployed, and every pull request targets main."""

from pathlib import Path

import scripts.deploy_ec2 as deploy
from scripts.deploy_ec2 import unmerged_reason

ROOT = Path(__file__).resolve().parents[1]


def test_only_a_clean_checkout_of_main_is_deployed():
    assert unmerged_reason("a" * 40, "a" * 40, dirty=False) is None
    assert "not origin/main" in unmerged_reason("b" * 40, "a" * 40, dirty=False)
    assert "uncommitted" in unmerged_reason("a" * 40, "a" * 40, dirty=True)
    script = (ROOT / "scripts" / "deploy_ec2.py").read_text()
    assert '"--allow-unmerged"' in script and "raise SystemExit(reason)" in script


def test_ci_fails_a_pull_request_that_does_not_target_main():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "pr-targets-main:" in workflow and 'if [ "$BASE" != "main" ]' in workflow
    assert "types: [opened, synchronize, reopened, edited]" in workflow


def test_an_untracked_file_in_the_release_counts_as_dirty(monkeypatch):
    calls = []

    def fake_git(*args):
        calls.append(args)
        return "?? logiops/static/new.js" if "--untracked-files=all" in args else ""

    monkeypatch.setattr(deploy, "git", fake_git)
    assert deploy.release_dirty() is True
    assert any("logiops" in call for call in calls)
    monkeypatch.setattr(deploy, "git", lambda *args: "")
    assert deploy.release_dirty() is False


def test_the_instance_reads_only_allowed_settings_from_ssm():
    template = (ROOT / "infra" / "amazon" / "bootstrap.sh.tftpl").read_text()
    assert "aws ssm get-parameters-by-path --region '${aws_region}' --path '${config_path}/'" in template
    allowed = ("LOGIOPS_COGNITO_ISSUER|LOGIOPS_COGNITO_DOMAIN|LOGIOPS_COGNITO_CLIENT_ID|LOGIOPS_MEMORY_ID|"
               "LOGIOPS_POLLY_VOICE|LOGIOPS_POLLY_ENGINE|LOGIOPS_DAILY_SPEECH_CHARS|LOGIOPS_DAILY_MODEL_CALLS)")
    assert allowed in template and "LOGIOPS_ACCESS_TOKEN|" not in template and "LOGIOPS_PUBLIC|" not in template
    assert """if [[ "$value" =~ ^[A-Za-z0-9:/._-]+$ ]]; then printf""" in template
    policy = (ROOT / "infra" / "amazon" / "main.tf").read_text()
    assert '"polly:SynthesizeSpeech"' in policy and "Resource = [aws_bedrockagentcore_memory.app.arn]" in policy
    assert "bedrock-agentcore:*" not in policy and '"ssm:GetParametersByPath"' in policy


def test_the_release_packages_static_subdirectories(tmp_path, monkeypatch):
    import scripts.deploy_ec2 as deploy

    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    for path in ("pyproject.toml", "uv.lock", "logiops/api.py", "logiops/routes/__init__.py", "logiops/routes/pages.py",
                 "logiops/__pycache__/api.cpython-312.pyc", "logiops/static/demo.js", "logiops/static/app/api.js", "skills/x/SKILL.md"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(path)
    (tmp_path / "logiops" / "static" / "empty").mkdir()
    monkeypatch.setattr(deploy.tempfile, "gettempdir", lambda: str(tmp_path / "out"))
    (tmp_path / "out").mkdir()
    archive, _ = deploy.package()
    import tarfile

    with tarfile.open(archive, "r:gz") as release:
        names = set(release.getnames())
    assert "logiops/static/app/api.js" in names and "logiops/static/demo.js" in names
    assert "logiops/routes/pages.py" in names and "logiops/routes/__init__.py" in names
    assert not any("__pycache__" in name for name in names)
    assert not any(name.endswith("/empty") for name in names)


def test_the_release_caps_live_model_calls_and_documents_it():
    variables = (ROOT / "infra" / "amazon" / "variables.tf").read_text()
    assert 'variable "daily_model_calls" {\n  type    = number\n  default = 40\n}' in variables
    readme = (ROOT / "README.md").read_text()
    row = next(line for line in readme.splitlines() if line.startswith("| `LOGIOPS_DAILY_MODEL_CALLS` |"))
    assert row.endswith("| `150`; the AWS deployment sets `40` |")
    assert "DEFAULT_DAILY_CALLS = 150" in (ROOT / "logiops" / "budget.py").read_text()
    assert "daily budget of 40 model calls" in readme and "mcp-apps-web-host" in readme

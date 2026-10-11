"""The demo user script sets a permanent password and keeps it out of the output."""

import json
import stat

import boto3
from botocore.stub import ANY, Stubber

from scripts.create_demo_user import create, new_password


def test_the_password_is_strong_and_random():
    first, second = new_password(), new_password()
    assert first != second and len(first) == 24
    assert any(c.islower() for c in first) and any(c.isupper() for c in first) and any(c.isdigit() for c in first)


def test_the_user_is_created_once_and_the_secret_file_is_private(tmp_path, capsys):
    client = boto3.client("cognito-idp", region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing")
    stubber = Stubber(client)
    stubber.add_client_error("admin_create_user", service_error_code="UsernameExistsException", http_status_code=400)
    stubber.add_response("admin_set_user_password", {},
                         {"UserPoolId": "us-east-1_Demo123", "Username": "judge", "Password": ANY, "Permanent": True})
    with stubber:
        path = create(client, "us-east-1_Demo123", "judge", root=tmp_path)
    saved = json.loads(path.read_text())
    assert saved["username"] == "judge" and len(saved["password"]) == 24
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert saved["password"] not in capsys.readouterr().out

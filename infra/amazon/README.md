# Amazon demo deployment

This is a **single-operator synthetic demo** in `us-east-1`. Terraform creates
an EC2 `t3.small`, a separate encrypted EBS data volume for SQLite, an IAM
instance profile, a private S3 release bucket, and two CloudFront
distributions on the same origin. The first provides the stable HTTPS URL; the
second is only the MCP Apps sandbox origin (`sandbox_domain` output, passed to
the app as `LOGIOPS_SANDBOX_HOST`), where the app serves
`/mcp-app/sandbox.html` and nothing else. It forwards to the EC2 origin over
HTTP; the instance security group accepts port 8000 only from AWS's
CloudFront origin-facing prefix list. The API requires a bearer token.

## Before provisioning

Tools on the operator's machine: Terraform 1.6+, Python 3.12+, `uv`, and the
AWS CLI v2 (the deploy and token scripts call it). The application itself
uses boto3 and does not need the CLI.

1. Sign in with `aws login --region us-east-1` and confirm
   `aws sts get-caller-identity --region us-east-1` succeeds. Confirm Bedrock
   access to `global.anthropic.claude-sonnet-4-6` with
   `bash scripts/test_bedrock.sh`.
2. Review expected charges in AWS Pricing Calculator and the existing budget
   alerts. EC2, EBS, and public IPv4 have ongoing hourly/monthly charges;
   CloudFront, S3, and Bedrock add usage charges.
3. Run `terraform -chdir=infra/amazon init` (the provider lock file is
   committed), then
   `terraform -chdir=infra/amazon plan -out=demo.tfplan` and inspect every
   resource. Apply with `terraform -chdir=infra/amazon apply demo.tfplan`.
   Terraform state and plan files are gitignored; keep a secure backup of
   state because it tracks the data volume.
4. Run `python3 scripts/create_access_token.py`. The 64-character random token
   is stored as an SSM `SecureString` and in `.secrets/access-token` (mode
   0600, gitignored). Do not paste it into a PR or issue.
5. On a clean, up-to-date `main`, run `python3 scripts/deploy_ec2.py` (it refuses any other checkout unless you pass `--allow-unmerged`). It builds a deterministic archive of
   the Python package and lockfile, uploads it to private S3, and installs it
   through Systems Manager. No GitHub or SSH credentials enter the instance.

The first deployment starts Uvicorn after the EBS volume is mounted. The
browser demo is at `https://<cloudfront-domain>/demo`; use the local
`.secrets/access-token` in its access-token field. The web assets are bundled
in the same release archive as the API, so the deployed UI and backend share
one version. The instance uses its role's temporary credentials for Bedrock
Converse; no static AWS key is stored on disk. The SSM command fetches the bearer token
into `/etc/logiops.env` with mode 0640. The data file is
`/var/lib/logiops/logiops.sqlite3` on the separate volume.

## Polly, AgentCore Memory and Cognito

The app's voice, memory and sign-in need four more pieces, all in this
directory:
- `memory.tf`: the AgentCore Memory `logiops_ai_memory` (events kept 30 days)
  with a USER_PREFERENCE strategy in `/users/{actorId}/preferences` and a
  SEMANTIC one in `/users/{actorId}/facts`.
- `identity.tf`: the Cognito user pool `logiops-ai-operators`. It has
  self-registration off, the managed login (v2) domain `logiops-ai-<hash>`, a
  resource server `https://<cloudfront>/mcp` with the scopes
  `incidents.operate` and `bookings.write`, and the public PKCE client
  `demo-web` (no secret). Its callbacks are `/demo`, `http://localhost:8000/demo`
  and MCP Inspector's.
- `config.tf`: the app settings as SSM parameters under `/logiops-ai/config/`
  (issuer, domain, client id, memory id, daily model calls).
- `main.tf`: the instance role gains `polly:SynthesizeSpeech`, the memory's
  event and record actions on that one memory ARN, and
  `ssm:GetParametersByPath` on the config path.

`logiops-deploy` copies only the allowed `LOGIOPS_*` settings whose values
match `^[A-Za-z0-9:/._-]+$` into `/etc/logiops.env`. The instance ignores
`user_data` changes, so the new deploy script needs a replaced instance. The
data stays on the EBS volume.

```sh
aws login --region us-east-1
terraform -chdir=infra/amazon plan -out=phase2.tfplan        # review it
terraform -chdir=infra/amazon apply phase2.tfplan
terraform -chdir=infra/amazon apply -replace=aws_instance.app
uv run python scripts/create_demo_user.py                    # writes .secrets/demo-user, prints no password
python3 scripts/deploy_ec2.py
```

Changing a setting later, such as `LOGIOPS_DAILY_MODEL_CALLS`, is a Terraform
variable or SSM change plus a redeploy. It needs no new instance.

Costs at demo scale:
- Cognito Essentials includes 10,000 monthly active users.
- Polly's generative voice is about US$30 per million characters, and the app
  caches every line and caps characters per day.
- AgentCore Memory bills events stored, records extracted and retrievals,
  which come to cents for a demo.

## Verify G3 and G4

```sh
export LOGIOPS_ACCESS_TOKEN="$(cat .secrets/access-token)"
MCP_URL="$(terraform -chdir=infra/amazon output -raw mcp_url)"
uv run python scripts/check_mcp.py "$MCP_URL"
BASE_URL="https://$(terraform -chdir=infra/amazon output -raw cloudfront_domain)"
uv run python scripts/verify_remote.py "$BASE_URL"
```

`check_mcp.py` must negotiate protocol 2025-11-25 and call `get_shipment` and
`list_incidents` (four incidents) from a machine outside EC2.
`verify_remote.py` resets every incident and the saved preferences, checks
the inbox, runs real Bedrock on SHIP-421, approves and executes the split
plan, and checks idempotence and the audit trace. It leaves SHIP-421
executed, so reset it afterwards. Restart EC2 through AWS, then repeat
`GET /incidents/SHIP-421` with the token; the execution and trace must still
be present. Record the URL, deployed archive checksum, token usage, and test
result in the decisions log.

The demo has four incidents and one shared preference profile. Before each
presentation, use "↺ Reset all incidents and preferences" (`POST /demo/reset`).
The EBS data volume has Terraform `prevent_destroy`; take a snapshot before
any intentional removal or replacement. Rotating the SSM token requires
`python3 scripts/create_access_token.py --rotate` followed by another
`python3 scripts/deploy_ec2.py` so the instance reloads it.

A release that raises the database schema migrates `/var/lib/logiops/logiops.sqlite3`
once on start and logs it (`journalctl -u logiops | grep -i schema`). An older
release cannot run on the migrated file. To roll back across a schema change,
open a Session Manager shell and run:

```sh
sudo systemctl stop logiops
sudo rm -f /var/lib/logiops/logiops.sqlite3 /var/lib/logiops/logiops.sqlite3-wal /var/lib/logiops/logiops.sqlite3-shm
sudo ln -sfn /opt/logiops/releases/<previous digest> /opt/logiops/current
sudo systemctl start logiops
```

The previous release reseeds its incidents; saved preferences are lost. Deploy
again from `main` once the fix is merged.

## Access and operational notes

- Systems Manager Session Manager provides shell access without SSH ingress.
- `systemctl status logiops` and `journalctl -u logiops` show service health.
- Public without a token: `/healthz`, `/demo`, `/assets/*`,
  `/mcp-app/sandbox.html`, `/docs`, `/openapi.json`, and `/redoc`. Every other
  route (incidents, agent, operator preferences, demo controls and MCP)
  requires the bearer token.
- The CloudFront origin read timeout is 60 seconds, the default quota, so no
  increase is needed. The agent stops after 50 seconds and returns an error
  instead of letting CloudFront cut the request.
- CloudFront uses a custom cache policy that forwards `Authorization` on every
  method. The managed `CachingDisabled` policy would drop it on GET requests,
  so the UI and `verify_remote.py` would get 401s. Nothing is cached: the app
  answers with `Cache-Control: no-store`.
- CloudFront also forwards `CloudFront-Viewer-Address`, and the instance runs
  with `LOGIOPS_TRUST_CLOUDFRONT=1`, so rate limits apply per viewer rather
  than per edge server.
- The instance ignores AMI and user-data drift, so routine plans do not
  replace it. To roll out a new Amazon Linux image or a changed
  `bootstrap.sh.tftpl`, run `terraform -chdir=infra/amazon apply
  -replace=aws_instance.app`, then `python3 scripts/deploy_ec2.py` again. The
  data volume is detached only after the instance stops, and SQLite survives.
- `terraform destroy` is blocked by design: the EBS volume has
  `prevent_destroy`, and the versioned release bucket is not force-destroyed.
  See "Teardown" below.
- The CloudFront default domain is the public URL. The connection from
  CloudFront to EC2 uses HTTP, restricted to CloudFront's origin-facing IP
  ranges. A later custom domain and origin certificate can add TLS on that
  hop.

## Teardown

Run this after judging ends. It deletes the demo and its data, so nothing keeps
billing. Use a local branch: the change to `main.tf` is never merged.

```sh
cd infra/amazon
REGION=$(terraform output -raw aws_region)
BUCKET=$(terraform output -raw release_bucket)
TOKEN_PARAM=$(terraform output -raw access_token_parameter_name)

# 1. Optional: keep a snapshot of the SQLite volume (it is billed until you delete it).
VOLUME=$(terraform state show -no-color aws_ebs_volume.data | awk '$1 == "id" {gsub(/"/, "", $3); print $3}')
aws ec2 create-snapshot --region "$REGION" --volume-id "$VOLUME" --description "logiops-ai demo data"

# 2. Allow the volume to be destroyed: delete the line `lifecycle { prevent_destroy = true }`
#    from aws_ebs_volume.data in main.tf.

# 3. Empty the versioned release bucket. Every object version and delete marker must go;
#    repeat while the listing is not empty, since each call deletes up to 1,000.
aws s3api list-object-versions --bucket "$BUCKET" --output json \
  --query '{Objects: [Versions, DeleteMarkers][][].{Key: Key, VersionId: VersionId}}' > /tmp/versions.json
aws s3api delete-objects --bucket "$BUCKET" --delete file:///tmp/versions.json

# 4. Destroy everything Terraform created, then the token it did not create.
terraform destroy
aws ssm delete-parameter --region "$REGION" --name "$TOKEN_PARAM"
```

CloudFront takes several minutes to disable and delete the two distributions.
Afterwards, check the Billing console for anything left, such as the snapshot
from step 1.


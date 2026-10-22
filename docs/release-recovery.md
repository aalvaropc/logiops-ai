# Release and SQLite recovery

This change prepares recovery controls. Applying Terraform and installing the
rendered host configuration are separate release steps; neither happens in CI.
The CloudFront origin transport remains a separate, deferred change.

## Review before the coordinated release

Merge the security, dependency, host, and demo fixes to `main`. Run the backend,
Chromium, dependency-audit, vendor, and Terraform checks on the resulting commit.
Use a clean checkout for `python scripts/deploy_ec2.py --package-only`; retain the
printed commit, archive SHA-256, and sidecar manifest. Repeating this build from
the same commit must produce the same archive hash.

Review `terraform plan` before applying it. The recovery addition creates a
private encrypted S3 bucket, seven-day snapshot expiration, version cleanup,
TLS-only bucket policy, and an instance-role policy limited to snapshot reads,
writes, and aborting an unfinished upload. S3 expires current snapshots after
seven days, which leaves a delete marker over the old version; that version is
removed seven days later and the then-empty delete marker is removed by its own
lifecycle rule, so a snapshot is recoverable for about fourteen days. It must
not replace the instance, EBS volume, identity pool, or either CloudFront
distribution.

## Install on an existing instance after the approved apply

The existing instance ignores `user_data` changes. Updating Terraform alone does
not install the timer or deployment hook. Generate a reviewable SSM payload:

```sh
python scripts/install_recovery.py --output /tmp/logiops-recovery-ssm.json
```

Inspect that file, then send it to the Terraform `instance_id` with the
`AWS-RunShellScript` document using `aws ssm send-command --parameters
file:///tmp/logiops-recovery-ssm.json`. Use the configured region and inspect the
command result. This installs the same recovery and deployment scripts used by
a new instance; it does not restart the running application.

Run `/usr/local/sbin/logiops-backup predeploy` through SSM and retain its S3 URI,
checksum, and successful restore result before deploying the reviewed archive.
The deployment hook repeats this check before changing the release symlink,
trying up to three times ten seconds apart. If it still fails, the deployment
stops with the reason and the release is unchanged; so does a host without the
hook, and `deploy_ec2.py` refuses to start in that case. There is no bypass:
repair the backup and retry. Installation checks for `logiops-reset.service`
before modifying the host and fails visibly if it is missing.

## Recovery behavior

The online SQLite backup API includes committed WAL data without copying live
database files. Every backup passes integrity checks, uploads with AES256 server
encryption, downloads to a temporary directory, compares bytes, and restores
into a second temporary database for verification. Temporary files use mode
0600 and are removed after the operation. A daily timer runs at 07:45 UTC;
inspect `journalctl -u logiops-backup.service` and the S3 object timestamps.

For an actual recovery, pause the reset timer, stop `logiops.service`, download
the chosen snapshot to a temporary file, and run `sqlite_backup.py verify`.
Preserve the failed database and its WAL/SHM files together before replacing
them. Restore the verified snapshot as `/var/lib/logiops/logiops.sqlite3`, owned
by `logiops:logiops`, mode 0600, with no stale WAL/SHM files at that path. Point
`/opt/logiops/current` at the matching known-good release, start the service, and
check health, incident reads, approvals, and idempotent execution in replay
before resuming normal operation. A live restore requires a separate approval.

## Recordings and verification

The instance timer is the only scheduled demo reset. GitHub's reset is manual.
Before recording, run `touch /etc/logiops-reset-paused` through SSM. The reset
unit checks the marker through `logiops-reset-gate` and skips while the marker
is younger than 30 hours. The marker's expiry does not schedule a reset:
the next daily run at 08:11 UTC performs it. A pause can therefore skip two
daily runs, and the next reset can occur almost 54 hours after the marker was
created. Touch the marker again to extend it, and remove it after recording.
Keep the timer active while recording. The skipped run is in
`journalctl -u logiops-reset.service` ("Reset skipped"). The timer uses
`Persistent=false`, so it does not replay a missed reset.

`scripts/verify_remote.py` spends one live investigation and a short speech call.
Run it deliberately after release, never on a schedule. It attempts memory
cleanup and a demo reset even when a verification step fails. Scheduled CI runs
use isolated replay containers and do not call paid model or speech services.

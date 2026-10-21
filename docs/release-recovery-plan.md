# Recovery plan review — 2026-10-21

The read-only plan was generated from the deployed local state copied to a
private temporary file, using Terraform 1.15.1 and the locked AWS provider
6.67.0. Existing notification input was preserved. The configuration reviewed
was commit `d22d656` on `chore/release-recovery`.

The result is **7 creates, 0 updates, 0 replacements, 0 deletes**:

| Resource | Action |
| --- | --- |
| `aws_s3_bucket.backups` | create |
| `aws_s3_bucket_public_access_block.backups` | create |
| `aws_s3_bucket_server_side_encryption_configuration.backups` | create |
| `aws_s3_bucket_versioning.backups` | create |
| `aws_s3_bucket_lifecycle_configuration.backups` | create |
| `aws_s3_bucket_policy.backups` | create |
| `aws_iam_role_policy.backups` | create |

The binary plan and full JSON stay outside Git because they contain state and
configuration details. No plan was applied. Re-plan at the coordinated release
if the deployment or configuration changes. Installation on the existing host
is still required after an approved apply because it ignores user-data changes.

Validation passed: Terraform formatting and schema checks, rendered shell
syntax and ShellCheck, a consistent backup while WAL contains committed and
uncommitted writes, temporary restoration, failed-backup preservation, cleanup
after verification failures, and repeatable archive metadata.

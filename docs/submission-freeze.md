# Submission freeze

The freeze starts on 2026-10-23 at 12:00 Pacific time (19:00 UTC) and lasts
through the winner announcement on 2026-12-03, as recorded in D-AMZ-22.
Finish the reviewed merges, deployment, video and submission materials before
the deadline. Keeping the demo available through November 20 is a separate
operational requirement and does not end the freeze.

## Before the deadline

Merge this configuration with the final reviewed changes. Every Dependabot
ecosystem has `open-pull-requests-limit: 0` and `rebase-strategy: disabled`.
These settings pause version-update PRs and automatic rebases after the merge.
Close any remaining Dependabot PRs before the deadline: existing PRs can still
be updated even after the rebase setting changes.

Security-update PRs have a separate limit and require a repository setting.
After the last merge, disable automatic security fixes for this repository:

```sh
gh api --method DELETE repos/aalvaropc/logiops-ai/automated-security-fixes
gh api --include repos/aalvaropc/logiops-ai/automated-security-fixes
gh api --include repos/aalvaropc/logiops-ai/vulnerability-alerts
```

The setting change returns HTTP 204; its status check returns HTTP 404 when
disabled. The vulnerability-alerts check must return HTTP 204. A 403 is a
permission error, not confirmation of the intended state. Check the repository
security settings in GitHub if a status is ambiguous. Keep Dependabot alerts,
secret scanning, scheduled dependency audits and uptime monitoring enabled.
Investigate failures and record findings without changing frozen source or
materials. Do not enable auto-merge during the freeze.

The configuration does not execute the repository-setting commands. Record
their results and the final main SHA in the private release checklist before
the deadline. Repository settings and alert visibility should be verified with
an administrator account.

## After the winner announcement

Restore the previous version-update limits (5 for GitHub Actions and uv, and
the default 5 for Docker), remove `rebase-strategy: disabled`, and enable
automatic security fixes again:

```sh
gh api --method PUT repos/aalvaropc/logiops-ai/automated-security-fixes
gh api --include repos/aalvaropc/logiops-ai/automated-security-fixes
```

The setting change returns HTTP 204; its check must return HTTP 200 with
`enabled: true` and `paused: false`. Review the accumulated security alerts
before resuming regular releases. Do not resume automatically on November 20.

References: [Dependabot options](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)
and [repository security settings API](https://docs.github.com/en/rest/repos/repos#disable-dependabot-security-updates).

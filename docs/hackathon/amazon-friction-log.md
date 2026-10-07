# Friction log — Amazon / AWS

Format per entry: date, technology, task, steps, expected vs actual, severity,
workaround, suggestion. Real friction only, logged as it happens (rules 3.17).

## 2026-10-02 — Bedrock model access UX

- **Technology:** Amazon Bedrock console.
- **Task:** enable access to a Claude model to test in the Playground.
- **Steps:** opened Model catalog, searched Anthropic, opened Claude Sonnet 5.5.
- **Expected:** either immediate access or a clear use-case form.
- **Actual:** `AccessDeniedException: anthropic.claude-sonnet-5-5 is not
  available for this account`, pointing to AWS Sales with no self-service
  option. Switched to Claude Sonnet 4.6, which showed the expected use-case
  form and granted access right after submitting it.
- **Severity:** low (workaround existed) but confusing — no indication of
  *why* one model self-serves and the newer one doesn't.
- **Workaround:** used Claude Sonnet 4.6 instead.
- **Suggestion:** surface *why* a model needs AWS Sales contact instead of a
  generic AccessDenied message.

## 2026-10-02 — Billing console region selector

- **Technology:** AWS Billing / Budgets console.
- **Task:** switch region to `us-east-1` before setting up Bedrock.
- **Steps:** opened the region selector from the Billing console.
- **Expected:** switch region normally.
- **Actual:** every region showed a lock icon and a note "There are 17 Regions
  that are not enabled for this account" — because Billing is a global
  service and doesn't support region switching at all. Not obvious to someone
  new to AWS.
- **Severity:** low, cost a few minutes of confusion.
- **Workaround:** navigated to a regional service (Bedrock) first, then used
  its own region selector.
- **Suggestion:** region selector could explain *why* it's locked on global
  services instead of just showing lock icons.

## 2026-10-02 — AWS Budgets email verification

- **Technology:** AWS Budgets.
- **Task:** create two budget alerts ($50, $100) with email notifications.
- **Actual:** AWS Budgets requires verifying the recipient email via a link
  before notifications actually send, via a banner easy to miss.
- **Severity:** low.
- **Workaround:** checked inbox/spam for the verification email.
- **Suggestion:** block alert creation until verification completes, instead
  of a dismissible banner.

## 2026-10-05 — CloudFront drops Authorization on GET with CachingDisabled

- **Technology:** Amazon CloudFront cache and origin request policies.
- **Task:** put a bearer-token API behind CloudFront without caching it.
- **Expected:** the managed `CachingDisabled` + `AllViewer` policies forward
  every viewer header, including `Authorization`.
- **Actual (found in configuration review, before deployment):**
  `Authorization` cannot be added to an origin request policy, and
  `CachingDisabled` cannot include headers in the cache key, so GET requests
  would reach the origin without the token. POST requests are unaffected,
  which makes the failure easy to miss in a quick test.
- **Severity:** high for any token-protected API; every read would fail.
- **Workaround:** a custom cache policy that whitelists `Authorization` with
  `max_ttl = 1`, plus `Cache-Control: no-store` from the app.
- **Suggestion:** document this combination on the `CachingDisabled` policy
  page, or offer a managed "forward Authorization, never cache" policy.

## 2026-10-05 — CloudFront origin timeout above the default quota

- **Technology:** Amazon CloudFront, Service Quotas.
- **Task:** allow slow LLM responses through CloudFront.
- **Actual:** `origin_read_timeout` above 60 s is accepted by `terraform plan`
  but needs a quota increase before `apply` succeeds.
- **Severity:** medium; it only fails at apply time.
- **Workaround:** keep 60 s and enforce a 50 s deadline in the agent.
- **Suggestion:** surface the quota limit in plan-time validation.

## 2026-10-05 — `aws login` session expired between work sessions

- **Technology:** AWS CLI `aws login`.
- **Task:** resume work the next day.
- **Actual:** every call failed with "Your session has expired. Please
  reauthenticate using 'aws login'." Re-login needs a browser, so it cannot
  be done from a headless agent session.
- **Severity:** low, but it blocks automation until a person signs in again.
- **Workaround:** run `aws login` interactively before deployment work.

## 2026-10-06 — boto3 cannot use an `aws login` session without the CRT extra

- **Technology:** boto3 / botocore with the AWS CLI `aws login` credentials.
- **Task:** call Bedrock Converse from Python with the same session the CLI uses.
- **Expected:** boto3 finds the CLI login session like any other credentials.
- **Actual:** `MissingDependencyException: Using the login credential provider
  requires an additional dependency ... pip install "botocore[crt]"`. The CLI
  worked in the same shell, so the failure looks like a credentials problem.
- **Severity:** medium; local live runs fail until the extra is installed.
- **Workaround:** depend on `boto3[crt]`.
- **Suggestion:** ship the login credential provider without an optional
  extra, or mention it in the `aws login` documentation.

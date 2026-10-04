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

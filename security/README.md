# Dependency audit

`python scripts/audit_dependencies.py` audits production requirements exported
from the frozen `uv.lock` with pip-audit 2.10.1. Scanner errors fail the check.
The current exception list is empty.

An exception must name one package, exact version, advisory ID, reason, advisory
URL, and expiration date (`YYYY-MM-DD`). It expires at the beginning of that
date. Aliases may match the advisory ID; the exception never covers another
package or version. Expired entries fail CI even after the dependency changes.

Actions and build/scanner images use immutable references. Dependabot proposes
weekly updates for Actions, uv dependencies, and Docker images. CI validates
workflows and Terraform without applying infrastructure. The daily CI run uses
fresh replay containers and synthetic data; it does not call paid services.

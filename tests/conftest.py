"""Keep the test run independent of the developer's shell.

Test modules import logiops.api at collection time, and create_app() reads
these variables, so they must be removed before any test module is imported;
a fixture would run too late.
"""

import os

for name in list(os.environ):
    if name.startswith(("LOGIOPS_", "BEDROCK_")):
        del os.environ[name]

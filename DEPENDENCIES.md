# Runtime dependency inventory

Audit snapshot: 2026-08-15 on Windows/Python 3.14. Direct version ranges are
declared in `pyproject.toml`; resolved versions below are what those ranges
resolve to on that platform.
All are runtime dependencies. None is bundled in the source distribution or
wheel. Frozen-executable bundling remains deferred behind the focused LGPL
review.

| Package | Resolved | Direct | License | Source |
|---|---:|:---:|---|---|
| paramiko | 5.0.0 | yes | LGPL-2.1 | https://github.com/paramiko/paramiko |
| starlette | 1.6.0 | yes | BSD-3-Clause | https://github.com/Kludex/starlette |
| uvicorn | 0.52.3 | yes | BSD-3-Clause | https://github.com/encode/uvicorn |
| anyio | 4.14.2 | no | MIT | https://github.com/agronholm/anyio |
| bcrypt | 5.0.0 | no | Apache-2.0 | https://github.com/pyca/bcrypt |
| cffi | 2.1.1 | no | MIT-0 | https://github.com/python-cffi/cffi |
| click | 8.4.2 | no | BSD-3-Clause | https://github.com/pallets/click |
| colorama | 0.4.6 | no | BSD-3-Clause | https://github.com/tartley/colorama |
| cryptography | 50.0.0 | yes | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| h11 | 0.16.0 | no | MIT | https://github.com/python-hyper/h11 |
| idna | 3.18 | no | BSD-3-Clause | https://github.com/kjd/idna |
| invoke | 3.0.3 | no | BSD-2-Clause | https://github.com/pyinvoke/invoke |
| pycparser | 3.0 | no | BSD-3-Clause | https://github.com/eliben/pycparser |
| PyNaCl | 1.6.2 | no | Apache-2.0 | https://github.com/pyca/pynacl |

Development-only dependency: pytest `>=8,<10` (MIT). Build-only dependency:
setuptools `>=77` (MIT). Re-run and review this inventory whenever dependency
ranges or resolved artifacts change.

CI installs this closure as pip constraints on the audited platform - rendered
from `dependency-inventory.json` by `tools/write_constraints.py`, so the
inventory stays the single source of truth. A release upstream therefore no
longer changes what that job resolves: `tools/check_dependency_inventory.py`
fails when the closure changes shape and a licence needs reviewing, and a
constrained install fails outright when a package can no longer be resolved
alongside the reviewed set. Bumping a version is a deliberate edit here. The
other CI jobs install unconstrained on purpose - the oldest supported Python
proves the declared ranges still resolve, and the experimental job is where a
breaking upstream release shows up first.

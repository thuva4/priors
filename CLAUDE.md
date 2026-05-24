<!-- BEGIN priors -->
## Personal AI priors (auto-generated, do not edit)
Last synced: 2026-05-24

- **.env copied to .env.example with manual redaction**: .env.example must be hand-written or schema-generated, never derived from a real .env [2026-05-24]
- **@Transactional method doing HTTP I/O** (java, spring): no network I/O inside @Transactional boundaries — extract calls out before commit [2026-05-24]
- **time.time() used for elapsed duration** (python): use time.monotonic() for any elapsed-time measurement; time.time() is wall-clock and can jump [2026-05-24]
- **Reaching for pip (pip install, python -m pip, pip-based venv setup) in a Python project**: In Python projects, always use uv; never use pip directly [2026-05-24]
- **mock DB hid migration bug in prod** (python, postgres): integration tests must hit a real database, never mocks [2026-05-24]
- **async function called inside Array.forEach** (node, typescript): never call an async function inside .forEach — use for...of or Promise.all [2026-05-24]
<!-- END priors -->

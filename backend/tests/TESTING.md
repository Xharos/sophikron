# Backend verification

Run commands from `backend/` using the project's configured Python interpreter.
Install development dependencies with `python -m pip install -e ".[dev]"`.

## Suites

- `unit/<domain>`: isolated business rules, validation and mocked boundary adapters.
- `integration/<domain>`: real PostgreSQL repositories, migrations and ASGI routes.
- `e2e/`: real TCP journeys against the disposable running API, without frontend changes.
- `perf/`: measured regression budgets with correctness assertions.
- `support/`: reusable fixtures and synthetic data helpers; never imported from test modules.

Fast feedback: `python -m pytest tests/unit -q`.

Full isolated verification: `python run_tests.py`. This reuses the project's existing
Compose configuration and removes only its uniquely named disposable resources.
It includes integration, E2E and performance tests; no persistent installation is accepted.

Select suites through the runner, for example `python run_tests.py -m integration`
or `python run_tests.py -m perf`. E2E bootstrap journeys must run before integration
fixtures remove the startup account; run them on a fresh runner installation.

## Coverage and CI commands

The workflow outside `backend/` is deliberately unchanged. Its existing test commands
still discover the nested suites. Proposed additional CI steps are:

```sh
python -m tests.verify
python -m tests.function_inventory --strict
ruff check .
```

Reports live in `backend/reports/`, ignored locally. `functions.json` enumerates every
module function and class method authored in `app/` and `run_tests.py`, including private
methods. Protocol declarations containing only `...` have no implementation to exercise
and are not counted. It lists test execution contexts in the first body statement. Nested helpers
remain visible in line/branch coverage. This is execution evidence, not proof that an
assertion verifies every behavior. Review test assertions and uncovered branches too.
An unobserved method remains a gap; do not hide it with exclusions or fabricate a test
that merely calls it. The strict audit fails until every enumerated callable is observed.
The verification wrapper collects coverage in memory before exporting HTML and compressed
JSON (`reports/coverage.json.gz`),
avoiding SQLite corruption when the workspace is on a network drive.
For independently executed additional tests, the inventory accepts
`--supplement reports/coverage-additional.json` to union their test contexts with the
main report. This does not change the main report's line/branch coverage percentage.

Performance tests record measurements in JUnit output (`--junitxml=reports/perf.xml`).
The report uses xUnit 1, which supports the per-case custom measurement properties.
Budgets are broad regression ceilings, not production latency commitments. Search covers
2,000 and 10,000 identities, including an encrypted PostgreSQL benchmark with three callers.
Pure ranking, annual occurrence expansion and timezone windows have separate budgets.
Real small-model CP-SAT generation verifies exact quotas within its runtime budget.
Document reception measures digest correctness, elapsed time and Python allocation peaks
for 1 MiB and 16 MiB uploads; this is not a measurement of total process RSS.
Run heavier measurements separately on a stable worker before tightening thresholds.

When a behavior test exposes an application defect, retain the failure and report it.
Do not change application code, mark the test xfail, or weaken its expectations to pass.

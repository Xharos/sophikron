"""Run disposable verification with in-memory coverage, safe on network-mounted workspaces."""

import gzip
import shutil
from pathlib import Path

from coverage import Coverage

from tests.function_inventory import main as audit_functions


def main() -> int:
    """Run all selected tests and export portable coverage reports even after test failures.

    Returns
    -------
    int
        The test runner's status, without suppressing failed application expectations.
    """
    coverage = Coverage(data_file=None)
    coverage.start()
    try:
        import run_tests

        result = run_tests.main()
    finally:
        coverage.stop()
        coverage.json_report()
        report = Path("reports/coverage.json")
        with report.open("rb") as source, gzip.open(report.with_suffix(".json.gz"), "wb") as target:
            shutil.copyfileobj(source, target)
        report.unlink()
        coverage.html_report()
        coverage.report()
    audit_result = audit_functions(["--strict"])
    return result or audit_result


if __name__ == "__main__":
    raise SystemExit(main())

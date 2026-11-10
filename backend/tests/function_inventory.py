"""Report authored callables without observed test execution using coverage contexts."""

import argparse
import ast
import gzip
import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def callables(tree: ast.AST, prefix: str = "") -> list[tuple[str, int, int]]:
    """Enumerate module functions and class methods using their first body statement.

    Parameters
    ----------
    tree
        Parsed module or class.
    prefix
        Enclosing class qualification.

    Returns
    -------
    list
        Qualified names and executable body lines; generated methods are excluded.
    """
    result = []
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.ClassDef):
            result.extend(callables(node, prefix + node.name + "."))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body = body[1:]
            if body and not (
                len(body) == 1
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and body[0].value.value is Ellipsis
            ):
                result.append((prefix + node.name, body[0].lineno, body[0].end_lineno))
    return result


def main(arguments: list[str] | None = None) -> int:
    """Write the callable inventory and optionally fail when any callable lacks test context.

    Parameters
    ----------
    arguments
        Optional CLI arguments; otherwise use the process arguments.

    Returns
    -------
    int
        Nonzero for a strict audit with unobserved callables.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--supplement", action="append", default=[])
    options = parser.parse_args(arguments)
    with gzip.open(BACKEND / "reports" / "coverage.json.gz", "rt", encoding="utf-8") as source:
        report = json.load(source)
    files = {name.replace("\\", "/"): facts for name, facts in report["files"].items()}
    for supplement in options.supplement:
        extra = json.loads(Path(supplement).read_text(encoding="utf-8"))
        for name, facts in extra["files"].items():
            contexts = files.setdefault(name.replace("\\", "/"), {}).setdefault("contexts", {})
            for line, values in facts.get("contexts", {}).items():
                contexts[line] = sorted(set(contexts.get(line, [])) | set(values))
    rows = []
    for path in sorted([*(BACKEND / "app").rglob("*.py"), BACKEND / "run_tests.py"]):
        facts = files.get(path.relative_to(BACKEND).as_posix(), {})
        contexts = {int(line): values for line, values in facts.get("contexts", {}).items()}
        for name, line, end_line in callables(ast.parse(path.read_text(encoding="utf-8"))):
            tests = sorted(
                {
                    c
                    for number in range(line, end_line + 1)
                    for c in contexts.get(number, [])
                    if "test_" in c
                }
            )
            rows.append(
                {
                    "file": str(path.relative_to(BACKEND)),
                    "name": name,
                    "line": line,
                    "test_contexts": tests,
                }
            )
    missing = [row for row in rows if not row["test_contexts"]]
    output = BACKEND / "reports" / "functions.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(
        json.dumps({"total": len(rows), "unobserved": len(missing), "functions": rows}, indent=2),
        encoding="utf-8",
    )
    print(f"{len(rows)} authored callables; {len(missing)} without observed test context: {output}")
    return int(options.strict and bool(missing))


if __name__ == "__main__":
    raise SystemExit(main())

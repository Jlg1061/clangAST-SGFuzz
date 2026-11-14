#!/usr/bin/env python3
"""Derive a pass/fail table from one regression-controls experiment index."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
EXPECTED = PROJECT / "experiments" / "regression-controls.json"
STATE_LINE = re.compile(r"states: (?P<states>\d+) leaves: (?P<leaves>\d+)")


def read_metadata(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("target_callback_sites="):
            values["callback_sites"] = int(line.partition("=")[2])
        match = STATE_LINE.search(line)
        if match:
            values["states"] = int(match.group("states"))
            values["leaves"] = int(match.group("leaves"))
    required = {"callback_sites", "states", "leaves"}
    if set(values) != required:
        raise ValueError(f"Incomplete metadata in {path}: {values}")
    return values


def format_result(value: dict[str, int]) -> str:
    callbacks = value["callback_sites"]
    states = value["states"]
    leaves = value["leaves"]
    callback_label = "callback" if callbacks == 1 else "callbacks"
    state_label = "state" if states == 1 else "states"
    leaf_label = "leaf" if leaves == 1 else "leaves"
    return f"{callbacks} {callback_label}; {states} {state_label}, {leaves} {leaf_label}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-index", type=Path, required=True)
    args = parser.parse_args()

    index_path = args.experiment_index.resolve()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    expected_cases = {case["id"]: case for case in expected["cases"]}
    rows: list[dict[str, object]] = []
    all_passed = True

    for run in index["runs"]:
        case_id = run["case"]
        case = expected_cases[case_id]
        row: dict[str, object] = {"case": case_id, "role": case["role"]}
        for mode in ("regex", "ast"):
            raw_dir = PROJECT / run["raw_dir"] / ("original" if mode == "regex" else "ast")
            observed = read_metadata(raw_dir / "metadata.txt")
            wanted = case["expected"][mode]
            match = observed == wanted
            all_passed = all_passed and match
            row[mode] = {"expected": wanted, "observed": observed, "pass": match}
        rows.append(row)

    output_dir = PROJECT / "derived"
    output_dir.mkdir(exist_ok=True)
    stem = index_path.parent.name
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    summary = {
        "schema": "clangast-sgfuzz-regression-controls-result-v1",
        "experiment_index": str(index_path.relative_to(PROJECT)),
        "all_expected_outcomes_matched": all_passed,
        "rows": rows,
    }
    json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Regression-control results",
        "",
        f"Source index: `{index_path.relative_to(PROJECT)}`.",
        "",
        "All expected outcomes were recorded in `experiments/regression-controls.json` before this run.",
        "",
        "| Case | Role | Regex: expected / observed | AST: expected / observed | Result |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        regex = row["regex"]
        ast = row["ast"]
        regex_cell = f"{format_result(regex['expected'])} / {format_result(regex['observed'])}"
        ast_cell = f"{format_result(ast['expected'])} / {format_result(ast['observed'])}"
        status = "PASS" if regex["pass"] and ast["pass"] else "FAIL"
        lines.append(f"| `{row['case']}` | {row['role']} | {regex_cell} | {ast_cell} | **{status}** |")
    lines.extend(["", f"Overall: **{'PASS' if all_passed else 'FAIL'}**.", ""])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

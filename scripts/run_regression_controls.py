#!/usr/bin/env python3
"""Run all pre-registered regression controls and retain an experiment index."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
PLAN = PROJECT / "experiments" / "regression-controls.json"
RUNNER = PROJECT / "scripts" / "run_mechanism_comparison.sh"
DERIVER = PROJECT / "scripts" / "derive_regression_controls.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", help="Optional stable suffix for the output directory.")
    args = parser.parse_args()
    label = args.label or dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    experiment_dir = PROJECT / "raw" / f"regression-controls-{label}"
    if experiment_dir.exists():
        raise SystemExit(f"Refusing to overwrite existing experiment directory: {experiment_dir}")
    experiment_dir.mkdir(parents=True)

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    runs: list[dict[str, str]] = []
    for case in plan["cases"]:
        case_id = case["id"]
        command = ["bash", str(RUNNER), case_id]
        result = subprocess.run(command, cwd=PROJECT, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=False)
        case_dir = experiment_dir / case_id
        case_dir.mkdir()
        (case_dir / "command.txt").write_text(" ".join(command) + "\n", encoding="utf-8")
        (case_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
        (case_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
        if result.returncode != 0:
            (experiment_dir / "index.json").write_text(json.dumps({
                "schema": "clangast-sgfuzz-regression-controls-index-v1",
                "plan": str(PLAN.relative_to(PROJECT)),
                "runs": runs,
                "failed_case": case_id,
                "returncode": result.returncode,
            }, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(f"{case_id} failed; retained output in {case_dir}")
        raw_line = next((line for line in result.stdout.splitlines()
                         if line.startswith("Raw evidence: ")), None)
        if raw_line is None:
            raise SystemExit(f"{case_id} succeeded without a raw-evidence path; see {case_dir}")
        raw_path = Path(raw_line.removeprefix("Raw evidence: ")).resolve()
        runs.append({"case": case_id, "raw_dir": str(raw_path.relative_to(PROJECT))})

    index_path = experiment_dir / "index.json"
    index_path.write_text(json.dumps({
        "schema": "clangast-sgfuzz-regression-controls-index-v1",
        "plan": str(PLAN.relative_to(PROJECT)),
        "runs": runs,
    }, indent=2) + "\n", encoding="utf-8")
    result = subprocess.run(["python3", str(DERIVER), "--experiment-index", str(index_path)],
                            cwd=PROJECT, text=True, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

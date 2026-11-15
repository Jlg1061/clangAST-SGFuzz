#!/usr/bin/env python3
"""Derive the Stage A feasibility table from a retained raw experiment index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-index", type=Path, required=True)
    args = parser.parse_args()
    index_path = args.experiment_index.resolve()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    rows = index["conditions"]
    if any(row["status"] != "ok" for row in rows):
        raise SystemExit("Cannot derive a failed Stage A run.")
    all_expected = all(row["observed"] == row["expected"] for row in rows)
    stem = index_path.parent.name
    result_path = PROJECT / "derived" / f"{stem}.json"
    markdown_path = PROJECT / "derived" / f"{stem}.md"
    result = {
        "schema": "clangast-sgfuzz-stage-a-feasibility-result-v1",
        "experiment_index": str(index_path.relative_to(PROJECT)),
        "all_pre_registered_outcomes_matched": all_expected,
        "conditions": rows,
        "interpretation": "This is an end-to-end copy-instrument-build-replay feasibility check with a fixed corpus and -runs=0. It is not a randomized fuzzing-performance comparison.",
    }
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Stage A — feasibility pilot",
        "",
        f"Raw index: `{index_path.relative_to(PROJECT)}`.",
        "",
        "The control and AST conditions compile the same 36-unit IXWebSocket library source list, use the same sanitizer flags, SGFuzz runtime, transport harness, four fixed inputs, and `-runs=0` replay budget. Only the AST condition rewrites a copied `IXWebSocketTransport.cpp`.",
        "",
        "| Condition | Callback sites: expected / observed | STT nodes: expected / observed | STT leaves: expected / observed | Build + replay |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        expected = row["expected"]
        observed = row["observed"]
        status = "PASS" if row["status"] == "ok" and expected == observed else "FAIL"
        lines.append(
            f"| `{row['id']}` | {expected['callback_sites']} / {observed['callback_sites']} | "
            f"{expected['states']} / {observed['states']} | {expected['leaves']} / "
            f"{observed['leaves']} | **{status}** |")
    lines.extend([
        "",
        f"Overall: **{'PASS' if all_expected else 'FAIL'}**.",
        "",
        "`states` includes the STT root. A leaf is a distinct root-to-leaf transition sequence. The AST condition's non-root nodes and two leaves show that at least one inserted callback resolves to the SGFuzz runtime and executes under the fixed harness. This harness is designed around `setReadyState`; it does not establish execution of all five inserted sites, nor higher fuzzing throughput, coverage, or bug discovery.",
        "",
    ])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {result_path}")
    print(f"Wrote {markdown_path}")
    return 0 if all_expected else 1


if __name__ == "__main__":
    raise SystemExit(main())

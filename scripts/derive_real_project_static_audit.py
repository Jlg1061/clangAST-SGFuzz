#!/usr/bin/env python3
"""Derive a concise, traceable static-audit table from one raw audit index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


def compound_statement_parent_writes(manifest: dict) -> int:
    return sum(candidate.get("rewrite_safety", {}).get("standalone_statement", False)
               for candidate in manifest["candidate_transition_writes"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-index", type=Path, required=True)
    args = parser.parse_args()
    index_path = args.experiment_index.resolve()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for target in index["targets"]:
        if target.get("status") != "ok":
            raise SystemExit(f"Cannot derive an incomplete audit: {target['id']} is {target.get('status')}")
        manifest_path = PROJECT / target["manifest"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        summary = manifest["summary"]
        rows.append({
            "id": target["id"],
            "project": target["project"],
            "language": target["language"],
            "scope": target["scope"],
            "source_list": target["source_list"],
            "source_list_sha256": target["source_list_sha256"],
            "manifest": target["manifest"],
            "summary": summary,
            "compound_statement_parent_candidate_writes": compound_statement_parent_writes(manifest),
            "sum_translation_unit_elapsed_seconds": round(sum(
                item.get("elapsed_seconds", 0) for item in manifest["translation_units"]), 6),
        })
    stem = index_path.parent.name
    output_json = PROJECT / "derived" / f"{stem}.json"
    output_md = PROJECT / "derived" / f"{stem}.md"
    result = {
        "schema": "clangast-sgfuzz-real-project-static-audit-result-v1",
        "experiment_index": str(index_path.relative_to(PROJECT)),
        "elapsed_wall_seconds": index["elapsed_wall_seconds"],
        "rows": rows,
        "interpretation": "Counts are unique AST-derived declaration or source-write locations across the frozen translation-unit scope. They measure candidate discovery and parsing coverage only; they do not establish semantic state-variable precision/recall, instrumentation buildability, fuzzing throughput, STT coverage, or bugs found.",
    }
    output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Real-project static audit",
        "",
        f"Raw index: `{index_path.relative_to(PROJECT)}`.",
        "",
        "Each row uses a frozen translation-unit list and a pinned checkout. H2O uses the fresh CMake compilation database; IXWebSocket uses its recorded default-library flags. The tool only writes manifests outside target checkouts.",
        "",
        "| Scope | Lang. | TU parsed / frozen | Parse failures | Enum decls. | Enum storage | Candidate writes | CompoundStmt-parent writes |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        summary = row["summary"]
        lines.append(
            f"| `{row['id']}` | {row['language']} | "
            f"{summary['translation_units_parsed']} / {summary['translation_units_requested']} | "
            f"{summary['parse_failures']} | {summary['enum_declarations']} | "
            f"{summary['state_storage_declarations']} | {summary['candidate_transition_writes']} | "
            f"{row['compound_statement_parent_candidate_writes']} |")
    lines.extend([
        "",
        "A *candidate write* is an AST assignment whose lvalue resolves to automatically selected project-local enum or `std::atomic<enum>` storage. A *CompoundStmt-parent write* additionally has a compound-statement AST parent. That is one conservative source-rewriter precondition, not a claim that the site is fully build-validated. Neither column claims that every candidate is a semantic protocol state; manual validation is a separate evaluation step.",
        "",
        f"Wall-clock audit time: {index['elapsed_wall_seconds']:.2f} s. The sum of per-translation-unit elapsed times is larger because analyses run concurrently.",
        "",
    ])
    output_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {output_json}")
    print(f"Wrote {output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

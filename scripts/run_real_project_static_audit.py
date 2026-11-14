#!/usr/bin/env python3
"""Run the pre-registered, read-only static audit on the two real targets."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
PLAN = PROJECT / "experiments" / "real-project-static-audit.json"
ANALYSER = PROJECT / "src" / "sgfuzz_clang_ast_dry_run.py"
DERIVER = PROJECT / "scripts" / "derive_real_project_static_audit.py"
LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_capture(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=False)


def record_process(directory: Path, stem: str, command: list[str],
                   result: subprocess.CompletedProcess[str]) -> None:
    (directory / f"{stem}.command.txt").write_text(shlex.join(command) + "\n",
                                                     encoding="utf-8")
    (directory / f"{stem}.stdout.txt").write_text(result.stdout, encoding="utf-8")
    (directory / f"{stem}.stderr.txt").write_text(result.stderr, encoding="utf-8")


def git_metadata(checkout: Path) -> dict[str, Any]:
    revision = run_capture(["git", "rev-parse", "HEAD"], checkout)
    status = run_capture(["git", "status", "--short"], checkout)
    if revision.returncode or status.returncode:
        message = revision.stderr or status.stderr
        raise RuntimeError(f"Cannot inspect {checkout}: {message.strip()}")
    return {
        "commit": revision.stdout.strip(),
        "status_short": status.stdout.splitlines(),
        "working_tree_clean": not status.stdout.strip(),
    }


def read_sources(checkout: Path, source_root: Path, source_list: Path) -> list[Path]:
    values = [line.strip() for line in source_list.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(values) != len(set(values)):
        raise ValueError(f"Duplicate source in frozen list: {source_list}")
    sources = [(checkout / value).resolve() for value in values]
    missing = [str(path) for path in sources if not path.is_file()]
    outside = []
    for path in sources:
        try:
            path.relative_to(source_root)
        except ValueError:
            outside.append(str(path))
    if missing or outside:
        problems = missing + outside
        raise ValueError(f"Invalid frozen source list {source_list}: {problems[:3]}")
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", help="Stable suffix for raw/ and runs/ directories.")
    parser.add_argument("--jobs", type=int, help="Override the pre-registered AST worker count.")
    args = parser.parse_args()
    label = args.label or dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if not LABEL.fullmatch(label):
        raise SystemExit("--label may contain only letters, digits, dot, underscore, and hyphen.")

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    jobs = args.jobs or plan["execution"]["jobs"]
    if jobs < 1:
        raise SystemExit("--jobs must be positive.")
    raw_root = PROJECT / "raw" / f"real-project-static-audit-{label}"
    run_root = PROJECT / "runs" / f"real-project-static-audit-{label}"
    if raw_root.exists() or run_root.exists():
        raise SystemExit(f"Refusing to overwrite existing audit label: {label}")
    raw_root.mkdir(parents=True)
    run_root.mkdir(parents=True)
    shutil.copy2(PLAN, raw_root / "plan.json")

    started = time.monotonic()
    index: dict[str, Any] = {
        "schema": "clangast-sgfuzz-real-project-static-audit-index-v1",
        "plan": str(PLAN.relative_to(PROJECT)),
        "label": label,
        "jobs": jobs,
        "target_source_modified": False,
        "targets": [],
    }
    all_ok = True
    for target in plan["targets"]:
        target_dir = raw_root / target["id"]
        target_dir.mkdir()
        checkout = (PROJECT / target["checkout"]).resolve()
        source_root = (checkout / target["source_root"]).resolve()
        source_list = PROJECT / target["translation_units"]
        try:
            metadata = git_metadata(checkout)
            if metadata["commit"] != target["expected_commit"]:
                raise RuntimeError(f"Pinned revision mismatch: {metadata['commit']} != {target['expected_commit']}")
            if not metadata["working_tree_clean"]:
                raise RuntimeError(f"Target checkout has uncommitted changes: {checkout}")
            sources = read_sources(checkout, source_root, source_list)
            if target.get("source_list_sha256") and sha256(source_list) != target["source_list_sha256"]:
                raise RuntimeError(f"Frozen source-list digest mismatch: {source_list}")
        except (OSError, RuntimeError, ValueError) as error:
            (target_dir / "setup-error.txt").write_text(str(error) + "\n", encoding="utf-8")
            index["targets"].append({"id": target["id"], "status": "setup-failed",
                                     "error": str(error)})
            all_ok = False
            continue

        shutil.copy2(source_list, target_dir / "source-list.txt")
        target_record: dict[str, Any] = {
            "id": target["id"],
            "project": target["project"],
            "language": target["language"],
            "scope": target["scope"],
            "checkout": str(checkout),
            "expected_commit": target["expected_commit"],
            "observed_commit": metadata["commit"],
            "working_tree_clean": metadata["working_tree_clean"],
            "working_tree_status_short": metadata["status_short"],
            "source_root": str(source_root),
            "source_list": str((target_dir / "source-list.txt").relative_to(PROJECT)),
            "source_list_sha256": sha256(source_list),
            "translation_units_frozen": len(sources),
        }

        command = [sys.executable, str(ANALYSER), "--source-root", str(source_root),
                   "--manifest", str(target_dir / "ast-manifest.json"), "--jobs", str(jobs)]
        for source in sources:
            command.extend(["--source", str(source)])
        if target.get("compilation_database") == "fresh-cmake":
            build_dir = run_root / f"{target['id']}-cmake-build"
            cmake_command = ["cmake", "-S", str(checkout), "-B", str(build_dir),
                             *plan["execution"]["h2o_cmake_arguments"]]
            cmake_result = run_capture(cmake_command, PROJECT)
            record_process(target_dir, "cmake-configure", cmake_command, cmake_result)
            target_record["cmake_build_directory"] = str(build_dir)
            target_record["cmake_returncode"] = cmake_result.returncode
            compilation_database = build_dir / "compile_commands.json"
            if cmake_result.returncode or not compilation_database.is_file():
                target_record["status"] = "cmake-configure-failed"
                target_record["error"] = "CMake did not produce compile_commands.json."
                index["targets"].append(target_record)
                all_ok = False
                continue
            shutil.copy2(compilation_database, target_dir / "compile_commands.json")
            command.extend(["--compile-commands", str(compilation_database)])
            target_record["compile_commands"] = str((target_dir / "compile_commands.json").relative_to(PROJECT))
        else:
            for compiler_argument in target["fallback_clang_arguments"]:
                command.append(f"--clang-arg={compiler_argument.replace('{checkout}', str(checkout))}")

        audit_result = run_capture(command, PROJECT)
        record_process(target_dir, "ast-audit", command, audit_result)
        target_record["ast_audit_returncode"] = audit_result.returncode
        target_record["manifest"] = str((target_dir / "ast-manifest.json").relative_to(PROJECT))
        if audit_result.returncode == 0 and (target_dir / "ast-manifest.json").is_file():
            manifest = json.loads((target_dir / "ast-manifest.json").read_text(encoding="utf-8"))
            target_record["status"] = "ok"
            target_record["summary"] = manifest["summary"]
        else:
            target_record["status"] = "ast-audit-failed"
            all_ok = False
        index["targets"].append(target_record)

    index["elapsed_wall_seconds"] = round(time.monotonic() - started, 6)
    index_path = raw_root / "index.json"
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not all_ok:
        print(f"Static audit failed; raw evidence retained in {raw_root}", file=sys.stderr)
        return 1
    derive = run_capture([sys.executable, str(DERIVER), "--experiment-index", str(index_path)], PROJECT)
    record_process(raw_root, "derive", [sys.executable, str(DERIVER), "--experiment-index", str(index_path)], derive)
    if derive.returncode:
        print(derive.stderr, file=sys.stderr)
        return derive.returncode
    print(derive.stdout, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

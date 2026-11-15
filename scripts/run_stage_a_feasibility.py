#!/usr/bin/env python3
"""Run the pre-registered Stage A IXWebSocket feasibility pilot."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
PLAN = PROJECT / "experiments" / "stage-a-feasibility.json"
INSTRUMENTER = PROJECT / "src" / "sgfuzz_clang_ast_instrument.py"
DERIVER = PROJECT / "scripts" / "derive_stage_a_feasibility.py"
LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
STT = re.compile(r"states: (?P<states>\d+) leaves: (?P<leaves>\d+)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_metadata(checkout: Path) -> dict[str, Any]:
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    status = subprocess.run(["git", "status", "--short"], cwd=checkout, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if revision.returncode or status.returncode:
        raise RuntimeError((revision.stderr or status.stderr).strip())
    return {"commit": revision.stdout.strip(), "status_short": status.stdout.splitlines()}


def run_logged(directory: Path, stem: str, command: list[str], *, cwd: Path,
               environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    (directory / f"{stem}.command.txt").write_text(shlex.join(command) + "\n", encoding="utf-8")
    result = subprocess.run(command, cwd=cwd, env=environment, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    (directory / f"{stem}.stdout.txt").write_text(result.stdout, encoding="utf-8")
    (directory / f"{stem}.stderr.txt").write_text(result.stderr, encoding="utf-8")
    return result


def source_list(checkout: Path, source_list_path: Path) -> list[Path]:
    paths = [line.strip() for line in source_list_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(paths) != len(set(paths)):
        raise ValueError("The frozen source list contains duplicate entries.")
    resolved = [(checkout / path).resolve() for path in paths]
    if any(not path.is_file() for path in resolved):
        raise ValueError("A frozen IXWebSocket source is missing from the checkout.")
    return resolved


def callback_sites(path: Path) -> int:
    return len(re.findall(r"__sfuzzer_instrument\(\d+", path.read_text(encoding="utf-8")))


def replay_metrics(stdout: str, stderr: str) -> dict[str, int]:
    matches = list(STT.finditer(stdout + "\n" + stderr))
    if not matches:
        raise ValueError("The replay log did not contain SGFuzz states/leaves statistics.")
    match = matches[-1]
    return {"states": int(match.group("states")), "leaves": int(match.group("leaves"))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", help="Stable suffix for raw/ and runs/ directories.")
    args = parser.parse_args()
    label = args.label or dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if not LABEL.fullmatch(label):
        raise SystemExit("--label may contain only letters, digits, dot, underscore, and hyphen.")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    raw_dir = PROJECT / "raw" / f"stage-a-feasibility-{label}"
    run_dir = PROJECT / "runs" / f"stage-a-feasibility-{label}"
    if raw_dir.exists() or run_dir.exists():
        raise SystemExit(f"Refusing to overwrite existing label: {label}")
    raw_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    shutil.copy2(PLAN, raw_dir / "plan.json")

    target = plan["target"]
    runtime = plan["runtime"]
    checkout = (PROJECT / target["checkout"]).resolve()
    sgfuzz = (PROJECT / runtime["sgfuzz_checkout"]).resolve()
    source_path = checkout / target["source"]
    source_list_path = PROJECT / target["source_list"]
    harness = PROJECT / target["harness"]
    seeds = PROJECT / target["seed_directory"]
    try:
        target_git = git_metadata(checkout)
        runtime_git = git_metadata(sgfuzz)
        if target_git["commit"] != target["expected_commit"] or target_git["status_short"]:
            raise RuntimeError("IXWebSocket checkout is not the required clean pinned revision.")
        if runtime_git["commit"] != runtime["expected_commit"]:
            raise RuntimeError("SGFuzz checkout is not at the required pinned revision.")
        if sha256(source_list_path) != target["source_list_sha256"]:
            raise RuntimeError("The frozen IXWebSocket source-list checksum does not match the plan.")
        if sha256(harness) != target["harness_sha256"]:
            raise RuntimeError("The harness checksum does not match the plan.")
        for name, expected in target["seed_sha256"].items():
            if sha256(seeds / name) != expected:
                raise RuntimeError(f"Seed checksum mismatch: {name}")
        runtime_library = sgfuzz / runtime["library"]
        if sha256(runtime_library) != runtime["library_sha256"]:
            raise RuntimeError("The SGFuzz runtime archive checksum does not match the plan.")
        sources = source_list(checkout, source_list_path)
    except (OSError, RuntimeError, ValueError) as error:
        (raw_dir / "setup-error.txt").write_text(str(error) + "\n", encoding="utf-8")
        raise SystemExit(str(error))

    index: dict[str, Any] = {
        "schema": "clangast-sgfuzz-stage-a-feasibility-index-v1",
        "plan": str(PLAN.relative_to(PROJECT)),
        "target_commit": target_git["commit"],
        "target_source_modified": False,
        "runtime_commit": runtime_git["commit"],
        "runtime_status_short": runtime_git["status_short"],
        "conditions": [],
    }
    original_source_hash = sha256(source_path)
    all_ok = True
    for condition in plan["conditions"]:
        condition_id = condition["id"]
        condition_raw = raw_dir / condition_id
        condition_run = run_dir / condition_id
        copied_tree = condition_run / "repo"
        condition_raw.mkdir()
        shutil.copy2(source_path, condition_raw / "target.before.cpp")
        record: dict[str, Any] = {"id": condition_id, "expected": condition["expected"],
                                  "raw_directory": str(condition_raw.relative_to(PROJECT))}
        if condition_id == "ast":
            # The copy-only instrumenter deliberately refuses an existing
            # output directory. It performs the source-tree copy itself.
            instrument = [sys.executable, str(INSTRUMENTER), "--input-root", str(checkout),
                          "--output-root", str(copied_tree), "--source-root", "ixwebsocket",
                          "--source", target["source"], "--manifest",
                          str(condition_raw / "instrumentation-manifest.json"),
                          "--clang-arg=-std=c++14", f"--clang-arg=-I{copied_tree}",
                          "--clang-arg=-DIXWEBSOCKET_USE_ZLIB"]
            result = run_logged(condition_raw, "instrument", instrument, cwd=PROJECT)
            record["instrument_returncode"] = result.returncode
            if result.returncode:
                record["status"] = "instrument-failed"
                index["conditions"].append(record)
                all_ok = False
                continue
        else:
            shutil.copytree(checkout, copied_tree, ignore=shutil.ignore_patterns(".git"))
            (condition_raw / "instrument.command.txt").write_text("control: no source rewrite\n", encoding="utf-8")
        copied_source = copied_tree / target["source"]
        shutil.copy2(copied_source, condition_raw / "target.after.cpp")
        diff = subprocess.run(["diff", "-u", str(condition_raw / "target.before.cpp"),
                               str(condition_raw / "target.after.cpp")], text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        (condition_raw / "target.diff").write_text(diff.stdout, encoding="utf-8")
        callbacks = callback_sites(copied_source)
        binary = condition_run / "ixwebsocket_transport_sfuzzer"
        copied_sources = [str(copied_tree / path.relative_to(checkout)) for path in sources]
        build = [runtime["compiler"], *runtime["compiler_arguments"], "-I", str(copied_tree),
                 str(harness), *copied_sources, str(runtime_library), "-pthread", "-lz", "-o", str(binary)]
        build_result = run_logged(condition_raw, "build", build, cwd=PROJECT)
        record["build_returncode"] = build_result.returncode
        if build_result.returncode:
            record["status"] = "build-failed"
            index["conditions"].append(record)
            all_ok = False
            continue
        replay = [str(binary), *runtime["replay_arguments"], str(seeds)]
        environment = dict(os.environ, **runtime["environment"])
        replay_result = run_logged(condition_raw, "replay", replay, cwd=PROJECT, environment=environment)
        record["replay_returncode"] = replay_result.returncode
        try:
            metrics = replay_metrics(replay_result.stdout, replay_result.stderr)
        except ValueError as error:
            record["status"] = "replay-metrics-missing"
            record["error"] = str(error)
            index["conditions"].append(record)
            all_ok = False
            continue
        record["observed"] = {"callback_sites": callbacks, **metrics}
        record["output_source_sha256"] = sha256(copied_source)
        record["status"] = "ok" if replay_result.returncode == 0 else "replay-failed"
        index["conditions"].append(record)
        all_ok = all_ok and record["status"] == "ok"

    index["input_source_sha256_before"] = original_source_hash
    index["input_source_sha256_after"] = sha256(source_path)
    index["input_source_unchanged"] = (
        index["input_source_sha256_before"] == index["input_source_sha256_after"])
    index["target_source_modified"] = not index["input_source_unchanged"]
    index_path = raw_dir / "index.json"
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not all_ok or not index["input_source_unchanged"]:
        print(f"Stage A failed; raw evidence retained in {raw_dir}", file=sys.stderr)
        return 1
    derive = run_logged(raw_dir, "derive", [sys.executable, str(DERIVER), "--experiment-index", str(index_path)], cwd=PROJECT)
    if derive.returncode:
        print(derive.stderr, file=sys.stderr)
        return derive.returncode
    print(derive.stdout, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

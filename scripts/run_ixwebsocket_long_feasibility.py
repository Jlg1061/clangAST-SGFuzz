#!/usr/bin/env python3
"""Run one persistent 23-hour AST-SGFuzz feasibility campaign on IXWebSocket."""

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
import time
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
PLAN = PROJECT / "experiments" / "ixwebsocket-long-feasibility.json"
INSTRUMENTER = PROJECT / "src" / "sgfuzz_clang_ast_instrument.py"
LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
STT = re.compile(r"states: (?P<states>\d+) leaves: (?P<leaves>\d+)")
RSS = re.compile(r"rss: (?P<rss>\d+)Mb")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def git_metadata(checkout: Path) -> dict[str, Any]:
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    status = subprocess.run(["git", "status", "--short"], cwd=checkout, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if revision.returncode or status.returncode:
        raise RuntimeError((revision.stderr or status.stderr).strip())
    return {"commit": revision.stdout.strip(), "status_short": status.stdout.splitlines()}


def source_list(checkout: Path, list_path: Path) -> list[Path]:
    relative_paths = [line.strip() for line in list_path.read_text(encoding="utf-8").splitlines()
                      if line.strip()]
    if len(relative_paths) != len(set(relative_paths)):
        raise ValueError("The source list contains duplicate paths.")
    paths = [(checkout / item).resolve() for item in relative_paths]
    if any(not path.is_file() for path in paths):
        raise ValueError("A source listed for the IXWebSocket target is missing.")
    return paths


def callback_sites(path: Path) -> int:
    return len(re.findall(r"__sfuzzer_instrument\(\d+", path.read_text(encoding="utf-8")))


def process_rss_kib(process_id: int) -> int | None:
    status = Path(f"/proc/{process_id}/status")
    try:
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        return None
    return None


def corpus_summary(corpus: Path) -> dict[str, int]:
    files = [path for path in corpus.rglob("*") if path.is_file()]
    return {"files": len(files), "bytes": sum(path.stat().st_size for path in files)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", help="Stable suffix for raw/ and runs/ directories.")
    parser.add_argument("--duration-seconds", type=int,
                        help="Override only for a short operational smoke check.")
    arguments = parser.parse_args()
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    campaign = plan["campaign"]
    duration = arguments.duration_seconds or campaign["duration_seconds"]
    if duration <= 0:
        raise SystemExit("--duration-seconds must be positive.")
    label = arguments.label or dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if not LABEL.fullmatch(label):
        raise SystemExit("--label may contain only letters, digits, dot, underscore, and hyphen.")
    raw_dir = PROJECT / "raw" / f"ixwebsocket-long-feasibility-{label}"
    run_dir = PROJECT / "runs" / f"ixwebsocket-long-feasibility-{label}"
    if raw_dir.exists() or run_dir.exists():
        raise SystemExit(f"Refusing to overwrite existing label: {label}")
    raw_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    shutil.copy2(PLAN, raw_dir / "plan.json")

    target = plan["target"]
    runtime = plan["runtime"]
    checkout = (PROJECT / target["checkout"]).resolve()
    sgfuzz = (PROJECT / runtime["sgfuzz_checkout"]).resolve()
    source = checkout / target["source"]
    source_paths = PROJECT / target["source_list"]
    harness = PROJECT / target["harness"]
    seeds = PROJECT / target["seed_directory"]
    copied_tree = run_dir / "repo"
    corpus = run_dir / "corpus"
    artifacts = run_dir / "artifacts"
    binary = run_dir / "ixwebsocket_transport_ast_sfuzzer"
    index: dict[str, Any] = {
        "schema": "clangast-sgfuzz-ixwebsocket-long-feasibility-index-v1",
        "status": "setup",
        "plan": str(PLAN.relative_to(PROJECT)),
        "duration_seconds": duration,
        "started_utc": dt.datetime.now(tz=dt.timezone.utc).isoformat(),
        "raw_directory": str(raw_dir.relative_to(PROJECT)),
        "run_directory": str(run_dir.relative_to(PROJECT)),
    }
    write_json(raw_dir / "index.json", index)

    try:
        target_git = git_metadata(checkout)
        runtime_git = git_metadata(sgfuzz)
        if target_git["commit"] != target["expected_commit"] or target_git["status_short"]:
            raise RuntimeError("IXWebSocket is not at the clean pinned revision.")
        if runtime_git["commit"] != runtime["expected_commit"]:
            raise RuntimeError("SGFuzz is not at the pinned revision.")
        if sha256(source_paths) != target["source_list_sha256"]:
            raise RuntimeError("The IXWebSocket source-list checksum does not match the plan.")
        if sha256(harness) != target["harness_sha256"]:
            raise RuntimeError("The harness checksum does not match the plan.")
        for name, expected in target["seed_sha256"].items():
            if sha256(seeds / name) != expected:
                raise RuntimeError(f"Seed checksum mismatch: {name}")
        runtime_library = sgfuzz / runtime["library"]
        if sha256(runtime_library) != runtime["library_sha256"]:
            raise RuntimeError("The SGFuzz runtime checksum does not match the plan.")
        sources = source_list(checkout, source_paths)
    except (OSError, RuntimeError, ValueError) as error:
        index.update(status="setup-failed", error=str(error))
        write_json(raw_dir / "index.json", index)
        raise SystemExit(str(error))

    index.update(target_git=target_git, runtime_git=runtime_git,
                 input_source_sha256_before=sha256(source))
    shutil.copy2(source, raw_dir / "IXWebSocketTransport.before.cpp")
    instrument = [sys.executable, str(INSTRUMENTER), "--input-root", str(checkout),
                  "--output-root", str(copied_tree), "--source-root", "ixwebsocket",
                  "--source", target["source"], "--manifest",
                  str(raw_dir / "instrumentation-manifest.json"), "--clang-arg=-std=c++14",
                  f"--clang-arg=-I{copied_tree}", "--clang-arg=-DIXWEBSOCKET_USE_ZLIB"]
    (raw_dir / "instrument.command.txt").write_text(shlex.join(instrument) + "\n", encoding="utf-8")
    instrument_result = subprocess.run(instrument, cwd=PROJECT, text=True, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, check=False)
    (raw_dir / "instrument.log").write_text(instrument_result.stdout, encoding="utf-8")
    if instrument_result.returncode:
        index.update(status="instrument-failed", instrument_returncode=instrument_result.returncode)
        write_json(raw_dir / "index.json", index)
        return instrument_result.returncode

    copied_source = copied_tree / target["source"]
    shutil.copy2(copied_source, raw_dir / "IXWebSocketTransport.after.cpp")
    diff = subprocess.run(["diff", "-u", str(raw_dir / "IXWebSocketTransport.before.cpp"),
                           str(raw_dir / "IXWebSocketTransport.after.cpp")], text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    (raw_dir / "target.diff").write_text(diff.stdout, encoding="utf-8")
    copied_sources = [str(copied_tree / item.relative_to(checkout)) for item in sources]
    build = [runtime["compiler"], *runtime["compiler_arguments"], "-I", str(copied_tree),
             str(harness), *copied_sources, str(runtime_library), "-pthread", "-lz", "-o", str(binary)]
    (raw_dir / "build.command.txt").write_text(shlex.join(build) + "\n", encoding="utf-8")
    build_result = subprocess.run(build, cwd=PROJECT, text=True, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, check=False)
    (raw_dir / "build.log").write_text(build_result.stdout, encoding="utf-8")
    if build_result.returncode:
        index.update(status="build-failed", build_returncode=build_result.returncode)
        write_json(raw_dir / "index.json", index)
        return build_result.returncode

    shutil.copytree(seeds, corpus)
    artifacts.mkdir()
    command = [str(binary), f"-max_total_time={duration}",
               f"-timeout={campaign['timeout_seconds']}", f"-seed={campaign['seed']}",
               "-print_final_stats=1", f"-artifact_prefix={artifacts}/", str(corpus)]
    (raw_dir / "fuzz.command.txt").write_text(shlex.join(command) + "\n", encoding="utf-8")
    environment = dict(os.environ, **runtime["environment"])
    started_monotonic = time.monotonic()
    checkpoints = iter(sorted(set(checkpoint for checkpoint in campaign["checkpoints_seconds"]
                                  if checkpoint <= duration)))
    next_checkpoint = next(checkpoints, None)
    log_path = raw_dir / "fuzzer.log"
    index.update(status="running", callback_sites=callback_sites(copied_source),
                 input_source_sha256_after=sha256(source),
                 input_source_unchanged=sha256(source) == index["input_source_sha256_before"],
                 process_id=None)
    write_json(raw_dir / "index.json", index)
    with log_path.open("w", encoding="utf-8", buffering=1) as log_file:
        process = subprocess.Popen(command, cwd=PROJECT, env=environment, stdout=log_file,
                                   stderr=subprocess.STDOUT, text=True)
        index["process_id"] = process.pid
        write_json(raw_dir / "index.json", index)
        while process.poll() is None:
            elapsed = time.monotonic() - started_monotonic
            if next_checkpoint is not None and elapsed >= next_checkpoint:
                snapshot = {
                    "elapsed_seconds": round(elapsed, 3),
                    "recorded_utc": dt.datetime.now(tz=dt.timezone.utc).isoformat(),
                    "process_rss_kib": process_rss_kib(process.pid),
                    "corpus": corpus_summary(corpus),
                }
                write_json(raw_dir / f"checkpoint-{next_checkpoint}s.json", snapshot)
                next_checkpoint = next(checkpoints, None)
            time.sleep(5)
        returncode = process.returncode

    log = log_path.read_text(encoding="utf-8", errors="replace")
    states = [int(match.group("states")) for match in STT.finditer(log)]
    leaves = [int(match.group("leaves")) for match in STT.finditer(log)]
    rss = [int(match.group("rss")) for match in RSS.finditer(log)]
    index.update(
        status="completed" if returncode == 0 else "fuzz-failed",
        fuzz_returncode=returncode,
        completed_utc=dt.datetime.now(tz=dt.timezone.utc).isoformat(),
        elapsed_seconds=round(time.monotonic() - started_monotonic, 3),
        final_stt={"states": states[-1], "leaves": leaves[-1]} if states and leaves else None,
        peak_rss_mb=max(rss) if rss else None,
        final_corpus=corpus_summary(corpus),
        sanitizer_error=bool(re.search(r"ERROR: (AddressSanitizer|UndefinedBehaviorSanitizer)", log)),
    )
    write_json(raw_dir / "index.json", index)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())

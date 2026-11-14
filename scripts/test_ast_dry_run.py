#!/usr/bin/env python3
"""Integration tests for the Clang-AST state-transition detector and rewriter.

The tests exercise automatic discovery on C++ and C fixtures and the
IXWebSocket primary case, plus a focused wrong-type negative control and Clang
parse-failure recording. The C cases prove named and anonymous enum handling,
including copy-and-instrument output that remains valid GNU C. The primary
source SHA-256 is checked before and after all tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
REPOSITORY = PROJECT.parent
DETECTOR = PROJECT / "src" / "sgfuzz_clang_ast_dry_run.py"
INSTRUMENTER = PROJECT / "src" / "sgfuzz_clang_ast_instrument.py"
IX_ROOT = REPOSITORY / "IXWebSocket"
IX_SOURCE_ROOT = IX_ROOT / "ixwebsocket"
IX_TARGET = IX_SOURCE_ROOT / "IXWebSocketTransport.cpp"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        help="Optional empty directory in which to keep manifests and command output.")
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_detector(name: str, output_root: Path, source_root: Path, source: Path | None,
                 state_type: str | None, *, clang_args: list[str] | None = None,
                 clang: str = "auto",
                 ast_filter: str | None = None,
                 expected_returncodes: tuple[int, ...] = (0,)) -> dict[str, Any]:
    case_dir = output_root / name
    case_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = case_dir / "manifest.json"
    command = [
        sys.executable, str(DETECTOR),
        "--source-root", str(source_root),
        "--manifest", str(manifest_path),
        "--clang", clang,
    ]
    if source is not None:
        command.extend(["--source", str(source)])
    if state_type:
        command.extend(["--state-type", state_type])
    for clang_arg in clang_args or ["-std=c++14"]:
        command.append(f"--clang-arg={clang_arg}")
    if ast_filter:
        command.extend(["--ast-filter", ast_filter])
    result = subprocess.run(command, cwd=REPOSITORY, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            check=False)
    write_text(case_dir / "command.txt", " ".join(command) + "\n")
    write_text(case_dir / "stdout.txt", result.stdout)
    write_text(case_dir / "stderr.txt", result.stderr)
    if result.returncode not in expected_returncodes:
        raise AssertionError(f"{name}: detector exited {result.returncode}; see {case_dir}")
    if not manifest_path.is_file():
        raise AssertionError(f"{name}: detector did not create its manifest")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_positive(manifest: dict[str, Any], name: str, storage_kind: str,
                   assignment_kind: str, storage_name: str,
                   expected_file: str | None = None,
                   expected_line: int | None = None) -> dict[str, Any]:
    check(manifest["mode"] == "dry-run", f"{name}: mode must be dry-run")
    check(manifest["target_source_modified"] is False,
          f"{name}: detector must declare that target source was unchanged")
    check(not manifest["parse_failures"], f"{name}: unexpected Clang parse failure")
    check(len(manifest["state_storage"]) == 1,
          f"{name}: expected exactly one configured state storage declaration")
    storage = manifest["state_storage"][0]
    check(storage["name"] == storage_name, f"{name}: wrong storage name")
    check(storage["storage_kind"] == storage_kind, f"{name}: wrong storage kind")
    check(len(manifest["candidate_transition_writes"]) == 1,
          f"{name}: expected exactly one candidate state assignment")
    candidate = manifest["candidate_transition_writes"][0]
    check(candidate["storage_name"] == storage_name, f"{name}: candidate linked to wrong storage")
    check(candidate["storage_kind"] == storage_kind, f"{name}: candidate has wrong storage kind")
    check(candidate["assignment_ast_kind"] == assignment_kind,
          f"{name}: wrong assignment AST kind")
    if expected_file is not None:
        check(candidate["assignment_location"]["file"] == expected_file,
              f"{name}: wrong assignment file")
    if expected_line is not None:
        check(candidate["assignment_location"]["line"] == expected_line,
              f"{name}: wrong assignment line")
    return candidate


def test_fixtures(output_root: Path) -> list[dict[str, Any]]:
    cases = [
        ("direct-unscoped", "line-direct-unscoped-control", "direct", "direct-operator="),
        ("direct-scoped", "line-direct-scoped-variant", "direct", "direct-operator="),
        ("atomic-unscoped", "line-atomic-unscoped-variant", "atomic", "overloaded-operator="),
    ]
    records: list[dict[str, Any]] = []
    for test_name, case_name, storage_kind, assignment_kind in cases:
        case_root = PROJECT / "cases" / case_name
        manifest = run_detector(test_name, output_root, case_root, case_root / "target.cpp",
                                None)
        check(manifest["selection_mode"] == "automatic",
              f"{test_name}: fixture must use automatic discovery")
        candidate = check_positive(manifest, test_name, storage_kind, assignment_kind,
                                   "current_state")
        records.append({"test": test_name, "status": "pass", "candidate": candidate})
    return records


def test_c_fixture_and_rewriter(output_root: Path) -> dict[str, Any]:
    """Exercise direct C-enum detection and compile the instrumented copy."""
    case_root = PROJECT / "cases" / "c-direct-enum-control"
    source = case_root / "target.c"
    source_hash_before = sha256(source)
    # Omit --source: this asserts that the automatic source enumeration now
    # selects a .c translation unit, rather than merely accepting one given
    # explicitly on the command line.
    manifest = run_detector("c-direct-enum", output_root, case_root, None, None,
                            clang_args=["-std=gnu11"])
    check(manifest["selection_mode"] == "automatic",
          "c-direct-enum: fixture must use automatic discovery")
    candidate = check_positive(manifest, "c-direct-enum", "direct", "direct-operator=",
                               "current_state")

    case_dir = output_root / "c-direct-enum"
    copied_root = case_dir / "instrumented-copy"
    instrumentation_manifest = case_dir / "instrumentation-manifest.json"
    command = [
        sys.executable, str(INSTRUMENTER),
        "--input-root", str(case_root),
        "--output-root", str(copied_root),
        "--source-root", ".",
        "--source", "target.c",
        "--manifest", str(instrumentation_manifest),
        "--clang-arg=-std=gnu11",
    ]
    result = subprocess.run(command, cwd=REPOSITORY, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    write_text(case_dir / "instrument-command.txt", " ".join(command) + "\n")
    write_text(case_dir / "instrument-stdout.txt", result.stdout)
    write_text(case_dir / "instrument-stderr.txt", result.stderr)
    check(result.returncode == 0,
          f"c-direct-enum: instrumenter exited {result.returncode}; see {case_dir}")
    instrumentation = json.loads(instrumentation_manifest.read_text(encoding="utf-8"))
    check(instrumentation["callback_sites"] == 1,
          "c-direct-enum: expected exactly one inserted callback")
    rewritten = (copied_root / "target.c").read_text(encoding="utf-8")
    check("__auto_type sfuzzer_ast_capture_1_0" in rewritten,
          "c-direct-enum: C rewrite must use a GNU C __auto_type capture")
    check("((unsigned int)sfuzzer_ast_capture_1_0)" in rewritten,
          "c-direct-enum: C rewrite must use a C-style state cast")
    compile_command = ["clang", "-std=gnu11", "-fsyntax-only", str(copied_root / "target.c")]
    compiled = subprocess.run(compile_command, cwd=REPOSITORY, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    write_text(case_dir / "compile-command.txt", " ".join(compile_command) + "\n")
    write_text(case_dir / "compile-stdout.txt", compiled.stdout)
    write_text(case_dir / "compile-stderr.txt", compiled.stderr)
    check(compiled.returncode == 0,
          f"c-direct-enum: instrumented C did not compile; see {case_dir}")
    check(sha256(source) == source_hash_before,
          "c-direct-enum: instrumenter changed the source input")
    return {"test": "c-direct-enum-copy-and-instrument", "status": "pass", "candidate": candidate}


def test_c_anonymous_enum_fixture(output_root: Path) -> dict[str, Any]:
    """Regression test for local and field C anonymous-enum storage."""
    case_root = PROJECT / "cases" / "c-anonymous-enum-control"
    source = case_root / "target.c"
    source_hash_before = sha256(source)
    manifest = run_detector("c-anonymous-enum", output_root, case_root, None, None,
                            clang_args=["-std=gnu11"])
    check(manifest["selection_mode"] == "automatic",
          "c-anonymous-enum: fixture must use automatic discovery")
    check(not manifest["parse_failures"], "c-anonymous-enum: source should parse")
    storage = {record["name"]: record for record in manifest["state_storage"]}
    check({"local_state", "field_state"} <= set(storage),
          "c-anonymous-enum: missed a local or field anonymous enum")
    check(all(record["state_type"].startswith("anonymous enum at ")
              for record in storage.values()),
          "c-anonymous-enum: anonymous enum identity was not retained")
    candidates = manifest["candidate_transition_writes"]
    check({record["storage_name"] for record in candidates} == {"local_state", "field_state"},
          "c-anonymous-enum: expected one write per anonymous enum storage")

    case_dir = output_root / "c-anonymous-enum"
    copied_root = case_dir / "instrumented-copy"
    instrumentation_manifest = case_dir / "instrumentation-manifest.json"
    command = [
        sys.executable, str(INSTRUMENTER),
        "--input-root", str(case_root), "--output-root", str(copied_root),
        "--source-root", ".", "--source", "target.c",
        "--manifest", str(instrumentation_manifest), "--clang-arg=-std=gnu11",
    ]
    result = subprocess.run(command, cwd=REPOSITORY, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    write_text(case_dir / "instrument-command.txt", " ".join(command) + "\n")
    write_text(case_dir / "instrument-stdout.txt", result.stdout)
    write_text(case_dir / "instrument-stderr.txt", result.stderr)
    check(result.returncode == 0,
          f"c-anonymous-enum: instrumenter exited {result.returncode}; see {case_dir}")
    instrumentation = json.loads(instrumentation_manifest.read_text(encoding="utf-8"))
    check(instrumentation["callback_sites"] == 2,
          "c-anonymous-enum: expected two inserted callbacks")
    compile_command = ["clang", "-std=gnu11", "-fsyntax-only", str(copied_root / "target.c")]
    compiled = subprocess.run(compile_command, cwd=REPOSITORY, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    write_text(case_dir / "compile-command.txt", " ".join(compile_command) + "\n")
    write_text(case_dir / "compile-stdout.txt", compiled.stdout)
    write_text(case_dir / "compile-stderr.txt", compiled.stderr)
    check(compiled.returncode == 0,
          "c-anonymous-enum: instrumented C did not compile")
    check(sha256(source) == source_hash_before,
          "c-anonymous-enum: instrumenter changed the source input")
    return {"test": "c-anonymous-enum-copy-and-instrument", "status": "pass"}


def test_primary(output_root: Path) -> list[dict[str, Any]]:
    primary_args = ["-std=c++14", f"-I{IX_ROOT}"]
    manifest = run_detector("ixwebsocket-primary", output_root, IX_SOURCE_ROOT, IX_TARGET,
                            None, clang_args=primary_args)
    check(manifest["selection_mode"] == "automatic",
          "ixwebsocket-primary: no state type may be configured")
    check(not manifest["parse_failures"], "ixwebsocket-primary: source should parse")
    storage = next((record for record in manifest["state_storage"]
                    if record["name"] == "_readyState"), None)
    check(storage is not None, "ixwebsocket-primary: automatic mode must find _readyState")
    check(storage["declaration_kind"] == "FieldDecl",
          "ixwebsocket-primary: _readyState must resolve to a class field")
    check(storage["canonical_type"] == "std::atomic<ix::WebSocketTransport::ReadyState>",
          "ixwebsocket-primary: canonical atomic state type did not match")
    candidate = next((record for record in manifest["candidate_transition_writes"]
                      if record["storage_name"] == "_readyState"), None)
    check(candidate is not None, "ixwebsocket-primary: automatic mode must find _readyState write")
    check(candidate["assignment_ast_kind"] == "overloaded-operator=",
          "ixwebsocket-primary: _readyState must use atomic assignment")
    check(candidate["assignment_location"]["file"] == "ixwebsocket/IXWebSocketTransport.cpp",
          "ixwebsocket-primary: _readyState write must be in the transport implementation")
    check(candidate["assignment_location"]["line"] == 237,
          "ixwebsocket-primary: wrong _readyState write line")
    check(candidate["rewrite_safety"]["standalone_statement"],
          "ixwebsocket-primary: selected write must be safely rewritable")
    expected_fields = {"_readyState", "_pingType", "opcode", "_fragmentedMessageKind"}
    detected_fields = {record["storage_name"] for record in manifest["candidate_transition_writes"]}
    check(expected_fields <= detected_fields,
          "ixwebsocket-primary: automatic mode missed one expected transition field")

    wrong_type = run_detector("wrong-type-negative", output_root, IX_SOURCE_ROOT, IX_TARGET,
                              "ix::WebSocketTransport::NotAState", clang_args=primary_args,
                              ast_filter="WebSocketTransport")
    check(not wrong_type["parse_failures"], "wrong-type-negative: source should still parse")
    check(not wrong_type["state_storage"], "wrong-type-negative: must not match _readyState")
    check(not wrong_type["candidate_transition_writes"],
          "wrong-type-negative: must not report any transition write")
    return [
        {"test": "ixwebsocket-primary-automatic", "status": "pass", "candidate": candidate},
        {"test": "wrong-type-negative", "status": "pass"},
    ]


def test_parse_failure(output_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="sgfuzz-ast-bad-source-") as temporary_dir:
        source_root = Path(temporary_dir)
        broken_source = source_root / "broken.cpp"
        broken_source.write_text("enum class State { OPEN };\nvoid f() {\n", encoding="utf-8")
        manifest = run_detector("parse-failure-recording", output_root, source_root, broken_source,
                                "State", expected_returncodes=(1,))
    check(len(manifest["parse_failures"]) == 1,
          "parse-failure-recording: malformed C++ must appear in parse_failures")
    check(manifest["translation_units"][0]["status"] == "parse-failed",
          "parse-failure-recording: translation unit must be labelled parse-failed")
    check(not manifest["candidate_transition_writes"],
          "parse-failure-recording: failed source cannot have candidates")
    return {"test": "parse-failure-recording", "status": "pass"}


def test_compact_source_location() -> dict[str, Any]:
    """Keep Clang's ``line:..., /path`` ranges from corrupting a file name."""
    api = runpy.run_path(str(DETECTOR))
    compact_range = (
        "|-FieldDecl 0x1 <line:163:5, "
        "/tmp/sgfuzz-location-regression/include/state.h:124:5> col:5 state 'int'\n"
    )
    observed = api["update_text_file"](compact_range, None)
    expected = "/tmp/sgfuzz-location-regression/include/state.h"
    check(observed == expected,
          "compact-location: Clang line: range must retain the real header path")
    return {"test": "compact-source-location-parser", "status": "pass"}


def main() -> int:
    arguments = parse_arguments()
    if shutil.which("clang++") is None or shutil.which("clang") is None:
        print("clang++ and clang are required for these integration tests.", file=sys.stderr)
        return 2
    if not DETECTOR.is_file() or not IX_TARGET.is_file():
        print("Expected detector or IXWebSocket primary source is missing.", file=sys.stderr)
        return 2

    if arguments.output_dir:
        output_root = arguments.output_dir.resolve()
        if output_root.exists():
            print(f"Refusing to overwrite existing output directory: {output_root}", file=sys.stderr)
            return 2
        output_root.mkdir(parents=True)
        cleanup = None
    else:
        cleanup = tempfile.TemporaryDirectory(prefix="sgfuzz-ast-tests-")
        output_root = Path(cleanup.name)

    before = sha256(IX_TARGET)
    try:
        records = test_fixtures(output_root)
        records.append(test_c_fixture_and_rewriter(output_root))
        records.append(test_c_anonymous_enum_fixture(output_root))
        records.extend(test_primary(output_root))
        records.append(test_parse_failure(output_root))
        records.append(test_compact_source_location())
        after = sha256(IX_TARGET)
        check(before == after, "IXWebSocketTransport.cpp changed during read-only detector tests")
        summary = {
            "schema": "sgfuzz-clang-ast-test-v2",
            "tests": records,
            "passed": len(records),
            "failed": 0,
            "primary_source": str(IX_TARGET),
            "primary_sha256_before": before,
            "primary_sha256_after": after,
            "primary_source_unchanged": True,
        }
        write_text(output_root / "summary.json", json.dumps(summary, indent=2) + "\n")
        print(f"PASS: {len(records)} integration tests")
        print("PASS: IXWebSocketTransport.cpp was unchanged")
        print(f"Evidence: {output_root}")
        return 0
    except AssertionError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    finally:
        if cleanup is not None:
            cleanup.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Copy a C/C++ tree and instrument AST-discovered SGFuzz state transitions.

This narrow prototype consumes the read-only detector's manifest.
It supports direct enum variables and ``std::atomic<Enum>`` variables for an
AST-confirmed standalone assignment. The right-hand side is captured once in a
fresh local variable before the original assignment is performed, allowing
casts and conditional expressions without evaluating them twice. The input tree
is never modified; only ``--output-root`` is rewritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
DETECTOR = PROJECT / "src" / "sgfuzz_clang_ast_dry_run.py"
SCHEMA = "sgfuzz-clang-ast-instrument-v3"
TRACKED_SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}
CALLBACK_PREAMBLE = """#ifndef SFUZZ_INSTRUMENT
#define SFUZZ_INSTRUMENT
#ifdef __cplusplus
extern \"C\" {
#endif
void __sfuzzer_instrument(unsigned int location, unsigned int state_value);
__attribute__((weak)) void __sfuzzer_instrument(unsigned int location, unsigned int state_value) { location = 0; state_value = 0; }
#ifdef __cplusplus
}
#endif
#endif /* SFUZZ_INSTRUMENT */
"""


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, type=Path,
                        help="Original source-tree root. It is copied but never modified.")
    parser.add_argument("--output-root", required=True, type=Path,
                        help="New destination for the disposable instrumented source copy.")
    parser.add_argument("--source-root", required=True, type=Path,
                        help="C/C++ analysis root, relative to --input-root (use . for the input root).")
    parser.add_argument("--source", action="append", type=Path, default=[],
                        help="Translation unit to analyse, relative to --input-root. Repeatable; "
                             "defaults to every C/C++ translation unit below --source-root.")
    parser.add_argument("--state-type",
                        help="Optional exact enum type for a focused pass. Omit for automatic discovery.")
    parser.add_argument("--manifest", required=True, type=Path,
                        help="Output instrumentation manifest outside the copied source tree.")
    parser.add_argument("--clang", default="auto",
                        help="Clang executable. Default 'auto' selects clang for .c and clang++ for C++ sources.")
    parser.add_argument("--clang-arg", action="append", default=[],
                        help="Extra compiler argument. Include paths must point at --output-root.")
    parser.add_argument("--ast-filter")
    parser.add_argument("--jobs", type=int, default=1,
                        help="Concurrent AST analyses in automatic discovery mode (default: 1).")
    parser.add_argument("--location-start", type=int, default=1,
                        help="First SGFuzz location ID (default: 1).")
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_relative(path: Path, root: Path, label: str) -> Path:
    candidate = path if path.is_absolute() else root / path
    try:
        return candidate.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"{label} must be inside --input-root: {path}") from error


def tracked_sources(input_root: Path, source_root_relative: Path,
                    requested_sources: list[Path]) -> list[Path]:
    """Return input paths whose hashes prove the source input stayed unchanged."""
    if requested_sources:
        return requested_sources
    source_root = input_root / source_root_relative
    return sorted(path.relative_to(input_root) for path in source_root.rglob("*")
                  if path.is_file() and path.suffix in TRACKED_SOURCE_SUFFIXES)


def run_detector(arguments: argparse.Namespace, analysis_root: Path, output_root: Path,
                 source_relatives: list[Path], temporary_dir: Path) -> dict[str, Any]:
    discovery_path = temporary_dir / "discovery.json"
    command = [
        sys.executable, str(DETECTOR),
        "--source-root", str(analysis_root),
        "--manifest", str(discovery_path),
        "--clang", arguments.clang,
        "--jobs", str(arguments.jobs),
    ]
    if arguments.state_type:
        command.extend(["--state-type", arguments.state_type])
    for source_relative in source_relatives:
        command.extend(["--source", str(output_root / source_relative)])
    for clang_arg in arguments.clang_arg:
        command.append(f"--clang-arg={clang_arg}")
    if arguments.ast_filter:
        command.extend(["--ast-filter", arguments.ast_filter])
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            check=False)
    if not discovery_path.is_file():
        raise RuntimeError("AST discovery did not write its manifest: " + result.stderr.strip())
    manifest = json.loads(discovery_path.read_text(encoding="utf-8"))
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError("AST discovery failed: " + details)
    return manifest


def top_level_assignment_index(expression: str) -> int | None:
    """Find the outer ordinary ``=`` without mistaking ``==`` for assignment.

    Candidate expressions already come from Clang assignment nodes. This small
    lexical pass merely separates that node's source spelling into its lvalue
    and rvalue while ignoring nested parentheses, strings, and comments.
    """
    parentheses = brackets = braces = 0
    quote: str | None = None
    index = 0
    while index < len(expression):
        character = expression[index]
        following = expression[index + 1] if index + 1 < len(expression) else ""
        previous = expression[index - 1] if index else ""
        if quote:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if character == "/" and following == "/":
            newline = expression.find("\n", index + 2)
            index = len(expression) if newline < 0 else newline + 1
            continue
        if character == "/" and following == "*":
            end_comment = expression.find("*/", index + 2)
            if end_comment < 0:
                return None
            index = end_comment + 2
            continue
        if character == "(":
            parentheses += 1
        elif character == ")":
            parentheses -= 1
        elif character == "[":
            brackets += 1
        elif character == "]":
            brackets -= 1
        elif character == "{":
            braces += 1
        elif character == "}":
            braces -= 1
        elif (character == "=" and not (parentheses or brackets or braces)
              and previous not in "=!<>+-*/%&|^" and following != "="):
            return index
        index += 1
    return None


def fresh_capture_name(source_text: str, location_id: int) -> str:
    """Choose a local capture name absent from the original source text."""
    suffix = 0
    while True:
        candidate = f"sfuzzer_ast_capture_{location_id}_{suffix}"
        if not re.search(r"\b" + re.escape(candidate) + r"\b", source_text):
            return candidate
        suffix += 1


def statement_replacement(source_text: str, candidate: dict[str, Any], location_id: int,
                          capture_name: str, *, is_c_source: bool) -> tuple[int, int, str, str, str]:
    """Return a safe replacement that evaluates an assignment rvalue once."""
    safety = candidate.get("rewrite_safety")
    if isinstance(safety, dict) and not safety.get("standalone_statement", False):
        raise ValueError("candidate is not a standalone statement according to its AST parent: "
                         + repr(safety.get("parent_ast_kind")))
    source_range = candidate["assignment_range"]
    begin = source_range["begin_offset"]
    end = source_range.get("end_offset_exclusive")
    if not isinstance(begin, int) or not isinstance(end, int) or begin < 0 or end <= begin:
        raise ValueError("candidate has no usable source offsets")
    expression = source_text[begin:end]
    semicolon = end
    while semicolon < len(source_text) and source_text[semicolon] in " \t\r\n":
        semicolon += 1
    if semicolon >= len(source_text) or source_text[semicolon] != ";":
        raise ValueError(f"candidate is not a standalone semicolon-terminated statement: {expression!r}")
    assignment_index = top_level_assignment_index(expression)
    if assignment_index is None:
        raise ValueError(f"candidate has no top-level ordinary assignment token: {expression!r}")
    left_hand_side = expression[:assignment_index].strip()
    right_hand_side = expression[assignment_index + 1:].strip()
    if not left_hand_side or not right_hand_side:
        raise ValueError(f"candidate has an empty assignment operand: {expression!r}")
    if is_c_source:
        # GNU C's __auto_type preserves the RHS type and evaluates it once,
        # which is the C spelling of the C++ `auto` capture below. SGFuzz's
        # supported Clang/GNU-C build environments accept this extension.
        capture_declaration = "__auto_type "
        state_cast = "((unsigned int)" + capture_name + ")"
    else:
        capture_declaration = "auto "
        state_cast = "static_cast<unsigned int>(" + capture_name + ")"
    replacement = (
        "{" + capture_declaration + capture_name + " = (" + right_hand_side + ");" +
        left_hand_side + " = " + capture_name + ";" +
        "__sfuzzer_instrument(" + str(location_id) + ", " + state_cast + ");}"
    )
    return begin, semicolon + 1, replacement, left_hand_side, right_hand_side


def instrument_file(path: Path, candidates: list[dict[str, Any]], location_start: int) -> dict[str, Any]:
    source_text = path.read_text(encoding="utf-8")
    if "__sfuzzer_instrument" in source_text:
        raise ValueError(f"refusing to instrument an already instrumented source file: {path}")
    replacements: list[tuple[int, int, str, dict[str, Any], str, str, str]] = []
    skipped_candidates: list[dict[str, Any]] = []
    location_id = location_start
    is_c_source = path.suffix == ".c"
    for candidate in candidates:
        capture_name = fresh_capture_name(source_text, location_id)
        try:
            begin, end, replacement, left_hand_side, right_hand_side = statement_replacement(
                source_text, candidate, location_id, capture_name, is_c_source=is_c_source)
        except ValueError as error:
            # Automatic mode must be conservative: preserve a source construct
            # unchanged when its safe rewriting precondition is not proven.
            skipped_candidates.append({"assignment": candidate, "reason": str(error)})
            continue
        replacements.append((begin, end, replacement, candidate, left_hand_side,
                             right_hand_side, capture_name))
        location_id += 1
    ordered = sorted(replacements, key=lambda item: item[0], reverse=True)
    previous_begin = len(source_text) + 1
    rewritten = source_text
    callback_sites: list[dict[str, Any]] = []
    for begin, end, replacement, candidate, left_hand_side, right_hand_side, capture_name in ordered:
        if end > previous_begin:
            raise ValueError(f"overlapping AST candidate ranges in {path}")
        rewritten = rewritten[:begin] + replacement + rewritten[end:]
        previous_begin = begin
        callback_sites.append({
            "location_id": location_start + len(replacements) - 1 - len(callback_sites),
            "capture_variable": capture_name,
            "left_hand_side": left_hand_side,
            "original_right_hand_side": right_hand_side,
            "assignment": candidate,
        })
    callback_sites.reverse()
    if replacements:
        path.write_text(CALLBACK_PREAMBLE + rewritten, encoding="utf-8")
    return {
        "source": str(path),
        "sha256_before": hashlib.sha256(source_text.encode()).hexdigest(),
        "sha256_after": sha256(path),
        "callback_sites": callback_sites,
        "skipped_candidates": skipped_candidates,
    }


def main() -> int:
    arguments = parse_arguments()
    input_root = arguments.input_root.resolve()
    output_root = arguments.output_root.resolve()
    if arguments.location_start < 1:
        print("--location-start must be positive.", file=sys.stderr)
        return 2
    if arguments.jobs < 1:
        print("--jobs must be positive.", file=sys.stderr)
        return 2
    if not input_root.is_dir():
        print(f"Input root does not exist: {input_root}", file=sys.stderr)
        return 2
    if output_root.exists():
        print(f"Refusing to overwrite output root: {output_root}", file=sys.stderr)
        return 2
    try:
        source_root_relative = ensure_relative(arguments.source_root, input_root, "--source-root")
        source_relatives = [ensure_relative(source, input_root, "--source") for source in arguments.source]
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    for source_relative in source_relatives:
        if not (input_root / source_relative).is_file():
            print(f"Source does not exist: {input_root / source_relative}", file=sys.stderr)
            return 2

    tracked_relatives = tracked_sources(input_root, source_root_relative, source_relatives)
    input_hashes_before = {str(relative): sha256(input_root / relative) for relative in tracked_relatives}
    try:
        shutil.copytree(input_root, output_root, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        analysis_root = output_root / source_root_relative
        if not analysis_root.is_dir():
            raise ValueError(f"Analysis root is missing in copied tree: {analysis_root}")
        with tempfile.TemporaryDirectory(prefix="sgfuzz-ast-discovery-") as temporary:
            discovery = run_detector(arguments, analysis_root, output_root, source_relatives, Path(temporary))
        if discovery["parse_failures"]:
            raise ValueError("AST discovery recorded parse failures")
        candidates_by_file: dict[Path, list[dict[str, Any]]] = {}
        analysis_project_root = analysis_root.parent
        selected_outputs = {output_root / relative for relative in source_relatives} if source_relatives else None
        for candidate in discovery["candidate_transition_writes"]:
            relative_file = Path(candidate["assignment_range"]["file"])
            output_file = (analysis_project_root / relative_file).resolve()
            try:
                output_file.relative_to(output_root)
            except ValueError:
                continue
            if selected_outputs is not None and output_file not in selected_outputs:
                continue
            candidates_by_file.setdefault(output_file, []).append(candidate)
        if not candidates_by_file and arguments.state_type:
            raise ValueError("No AST transition candidates were found in the requested source files")

        instrumented_files: list[dict[str, Any]] = []
        next_location = arguments.location_start
        for path in sorted(candidates_by_file):
            record = instrument_file(path, candidates_by_file[path], next_location)
            instrumented_files.append(record)
            next_location += len(record["callback_sites"])
        input_hashes_after = {str(relative): sha256(input_root / relative) for relative in tracked_relatives}
        if input_hashes_before != input_hashes_after:
            raise RuntimeError("Input source changed while instrumenting the copied tree")
        manifest = {
            "schema": SCHEMA,
            "mode": "copy-and-instrument",
            "input_root": str(input_root),
            "output_root": str(output_root),
            "input_source_modified": False,
            "input_source_sha256_before": input_hashes_before,
            "input_source_sha256_after": input_hashes_after,
            "state_type": arguments.state_type,
            "selection_mode": "focused" if arguments.state_type else "automatic",
            "discovery": discovery,
            "instrumented_files": instrumented_files,
            "callback_sites": sum(len(record["callback_sites"]) for record in instrumented_files),
            "skipped_candidates": sum(len(record["skipped_candidates"]) for record in instrumented_files),
        }
        arguments.manifest.parent.mkdir(parents=True, exist_ok=True)
        arguments.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"instrumented {manifest['callback_sites']} callback site(s) in copied source: {output_root}")
        print(f"manifest: {arguments.manifest}")
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"Instrumentation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

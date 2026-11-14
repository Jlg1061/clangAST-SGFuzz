#!/usr/bin/env python3
"""Discover SGFuzz state-transition writes through Clang AST JSON.

This is the read-only detection stage. It is read-only with respect
to the target: the requested JSON manifest is the only file it writes. A later
stage can consume these candidate records while instrumenting a copied tree.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterator


# C sources use the same Clang AST discovery path as C++ sources. C++-only
# constructs such as std::atomic are simply absent from a C AST.
CPP_SUFFIXES = {".c", ".cc", ".cpp", ".cxx"}
SCHEMA = "sgfuzz-clang-ast-dry-run-v3"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path,
                        help="Directory containing C/C++ translation units.")
    parser.add_argument("--source", action="append", type=Path, default=[],
                        help="Translation unit to inspect. Repeatable; defaults to all C/C++ files under --source-root.")
    parser.add_argument("--state-type",
                        help="Optional exact enum type, e.g. ix::WebSocketTransport::ReadyState. "
                             "When omitted, discover all project-defined enum storage automatically.")
    parser.add_argument("--manifest", required=True, type=Path,
                        help="Output JSON manifest. This is the only file the tool writes.")
    parser.add_argument("--clang", default="auto",
                        help="Clang executable. Default 'auto' selects clang for .c and clang++ for C++ sources.")
    parser.add_argument("--clang-arg", action="append", default=[],
                        help="Extra compiler argument; repeat as needed, e.g. --clang-arg=-std=c++14.")
    parser.add_argument("--compile-commands", type=Path,
                        help="Optional compile_commands.json. In automatic mode, use each selected "
                             "translation unit's recorded compiler, working directory, and preprocessing "
                             "arguments instead of the fallback --clang/--clang-arg values.")
    parser.add_argument("--ast-filter",
                        help="Optional Clang declaration-name filter for a smaller AST. It is a performance optimization, not a type-selection mechanism.")
    parser.add_argument("--jobs", type=int, default=1,
                        help="Concurrent translation-unit analyses in automatic mode (default: 1).")
    return parser.parse_args()


def normalized_type(type_name: str) -> str:
    """Normalize harmless spelling differences without resolving aliases."""
    return "".join(type_name.replace("const ", "").split())


def state_storage_kind(type_info: dict[str, Any], state_type: str) -> str | None:
    """Classify an explicitly configured enum type (focused mode)."""
    spelling = type_info.get("desugaredQualType") or type_info.get("qualType")
    if not spelling:
        return None
    actual = normalized_type(spelling)
    target = normalized_type(state_type)
    short_target = target.rsplit("::", 1)[-1]
    if actual in {target, short_target}:
        return "direct"
    if actual in {f"std::atomic<{target}>", f"std::atomic<{short_target}>"}:
        return "atomic"
    return None


def anonymous_enum_state_type(type_info: dict[str, Any],
                              anonymous_enum_types: dict[tuple[str, int, int], str] | None,
                              fallback: Path, project_root: Path) -> str | None:
    """Resolve a project-local anonymous enum by its AST source coordinate.

    C permits both ``enum { ... } local;`` and anonymous enum fields.  There is
    no stable spelling to compare in these cases, but Clang includes the
    declaration coordinate in the canonical type.  The collector records the
    coordinates of anonymous project ``EnumDecl`` nodes, then uses this helper
    to join an enum-typed declaration back to that project-local identity.
    """
    if not anonymous_enum_types:
        return None
    spelling = type_info.get("desugaredQualType") or type_info.get("qualType")
    if not isinstance(spelling, str) or "enum" not in spelling or "(unnamed" not in spelling:
        return None
    match = re.search(r"\(unnamed(?: enum)? at (?P<file>.+):(?P<line>\d+):(?P<column>\d+)\)", spelling)
    if not match:
        return None
    raw_file = match.group("file")
    line = int(match.group("line"))
    column = int(match.group("column"))
    path = source_path(raw_file, fallback, project_root)
    key = (str(path), line, column)
    direct_match = anonymous_enum_types.get(key)
    if direct_match is not None:
        return direct_match

    # Clang can spell this coordinate relative to the source root whereas the
    # EnumDecl position above has already been made absolute.  The current
    # translation unit owns this small map, so a unique suffix-and-coordinate
    # match is a safe fallback and avoids losing anonymous struct fields.
    normalized_raw = raw_file.lstrip("./")
    suffix_matches = [state_type for (known_file, known_line, known_column), state_type
                      in anonymous_enum_types.items()
                      if known_line == line and known_column == column
                      and known_file.replace("\\", "/").endswith(normalized_raw)]
    return suffix_matches[0] if len(suffix_matches) == 1 else None


def automatic_state_storage(type_info: dict[str, Any], enum_names: set[str],
                            anonymous_enum_types: dict[tuple[str, int, int], str] | None = None,
                            fallback: Path | None = None,
                            project_root: Path | None = None) -> tuple[str, str] | None:
    """Recognize direct or atomic storage of an enum declared in project code.

    Clang gives a canonical type on each field/variable declaration.  In
    automatic mode we unwrap ``std::atomic<T>`` if needed, then retain it only
    when T's short name corresponds to a project ``EnumDecl`` found in the
    same translation unit's AST.  This avoids treating arbitrary integer or
    standard-library fields as state storage.
    """
    spelling = type_info.get("desugaredQualType") or type_info.get("qualType")
    if not spelling:
        return None
    actual = normalized_type(spelling)
    if actual.startswith("std::atomic<") and actual.endswith(">"):
        storage_kind = "atomic"
        enum_type = actual[len("std::atomic<"):-1]
    else:
        storage_kind = "direct"
        enum_type = actual
    if fallback is not None and project_root is not None:
        anonymous_type = anonymous_enum_state_type(type_info, anonymous_enum_types,
                                                    fallback, project_root)
        if anonymous_type is not None:
            return storage_kind, anonymous_type
    if enum_type.startswith("enum"):
        enum_type = enum_type[len("enum"):]
    short_name = enum_type.rsplit("::", 1)[-1]
    if short_name not in enum_names:
        return None
    return storage_kind, enum_type


def classify_state_storage(type_info: dict[str, Any], configured_type: str | None,
                           enum_names: set[str]) -> tuple[str, str] | None:
    """Return storage kind and canonical state type in focused or auto mode."""
    if configured_type:
        storage_kind = state_storage_kind(type_info, configured_type)
        return (storage_kind, configured_type) if storage_kind else None
    return automatic_state_storage(type_info, enum_names)


def json_documents(text: str) -> list[dict[str, Any]]:
    """Clang can print several adjacent JSON declaration objects."""
    decoder = json.JSONDecoder()
    documents: list[dict[str, Any]] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text):
            break
        document, index = decoder.raw_decode(text, index)
        if not isinstance(document, dict):
            raise ValueError("Clang AST output contained a non-object JSON value.")
        documents.append(document)
    return documents


def walk(node: Any) -> Iterator[dict[str, Any]]:
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("inner", []):
        yield from walk(child)


def walk_with_file(node: Any, file_state: list[str | None] | None = None) -> Iterator[tuple[dict[str, Any], str | None]]:
    """Walk AST nodes while retaining Clang's stream-level file context.

    AST JSON omits a file name when it is the same as the preceding location,
    including across sibling declarations. A mutable state shared by the walk
    mirrors that compact encoding.
    """
    if not isinstance(node, dict):
        return
    if file_state is None:
        file_state = [None]
    location = node.get("loc") or node.get("range", {}).get("begin", {})
    if location.get("file"):
        file_state[0] = location["file"]
    yield node, file_state[0]
    for child in node.get("inner", []):
        yield from walk_with_file(child, file_state)


def display_path(raw_path: str | None, fallback: Path, project_root: Path) -> str:
    path = fallback if raw_path is None else Path(raw_path)
    if not path.is_absolute():
        project_candidate = project_root / path
        sibling_candidate = fallback.parent / path
        # Clang prints paths relative to the compiler working directory for
        # IXWebSocket, but prints just "target.cpp" for standalone fixtures.
        # Prefer the existing interpretation in either form.
        if project_candidate.exists():
            path = project_candidate
        elif sibling_candidate.exists():
            path = sibling_candidate
        else:
            path = project_candidate
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


def point(node: dict[str, Any], fallback: Path, project_root: Path,
          inherited_file: str | None = None) -> dict[str, Any]:
    location = node.get("loc") or node.get("range", {}).get("begin", {})
    return {
        "file": display_path(location.get("file") or inherited_file, fallback, project_root),
        "line": location.get("line"),
        "column": location.get("col"),
        "offset": location.get("offset"),
    }


def source_range(node: dict[str, Any], fallback: Path, project_root: Path,
                 inherited_file: str | None = None) -> dict[str, Any]:
    range_info = node.get("range", {})
    begin = range_info.get("begin", {})
    end = range_info.get("end", {})
    end_offset = end.get("offset")
    end_token_length = end.get("tokLen")
    return {
        "file": display_path(begin.get("file") or inherited_file, fallback, project_root),
        "begin_offset": begin.get("offset"),
        "end_offset": end.get("offset"),
        # Clang locations mark the *start* of the last token. Preserve tokLen
        # so a source-to-source consumer can form an exact half-open range.
        "end_token_length": end_token_length,
        "end_offset_exclusive": (end_offset + end_token_length
                                  if isinstance(end_offset, int) and isinstance(end_token_length, int)
                                  else None),
        "begin_line": begin.get("line"),
        "begin_column": begin.get("col"),
        "end_line": end.get("line"),
        "end_column": end.get("col"),
    }


def is_project_source(raw_path: str | None, source_root: Path, project_root: Path) -> bool:
    if raw_path is None:
        return False
    path = Path(raw_path)
    candidates = [path] if path.is_absolute() else [project_root / path, source_root / path]
    for candidate in candidates:
        try:
            candidate.resolve().relative_to(source_root.resolve())
            return True
        except ValueError:
            continue
    return False


def reference_id(node: dict[str, Any]) -> str | None:
    if node.get("kind") == "MemberExpr":
        return node.get("referencedMemberDecl")
    if node.get("kind") == "DeclRefExpr":
        return node.get("referencedDecl", {}).get("id")
    return None


def inferred_storage_record(node: dict[str, Any], configured_type: str | None,
                            enum_names: set[str], fallback: Path, project_root: Path,
                            inherited_file: str | None) -> tuple[str, dict[str, Any]] | None:
    """Recover a state declaration omitted by Clang's name-filtered dump.

    `-ast-dump-filter=ReadyState` retains uses of a field such as
    `_readyState`, but Clang 14 can omit the field's standalone `FieldDecl`.
    The use still carries its declaration ID, name, and type, which is enough
    for dry-run discovery and later source-location matching.
    """
    kind = node.get("kind")
    if kind == "MemberExpr":
        decl_id = node.get("referencedMemberDecl")
        declaration_kind = "FieldDecl (inferred from MemberExpr)"
        name = node.get("name")
        type_info = node.get("type", {})
    elif kind == "DeclRefExpr":
        reference = node.get("referencedDecl", {})
        if reference.get("kind") != "VarDecl":
            return None
        decl_id = reference.get("id")
        declaration_kind = "VarDecl (inferred from DeclRefExpr)"
        name = reference.get("name")
        type_info = reference.get("type", {})
    else:
        return None
    classification = classify_state_storage(type_info, configured_type, enum_names)
    if classification is None or not decl_id:
        return None
    storage_kind, state_type = classification
    canonical = type_info.get("desugaredQualType") or type_info.get("qualType")
    return decl_id, {
        "decl_id": decl_id,
        "declaration_kind": declaration_kind,
        "name": name,
        "storage_kind": storage_kind,
        "state_type": state_type,
        "spelled_type": type_info.get("qualType"),
        "canonical_type": canonical,
        "location": point(node, fallback, project_root, inherited_file),
        "declaration_location_is_inferred": True,
    }


def referenced_storage(node: dict[str, Any], storage: dict[str, dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for descendant in walk(node):
        decl_id = reference_id(descendant)
        if decl_id in storage and decl_id not in found:
            found.append(decl_id)
    return found


def has_assignment_operator(node: dict[str, Any]) -> bool:
    for descendant in walk(node):
        if descendant.get("kind") != "DeclRefExpr":
            continue
        if descendant.get("referencedDecl", {}).get("name") == "operator=":
            return True
    return False


def candidate_from_assignment(node: dict[str, Any], storage: dict[str, dict[str, Any]],
                              fallback: Path, project_root: Path,
                              inherited_file: str | None) -> dict[str, Any] | None:
    children = node.get("inner", [])
    if node.get("kind") == "BinaryOperator" and node.get("opcode") == "=":
        if not children:
            return None
        storage_ids = referenced_storage(children[0], storage)
        assignment_kind = "direct-operator="
    elif node.get("kind") == "CXXOperatorCallExpr" and has_assignment_operator(node):
        storage_ids = referenced_storage(node, storage)
        assignment_kind = "overloaded-operator="
    else:
        return None

    # A future rewrite phase will only handle one target lvalue per statement.
    # Preserve ambiguous expressions as an explicit non-candidate for now.
    if len(storage_ids) != 1:
        return None
    decl_id = storage_ids[0]
    record = storage[decl_id]
    return {
        "assignment_ast_kind": assignment_kind,
        "storage_decl_id": decl_id,
        "storage_name": record["name"],
        "storage_kind": record["storage_kind"],
        "state_type": record["state_type"],
        "assignment_location": point(node, fallback, project_root, inherited_file),
        "assignment_range": source_range(node, fallback, project_root, inherited_file),
    }


def compiler_version(clang: str) -> str:
    result = subprocess.run([clang, "--version"], text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        return f"unavailable: {result.stderr.strip()}"
    return result.stdout.splitlines()[0] if result.stdout else "unknown"


def compiler_for_unit(arguments: argparse.Namespace, unit: Path) -> str:
    """Select the matching frontend unless the user explicitly overrides it."""
    if arguments.clang != "auto":
        return arguments.clang
    return "clang" if unit.suffix == ".c" else "clang++"


def configured_compiler_version(arguments: argparse.Namespace) -> str:
    """Record both frontends when automatic mixed-language selection is used."""
    database = getattr(arguments, "compilation_database", None)
    if database:
        compilers = sorted({entry["compiler"] for entry in database.values()})
        return "; ".join(f"{compiler}: {compiler_version(compiler)}" for compiler in compilers)
    if arguments.clang != "auto":
        return compiler_version(arguments.clang)
    return f"clang: {compiler_version('clang')}; clang++: {compiler_version('clang++')}"


_COMPILE_DB_OUTPUT_OPTIONS = {"-o", "-MF", "-MJ", "-MQ", "-MT"}


def compile_database_arguments(entry: dict[str, Any], database_path: Path) -> list[str]:
    """Return the recorded argument vector, accepting both database formats."""
    argv = entry.get("arguments")
    if isinstance(argv, list) and all(isinstance(argument, str) for argument in argv):
        return list(argv)
    command = entry.get("command")
    if isinstance(command, str):
        return shlex.split(command)
    raise ValueError(f"Invalid compilation-database entry in {database_path}: no command or arguments.")


def sanitise_compile_database_entry(entry: dict[str, Any], database_path: Path,
                                    project_root: Path) -> tuple[Path, dict[str, Any]]:
    """Remove code-generation arguments while preserving a unit's preprocessor setup.

    The audit performs ``-fsyntax-only`` AST dumps.  Carrying the compile
    command's object/dependency output arguments would either be misleading or
    create target-side files, so only those output switches and the source
    operand are removed.  Include paths, defines, language flags, and warning
    flags are deliberately retained exactly as generated by CMake.
    """
    directory_raw = entry.get("directory")
    if not isinstance(directory_raw, str):
        raise ValueError(f"Invalid compilation-database entry in {database_path}: no directory.")
    directory = Path(directory_raw)
    if not directory.is_absolute():
        directory = (database_path.parent / directory).resolve()
    else:
        directory = directory.resolve()
    file_raw = entry.get("file")
    if not isinstance(file_raw, str):
        raise ValueError(f"Invalid compilation-database entry in {database_path}: no file.")
    unit = Path(file_raw)
    if not unit.is_absolute():
        unit = (directory / unit).resolve()
    else:
        unit = unit.resolve()
    argv = compile_database_arguments(entry, database_path)
    if not argv:
        raise ValueError(f"Invalid compilation-database entry in {database_path}: empty command.")
    compiler = argv[0]
    retained: list[str] = []
    index = 1
    while index < len(argv):
        argument = argv[index]
        if argument in _COMPILE_DB_OUTPUT_OPTIONS:
            index += 2
            continue
        if argument == "-c":
            index += 1
            continue
        candidate = Path(argument)
        if not candidate.is_absolute():
            candidate = directory / candidate
        try:
            is_source_operand = candidate.resolve() == unit
        except OSError:
            is_source_operand = False
        if is_source_operand or argument == file_raw:
            index += 1
            continue
        retained.append(argument)
        index += 1
    return unit, {
        "compiler": compiler,
        "arguments": retained,
        "directory": directory,
        "database_file": str(database_path.resolve()),
        "original_directory": str(directory),
        "original_file": str(unit),
    }


def load_compilation_database(arguments: argparse.Namespace, project_root: Path,
                              units: list[Path]) -> None:
    """Attach selected compile_commands entries to the parsed arguments.

    A missing entry is an error rather than a silent fallback: auditing a
    target scope with guessed flags would make the parse-coverage metric
    ambiguous.  The fallback flags remain available when no database was
    requested, which keeps the fixture and focused-mode workflows unchanged.
    """
    if arguments.compile_commands is None:
        arguments.compilation_database = {}
        return
    database_path = arguments.compile_commands.resolve()
    try:
        documents = json.loads(database_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read compilation database {database_path}: {error}") from error
    if not isinstance(documents, list):
        raise ValueError(f"Compilation database {database_path} must contain a JSON list.")
    database: dict[Path, dict[str, Any]] = {}
    for entry in documents:
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid non-object entry in compilation database {database_path}.")
        unit, details = sanitise_compile_database_entry(entry, database_path, project_root)
        # CMake databases can have multiple commands for one source, often
        # from a test target.  Keep the first generated command and preserve
        # its selected command verbatim in every unit's audit record.
        database.setdefault(unit, details)
    missing = [str(unit) for unit in units if unit not in database]
    if missing:
        sample = ", ".join(missing[:3])
        suffix = "" if len(missing) <= 3 else f" (+{len(missing) - 3} more)"
        raise ValueError(f"Compilation database lacks {len(missing)} selected unit(s): {sample}{suffix}")
    arguments.compilation_database = database


def compilation_for_unit(arguments: argparse.Namespace, unit: Path,
                         project_root: Path) -> tuple[str, list[str], Path, bool]:
    """Return compiler, flags, working directory, and provenance for one unit."""
    details = getattr(arguments, "compilation_database", {}).get(unit.resolve())
    if details is not None:
        return details["compiler"], list(details["arguments"]), details["directory"], True
    return compiler_for_unit(arguments, unit), list(arguments.clang_arg), project_root, False


def translation_units(arguments: argparse.Namespace) -> list[Path]:
    root = arguments.source_root.resolve()
    requested = [path.resolve() for path in arguments.source]
    units = requested if requested else sorted(
        path.resolve() for path in root.rglob("*") if path.suffix in CPP_SUFFIXES
    )
    if not units:
        raise ValueError("No C/C++ translation units selected.")
    for unit in units:
        if not unit.is_file():
            raise ValueError(f"Translation unit does not exist: {unit}")
        try:
            unit.relative_to(root)
        except ValueError as error:
            raise ValueError(f"Translation unit is outside --source-root: {unit}") from error
    return units


def run_clang(arguments: argparse.Namespace, unit: Path, project_root: Path) -> tuple[subprocess.CompletedProcess[str], float, list[str]]:
    compiler, compiler_args, working_directory, from_database = compilation_for_unit(arguments, unit, project_root)
    unit_arg = str(unit) if from_database else str(unit.relative_to(project_root))
    command = [
        compiler,
        *compiler_args,
        "-Xclang", "-ast-dump=json",
    ]
    if arguments.ast_filter:
        command.extend(["-Xclang", "-ast-dump-filter", "-Xclang", arguments.ast_filter])
    command.extend(["-fsyntax-only", unit_arg])
    started = time.monotonic()
    result = subprocess.run(command, cwd=working_directory, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    return result, time.monotonic() - started, command


TEXT_NODE = re.compile(r"^(?P<prefix>[|` \-]*)(?P<kind>[A-Za-z][A-Za-z0-9_]*)\b(?P<tail>.*)$")
# A compact Clang range may begin ``<line:163:5, /path/header.h:124:5>``.
# Capture a file only at a range boundary (``<`` or the comma), otherwise the
# old expression absorbed ``line:163:5, `` into the file name.
TEXT_FILE = re.compile(
    r"(?:<|,\s*)(?P<file>[^<>,\n]+?\.(?:c|cc|cpp|cxx|h|hh|hpp|hxx)):(?:line:)?\d+:\d+"
)
TEXT_NAME = re.compile(r"(?:class |struct )?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+'");


def text_node(line: str) -> tuple[int, str, str] | None:
    """Extract indentation depth, kind, and tail from Clang's text AST line."""
    match = TEXT_NODE.match(line.rstrip("\n"))
    if not match:
        return None
    prefix = match.group("prefix")
    # Clang renders each tree level with two prefix columns ("|-", "| ",
    # "  "). The root has no prefix.
    depth = max(0, len(prefix) // 2 - 1)
    return depth, match.group("kind"), match.group("tail")


def update_text_file(line: str, active_file: str | None) -> str | None:
    match = TEXT_FILE.search(line)
    return match.group("file") if match else active_file


def source_path(raw_path: str | None, fallback: Path, project_root: Path) -> Path:
    """Resolve a Clang text-AST file spelling using the JSON path rules."""
    path = fallback if raw_path is None else Path(raw_path)
    if not path.is_absolute():
        project_candidate = project_root / path
        sibling_candidate = fallback.parent / path
        if project_candidate.exists():
            path = project_candidate
        elif sibling_candidate.exists():
            path = sibling_candidate
        else:
            path = project_candidate
    return path.resolve()


def text_position(tail: str, active_file: str | None, fallback: Path,
                  project_root: Path,
                  inherited_position: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Translate a text-AST source location into a project-relative point."""
    location_match = re.search(r"<([^>]*)>", tail)
    if not location_match:
        return None
    start = location_match.group(1).split(",", 1)[0].strip()
    if start.startswith("line:"):
        raw_file = active_file
        coordinate = start[len("line:"):].split(":", 1)
    elif start.startswith("col:"):
        # Local VarDecl nodes frequently inherit their source line from an
        # enclosing DeclStmt. Keep their exact column while using that known
        # project location instead of dropping a valid enum declaration.
        if inherited_position is None:
            return None
        raw_file = str(inherited_position["_path"])
        coordinate = [str(inherited_position["line"]), start[len("col:"):].split(":", 1)[0]]
    else:
        coordinate = start.rsplit(":", 2)
        if len(coordinate) != 3:
            return None
        raw_file, coordinate = coordinate[0], coordinate[1:]
    if raw_file is None or len(coordinate) != 2:
        return None
    try:
        line = int(coordinate[0])
        column = int(coordinate[1])
    except ValueError:
        return None
    path = source_path(raw_file, fallback, project_root)
    try:
        source_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        offset = sum(len(item) for item in source_lines[:line - 1]) + column - 1
    except (OSError, UnicodeDecodeError):
        offset = None
    return {
        "file": display_path(str(path), fallback, project_root),
        "line": line,
        "column": column,
        "offset": offset,
        "_path": path,
    }


def text_assignment_range(position: dict[str, Any]) -> dict[str, Any]:
    """Build a safe, half-open range by locating the statement semicolon."""
    path = position["_path"]
    begin = position["offset"]
    end = None
    if isinstance(begin, int):
        try:
            source = path.read_text(encoding="utf-8")
            semicolon = source.find(";", begin)
            if semicolon >= 0:
                end = semicolon
        except (OSError, UnicodeDecodeError):
            pass
    return {
        "file": position["file"],
        "begin_offset": begin,
        "end_offset": end - 1 if isinstance(end, int) else None,
        "end_token_length": None,
        "end_offset_exclusive": end,
        "begin_line": position["line"],
        "begin_column": position["column"],
        "end_line": None,
        "end_column": None,
    }


def text_decl_name_and_types(tail: str) -> tuple[str | None, dict[str, Any]]:
    """Read declaration name and Clang spelling/canonical types from a text node."""
    names = TEXT_NAME.findall(tail)
    type_strings = re.findall(r"'([^']*)'", tail)
    name = names[0] if names else None
    if not type_strings:
        return name, {}
    return name, {
        "qualType": type_strings[0],
        "desugaredQualType": type_strings[-1],
    }


def text_enum_name(tail: str) -> str | None:
    """Read both `enum X` and `enum class X` spellings from text AST output."""
    quoted = TEXT_NAME.search(tail)
    if quoted:
        return quoted.group("name")
    # C named enums are commonly printed as ``... line:4:6 State`` rather
    # than with C++'s ``referenced State`` spelling. Recover that terminal
    # declaration name without treating an unnamed enum's ``definition``
    # marker as a usable type name.
    direct = re.search(
        r">\s+(?:line:\d+:\d+|col:\d+)(?:\s+referenced)?\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*$", tail)
    if direct:
        return direct.group("name")
    referenced = tail.split("referenced", 1)[-1].strip()
    class_name = re.match(r"(?:class |struct )?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b", referenced)
    return class_name.group("name") if class_name else None


def is_enum_typedef(type_info: dict[str, Any]) -> bool:
    """Return whether a C ``TypedefDecl`` aliases an enum type.

    Clang gives the ``EnumDecl`` of ``typedef enum { ... } Name`` no usable
    name. Its following ``TypedefDecl`` carries the stable project type name,
    so automatic discovery must retain that alias as an enum type as well.
    """
    spelling = type_info.get("qualType")
    return isinstance(spelling, str) and normalized_type(spelling).startswith("enum")


def text_reference_id(kind: str, tail: str) -> tuple[str | None, bool]:
    """Return declaration ID and whether this is the atomic operator= method."""
    if kind == "MemberExpr":
        match = re.search(r"(?:->|\.)(?:[A-Za-z_][A-Za-z0-9_]*)\s+(0x[0-9a-f]+)", tail)
        return (match.group(1) if match else None), False
    if kind != "DeclRefExpr":
        return None, False
    match = re.search(r"\b(?:Var|ParmVar|Field|CXXMethod)\s+(0x[0-9a-f]+)", tail)
    return (match.group(1) if match else None), "'operator='" in tail


def text_ast(command: list[str], project_root: Path) -> tuple[subprocess.Popen[str], Any]:
    """Stream Clang's complete text AST without retaining it in memory.

    The automatic collector needs the original tree indentation to identify an
    assignment's *left-hand-side child*.  Filtering out intermediate AST nodes
    destroys that relationship and can incorrectly attach a later reference to
    the wrong assignment.  A full text dump is inexpensive to stream (unlike a
    JSON DOM), and Python keeps only the small active-node stack.
    """
    # A full AST can take minutes on a real translation unit.  Clang warnings
    # must not share a bounded pipe with that streaming parser: if stderr fills
    # first, Clang blocks before closing stdout and an otherwise valid audit
    # appears to hang.  A temporary stderr file retains diagnostics without
    # throttling either stream or writing into the target checkout.
    stderr_file = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
    process = subprocess.Popen(command, cwd=project_root, text=True, stdout=subprocess.PIPE,
                               stderr=stderr_file)
    return process, stderr_file


def text_auto_enum_names(arguments: argparse.Namespace, unit: Path, project_root: Path,
                         source_root: Path) -> tuple[set[str], list[dict[str, Any]], int, str, list[str]]:
    """First automatic pass: stream Clang's text AST to enumerate project enums."""
    compiler, compiler_args, working_directory, from_database = compilation_for_unit(arguments, unit, project_root)
    unit_arg = str(unit) if from_database else str(unit.relative_to(project_root))
    command = [compiler, *compiler_args,
               "-Xclang", "-ast-dump", "-fsyntax-only", unit_arg]
    started = time.monotonic()
    process, stderr_file = text_ast(command, working_directory)
    assert process.stdout is not None
    active_file: str | None = None
    names: set[str] = set()
    records: list[dict[str, Any]] = []
    for line in process.stdout:
        active_file = update_text_file(line, active_file)
        parsed = text_node(line)
        if parsed is None:
            continue
        _, kind, tail = parsed
        if kind != "EnumDecl" or not is_project_source(active_file, source_root, project_root):
            continue
        name = text_enum_name(tail)
        position = text_position(tail, active_file, unit, project_root)
        if not name or position is None:
            continue
        names.add(name)
        records.append({"name": name, "location": {key: value for key, value in position.items() if key != "_path"}})
    returncode = process.wait()
    stderr_file.seek(0)
    stderr = stderr_file.read()
    stderr_file.close()
    return names, records, returncode, stderr, command


def text_auto_discover(arguments: argparse.Namespace, unit: Path, project_root: Path,
                       source_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]],
                                                  list[dict[str, Any]], int, str, list[str], float]:
    """Stream one AST pass, then link enum storage and writes by declaration ID."""
    compiler, compiler_args, working_directory, from_database = compilation_for_unit(arguments, unit, project_root)
    unit_arg = str(unit) if from_database else str(unit.relative_to(project_root))
    command = [compiler, *compiler_args,
               "-Xclang", "-ast-dump", "-fsyntax-only", unit_arg]
    started = time.monotonic()
    process, stderr_file = text_ast(command, working_directory)
    assert process.stdout is not None
    active_file: str | None = None
    enum_names: set[str] = set()
    enum_records: list[dict[str, Any]] = []
    raw_storage: dict[str, dict[str, Any]] = {}
    raw_candidates: list[dict[str, Any]] = []
    active_candidates: list[dict[str, Any]] = []
    project_file_cache: dict[str | None, bool] = {}
    node_stack: list[tuple[int, str, dict[str, Any] | None]] = []
    anonymous_enum_types: dict[tuple[str, int, int], str] = {}

    def finish_candidates(depth: int) -> None:
        while active_candidates and depth <= active_candidates[-1]["depth"]:
            raw_candidates.append(active_candidates.pop())

    for line in process.stdout:
        active_file = update_text_file(line, active_file)
        parsed = text_node(line)
        if parsed is None:
            continue
        depth, kind, tail = parsed
        finish_candidates(depth)
        while node_stack and depth <= node_stack[-1][0]:
            node_stack.pop()
        parent_kind = node_stack[-1][1] if node_stack else None
        declaration_position = next((position for _, kind, position in reversed(node_stack)
                                     if kind in {"DeclStmt", "RecordDecl"} and position is not None), None)
        if active_file not in project_file_cache:
            project_file_cache[active_file] = is_project_source(active_file, source_root, project_root)
        project_node = project_file_cache[active_file]

        # Existing candidate nodes receive references only from the lvalue
        # child.  For a CXX operator call, child 0 names operator= and child 1
        # is the lvalue.  For a BinaryOperator, child 0 is the lvalue.  Keeping
        # this original AST-child relation prevents a declaration reference in
        # a later statement or in an assignment's RHS from becoming a false
        # state transition.
        reference, is_operator_assignment = text_reference_id(kind, tail)
        for candidate in active_candidates:
            if depth <= candidate["depth"]:
                continue
            if depth == candidate["depth"] + 1:
                candidate["direct_child"] += 1
            if candidate["direct_child"] == candidate["lvalue_child"] and reference:
                candidate["references"].append(reference)
            if is_operator_assignment:
                candidate["has_operator_assignment"] = True

        if kind == "EnumDecl" and project_node:
            name = text_enum_name(tail)
            position = text_position(tail, active_file, unit, project_root,
                                     inherited_position=declaration_position)
            if name and position:
                enum_names.add(name)
                enum_records.append({
                    "name": name,
                    "location": {key: value for key, value in position.items() if key != "_path"},
                })
            elif position:
                state_type = (f"anonymous enum at {position['file']}:"
                              f"{position['line']}:{position['column']}")
                anonymous_enum_types[(str(position["_path"]), position["line"], position["column"])] = state_type
                enum_records.append({
                    "name": state_type,
                    "location": {key: value for key, value in position.items() if key != "_path"},
                    "declaration_kind": "anonymous EnumDecl",
                })

        if kind == "TypedefDecl" and project_node:
            name, type_info = text_decl_name_and_types(tail)
            position = text_position(tail, active_file, unit, project_root)
            if name and position and is_enum_typedef(type_info):
                enum_names.add(name)
                enum_records.append({
                    "name": name,
                    "location": {key: value for key, value in position.items() if key != "_path"},
                    "declaration_kind": "TypedefDecl",
                })

        if kind in {"FieldDecl", "VarDecl"} and project_node:
            name, type_info = text_decl_name_and_types(tail)
            declaration = re.search(r"\b(0x[0-9a-f]+)\b", tail)
            position = text_position(tail, active_file, unit, project_root,
                                     inherited_position=declaration_position)
            if declaration and position:
                declaration_id = declaration.group(1)
                raw_storage[declaration_id] = {
                    "decl_id": declaration_id,
                    "declaration_kind": kind,
                    "name": name,
                    "spelled_type": type_info.get("qualType"),
                    "canonical_type": type_info.get("desugaredQualType") or type_info.get("qualType"),
                    "type_info": type_info,
                    "location": {key: value for key, value in position.items() if key != "_path"},
                }

        node_position = (text_position(tail, active_file, unit, project_root)
                         if kind in {"DeclStmt", "RecordDecl"} else None)

        # Preserve every AST node in the stack, including library and
        # non-assignment nodes, so a candidate's immediate parent is reliable.
        node_stack.append((depth, kind, node_position))
        if not project_node or kind not in {"BinaryOperator", "CXXOperatorCallExpr"}:
            continue
        position = text_position(tail, active_file, unit, project_root)
        if position is None:
            continue
        if kind == "BinaryOperator" and re.search(r"'='\s*$", tail):
            active_candidates.append({"depth": depth, "kind": "direct", "position": position,
                                      "references": [], "direct_child": -1,
                                      "lvalue_child": 0, "has_operator_assignment": False,
                                      "parent_kind": parent_kind})
        elif kind == "CXXOperatorCallExpr" and re.search(r"'='\s*$", tail):
            active_candidates.append({"depth": depth, "kind": "atomic", "position": position,
                                      "references": [], "direct_child": -1,
                                      "lvalue_child": 1, "has_operator_assignment": False,
                                      "parent_kind": parent_kind})
    finish_candidates(-1)
    returncode = process.wait()
    stderr_file.seek(0)
    stderr = stderr_file.read()
    stderr_file.close()
    storage: dict[str, dict[str, Any]] = {}
    for declaration_id, record in raw_storage.items():
        classification = automatic_state_storage(record["type_info"], enum_names,
                                                 anonymous_enum_types, unit, project_root)
        if classification is None:
            continue
        storage_kind, state_type = classification
        storage[declaration_id] = {
            key: value for key, value in record.items() if key != "type_info"
        }
        storage[declaration_id]["storage_kind"] = storage_kind
        storage[declaration_id]["state_type"] = state_type
    candidates: list[dict[str, Any]] = []
    for raw in raw_candidates:
        if raw["kind"] == "atomic" and not raw["has_operator_assignment"]:
            continue
        storage_ids = list(dict.fromkeys(item for item in raw["references"] if item in storage))
        if len(storage_ids) != 1:
            continue
        record = storage[storage_ids[0]]
        position = raw["position"]
        candidates.append({
            "assignment_ast_kind": "direct-operator=" if raw["kind"] == "direct" else "overloaded-operator=",
            "storage_decl_id": storage_ids[0],
            "storage_name": record["name"],
            "storage_kind": record["storage_kind"],
            "state_type": record["state_type"],
            "assignment_location": {key: value for key, value in position.items() if key != "_path"},
            "assignment_range": text_assignment_range(position),
            "rewrite_safety": {
                "standalone_statement": raw["parent_kind"] == "CompoundStmt",
                "parent_ast_kind": raw["parent_kind"],
            },
        })
    return (enum_records, list(storage.values()), candidates, returncode, stderr,
            command, time.monotonic() - started)


def write_manifest(arguments: argparse.Namespace, manifest: dict[str, Any]) -> int:
    manifest["summary"] = {
        "translation_units_requested": len(manifest["translation_units"]),
        "translation_units_parsed": sum(item["status"] == "ok" for item in manifest["translation_units"]),
        "parse_failures": len(manifest["parse_failures"]),
        "enum_declarations": len(manifest["enum_declarations"]),
        "state_storage_declarations": len(manifest["state_storage"]),
        "candidate_transition_writes": len(manifest["candidate_transition_writes"]),
        "state_types_detected": len({record["state_type"] for record in manifest["state_storage"]}),
    }
    arguments.manifest.parent.mkdir(parents=True, exist_ok=True)
    arguments.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = manifest["summary"]
    print("dry-run complete: "
          f"{summary['state_storage_declarations']} state-storage declaration(s), "
          f"{summary['candidate_transition_writes']} candidate transition write(s), "
          f"{summary['parse_failures']} parse failure(s)")
    print(f"manifest: {arguments.manifest}")
    return 0 if not manifest["parse_failures"] else 1


def automatic_unit(arguments: argparse.Namespace, unit: Path, source_root: Path,
                   project_root: Path) -> dict[str, Any]:
    """Analyse one independent translation unit for automatic discovery."""
    _, _, working_directory, from_database = compilation_for_unit(arguments, unit, project_root)
    (enum_records, storage_records, candidates, discover_exit, discover_stderr,
     discover_command, elapsed) = text_auto_discover(arguments, unit, project_root, source_root)
    unit_record: dict[str, Any] = {
        "source": display_path(str(unit), unit, project_root),
        "automatic_ast_format": "clang-text-ast",
        "automatic_ast_passes": 1,
        "analysis_command": discover_command,
        "elapsed_seconds": round(elapsed, 6),
    }
    if from_database:
        unit_record["compilation_database_working_directory"] = str(working_directory)
    if discover_exit != 0:
        unit_record["status"] = "parse-failed"
        unit_record["stderr"] = discover_stderr[-4000:]
        return {"unit_record": unit_record, "enum_records": [], "storage_records": [],
                "candidates": [], "failure": {"source": unit_record["source"],
                                                   "stderr": discover_stderr[-4000:]}}
    unit_record["status"] = "ok"
    return {"unit_record": unit_record, "enum_records": enum_records,
            "storage_records": storage_records, "candidates": candidates, "failure": None}


def automatic_main(arguments: argparse.Namespace, source_root: Path, project_root: Path,
                   units: list[Path], manifest: dict[str, Any]) -> int:
    """Run independent automatic AST analyses, merging their evidence deterministically."""
    unique_storage: set[tuple[Any, ...]] = set()
    unique_enums: set[tuple[Any, ...]] = set()
    unique_writes: set[tuple[Any, ...]] = set()
    if arguments.jobs == 1:
        results = [automatic_unit(arguments, unit, source_root, project_root) for unit in units]
    else:
        with ThreadPoolExecutor(max_workers=arguments.jobs) as pool:
            results = list(pool.map(
                lambda unit: automatic_unit(arguments, unit, source_root, project_root), units))

    for result in results:
        manifest["translation_units"].append(result["unit_record"])
        if result["failure"] is not None:
            manifest["parse_failures"].append(result["failure"])
            continue
        for enum_record in result["enum_records"]:
            enum_key = (enum_record["name"], enum_record["location"]["file"], enum_record["location"]["offset"])
            if enum_key not in unique_enums:
                unique_enums.add(enum_key)
                manifest["enum_declarations"].append(enum_record)
        for record in result["storage_records"]:
            storage_key = (record["declaration_kind"], record["name"], record["location"]["file"],
                           record["location"]["offset"], record["canonical_type"])
            if storage_key not in unique_storage:
                unique_storage.add(storage_key)
                manifest["state_storage"].append(record)
        for candidate in result["candidates"]:
            candidate_key = (candidate["assignment_range"]["file"],
                             candidate["assignment_range"]["begin_offset"],
                             candidate["assignment_range"]["end_offset"],
                             candidate["storage_name"])
            if candidate_key not in unique_writes:
                unique_writes.add(candidate_key)
                manifest["candidate_transition_writes"].append(candidate)
    return write_manifest(arguments, manifest)


def main() -> int:
    arguments = parse_arguments()
    if arguments.jobs < 1:
        print("--jobs must be positive.", file=sys.stderr)
        return 2
    if not arguments.state_type and arguments.ast_filter:
        print("--ast-filter cannot be used in automatic mode because it can hide enum declarations or writes.",
              file=sys.stderr)
        return 2
    source_root = arguments.source_root.resolve()
    if not source_root.is_dir():
        print(f"Source root does not exist: {source_root}", file=sys.stderr)
        return 2
    project_root = source_root.parent
    try:
        units = translation_units(arguments)
        load_compilation_database(arguments, project_root, units)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "mode": "dry-run",
        "target_source_modified": False,
        "source_root": str(source_root),
        "state_type": arguments.state_type,
        "selection_mode": "focused" if arguments.state_type else "automatic",
        "clang": {
            "executable": arguments.clang,
            "version": configured_compiler_version(arguments),
            "arguments": arguments.clang_arg,
            "compile_commands": (str(arguments.compile_commands.resolve())
                                 if arguments.compile_commands is not None else None),
            "compile_commands_entries_available": len(getattr(arguments, "compilation_database", {})),
            "compile_commands_entries_selected": len(units) if arguments.compile_commands is not None else 0,
            "ast_filter": arguments.ast_filter,
            "jobs": arguments.jobs,
        },
        "translation_units": [],
        "enum_declarations": [],
        "state_storage": [],
        "candidate_transition_writes": [],
        "parse_failures": [],
    }
    unique_storage: set[tuple[Any, ...]] = set()
    unique_enums: set[tuple[Any, ...]] = set()
    unique_writes: set[tuple[Any, ...]] = set()

    if not arguments.state_type:
        return automatic_main(arguments, source_root, project_root, units, manifest)

    for unit in units:
        result, elapsed, command = run_clang(arguments, unit, project_root)
        unit_record: dict[str, Any] = {
            "source": display_path(str(unit), unit, project_root),
            "command": command,
            "elapsed_seconds": round(elapsed, 6),
            "exit_code": result.returncode,
        }
        if result.returncode != 0:
            unit_record["status"] = "parse-failed"
            unit_record["stderr"] = result.stderr[-4000:]
            manifest["translation_units"].append(unit_record)
            manifest["parse_failures"].append({"source": unit_record["source"],
                                               "stderr": result.stderr[-4000:]})
            continue
        try:
            documents = json_documents(result.stdout)
        except (ValueError, json.JSONDecodeError) as error:
            unit_record["status"] = "ast-json-failed"
            unit_record["error"] = str(error)
            manifest["translation_units"].append(unit_record)
            manifest["parse_failures"].append({"source": unit_record["source"], "stderr": str(error)})
            continue
        unit_record["status"] = "ok"
        unit_record["ast_documents"] = len(documents)
        manifest["translation_units"].append(unit_record)

        nodes = [item for document in documents for item in walk_with_file(document)]
        storage: dict[str, dict[str, Any]] = {}
        short_name = arguments.state_type.rsplit("::", 1)[-1] if arguments.state_type else None
        enum_names: set[str] = set()

        # First establish which enum declarations belong to the project. The
        # next pass uses that evidence to reject non-enum fields in automatic
        # mode, rather than relying on source-text patterns.
        for node, defining_file in nodes:
            if node.get("kind") != "EnumDecl":
                continue
            if not is_project_source(defining_file, source_root, project_root):
                continue
            enum_name = node.get("name")
            if not enum_name or (short_name and enum_name != short_name):
                continue
            enum_names.add(enum_name)
            enum_record = {"name": enum_name,
                           "location": point(node, unit, project_root, defining_file)}
            enum_key = (enum_record["name"], enum_record["location"]["file"], enum_record["location"]["offset"])
            if enum_key not in unique_enums:
                unique_enums.add(enum_key)
                manifest["enum_declarations"].append(enum_record)

        # Then identify storage of the focused type, or of any project enum in
        # automatic mode. The declaration ID is retained to link writes later.
        for node, defining_file in nodes:
            if node.get("kind") not in {"FieldDecl", "VarDecl"}:
                continue
            if not is_project_source(defining_file, source_root, project_root):
                continue
            classification = classify_state_storage(node.get("type", {}), arguments.state_type, enum_names)
            decl_id = node.get("id")
            if classification is None or not decl_id:
                continue
            storage_kind, state_type = classification
            record = {
                "decl_id": decl_id,
                "declaration_kind": node["kind"],
                "name": node.get("name"),
                "storage_kind": storage_kind,
                "state_type": state_type,
                "spelled_type": node.get("type", {}).get("qualType"),
                "canonical_type": node.get("type", {}).get("desugaredQualType") or node.get("type", {}).get("qualType"),
                "location": point(node, unit, project_root, defining_file),
            }
            storage[decl_id] = record
            storage_key = (record["declaration_kind"], record["name"], record["location"]["file"],
                           record["location"]["offset"], record["canonical_type"])
            if storage_key not in unique_storage:
                unique_storage.add(storage_key)
                manifest["state_storage"].append(record)

        # See inferred_storage_record() for why this second pass is needed
        # with Clang 14's filtered JSON output.
        for node, defining_file in nodes:
            if not is_project_source(defining_file, source_root, project_root):
                continue
            inferred = inferred_storage_record(node, arguments.state_type, enum_names, unit, project_root,
                                               defining_file)
            if inferred is None:
                continue
            decl_id, record = inferred
            if decl_id in storage:
                continue
            storage[decl_id] = record
            storage_key = (record["declaration_kind"], record["name"], record["location"]["file"],
                           record["location"]["offset"], record["canonical_type"])
            if storage_key not in unique_storage:
                unique_storage.add(storage_key)
                manifest["state_storage"].append(record)

        for node, defining_file in nodes:
            if not is_project_source(defining_file, source_root, project_root):
                continue
            candidate = candidate_from_assignment(node, storage, unit, project_root, defining_file)
            if candidate is None:
                continue
            candidate_key = (candidate["assignment_range"]["file"],
                             candidate["assignment_range"]["begin_offset"],
                             candidate["assignment_range"]["end_offset"],
                             candidate["storage_name"])
            if candidate_key not in unique_writes:
                unique_writes.add(candidate_key)
                manifest["candidate_transition_writes"].append(candidate)

    return write_manifest(arguments, manifest)


if __name__ == "__main__":
    raise SystemExit(main())

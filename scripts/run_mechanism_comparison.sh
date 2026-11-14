#!/usr/bin/env bash
# Compare original SGFuzz regex instrumentation and AST instrumentation on
# deterministic mechanism cases. Every source modification occurs only in a
# newly-created run directory.
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 line-direct-unscoped-control|line-direct-scoped-variant|line-atomic-unscoped-variant|ixwebsocket-primary" >&2
    exit 64
fi

case_name="$1"
case "$case_name" in
    line-direct-unscoped-control|line-direct-scoped-variant|line-atomic-unscoped-variant|ixwebsocket-primary) ;;
    *) echo "Unknown case: $case_name" >&2; exit 64 ;;
esac

root_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
repository_dir="$(CDPATH= cd -- "$root_dir/.." && pwd)"
sgfuzz_dir="$repository_dir/SGFuzz"
ixwebsocket_dir="$repository_dir/IXWebSocket"
original_instrumenter="$sgfuzz_dir/sanitizer/State_machine_instrument.py"
ast_instrumenter="$root_dir/src/sgfuzz_clang_ast_instrument.py"
run_id="mechanism-comparison-${case_name}-$(date -u +%Y%m%dT%H%M%SZ)"
run_dir="$root_dir/runs/$run_id"
raw_dir="$root_dir/raw/$run_id"

if [[ ! -f "$sgfuzz_dir/libsfuzzer.a" ]]; then
    echo "Missing $sgfuzz_dir/libsfuzzer.a; build SGFuzz before running this comparison." >&2
    exit 1
fi
if [[ ! -f "$original_instrumenter" || ! -f "$ast_instrumenter" ]]; then
    echo "Missing an instrumentation script." >&2
    exit 1
fi
if [[ -e "$run_dir" || -e "$raw_dir" ]]; then
    echo "Refusing to overwrite an existing run: $run_id" >&2
    exit 1
fi

mkdir -p "$run_dir" "$raw_dir"

write_command() {
    local path="$1"
    shift
    printf '%q ' "$@" > "$path"
    printf '\n' >> "$path"
}

state_line() {
    local replay_log="$1"
    grep -E 'states: [0-9]+ leaves: [0-9]+' "$replay_log" | tail -n 1 || true
}

callback_count() {
    local source_file="$1"
    local matches
    matches="$(grep -Eo '__sfuzzer_instrument\([0-9]+' "$source_file" || true)"
    if [[ -z "$matches" ]]; then
        printf '0\n'
    else
        printf '%s\n' "$matches" | wc -l | tr -d ' '
    fi
}

record_common_metadata() {
    local metadata="$1"
    local mode="$2"
    local target_before="$3"
    local target_after="$4"
    local callbacks="$5"
    local replay_log="$6"
    {
        printf 'case=%s\n' "$case_name"
        printf 'mode=%s\n' "$mode"
        printf 'sgfuzz_commit=%s\n' "$(git -C "$sgfuzz_dir" rev-parse HEAD)"
        printf 'sgfuzz_library_sha256=%s\n' "$(sha256sum "$sgfuzz_dir/libsfuzzer.a" | awk '{print $1}')"
        printf 'compiler=%s\n' "$(clang++ --version | head -n 1)"
        printf 'target_before_sha256=%s\n' "$(sha256sum "$target_before" | awk '{print $1}')"
        printf 'target_after_sha256=%s\n' "$(sha256sum "$target_after" | awk '{print $1}')"
        printf 'target_callback_sites=%s\n' "$callbacks"
        state_line "$replay_log"
    } > "$metadata"
}

run_fixture_mode() {
    local mode="$1"
    local input_case="$root_dir/cases/$case_name"
    local mode_dir="$run_dir/$mode"
    local source_dir="$mode_dir/source"
    local mode_raw="$raw_dir/$mode"
    local target_before="$mode_raw/target.before.cpp"
    local target_after="$mode_raw/target.after.cpp"
    local binary="$mode_dir/${case_name}_sfuzzer"

    mkdir -p "$mode_dir" "$mode_raw"
    cp "$input_case/target.cpp" "$target_before"
    if [[ "$mode" == "original" ]]; then
        mkdir -p "$source_dir"
        cp -a "$input_case/." "$source_dir/"
        local instrument_cmd=(python3 "$original_instrumenter" "$source_dir")
        write_command "$mode_raw/instrument-command.txt" "${instrument_cmd[@]}"
        "${instrument_cmd[@]}" > "$mode_raw/instrumenter.log" 2>&1
    else
        local instrument_cmd=(python3 "$ast_instrumenter"
            --input-root "$input_case"
            --output-root "$source_dir"
            --source-root .
            --source target.cpp
            --manifest "$mode_raw/instrumentation-manifest.json"
            --clang-arg=-std=c++14)
        write_command "$mode_raw/instrument-command.txt" "${instrument_cmd[@]}"
        "${instrument_cmd[@]}" > "$mode_raw/instrumenter.log" 2>&1
    fi
    cp "$source_dir/target.cpp" "$target_after"
    diff -u "$target_before" "$target_after" > "$mode_raw/target.diff" || true
    local callbacks
    callbacks="$(callback_count "$source_dir/target.cpp")"
    printf '%s\n' "$callbacks" > "$mode_raw/target-callback-count.txt"

    local build_cmd=(clang++ -std=c++14 -g -O1 -fno-omit-frame-pointer
        -fsanitize=address,undefined,fuzzer-no-link "$source_dir/target.cpp"
        "$sgfuzz_dir/libsfuzzer.a" -pthread -o "$binary")
    write_command "$mode_raw/build-command.txt" "${build_cmd[@]}"
    "${build_cmd[@]}" > "$mode_raw/build.log" 2>&1
    local replay_cmd=("$binary" -runs=0 "$source_dir/seeds")
    printf 'ASAN_OPTIONS=detect_leaks=0 ' > "$mode_raw/replay-command.txt"
    printf '%q ' "${replay_cmd[@]}" >> "$mode_raw/replay-command.txt"
    printf '\n' >> "$mode_raw/replay-command.txt"
    ASAN_OPTIONS=detect_leaks=0 "${replay_cmd[@]}" > "$mode_raw/replay.log" 2>&1
    record_common_metadata "$mode_raw/metadata.txt" "$mode" "$target_before" "$target_after" "$callbacks" "$mode_raw/replay.log"
}

run_ixwebsocket_mode() {
    local mode="$1"
    local mode_dir="$run_dir/$mode"
    local repo_copy="$mode_dir/repo"
    local mode_raw="$raw_dir/$mode"
    local target_before="$mode_raw/IXWebSocketTransport.before.cpp"
    local target_after="$mode_raw/IXWebSocketTransport.after.cpp"
    local binary="$mode_dir/ixwebsocket_state_sequence_sfuzzer"

    mkdir -p "$mode_dir" "$mode_raw"
    cp "$ixwebsocket_dir/ixwebsocket/IXWebSocketTransport.cpp" "$target_before"
    if [[ "$mode" == "original" ]]; then
        cp -a "$ixwebsocket_dir" "$repo_copy"
        local instrument_cmd=(python3 "$original_instrumenter" "$repo_copy/ixwebsocket")
        write_command "$mode_raw/instrument-command.txt" "${instrument_cmd[@]}"
        "${instrument_cmd[@]}" > "$mode_raw/instrumenter.log" 2>&1
    else
        local instrument_cmd=(python3 "$ast_instrumenter"
            --input-root "$ixwebsocket_dir"
            --output-root "$repo_copy"
            --source-root ixwebsocket
            --source ixwebsocket/IXWebSocketTransport.cpp
            --manifest "$mode_raw/instrumentation-manifest.json"
            --clang-arg=-std=c++14
            --clang-arg=-I"$repo_copy")
        write_command "$mode_raw/instrument-command.txt" "${instrument_cmd[@]}"
        "${instrument_cmd[@]}" > "$mode_raw/instrumenter.log" 2>&1
    fi
    cp "$repo_copy/ixwebsocket/IXWebSocketTransport.cpp" "$target_after"
    diff -u "$target_before" "$target_after" > "$mode_raw/target.diff" || true
    local callbacks
    callbacks="$(callback_count "$repo_copy/ixwebsocket/IXWebSocketTransport.cpp")"
    printf '%s\n' "$callbacks" > "$mode_raw/target-callback-count.txt"

    mapfile -t ix_sources < <(
        find "$repo_copy/ixwebsocket" -maxdepth 1 -type f -name '*.cpp' \
            ! -name 'IXSocketAppleSSL.cpp' ! -name 'IXSocketMbedTLS.cpp' \
            ! -name 'IXSocketOpenSSL.cpp' | sort
    )
    local build_cmd=(clang++ -std=c++14 -g -O1 -fno-omit-frame-pointer
        -fsanitize=address,undefined,fuzzer-no-link -I "$repo_copy"
        "$root_dir/cases/ixwebsocket-transport/fuzz_state_sequence.cpp"
        "${ix_sources[@]}" "$sgfuzz_dir/libsfuzzer.a" -pthread -o "$binary")
    write_command "$mode_raw/build-command.txt" "${build_cmd[@]}"
    "${build_cmd[@]}" > "$mode_raw/build.log" 2>&1
    local replay_cmd=("$binary" -runs=0 "$root_dir/cases/ixwebsocket-transport/seeds")
    printf 'ASAN_OPTIONS=detect_leaks=0 ' > "$mode_raw/replay-command.txt"
    printf '%q ' "${replay_cmd[@]}" >> "$mode_raw/replay-command.txt"
    printf '\n' >> "$mode_raw/replay-command.txt"
    ASAN_OPTIONS=detect_leaks=0 "${replay_cmd[@]}" > "$mode_raw/replay.log" 2>&1
    record_common_metadata "$mode_raw/metadata.txt" "$mode" "$target_before" "$target_after" "$callbacks" "$mode_raw/replay.log"
}

if [[ "$case_name" == "ixwebsocket-primary" ]]; then
    run_ixwebsocket_mode original
    run_ixwebsocket_mode ast
else
    run_fixture_mode original
    run_fixture_mode ast
fi

printf 'Completed deterministic mechanism comparison: %s\nRaw evidence: %s\n' "$case_name" "$raw_dir"

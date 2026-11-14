#!/usr/bin/env bash
# Build and replay the IXWebSocket state-sequence harness after fully automatic
# AST instrumentation of IXWebSocketTransport.cpp. The original IXWebSocket
# checkout is never modified.
set -euo pipefail

root_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
repository_dir="$(CDPATH= cd -- "$root_dir/.." && pwd)"
ixwebsocket_dir="$repository_dir/IXWebSocket"
sgfuzz_dir="$repository_dir/SGFuzz"
instrumenter="$root_dir/src/sgfuzz_clang_ast_instrument.py"
run_id="auto-ixwebsocket-smoke-$(date -u +%Y%m%dT%H%M%SZ)"
run_dir="$root_dir/runs/$run_id"
raw_dir="$root_dir/raw/$run_id"
repo_copy="$run_dir/repo"
binary="$run_dir/ixwebsocket_state_sequence_sfuzzer"

if [[ ! -f "$instrumenter" || ! -f "$sgfuzz_dir/libsfuzzer.a" ]]; then
    echo "Expected AST instrumenter or SGFuzz runtime library is missing." >&2
    exit 1
fi
if [[ -e "$run_dir" || -e "$raw_dir" ]]; then
    echo "Refusing to overwrite existing run directories." >&2
    exit 1
fi

mkdir -p "$run_dir" "$raw_dir"

write_command() {
    local output="$1"
    shift
    printf '%q ' "$@" > "$output"
    printf '\n' >> "$output"
}

target="$ixwebsocket_dir/ixwebsocket/IXWebSocketTransport.cpp"
sha256sum "$target" > "$raw_dir/input-source-before.sha256"

instrument_command=(python3 "$instrumenter"
    --input-root "$ixwebsocket_dir"
    --output-root "$repo_copy"
    --source-root ixwebsocket
    --source ixwebsocket/IXWebSocketTransport.cpp
    --manifest "$raw_dir/instrumentation-manifest.json"
    --clang-arg=-std=c++14
    --clang-arg=-I"$repo_copy")
write_command "$raw_dir/instrument-command.txt" "${instrument_command[@]}"
"${instrument_command[@]}" > "$raw_dir/instrumenter.log" 2>&1

mapfile -t ix_sources < <(
    find "$repo_copy/ixwebsocket" -maxdepth 1 -type f -name '*.cpp' \
        ! -name 'IXSocketAppleSSL.cpp' ! -name 'IXSocketMbedTLS.cpp' \
        ! -name 'IXSocketOpenSSL.cpp' | sort
)
build_command=(clang++ -std=c++14 -g -O1 -fno-omit-frame-pointer
    -fsanitize=address,undefined,fuzzer-no-link -I "$repo_copy"
    "$root_dir/cases/ixwebsocket-transport/fuzz_state_sequence.cpp"
    "${ix_sources[@]}" "$sgfuzz_dir/libsfuzzer.a" -pthread -o "$binary")
write_command "$raw_dir/build-command.txt" "${build_command[@]}"
"${build_command[@]}" > "$raw_dir/build.log" 2>&1

replay_command=("$binary" -runs=0 "$root_dir/cases/ixwebsocket-transport/seeds")
printf 'ASAN_OPTIONS=detect_leaks=0 ' > "$raw_dir/replay-command.txt"
printf '%q ' "${replay_command[@]}" >> "$raw_dir/replay-command.txt"
printf '\n' >> "$raw_dir/replay-command.txt"
ASAN_OPTIONS=detect_leaks=0 "${replay_command[@]}" > "$raw_dir/replay.log" 2>&1

sha256sum "$target" > "$raw_dir/input-source-after.sha256"
grep -E 'states: [0-9]+ leaves: [0-9]+' "$raw_dir/replay.log" | tail -n 1 > "$raw_dir/replay-summary.txt" || true
jq '{selection_mode, callback_sites, skipped_candidates, discovery: .discovery.summary}' \
    "$raw_dir/instrumentation-manifest.json" > "$raw_dir/instrumentation-summary.json"

printf 'Completed automatic IXWebSocket smoke replay.\nRaw evidence: %s\n' "$raw_dir"

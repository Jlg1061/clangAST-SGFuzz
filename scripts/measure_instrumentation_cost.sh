#!/usr/bin/env bash
# Measure the end-to-end source-copy-and-instrument stage on a fixed small
# atomic-enum fixture. This is a preprocessing-cost check, not a fuzzing run.
set -euo pipefail

root_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
repository_dir="$(CDPATH= cd -- "$root_dir/.." && pwd)"
sgfuzz_dir="$repository_dir/SGFuzz"
original_instrumenter="$sgfuzz_dir/sanitizer/State_machine_instrument.py"
ast_instrumenter="$root_dir/src/sgfuzz_clang_ast_instrument.py"
input_case="$root_dir/cases/line-atomic-unscoped-variant"
run_id="instrumentation-cost-$(date -u +%Y%m%dT%H%M%SZ)"
run_dir="$root_dir/runs/$run_id"
raw_dir="$root_dir/raw/$run_id"

if [[ ! -f "$original_instrumenter" || ! -f "$ast_instrumenter" ]]; then
    echo "Expected instrumenter is missing." >&2
    exit 1
fi

mkdir -p "$run_dir" "$raw_dir"
printf 'mode\trepetition\tcallback_sites\twall_ms\n' > "$raw_dir/results.tsv"

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

run_mode() {
    local mode="$1"
    local repetition="$2"
    local work_dir="$run_dir/$mode-$repetition"
    local start_ns end_ns elapsed_ms callbacks
    start_ns="$(date +%s%N)"
    if [[ "$mode" == "regex" ]]; then
        cp -a "$input_case" "$work_dir"
        python3 "$original_instrumenter" "$work_dir" > "$raw_dir/$mode-$repetition.log" 2>&1
    else
        python3 "$ast_instrumenter" \
            --input-root "$input_case" \
            --output-root "$work_dir" \
            --source-root . \
            --source target.cpp \
            --manifest "$raw_dir/$mode-$repetition-manifest.json" \
            --clang-arg=-std=c++14 > "$raw_dir/$mode-$repetition.log" 2>&1
    fi
    end_ns="$(date +%s%N)"
    elapsed_ms="$(((end_ns - start_ns) / 1000000))"
    callbacks="$(callback_count "$work_dir/target.cpp")"
    printf '%s\t%s\t%s\t%s\n' "$mode" "$repetition" "$callbacks" "$elapsed_ms" >> "$raw_dir/results.tsv"
}

for repetition in 1 2 3; do
    run_mode regex "$repetition"
    run_mode ast "$repetition"
done

{
    printf 'case=line-atomic-unscoped-variant\n'
    printf 'measurement=wall-clock milliseconds for source-copy-and-instrument stage\n'
    printf 'source_sha256=%s\n' "$(sha256sum "$input_case/target.cpp" | awk '{print $1}')"
    printf 'compiler=%s\n' "$(clang++ --version | head -n 1)"
    printf 'sgfuzz_commit=%s\n' "$(git -C "$sgfuzz_dir" rev-parse HEAD)"
} > "$raw_dir/metadata.txt"

printf 'Completed preprocessing-cost check. Raw evidence: %s\n' "$raw_dir"

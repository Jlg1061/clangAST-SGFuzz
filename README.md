# ClangAST-SGFuzz

ClangAST-SGFuzz is a source-selection and copy-only instrumentation extension
for [SGFuzz](https://github.com/bajinsheng/SGFuzz). It replaces the baseline's
regex-based discovery of state writes with Clang-AST declaration and type
analysis, while retaining SGFuzz's existing
`__sfuzzer_instrument(location, value)` callback and State Transition Tree
(STT) runtime.

The final-project question is deliberately narrow: can typed AST analysis find
and safely instrument direct, scoped, atomic, and anonymous-C enum state
storage that the regex selector misses, without regressing the cases that the
baseline already handles?

## Repository status

This repository contains the working implementation and the preliminary
mechanism evidence produced before the final evaluation. The contents of
`preliminary/` are retained for provenance; they are **not** final randomized
fuzzing results. Final experiments will write new, timestamped evidence under
`raw/` and disposable source/build copies under `runs/`.

## Layout

- `src/` — automatic detector and copy-only instrumenter.
- `cases/` — small regression cases and the IXWebSocket transport harness.
- `scripts/` — repeatable checks, deterministic replays, and result derivation.
- `environment/` — frozen upstream revisions and recorded toolchain details.
- `raw/` — retained raw output from final-project runs; initially empty.
- `preliminary/` — curated historical evidence, notes, and derived table.
- `notes/` — current attribution and AI-use disclosure.

Generated `runs/`, build directories, and external target checkouts are not
versioned.

## Prerequisites

The recorded environment is Debian/Ubuntu with Clang, Python 3, CMake, a C/C++
toolchain, OpenSSL headers, and zlib headers:

```bash
sudo apt-get update
sudo apt-get install -y clang cmake make python3 build-essential libssl-dev zlib1g-dev
```

Clone the pinned upstream inputs as siblings of this repository:

```bash
git clone https://github.com/bajinsheng/SGFuzz.git ../SGFuzz
git -C ../SGFuzz checkout 35f1ffc9482d524b03e54c7a48f4a742ba9fc9a3
git clone https://github.com/machinezone/IXWebSocket.git ../IXWebSocket
git -C ../IXWebSocket checkout 514a0b968503d758a2954ff9016289f41f489616
git clone https://github.com/h2o/h2o.git ../h2o
git -C ../h2o checkout 1e7344932fcab8767e5c1297d08d3b06db4fc5a6
(cd ../SGFuzz && ./build.sh)
```

See `environment/versions.md` for the frozen revisions and recorded runtime
archive hash.

## Short verification

From this repository root, run:

```bash
python3 scripts/test_ast_dry_run.py --output-dir raw/ast-check-$(date -u +%Y%m%dT%H%M%SZ)
```

Expected result: nine passing checks. The suite checks direct, scoped, atomic,
and anonymous-C enum cases; verifies the IXWebSocket `_readyState` discovery;
rejects a wrong type; records a parse failure; and syntax-checks rewritten C
copies. It normally completes in under one minute on the recorded machine.

The deterministic comparison runner is:

```bash
bash scripts/run_mechanism_comparison.sh line-direct-unscoped-control
```

It is useful for a mechanism check, not a randomized fuzzing-performance
claim: it uses a fixed seed corpus and `-runs=0`.

## Baseline and attribution

The baseline source instrumenter remains the upstream SGFuzz script at the
pinned revision. This repository does not vendor SGFuzz, IXWebSocket, or H2O.
Their origins and the new files are distinguished in
`THIRD_PARTY_NOTICES.md` and `notes/ai-use.md`.

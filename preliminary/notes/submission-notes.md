# Decisions, contributions, and deviations

## Prediction recorded before the implementation

On 2026-10-21, before the AST detector was written, the prediction was that
the regex baseline would retain the direct unscoped control but miss the scoped
and atomic variants, while AST type/declaration matching would recover one
callback in each. For IXWebSocket, the prediction was that the atomic
`_readyState` write would be recovered. The original note is included as
`notes/predictions-before-implementation.md`; the submitted comparison table
and raw commands are in `derived/sgfuzz-vs-ast-comparison.md` and `raw/`.

## Technical decision: do not use a name-filtered AST as the rule

**2026-10-21 hypothesis.** A Clang AST dump filtered on `ReadyState` would
retain all relevant declarations and writes. **Evidence.** The initial failed
attempt at `raw/ast-dry-run-20261021T202027Z/manifest.json` found the enum but
zero storage declarations and zero writes. The filter selects declaration names,
not all uses of a type. **Action.** Automatic discovery now streams a complete text
AST once and keeps the parent/child relation needed to examine only the lvalue
of `=`; see `src/sgfuzz_clang_ast_dry_run.py:547-684`. **Verification.** The
fresh nine-check suite at `raw/ast-fidelity-regression-20261023T213245Z/summary.json`
passed, including automatic identification of `_readyState` at line 237; it
also verified that the original IXWebSocket source hash was unchanged.

This ruled out the alternative explanation that the primary miss was caused
only by a broken compiler invocation or a modified target. It does not yet
rule out false positives arising from enums with the same short name in a
large project.

## Individual contributions and reuse

- Reused unchanged: SGFuzz callback ABI and runtime archive, the original
  regex baseline at the pinned upstream revision, IXWebSocket source at its
  pinned revision, and the Assignment 2 harness/cases.
- Will D'Andrade: formulated the project framing and AST-aware direction;
  wrote and organized the report; and designed the evaluation questions,
  interpretation, limitations, and future-experiment plan.
- Jose Luis Gonzalez Paniagua: implemented automatic project-enum and
  atomic-enum discovery, AST declaration-ID-to-write matching, and safe
  copy-only rewriting; created the deterministic cases and runners; executed
  and preserved the IXWebSocket/H2O evidence; generated results; and assembled
  the deliverable. The new code is limited to `src/` and supporting `scripts/`.
- Both authors: reviewed the evidence-backed claims and limited the conclusions
  to instrumentation fidelity and build safety.
- Verification: `bash -n scripts/*.sh`, `python3 -m py_compile src/*.py
  scripts/*.py`, the nine-check integration suite, source SHA-256 checks, and
  sanitizer-enabled deterministic replays. Evidence is retained under `raw/`.

## Known deviations

The primary prototype replay automatically discovers four writes in the chosen
`IXWebSocketTransport.cpp` translation unit. A separate 36-translation-unit
default CMake build is retained as build-and-replay evidence, but the prototype
does not yet consume a project's compilation database. Both methods use the
same frozen targets, harness, four seeds, C++14 compiler, SGFuzz runtime, and
`-runs=0` replay budget. The remaining source-selection difference is a
limitation, not evidence of semantic full-project coverage.

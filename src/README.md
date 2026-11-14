# Source changes

Everything in this directory is new project code; no file in the upstream
SGFuzz checkout is changed. The baseline is retrieved at commit
`35f1ffc9482d524b03e54c7a48f4a742ba9fc9a3`; its original source instrumenter
is `sanitizer/State_machine_instrument.py`.

- `sgfuzz_clang_ast_dry_run.py` is the read-only automatic detector. It emits a
  manifest of project enum storage and AST-confirmed writes.
- `sgfuzz_clang_ast_instrument.py` copies an input tree, consumes that detector,
  and inserts the existing SGFuzz `__sfuzzer_instrument` callback only in the
  copy.

The prototype deliberately retains the baseline callback ABI and
`libsfuzzer.a`; it replaces only source-level discovery and rewriting. See
`THIRD_PARTY_NOTICES.md` and `notes/ai-use.md` for authorship, reuse, and
verification.

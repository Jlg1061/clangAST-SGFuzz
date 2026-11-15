# Superseded Stage A setup attempt

The control condition completed successfully, but the AST condition was stopped
before source instrumentation because the Stage A runner pre-created the
instrumenter's output directory. The copy-only instrumenter correctly refused
to overwrite it. No IXWebSocket source was modified.

The runner was corrected to let the instrumenter create its own copied output
tree, and the unchanged pre-registered plan was rerun successfully under
`stage-a-feasibility-20261115T101000Z/`. This directory is retained as setup
diagnostic evidence only, not a Stage A result.

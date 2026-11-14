# Predictions recorded before implementation

**Recorded:** 2026-10-21, before writing or running the AST detector.

## Rule to test

For a configured enum type `E`, the prototype will treat declarations of `E`
and `std::atomic<E>` as state storage, then identify standalone assignments to
that storage from the Clang AST. It will initially support ordinary assignment
and atomic `operator=` only; it will not yet support `.store(...)`, aliases,
macros, header-only writes, or assignments embedded inside larger expressions.

## Predictions for the later fresh pilot

| Case ID | Baseline target callback sites / STT | Full AST prototype target callback sites / STT | Atomic-recognition ablation | Reason |
| --- | --- | --- | --- | --- |
| `ixwebsocket-transport` | 0 / 1 state, 1 leaf | 1 / 5 states, 1 leaf | 0 / 1 state, 1 leaf | The target field is `std::atomic<WebSocketTransport::ReadyState>` and the replay has four transition values. |
| `line-direct-unscoped-control` | 1 / 4 states, 1 leaf | 1 / 4 states, 1 leaf | 1 / 4 states, 1 leaf | Direct unscoped enum assignment is an existing baseline success and regression check. |
| `line-direct-scoped-variant` | 0 / 1 state, 1 leaf | 1 / 4 states, 1 leaf | 1 / 4 states, 1 leaf | The state is a direct `enum class`; no atomic wrapper is needed. |
| `line-atomic-unscoped-variant` | 0 / 1 state, 1 leaf | 1 / 4 states, 1 leaf | 0 / 1 state, 1 leaf | The state is an atomic unscoped enum; the wrapper is the changed factor. |

`states` is the number of observed STT nodes, including the root. `leaves` is
the number of observed distinct root-to-leaf transition sequences. The stated
replays are deterministic, so repeated randomized trials are not applicable to
this pilot. A later randomized fuzzing comparison, if performed, will use at
least three independent runs per configuration.

The primary expectation is intentionally narrow: recovering a target callback
site and a non-root state-transition trace proves the mechanism executes. It
does not prove increased bug discovery or full network-protocol coverage.

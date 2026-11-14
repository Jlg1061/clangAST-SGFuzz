# Case map and independent expectations

All cases are deterministic `-runs=0` replays. `states` counts observed STT
nodes including the root; `leaves` counts distinct observed root-to-leaf state
transition sequences. Repeated observations of one sequence do not add leaves.

| ID | Role | Input | Independent expectation |
| --- | --- | --- | --- |
| `ixwebsocket-transport` | Real-project mechanism case | The four fixed seed sequences and `fuzz_state_sequence.cpp`, run against upstream `IXWebSocketTransport.cpp` | The regex pass misses the atomic `ReadyState` field; AST discovery finds `_readyState` and its assignment at line 237. |
| `line-direct-unscoped-control` | Matched control and regression | `target.cpp` plus one fixed seed | Both methods insert one callback and replay 4 states, 1 leaf. |
| `line-direct-scoped-variant` | Additional variant | `target.cpp` plus one fixed seed | Regex misses the scoped enum; the AST method inserts one callback and replays 4 states, 1 leaf. |
| `line-atomic-unscoped-variant` | Additional variant and mechanism check | `target.cpp` plus one fixed seed | Regex misses atomic enum storage; the AST method inserts one callback and replays 4 states, 1 leaf. |
| `c-direct-enum-control` | C-language regression | `target.c` plus one fixed seed | Automatic AST discovery finds the direct `typedef enum` C assignment. The copied GNU C output receives one callback and passes `clang -std=gnu11 -fsyntax-only`. |
| `c-anonymous-enum-control` | C-language remediation regression | `target.c` | Automatic AST discovery finds one local and one struct-field anonymous enum assignment. The copied GNU C output receives two callbacks and passes `clang -std=gnu11 -fsyntax-only`. |

The primary target source is retrieved at the commit in
`environment/versions.md`, rather than copied into this package. This avoids
shipping an unnecessary full upstream repository while preserving its exact
identifier and the harness/seeds used here.

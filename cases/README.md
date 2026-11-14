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
| `c-direct-enum-control` | C-language regression | `target.c` plus one fixed seed | Both methods instrument the direct `typedef enum` assignment. The copied GNU C output compiles and replaying four transitions yields 5 states (root included), 1 leaf. |
| `c-anonymous-enum-control` | C-language remediation regression | `target.c` plus one fixed seed | Regex safely inserts no callback. AST finds one local and one struct-field anonymous enum assignment, compiles the copied GNU C output, and replays 3 states (root included), 1 leaf. |

The primary target source is retrieved at the commit in
`environment/versions.md`, rather than copied into this package. This avoids
shipping an unnecessary full upstream repository while preserving its exact
identifier and the harness/seeds used here.

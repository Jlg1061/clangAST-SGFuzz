# Stage A — feasibility pilot

Raw index: `raw/stage-a-feasibility-20261115T101000Z/index.json`.

The control and AST conditions compile the same 36-unit IXWebSocket library source list, use the same sanitizer flags, SGFuzz runtime, transport harness, four fixed inputs, and `-runs=0` replay budget. Only the AST condition rewrites a copied `IXWebSocketTransport.cpp`.

| Condition | Callback sites: expected / observed | STT nodes: expected / observed | STT leaves: expected / observed | Build + replay |
| --- | --- | --- | --- | --- |
| `control` | 0 / 0 | 1 / 1 | 1 / 1 | **PASS** |
| `ast` | 5 / 5 | 7 / 7 | 2 / 2 | **PASS** |

Overall: **PASS**.

`states` includes the STT root. A leaf is a distinct root-to-leaf transition sequence. The AST condition's non-root nodes and two leaves show that at least one inserted callback resolves to the SGFuzz runtime and executes under the fixed harness. This harness is designed around `setReadyState`; it does not establish execution of all five inserted sites, nor higher fuzzing throughput, coverage, or bug discovery.

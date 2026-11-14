# Regression-control results

Source index: `raw/regression-controls-20261114T164000Z/index.json`.

All expected outcomes were recorded in `experiments/regression-controls.json` before this run.

| Case | Role | Regex: expected / observed | AST: expected / observed | Result |
| --- | --- | --- | --- | --- |
| `line-direct-unscoped-control` | baseline-preservation control | 1 callback; 4 states, 1 leaf / 1 callback; 4 states, 1 leaf | 1 callback; 4 states, 1 leaf / 1 callback; 4 states, 1 leaf | **PASS** |
| `line-direct-scoped-variant` | scoped-enum mechanism control | 0 callbacks; 1 state, 1 leaf / 0 callbacks; 1 state, 1 leaf | 1 callback; 4 states, 1 leaf / 1 callback; 4 states, 1 leaf | **PASS** |
| `line-atomic-unscoped-variant` | atomic-enum mechanism control | 0 callbacks; 1 state, 1 leaf / 0 callbacks; 1 state, 1 leaf | 1 callback; 4 states, 1 leaf / 1 callback; 4 states, 1 leaf | **PASS** |
| `c-direct-enum-control` | C-language baseline-preservation control | 1 callback; 5 states, 1 leaf / 1 callback; 5 states, 1 leaf | 1 callback; 5 states, 1 leaf / 1 callback; 5 states, 1 leaf | **PASS** |
| `c-anonymous-enum-control` | anonymous-C-enum regression control | 0 callbacks; 1 state, 1 leaf / 0 callbacks; 1 state, 1 leaf | 2 callbacks; 3 states, 1 leaf / 2 callbacks; 3 states, 1 leaf | **PASS** |

Overall: **PASS**.

# Regression-control results

Source index: `raw/regression-controls-20261114T163000Z/index.json`.

All expected outcomes were recorded in `experiments/regression-controls.json` before this run.

| Case | Role | Regex: expected / observed | AST: expected / observed | Result |
| --- | --- | --- | --- | --- |
| `line-direct-unscoped-control` | baseline-preservation control | 1 callback(s); 4 state(s), 1 leaf/leaves / 1 callback(s); 4 state(s), 1 leaf/leaves | 1 callback(s); 4 state(s), 1 leaf/leaves / 1 callback(s); 4 state(s), 1 leaf/leaves | **PASS** |
| `line-direct-scoped-variant` | scoped-enum mechanism control | 0 callback(s); 1 state(s), 1 leaf/leaves / 0 callback(s); 1 state(s), 1 leaf/leaves | 1 callback(s); 4 state(s), 1 leaf/leaves / 1 callback(s); 4 state(s), 1 leaf/leaves | **PASS** |
| `line-atomic-unscoped-variant` | atomic-enum mechanism control | 0 callback(s); 1 state(s), 1 leaf/leaves / 0 callback(s); 1 state(s), 1 leaf/leaves | 1 callback(s); 4 state(s), 1 leaf/leaves / 1 callback(s); 4 state(s), 1 leaf/leaves | **PASS** |
| `c-direct-enum-control` | C-language baseline-preservation control | 1 callback(s); 5 state(s), 1 leaf/leaves / 1 callback(s); 5 state(s), 1 leaf/leaves | 1 callback(s); 5 state(s), 1 leaf/leaves / 1 callback(s); 5 state(s), 1 leaf/leaves | **PASS** |
| `c-anonymous-enum-control` | anonymous-C-enum regression control | 0 callback(s); 1 state(s), 1 leaf/leaves / 0 callback(s); 1 state(s), 1 leaf/leaves | 2 callback(s); 3 state(s), 1 leaf/leaves / 2 callback(s); 3 state(s), 1 leaf/leaves | **PASS** |

Overall: **PASS**.

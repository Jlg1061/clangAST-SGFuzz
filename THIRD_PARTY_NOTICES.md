# Third-party code and provenance

## New project code

The AST detector and copy-only instrumenter in `src/`, the cases in `cases/`,
and the supporting runners in `scripts/` are the project implementation by
Jose Luis Gonzalez Paniagua and Will D'Andrade. Individual responsibilities and
AI-use verification are documented in `notes/ai-use.md`.

## Reused upstream components

This repository does not include copies of these upstream projects:

| Component | Use in this project | Pinned revision |
| --- | --- | --- |
| [SGFuzz](https://github.com/bajinsheng/SGFuzz) | Baseline regex selector, callback ABI, and `libsfuzzer.a` runtime | `35f1ffc9482d524b03e54c7a48f4a742ba9fc9a3` |
| [IXWebSocket](https://github.com/machinezone/IXWebSocket) | Real C++ stateful target and the source of `_readyState` | `514a0b968503d758a2954ff9016289f41f489616` |
| [H2O](https://github.com/h2o/h2o) | C build-safety target and paper-aligned HTTP/2 target | `1e7344932fcab8767e5c1297d08d3b06db4fc5a6` |

Retrieve and use each upstream project under its own license. This repository
changes neither an upstream checkout nor the baseline SGFuzz runtime; the
instrumenter always writes a separate copied tree.

# Real-project static audit

Raw index: `raw/real-project-static-audit-20261114T173000Z/index.json`.

Each row uses a frozen translation-unit list and a pinned checkout. H2O uses the fresh CMake compilation database; IXWebSocket uses its recorded default-library flags. The tool only writes manifests outside target checkouts.

| Scope | Lang. | TU parsed / frozen | Parse failures | Enum decls. | Enum storage | Candidate writes | CompoundStmt-parent writes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `ixwebsocket-default-library` | C++ | 36 / 36 | 0 | 18 | 17 | 17 | 17 |
| `h2o-h2o-fuzzer-http2` | C | 124 / 124 | 0 | 98 | 73 | 171 | 147 |

A *candidate write* is an AST assignment whose lvalue resolves to automatically selected project-local enum or `std::atomic<enum>` storage. A *CompoundStmt-parent write* additionally has a compound-statement AST parent. That is one conservative source-rewriter precondition, not a claim that the site is fully build-validated. Neither column claims that every candidate is a semantic protocol state; manual validation is a separate evaluation step.

Wall-clock audit time: 534.55 s. The sum of per-translation-unit elapsed times is larger because analyses run concurrently.

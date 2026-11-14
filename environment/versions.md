# Frozen versions and environment

## Upstream inputs

| Component | Repository | Frozen revision | Retrieval |
| --- | --- | --- |
| SGFuzz baseline | `https://github.com/bajinsheng/SGFuzz.git` | `35f1ffc9482d524b03e54c7a48f4a742ba9fc9a3` |
| IXWebSocket primary target | `https://github.com/machinezone/IXWebSocket.git` | `514a0b968503d758a2954ff9016289f41f489616` |
| H2O build-safety target | `https://github.com/h2o/h2o.git` | `1e7344932fcab8767e5c1297d08d3b06db4fc5a6` |

Retrieve each with `git clone` followed by `git -C <directory> checkout <revision>`.

The local SGFuzz checkout has unrelated pre-existing modifications to
`FuzzerStateMachine.h`, `build.sh`, and `environment/`. They are not part of
this project. The new source-level implementation is in this repository and
is used against a clean checkout of the frozen SGFuzz revision above.

## Local toolchain recorded on 2026-10-22

| Item | Value |
| --- | --- |
| OS family | Debian-based Linux |
| Architecture | x86_64 |
| CPU available to the run | 12 logical CPUs; AMD Ryzen 9 3900X 12-Core Processor |
| Memory available to the run | 5.7 GiB RAM; 975 MiB swap |
| Python | 3.11.2 |
| Clang | Debian Clang 14.0.6 |
| Parse language mode | C++14 for IXWebSocket; GNU C11 for C cases and H2O |
| SGFuzz runtime archive | `libsfuzzer.a`, SHA-256 `783e83c4102e0490f4ee828c40041f01a2018f9f6d9ead14b6c963dd4ab50559` |

Automatic discovery chooses `clang++` for C++ and `clang` for C by default, with
`-Xclang -ast-dump` and `-fsyntax-only`, streaming the textual AST so that
parent/child relations can identify the assignment left-hand side. Focused
debug mode retains a JSON-AST path. Neither discovery mode links or executes
the target. The IXWebSocket pilot uses the same C++14 mode, compiler, target
commit, and SGFuzz runtime for baseline and prototype. The full-target
IXWebSocket check uses its default CMake target with TLS disabled and Zlib
enabled (36 C++ translation units). The H2O check uses the 124 C source files
listed by the `h2o-fuzzer-http2` CMake dependency closure, with
OSS-Fuzz-related options and MRuby disabled; its exact configure and build
commands are retained in `preliminary/raw/`; final-project commands and runs
will be retained in `raw/`. The C regression uses
Clang in GNU C11 mode because copy-and-instrument emits `__auto_type` to
preserve an assignment right-hand side's type while evaluating it once.

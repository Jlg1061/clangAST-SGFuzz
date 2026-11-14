# Superseded audit attempt

This first fresh audit attempt was stopped before H2O produced a manifest. The
IXWebSocket manifest, frozen plan, H2O CMake configuration, source list, and
compilation database are retained unedited as raw diagnostic evidence.

Diagnosis: `text_ast` streamed Clang's large AST through stdout but read stderr
only after stdout closed. A warning-heavy H2O translation unit can fill the
stderr pipe first, leaving Clang blocked and preventing stdout closure. The
analyzer was changed to retain stderr in a temporary file outside the target
checkout, then the unchanged audit plan was rerun under a new timestamp.

# Test-only CMake overlay for the instrumented H2O smoke target.
# H2O's OSS_FUZZ branch expects an externally supplied FuzzingEngine.  This
# interface target satisfies that dependency while the forced archive link
# supplies SGFuzz's modified LibFuzzer main and __sfuzzer_instrument runtime.
add_library(FuzzingEngine INTERFACE)
add_link_options(-Wl,--whole-archive,/home/kunaicito/Documents/759/SGFuzz/libsfuzzer.a,--no-whole-archive)

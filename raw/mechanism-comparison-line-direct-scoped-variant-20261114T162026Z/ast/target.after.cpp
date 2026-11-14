#ifndef SFUZZ_INSTRUMENT
#define SFUZZ_INSTRUMENT
#ifdef __cplusplus
extern "C" {
#endif
void __sfuzzer_instrument(unsigned int location, unsigned int state_value);
__attribute__((weak)) void __sfuzzer_instrument(unsigned int location, unsigned int state_value) { location = 0; state_value = 0; }
#ifdef __cplusplus
}
#endif
#endif /* SFUZZ_INSTRUMENT */
#include <cstddef>
#include <cstdint>

enum class ConnectionState : unsigned int
{
    CONNECTING,
    OPEN,
    CLOSING,
    CLOSED
};

static ConnectionState current_state = ConnectionState::CLOSED;

static void set_state(ConnectionState next_state)
{
    {auto sfuzzer_ast_capture_1_0 = (next_state);current_state = sfuzzer_ast_capture_1_0;__sfuzzer_instrument(1, static_cast<unsigned int>(sfuzzer_ast_capture_1_0));}
}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size)
{
    for (size_t index = 0; index < size; ++index)
    {
        switch (data[index])
        {
            case 'G': set_state(ConnectionState::CONNECTING); break;
            case 'O': set_state(ConnectionState::OPEN); break;
            case 'X': set_state(ConnectionState::CLOSING); break;
            case 'D': set_state(ConnectionState::CLOSED); break;
            default: break;
        }
    }
    return 0;
}

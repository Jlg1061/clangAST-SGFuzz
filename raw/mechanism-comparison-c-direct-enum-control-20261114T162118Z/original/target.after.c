#ifndef SFUZZ_INSTRUMENT
#define SFUZZ_INSTRUMENT
#ifdef __cplusplus
extern "C" {
#endif
void __sfuzzer_instrument(unsigned int location, unsigned int state_value);
__attribute__((weak)) void __sfuzzer_instrument(unsigned int location, unsigned int state_value){location=0;state_value=0;};
#ifdef __cplusplus
}
#endif /* __cplusplus */
#endif /* SFUZZ_INSTRUMENT */
#include <stddef.h>
#include <stdint.h>

typedef enum
{
    CONNECTING,
    OPEN,
    CLOSING,
    CLOSED
} ConnectionState;

static ConnectionState current_state = CLOSED;

static void set_state(ConnectionState next_state)
{
{__sfuzzer_instrument(1, next_state);    current_state = next_state;}
}

int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size)
{
    for (size_t index = 0; index < size; ++index)
    {
        switch (data[index])
        {
            case 'G': set_state(CONNECTING); break;
            case 'O': set_state(OPEN); break;
            case 'X': set_state(CLOSING); break;
            case 'D': set_state(CLOSED); break;
            default: break;
        }
    }
    return 0;
}

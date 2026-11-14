#include <atomic>
#include <cstddef>
#include <cstdint>

enum ConnectionState
{
    CONNECTING,
    OPEN,
    CLOSING,
    CLOSED
};

static std::atomic<ConnectionState> current_state{CLOSED};

static void set_state(ConnectionState next_state)
{
    current_state = next_state;
}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size)
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

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
    current_state = next_state;
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

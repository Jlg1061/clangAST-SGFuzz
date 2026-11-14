#include <cstddef>
#include <cstdint>

#include <ixwebsocket/IXWebSocketTransport.h>

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size)
{
    ix::WebSocketTransport transport;
    for (size_t index = 0; index < size; ++index)
    {
        switch (data[index])
        {
            case 'G': transport.setReadyState(ix::WebSocketTransport::ReadyState::CONNECTING); break;
            case 'O': transport.setReadyState(ix::WebSocketTransport::ReadyState::OPEN); break;
            case 'X': transport.setReadyState(ix::WebSocketTransport::ReadyState::CLOSING); break;
            case 'D': transport.setReadyState(ix::WebSocketTransport::ReadyState::CLOSED); break;
            default: break;
        }
    }
    return 0;
}

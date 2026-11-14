#include <stddef.h>
#include <stdint.h>

struct transport {
    enum { TRANSPORT_IDLE, TRANSPORT_OPEN } field_state;
};

int drive_transport(unsigned char local_open, unsigned char field_open)
{
    enum { LOCAL_IDLE, LOCAL_OPEN } local_state;
    struct transport transport = {TRANSPORT_IDLE};

    local_state = local_open ? LOCAL_OPEN : LOCAL_IDLE;
    transport.field_state = field_open ? TRANSPORT_OPEN : TRANSPORT_IDLE;
    return local_state == LOCAL_OPEN && transport.field_state == TRANSPORT_OPEN;
}

int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size)
{
    if (size < 2)
        return 0;
    (void)drive_transport(data[0] == '1', data[1] == '1');
    return 0;
}

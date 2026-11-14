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
#include <stddef.h>
#include <stdint.h>

struct transport {
    enum { TRANSPORT_IDLE, TRANSPORT_OPEN } field_state;
};

int drive_transport(unsigned char local_open, unsigned char field_open)
{
    enum { LOCAL_IDLE, LOCAL_OPEN } local_state;
    struct transport transport = {TRANSPORT_IDLE};

    {__auto_type sfuzzer_ast_capture_1_0 = (local_open ? LOCAL_OPEN : LOCAL_IDLE);local_state = sfuzzer_ast_capture_1_0;__sfuzzer_instrument(1, ((unsigned int)sfuzzer_ast_capture_1_0));}
    {__auto_type sfuzzer_ast_capture_2_0 = (field_open ? TRANSPORT_OPEN : TRANSPORT_IDLE);transport.field_state = sfuzzer_ast_capture_2_0;__sfuzzer_instrument(2, ((unsigned int)sfuzzer_ast_capture_2_0));}
    return local_state == LOCAL_OPEN && transport.field_state == TRANSPORT_OPEN;
}

int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size)
{
    if (size < 2)
        return 0;
    (void)drive_transport(data[0] == '1', data[1] == '1');
    return 0;
}

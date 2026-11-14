#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>

int bind(int fd, const struct sockaddr *address, socklen_t length)
{
    static int (*real_bind)(int, const struct sockaddr *, socklen_t);
    if (real_bind == NULL)
        real_bind = dlsym(RTLD_NEXT, "bind");
    int result = real_bind(fd, address, length);
    if (result != 0 && address != NULL && address->sa_family == AF_UNIX) {
        const struct sockaddr_un *unix_address = (const struct sockaddr_un *)address;
        fprintf(stderr, "SGFUZZ_BIND_DIAGNOSTIC errno=%d (%s) path=%s length=%u\n",
                errno, strerror(errno), unix_address->sun_path, (unsigned)length);
    }
    return result;
}

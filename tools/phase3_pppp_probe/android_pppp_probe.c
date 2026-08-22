#include <stdint.h>
#include <stddef.h>

#define RTLD_NOW 2
#define RTLD_LOCAL 0

extern void *dlopen(const char *filename, int flags);
extern void *dlsym(void *handle, const char *symbol);
extern char *dlerror(void);

static long sys_write(int fd, const void *buf, unsigned long count) {
    register long x0 __asm__("x0") = fd;
    register long x1 __asm__("x1") = (long)buf;
    register long x2 __asm__("x2") = (long)count;
    register long x8 __asm__("x8") = 64;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}

static unsigned long str_len(const char *s) {
    unsigned long n = 0;
    if (!s) return 0;
    while (s[n]) n++;
    return n;
}

static void put_str(const char *s) {
    if (s) sys_write(1, s, str_len(s));
}

static void put_hex32(uint32_t value) {
    static const char hex[] = "0123456789ABCDEF";
    char out[11];
    out[0] = '0';
    out[1] = 'x';
    for (int i = 0; i < 8; i++) {
        out[2 + i] = hex[(value >> (28 - i * 4)) & 0xF];
    }
    out[10] = '\n';
    sys_write(1, out, sizeof(out));
}

int main(int argc, char **argv) {
    const char *library = argc > 1 ? argv[1] : "/data/local/tmp/yi-phase3/libPPPP_API.so";

    put_str("phase3_bionic_probe=START\n");
    put_str("stage=before_dlopen\n");

    void *handle = dlopen(library, RTLD_NOW | RTLD_LOCAL);
    if (!handle) {
        put_str("stage=dlopen_failed\n");
        put_str("dlerror=");
        put_str(dlerror());
        put_str("\n");
        return 20;
    }

    put_str("stage=after_dlopen\n");
    void *sym = dlsym(handle, "PPPP_GetAPIVersion");
    if (!sym) {
        put_str("stage=dlsym_failed\n");
        put_str("dlerror=");
        put_str(dlerror());
        put_str("\n");
        return 21;
    }

    put_str("stage=before_call\n");
    int32_t (*get_api_version)(void) = (int32_t (*)(void))sym;
    uint32_t version = (uint32_t)get_api_version();
    put_str("PPPP_GetAPIVersion_hex=");
    put_hex32(version);
    put_str("phase3_bionic_probe=PASS\n");
    return 0;
}

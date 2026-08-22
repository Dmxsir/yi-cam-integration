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

static int resolve_required(void *handle, const char *name, void **out) {
    *out = dlsym(handle, name);
    if (*out) return 0;
    put_str("stage=dlsym_failed\n");
    put_str("symbol=");
    put_str(name);
    put_str("\ndlerror=");
    put_str(dlerror());
    put_str("\n");
    return -1;
}

int main(int argc, char **argv) {
    const char *library = argc > 1 ? argv[1] : "/data/local/tmp/yi-phase3/libPPPP_API.so";

    put_str("phase3c_init_probe=START\n");
    put_str("stage=before_dlopen\n");

    void *handle = dlopen(library, RTLD_NOW | RTLD_LOCAL);
    if (!handle) {
        put_str("stage=dlopen_failed\ndlerror=");
        put_str(dlerror());
        put_str("\n");
        return 20;
    }
    put_str("stage=after_dlopen\n");

    void *init_sym = NULL;
    void *version_sym = NULL;
    void *deinit_sym = NULL;
    if (resolve_required(handle, "PPPP_Initialize", &init_sym) != 0) return 21;
    if (resolve_required(handle, "PPPP_GetAPIVersion", &version_sym) != 0) return 22;
    if (resolve_required(handle, "PPPP_DeInitialize", &deinit_sym) != 0) return 23;
    put_str("stage=after_dlsym\n");

    int32_t (*initialize)(const unsigned char *, int) =
        (int32_t (*)(const unsigned char *, int))init_sym;
    int32_t (*get_api_version)(void) = (int32_t (*)(void))version_sym;
    int32_t (*deinitialize)(void) = (int32_t (*)(void))deinit_sym;

    /* Exact lifecycle inputs used by the already-proven Android oracle. */
    static const unsigned char init_string[] = {0};
    const int max_sessions = 12;

    put_str("stage=before_initialize\n");
    int32_t init_rc = initialize(init_string, max_sessions);
    put_str("PPPP_Initialize_rc_hex=");
    put_hex32((uint32_t)init_rc);
    if (init_rc != 0) {
        put_str("phase3c_init_probe=INIT_FAILED\n");
        return 30;
    }
    put_str("stage=after_initialize\n");

    uint32_t version = (uint32_t)get_api_version();
    put_str("PPPP_GetAPIVersion_hex=");
    put_hex32(version);
    if (version != 0xA2030401u) {
        put_str("stage=unexpected_api_version\n");
        put_str("stage=before_deinitialize_after_version_mismatch\n");
        int32_t cleanup_rc = deinitialize();
        put_str("PPPP_DeInitialize_rc_hex=");
        put_hex32((uint32_t)cleanup_rc);
        return 31;
    }

    put_str("stage=before_deinitialize\n");
    int32_t deinit_rc = deinitialize();
    put_str("PPPP_DeInitialize_rc_hex=");
    put_hex32((uint32_t)deinit_rc);
    if (deinit_rc != 0) {
        put_str("phase3c_init_probe=DEINIT_FAILED\n");
        return 32;
    }

    put_str("stage=after_deinitialize\n");
    put_str("phase3c_init_probe=PASS\n");
    return 0;
}

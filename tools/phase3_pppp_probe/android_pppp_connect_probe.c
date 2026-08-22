#include <stdint.h>
#include <stddef.h>

#define RTLD_NOW 2
#define RTLD_LOCAL 0
#define MAX_FIELD 4096

extern void *dlopen(const char *filename, int flags);
extern void *dlsym(void *handle, const char *symbol);
extern char *dlerror(void);

static long sys_read(int fd, void *buf, unsigned long count) {
    register long x0 __asm__("x0") = fd;
    register long x1 __asm__("x1") = (long)buf;
    register long x2 __asm__("x2") = (long)count;
    register long x8 __asm__("x8") = 63;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}

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
    for (int i = 0; i < 8; i++) out[2 + i] = hex[(value >> (28 - i * 4)) & 0xF];
    out[10] = '\n';
    sys_write(1, out, sizeof(out));
}

static int read_exact(void *buf, unsigned long count) {
    unsigned char *p = (unsigned char *)buf;
    unsigned long done = 0;
    while (done < count) {
        long rc = sys_read(0, p + done, count - done);
        if (rc <= 0) return -1;
        done += (unsigned long)rc;
    }
    return 0;
}

static uint16_t be16(const unsigned char *p) {
    return (uint16_t)(((uint16_t)p[0] << 8) | p[1]);
}

static uint32_t be32(const unsigned char *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

static int magic_ok(const unsigned char *p) {
    return p[0] == 'Y' && p[1] == '3' && p[2] == 'D' && p[3] == '1';
}

int main(int argc, char **argv) {
    const char *library = argc > 1 ? argv[1] : "/data/local/tmp/yi-phase3d/libPPPP_API.so";
    unsigned char header[20];
    char did[MAX_FIELD];
    char server[MAX_FIELD];
    char device_key[MAX_FIELD];
    unsigned char init_string[1] = {0};
    int initialized = 0;
    int handle_value = -1;

    put_str("phase3d_connect_probe=START\n");
    put_str("stage=before_config_read\n");
    if (read_exact(header, sizeof(header)) != 0 || !magic_ok(header)) {
        put_str("stage=config_header_failed\n");
        return 10;
    }

    unsigned char wakeup = header[4];
    unsigned char flag = header[5];
    uint16_t udp_port = be16(header + 6);
    uint32_t did_len = be32(header + 8);
    uint32_t server_len = be32(header + 12);
    uint32_t key_len = be32(header + 16);
    if (did_len == 0 || server_len == 0 || key_len == 0 ||
        did_len >= MAX_FIELD || server_len >= MAX_FIELD || key_len >= MAX_FIELD) {
        put_str("stage=config_length_failed\n");
        return 11;
    }
    if (read_exact(did, did_len) || read_exact(server, server_len) || read_exact(device_key, key_len)) {
        put_str("stage=config_payload_failed\n");
        return 12;
    }
    did[did_len] = '\0';
    server[server_len] = '\0';
    device_key[key_len] = '\0';
    put_str("stage=after_config_read\n");

    put_str("stage=before_dlopen\n");
    void *so = dlopen(library, RTLD_NOW | RTLD_LOCAL);
    if (!so) {
        put_str("stage=dlopen_failed\n");
        put_str("dlerror="); put_str(dlerror()); put_str("\n");
        return 20;
    }
    put_str("stage=after_dlopen\n");

    int (*pppp_initialize)(const unsigned char *, int) =
        (int (*)(const unsigned char *, int))dlsym(so, "PPPP_Initialize");
    int (*pppp_deinitialize)(void) =
        (int (*)(void))dlsym(so, "PPPP_DeInitialize");
    int (*pppp_connect)(const char *, unsigned char, unsigned short, char *, char *) =
        (int (*)(const char *, unsigned char, unsigned short, char *, char *))dlsym(so, "PPPP_Connect");
    int (*pppp_wakeup_connect)(const char *, unsigned char, unsigned short, char *, char *) =
        (int (*)(const char *, unsigned char, unsigned short, char *, char *))dlsym(so, "PPPP_WakeUp_And_Connect");
    int (*pppp_connect_break)(const char *) =
        (int (*)(const char *))dlsym(so, "PPPP_Connect_Break");
    int (*pppp_force_close)(int) =
        (int (*)(int))dlsym(so, "PPPP_ForceClose");

    if (!pppp_initialize || !pppp_deinitialize || !pppp_connect || !pppp_wakeup_connect ||
        !pppp_connect_break || !pppp_force_close) {
        put_str("stage=dlsym_failed\n");
        put_str("dlerror="); put_str(dlerror()); put_str("\n");
        return 21;
    }
    put_str("stage=after_dlsym\n");

    put_str("stage=before_initialize\n");
    int init_rc = pppp_initialize(init_string, 12);
    put_str("PPPP_Initialize_rc_hex="); put_hex32((uint32_t)init_rc);
    if (init_rc != 0) return 30;
    initialized = 1;
    put_str("stage=after_initialize\n");

    put_str(wakeup ? "connect_function=PPPP_WakeUp_And_Connect\n" : "connect_function=PPPP_Connect\n");
    put_str("connection_flag_hex="); put_hex32((uint32_t)flag);
    put_str("stage=before_connect\n");
    handle_value = wakeup
        ? pppp_wakeup_connect(did, flag, udp_port, server, device_key)
        : pppp_connect(did, flag, udp_port, server, device_key);
    put_str("PPPP_Connect_rc_hex="); put_hex32((uint32_t)handle_value);
    put_str("stage=after_connect\n");

    if (handle_value < 0) {
        if (initialized) {
            put_str("stage=before_deinitialize_after_connect_failure\n");
            int deinit_rc = pppp_deinitialize();
            put_str("PPPP_DeInitialize_rc_hex="); put_hex32((uint32_t)deinit_rc);
        }
        put_str("phase3d_connect_probe=CONNECT_FAILED\n");
        return 40;
    }

    put_str("stage=before_connect_break\n");
    int break_rc = pppp_connect_break(did);
    put_str("PPPP_Connect_Break_rc_hex="); put_hex32((uint32_t)break_rc);

    put_str("stage=before_force_close\n");
    int close_rc = pppp_force_close(handle_value);
    put_str("PPPP_ForceClose_rc_hex="); put_hex32((uint32_t)close_rc);

    put_str("stage=before_deinitialize\n");
    int deinit_rc = pppp_deinitialize();
    initialized = 0;
    put_str("PPPP_DeInitialize_rc_hex="); put_hex32((uint32_t)deinit_rc);
    put_str("stage=after_deinitialize\n");

    if (break_rc != 0 || close_rc != 0 || deinit_rc != 0) {
        put_str("phase3d_connect_probe=CLEANUP_FAILED\n");
        return 41;
    }

    put_str("phase3d_connect_probe=PASS\n");
    return 0;
}

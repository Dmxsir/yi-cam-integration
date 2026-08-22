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

static void put_u32(uint32_t value) {
    char out[11];
    int pos = 10;
    out[pos--] = '\n';
    if (value == 0) {
        out[pos--] = '0';
    } else {
        while (value && pos >= 0) {
            out[pos--] = (char)('0' + (value % 10));
            value /= 10;
        }
    }
    sys_write(1, out + pos + 1, (unsigned long)(10 - pos));
}

static void put_i32(int32_t value) {
    if (value < 0) {
        put_str("-");
        put_u32((uint32_t)(-(int64_t)value));
    } else {
        put_u32((uint32_t)value);
    }
}

static uint32_t be32(const unsigned char *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

static int read_exact_fd(void *buf, unsigned long count) {
    unsigned char *p = (unsigned char *)buf;
    unsigned long done = 0;
    while (done < count) {
        long rc = sys_read(0, p + done, count - done);
        if (rc <= 0) return -1;
        done += (unsigned long)rc;
    }
    return 0;
}

static int magic_ok(const unsigned char *p) {
    return p[0] == 'Y' && p[1] == 'O' && p[2] == 'N' && p[3] == '1';
}

int main(int argc, char **argv) {
    const char *library = argc > 1 ? argv[1] : "/data/local/tmp/yi-online-status/libPPPP_API.so";
    unsigned char header[12];
    char p2pid[MAX_FIELD], server[MAX_FIELD];
    unsigned char init_string[1] = {0};
    int initialized = 0;
    int result_code = 1;

    put_str("yi_online_probe=START\n");
    if (read_exact_fd(header, sizeof(header)) != 0 || !magic_ok(header)) {
        put_str("stage=config_header_failed\n");
        return 10;
    }

    uint32_t p2pid_len = be32(header + 4);
    uint32_t server_len = be32(header + 8);
    if (!p2pid_len || !server_len || p2pid_len >= MAX_FIELD || server_len >= MAX_FIELD) {
        put_str("stage=config_length_failed\n");
        return 11;
    }
    if (read_exact_fd(p2pid, p2pid_len) != 0 || read_exact_fd(server, server_len) != 0) {
        put_str("stage=config_payload_failed\n");
        return 12;
    }
    p2pid[p2pid_len] = '\0';
    server[server_len] = '\0';

    void *so = dlopen(library, RTLD_NOW | RTLD_LOCAL);
    if (!so) {
        put_str("stage=dlopen_failed\n");
        put_str("dlerror="); put_str(dlerror()); put_str("\n");
        return 20;
    }

    int (*pppp_initialize)(const unsigned char *, int) =
        (int (*)(const unsigned char *, int))dlsym(so, "PPPP_Initialize");
    int (*pppp_deinitialize)(void) =
        (int (*)(void))dlsym(so, "PPPP_DeInitialize");
    int (*pppp_check_dev_online)(const char *, const char *, int, int *) =
        (int (*)(const char *, const char *, int, int *))dlsym(so, "PPPP_CheckDevOnline");

    if (!pppp_initialize || !pppp_deinitialize || !pppp_check_dev_online) {
        put_str("stage=dlsym_failed\n");
        put_str("dlerror="); put_str(dlerror()); put_str("\n");
        return 21;
    }

    int init_rc = pppp_initialize(init_string, 12);
    put_str("PPPP_Initialize_rc="); put_i32((int32_t)init_rc);
    if (init_rc != 0) return 30;
    initialized = 1;

    int last_online_time = 0;
    int online_rc = pppp_check_dev_online(p2pid, server, 2, &last_online_time);
    put_str("PPPP_CheckDevOnline_rc="); put_i32((int32_t)online_rc);
    put_str("last_online_time="); put_u32((uint32_t)last_online_time);

    if (online_rc == 1) {
        put_str("device_online=online\n");
        result_code = 0;
    } else if (online_rc == 0) {
        put_str("device_online=offline\n");
        result_code = 0;
    } else {
        put_str("device_online=unknown\n");
        result_code = 0;
    }

    if (initialized) {
        int deinit_rc = pppp_deinitialize();
        put_str("PPPP_DeInitialize_rc="); put_i32((int32_t)deinit_rc);
        if (deinit_rc != 0 && result_code == 0) result_code = 31;
    }

    put_str(result_code == 0 ? "yi_online_probe=PASS\n" : "yi_online_probe=FAIL\n");
    return result_code;
}

#include <stdint.h>
#include <stddef.h>

#define RTLD_NOW 2
#define RTLD_LOCAL 0
#define MAX_FIELD 4096
#define MAX_UNIT 4096
#define TNP_VERSION 2
#define CMD_SET_RESOLUTION 4881
#define CMD_SET_RESOLUTION_RESP 4882

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
    out[0] = '0'; out[1] = 'x';
    for (int i = 0; i < 8; i++) out[2 + i] = hex[(value >> (28 - i * 4)) & 0xF];
    out[10] = '\n';
    sys_write(1, out, sizeof(out));
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

static uint16_t be16(const unsigned char *p) {
    return (uint16_t)(((uint16_t)p[0] << 8) | p[1]);
}

static uint32_t be32(const unsigned char *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

static int magic_ok(const unsigned char *p) {
    return p[0] == 'Y' && p[1] == '3' && p[2] == 'E' && p[3] == '1';
}

int main(int argc, char **argv) {
    const char *library = argc > 1 ? argv[1] : "/data/local/tmp/yi-phase3e/libPPPP_API.so";
    unsigned char header[36];
    char did[MAX_FIELD], server[MAX_FIELD], device_key[MAX_FIELD];
    unsigned char unit1[MAX_UNIT], unit2[MAX_UNIT], unit3[MAX_UNIT], stop_unit[MAX_UNIT];
    unsigned char response[MAX_UNIT];
    unsigned char init_string[1] = {0};
    int initialized = 0;
    int handle_value = -1;
    int live_started = 0;
    int result_code = 1;
    int stop_rc = 0;

    put_str("phase3e_tnp_probe=START\n");
    put_str("stage=before_config_read\n");
    if (read_exact_fd(header, sizeof(header)) != 0 || !magic_ok(header)) {
        put_str("stage=config_header_failed\n");
        return 10;
    }

    unsigned char wakeup = header[4];
    unsigned char flag = header[5];
    uint16_t udp_port = be16(header + 6);
    uint32_t did_len = be32(header + 8);
    uint32_t server_len = be32(header + 12);
    uint32_t key_len = be32(header + 16);
    uint32_t unit1_len = be32(header + 20);
    uint32_t unit2_len = be32(header + 24);
    uint32_t unit3_len = be32(header + 28);
    uint32_t stop_len = be32(header + 32);

    if (!did_len || !server_len || !key_len ||
        did_len >= MAX_FIELD || server_len >= MAX_FIELD || key_len >= MAX_FIELD ||
        !unit1_len || !unit2_len || !unit3_len || !stop_len ||
        unit1_len > MAX_UNIT || unit2_len > MAX_UNIT || unit3_len > MAX_UNIT || stop_len > MAX_UNIT) {
        put_str("stage=config_length_failed\n");
        return 11;
    }

    if (read_exact_fd(did, did_len) || read_exact_fd(server, server_len) || read_exact_fd(device_key, key_len) ||
        read_exact_fd(unit1, unit1_len) || read_exact_fd(unit2, unit2_len) ||
        read_exact_fd(unit3, unit3_len) || read_exact_fd(stop_unit, stop_len)) {
        put_str("stage=config_payload_failed\n");
        return 12;
    }
    did[did_len] = '\0'; server[server_len] = '\0'; device_key[key_len] = '\0';
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
    int (*pppp_write)(int, unsigned char, const unsigned char *, int) =
        (int (*)(int, unsigned char, const unsigned char *, int))dlsym(so, "PPPP_Write");
    int (*pppp_read)(int, unsigned char, unsigned char *, int *, int) =
        (int (*)(int, unsigned char, unsigned char *, int *, int))dlsym(so, "PPPP_Read");

    if (!pppp_initialize || !pppp_deinitialize || !pppp_connect || !pppp_wakeup_connect ||
        !pppp_connect_break || !pppp_force_close || !pppp_write || !pppp_read) {
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
    put_str("stage=before_connect\n");
    handle_value = wakeup
        ? pppp_wakeup_connect(did, flag, udp_port, server, device_key)
        : pppp_connect(did, flag, udp_port, server, device_key);
    put_str("PPPP_Connect_rc_hex="); put_hex32((uint32_t)handle_value);
    if (handle_value < 0) {
        result_code = 40;
        goto cleanup;
    }
    put_str("stage=after_connect\n");

    /* Preserve the proven 4881 -> 9029 -> 768 burst: no diagnostics between writes. */
    put_str("stage=before_startup_burst\n");
    int write1_rc = pppp_write(handle_value, 0, unit1, (int)unit1_len);
    int write2_rc = pppp_write(handle_value, 0, unit2, (int)unit2_len);
    if (write2_rc >= 0) live_started = 1;
    int write3_rc = pppp_write(handle_value, 0, unit3, (int)unit3_len);
    put_str("stage=after_startup_burst\n");
    put_str("PPPP_Write_4881_rc_hex="); put_hex32((uint32_t)write1_rc);
    put_str("PPPP_Write_9029_rc_hex="); put_hex32((uint32_t)write2_rc);
    put_str("PPPP_Write_768_rc_hex="); put_hex32((uint32_t)write3_rc);
    if (write1_rc < 0 || write2_rc < 0 || write3_rc < 0) {
        result_code = 50;
        goto cleanup;
    }

    put_str("stage=before_channel0_read_header\n");
    int read_size = 8;
    int read_header_rc = pppp_read(handle_value, 0, response, &read_size, -1);
    put_str("PPPP_Read_header_rc_hex="); put_hex32((uint32_t)read_header_rc);
    put_str("PPPP_Read_header_size="); put_u32((uint32_t)read_size);
    if (read_header_rc < 0 || read_size != 8) {
        result_code = 60;
        goto cleanup;
    }

    uint32_t data_size = be32(response + 4);
    if (response[1] != 3 || data_size < 40 || data_size > MAX_UNIT - 8) {
        put_str("stage=invalid_tnp_response_header\n");
        result_code = 61;
        goto cleanup;
    }

    read_size = (int)data_size;
    put_str("stage=before_channel0_read_body\n");
    int read_body_rc = pppp_read(handle_value, 0, response + 8, &read_size, -1);
    put_str("PPPP_Read_body_rc_hex="); put_hex32((uint32_t)read_body_rc);
    put_str("PPPP_Read_body_size="); put_u32((uint32_t)read_size);
    if (read_body_rc < 0 || read_size != (int)data_size) {
        result_code = 62;
        goto cleanup;
    }

    uint32_t response_version = response[0];
    uint32_t response_command = be16(response + 8);
    uint32_t response_number = be16(response + 10);
    uint32_t auth_result = be32(response + 16);
    put_str("tnp_response_version="); put_u32(response_version);
    put_str("tnp_response_command="); put_u32(response_command);
    put_str("tnp_response_command_number="); put_u32(response_number);
    put_str("tnp_auth_result="); put_u32(auth_result);

    if (response_version != TNP_VERSION || response_command != CMD_SET_RESOLUTION_RESP ||
        response_number != 1 || auth_result != 0) {
        put_str("phase3e_tnp_auth=FAIL\n");
        result_code = 63;
        goto cleanup;
    }
    put_str("phase3e_tnp_auth=PASS\n");
    result_code = 0;

cleanup:
    if (handle_value >= 0 && live_started) {
        put_str("stage=before_stop_live\n");
        stop_rc = pppp_write(handle_value, 0, stop_unit, (int)stop_len);
        put_str("PPPP_Write_767_rc_hex="); put_hex32((uint32_t)stop_rc);
        if (stop_rc < 0 && result_code == 0) result_code = 70;
        live_started = 0;
    }
    if (handle_value >= 0) {
        put_str("stage=before_connect_break\n");
        int break_rc = pppp_connect_break(did);
        put_str("PPPP_Connect_Break_rc_hex="); put_hex32((uint32_t)break_rc);
        put_str("stage=before_force_close\n");
        int close_rc = pppp_force_close(handle_value);
        put_str("PPPP_ForceClose_rc_hex="); put_hex32((uint32_t)close_rc);
        if ((break_rc != 0 || close_rc != 0) && result_code == 0) result_code = 71;
        handle_value = -1;
    }
    if (initialized) {
        put_str("stage=before_deinitialize\n");
        int deinit_rc = pppp_deinitialize();
        put_str("PPPP_DeInitialize_rc_hex="); put_hex32((uint32_t)deinit_rc);
        if (deinit_rc != 0 && result_code == 0) result_code = 72;
        initialized = 0;
    }

    if (result_code == 0) {
        put_str("phase3e_tnp_probe=PASS\n");
        return 0;
    }
    put_str("phase3e_tnp_probe=FAIL\n");
    return result_code;
}

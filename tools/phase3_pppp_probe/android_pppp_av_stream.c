#include <stdint.h>
#include <stddef.h>

#define RTLD_NOW 2
#define RTLD_LOCAL 0
#define MAX_FIELD 4096
#define MAX_UNIT 4096
#define MAX_MEDIA (2U * 1024U * 1024U)
#define TNP_VERSION 2
#define CMD_START_REALTIME 9029
#define CMD_START_AUDIO 768
#define CMD_SET_RESOLUTION_RESP 4882
#define LIVE_REFRESH_DELAY_MS 5900U

extern void *dlopen(const char *filename, int flags);
extern void *dlsym(void *handle, const char *symbol);
extern char *dlerror(void);
extern void *malloc(unsigned long size);
extern void free(void *ptr);

typedef unsigned long pthread_t;
extern int pthread_create(pthread_t *thread, const void *attr, void *(*start)(void *), void *arg);
extern int pthread_join(pthread_t thread, void **retval);

static volatile int stop_requested = 0;
static volatile int stdout_lock = 0;

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

typedef struct {
    long tv_sec;
    long tv_nsec;
} kernel_timespec;

static long sys_nanosleep(const kernel_timespec *request) {
    register long x0 __asm__("x0") = (long)request;
    register long x1 __asm__("x1") = 0;
    register long x8 __asm__("x8") = 101;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x1), "r"(x8) : "memory");
    return x0;
}

static int wait_interruptible_ms(uint32_t milliseconds) {
    uint32_t remaining = milliseconds;
    while (remaining && !stop_requested) {
        uint32_t step = remaining > 100U ? 100U : remaining;
        kernel_timespec request;
        request.tv_sec = 0;
        request.tv_nsec = (long)step * 1000000L;
        if (sys_nanosleep(&request) < 0 && !stop_requested) return -1;
        remaining -= step;
    }
    return stop_requested ? 1 : 0;
}

static unsigned long str_len(const char *s) {
    unsigned long n = 0;
    if (!s) return 0;
    while (s[n]) n++;
    return n;
}

static void log_str(const char *s) {
    if (s) sys_write(2, s, str_len(s));
}

static void log_hex32(uint32_t value) {
    static const char hex[] = "0123456789ABCDEF";
    char out[11];
    out[0] = '0'; out[1] = 'x';
    for (int i = 0; i < 8; i++) out[2 + i] = hex[(value >> (28 - i * 4)) & 0xF];
    out[10] = '\n';
    sys_write(2, out, sizeof(out));
}

static void log_u32(uint32_t value) {
    char out[11];
    int pos = 10;
    out[pos--] = '\n';
    if (value == 0) out[pos--] = '0';
    else while (value && pos >= 0) { out[pos--] = (char)('0' + value % 10); value /= 10; }
    sys_write(2, out + pos + 1, (unsigned long)(10 - pos));
}

static int read_exact_stdin(void *buf, unsigned long count) {
    unsigned char *p = (unsigned char *)buf;
    unsigned long done = 0;
    while (done < count) {
        long rc = sys_read(0, p + done, count - done);
        if (rc <= 0) return -1;
        done += (unsigned long)rc;
    }
    return 0;
}

static int write_exact_stdout(const void *buf, unsigned long count) {
    const unsigned char *p = (const unsigned char *)buf;
    unsigned long done = 0;
    while (done < count) {
        long rc = sys_write(1, p + done, count - done);
        if (rc <= 0) return -1;
        done += (unsigned long)rc;
    }
    return 0;
}

static void copy_bytes(unsigned char *destination, const unsigned char *source, uint32_t count) {
    for (uint32_t i = 0; i < count; i++) destination[i] = source[i];
}

static uint16_t be16(const unsigned char *p) {
    return (uint16_t)(((uint16_t)p[0] << 8) | p[1]);
}

static uint32_t be32(const unsigned char *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

static void store_be16(unsigned char *p, uint16_t value) {
    p[0] = (unsigned char)(value >> 8);
    p[1] = (unsigned char)value;
}

static void store_be32(unsigned char *p, uint32_t value) {
    p[0] = (unsigned char)(value >> 24);
    p[1] = (unsigned char)(value >> 16);
    p[2] = (unsigned char)(value >> 8);
    p[3] = (unsigned char)value;
}

static int magic_ok(const unsigned char *p) {
    return p[0] == 'Y' && p[1] == '3' && p[2] == 'F' && p[3] == '1';
}

typedef int (*pppp_read_fn)(int, unsigned char, unsigned char *, int *, int);
typedef int (*pppp_write_fn)(int, unsigned char, const unsigned char *, int);

static int read_exact_pppp(pppp_read_fn fn, int handle, unsigned char channel,
                           unsigned char *buffer, uint32_t count) {
    uint32_t done = 0;
    while (done < count && !stop_requested) {
        int requested = (int)(count - done);
        int rc = fn(handle, channel, buffer + done, &requested, -1);
        if (rc < 0 || requested <= 0) return rc < 0 ? rc : -1;
        done += (uint32_t)requested;
    }
    return done == count ? 0 : -1;
}

static void lock_stdout(void) {
    while (__sync_lock_test_and_set(&stdout_lock, 1)) { }
}

static void unlock_stdout(void) {
    __sync_lock_release(&stdout_lock);
}

typedef struct {
    pppp_read_fn read_fn;
    int handle;
    unsigned char channel;
    unsigned char expected_io_type;
    uint32_t emitted;
    int rc;
} reader_ctx;

typedef struct {
    pppp_write_fn write_fn;
    int handle;
    const unsigned char *start_unit;
    uint32_t start_len;
    const unsigned char *audio_unit;
    uint32_t audio_len;
} refresh_ctx;

static int emit_record(unsigned char channel, const unsigned char *outer,
                       const unsigned char *body, uint32_t body_size) {
    unsigned char header[12] = {'Y','A','V','1', channel, 0, 0, 0, 0, 0, 0, 0};
    store_be32(header + 8, body_size + 8U);
    lock_stdout();
    int rc = 0;
    if (write_exact_stdout(header, sizeof(header)) ||
        write_exact_stdout(outer, 8) ||
        write_exact_stdout(body, body_size)) rc = -1;
    unlock_stdout();
    return rc;
}

static void *reader_main(void *opaque) {
    reader_ctx *ctx = (reader_ctx *)opaque;
    ctx->rc = 0;
    while (!stop_requested) {
        unsigned char outer[8];
        int rc = read_exact_pppp(ctx->read_fn, ctx->handle, ctx->channel, outer, 8);
        if (rc < 0) {
            if (!stop_requested) ctx->rc = rc;
            return 0;
        }
        uint32_t data_size = be32(outer + 4);
        if (outer[0] != TNP_VERSION || outer[1] != ctx->expected_io_type ||
            data_size < 24 || data_size > MAX_MEDIA) {
            ctx->rc = -200 - ctx->channel;
            return 0;
        }
        unsigned char *body = (unsigned char *)malloc(data_size);
        if (!body) { ctx->rc = -210 - ctx->channel; return 0; }
        rc = read_exact_pppp(ctx->read_fn, ctx->handle, ctx->channel, body, data_size);
        if (rc < 0) {
            free(body);
            if (!stop_requested) ctx->rc = rc;
            return 0;
        }
        if (emit_record(ctx->channel, outer, body, data_size)) {
            free(body);
            ctx->rc = -220 - ctx->channel;
            stop_requested = 1;
            return 0;
        }
        free(body);
        ctx->emitted++;
    }
    return 0;
}

static void *refresh_main(void *opaque) {
    refresh_ctx *ctx = (refresh_ctx *)opaque;
    if (wait_interruptible_ms(LIVE_REFRESH_DELAY_MS) != 0 || stop_requested) return 0;

    int start_rc = ctx->write_fn(ctx->handle, 0, ctx->start_unit, (int)ctx->start_len);
    log_str("PPPP_Write_9029_rc_hex="); log_hex32((uint32_t)start_rc);
    if (start_rc < 0 || stop_requested) return 0;

    int audio_rc = ctx->write_fn(ctx->handle, 0, ctx->audio_unit, (int)ctx->audio_len);
    log_str("PPPP_Write_768_rc_hex="); log_hex32((uint32_t)audio_rc);
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 2) { log_str("phase3g_argument_error\n"); return 2; }
    const char *library = argv[1];

    unsigned char header[36];
    char did[MAX_FIELD], server[MAX_FIELD], device_key[MAX_FIELD];
    unsigned char unit1[MAX_UNIT], unit2[MAX_UNIT], unit3[MAX_UNIT], stop_unit[MAX_UNIT];
    unsigned char initial_start_unit[MAX_UNIT], refresh_start_unit[MAX_UNIT], refresh_audio_unit[MAX_UNIT];
    unsigned char response[MAX_UNIT];
    unsigned char init_string[1] = {0};
    int initialized = 0;
    int handle_value = -1;
    int live_started = 0;
    int result_code = 1;
    int normal_stop = 0;

    log_str("phase3g_av_stream=START\n");
    if (read_exact_stdin(header, sizeof(header)) != 0 || !magic_ok(header)) return 10;
    unsigned char wakeup = header[4];
    unsigned char flag = header[5];
    uint16_t udp_port = be16(header + 6);
    uint32_t did_len = be32(header + 8), server_len = be32(header + 12), key_len = be32(header + 16);
    uint32_t unit1_len = be32(header + 20), unit2_len = be32(header + 24), unit3_len = be32(header + 28), stop_len = be32(header + 32);
    if (!did_len || !server_len || !key_len || did_len >= MAX_FIELD || server_len >= MAX_FIELD || key_len >= MAX_FIELD ||
        !unit1_len || !unit2_len || !unit3_len || !stop_len || unit1_len > MAX_UNIT || unit2_len > MAX_UNIT || unit3_len > MAX_UNIT || stop_len > MAX_UNIT) return 11;
    if (read_exact_stdin(did, did_len) || read_exact_stdin(server, server_len) || read_exact_stdin(device_key, key_len) ||
        read_exact_stdin(unit1, unit1_len) || read_exact_stdin(unit2, unit2_len) || read_exact_stdin(unit3, unit3_len) || read_exact_stdin(stop_unit, stop_len)) return 12;
    did[did_len] = '\0'; server[server_len] = '\0'; device_key[key_len] = '\0';

    /*
     * The host already supplies the proven legacy burst as authenticated TNP
     * units: 4881/no.1, 9029/no.2 with use-count 2, 768/no.3 and STOP 767.
     * The current official client proves a two-stage live transition instead:
     * 9029/no.2 use-count 1 first, then about 5.9s later 9029/no.11
     * use-count 2 plus 768/no.12. TNP authInfo authenticates the session nonce,
     * not these command-number/payload bytes, so derive the official variants
     * locally without changing the secret-safe host/worker transport format.
     */
    if (unit2_len != 52U || unit2[0] != TNP_VERSION || unit2[1] != 3 ||
        be32(unit2 + 4) != 44U || be16(unit2 + 8) != CMD_START_REALTIME ||
        be16(unit2 + 10) != 2U || be16(unit2 + 14) != 4U || unit2[48] != 2U) return 13;
    if (unit3_len != 56U || unit3[0] != TNP_VERSION || unit3[1] != 3 ||
        be32(unit3 + 4) != 48U || be16(unit3 + 8) != CMD_START_AUDIO ||
        be16(unit3 + 10) != 3U || be16(unit3 + 14) != 8U) return 14;

    copy_bytes(initial_start_unit, unit2, unit2_len);
    initial_start_unit[48] = 1U;
    copy_bytes(refresh_start_unit, unit2, unit2_len);
    store_be16(refresh_start_unit + 10, 11U);
    copy_bytes(refresh_audio_unit, unit3, unit3_len);
    store_be16(refresh_audio_unit + 10, 12U);

    void *so = dlopen(library, RTLD_NOW | RTLD_LOCAL);
    if (!so) { log_str("dlerror="); log_str(dlerror()); log_str("\n"); return 20; }
    int (*pppp_initialize)(const unsigned char *, int) = (int (*)(const unsigned char *, int))dlsym(so, "PPPP_Initialize");
    int (*pppp_deinitialize)(void) = (int (*)(void))dlsym(so, "PPPP_DeInitialize");
    int (*pppp_connect)(const char *, unsigned char, unsigned short, char *, char *) = (int (*)(const char *, unsigned char, unsigned short, char *, char *))dlsym(so, "PPPP_Connect");
    int (*pppp_wakeup_connect)(const char *, unsigned char, unsigned short, char *, char *) = (int (*)(const char *, unsigned char, unsigned short, char *, char *))dlsym(so, "PPPP_WakeUp_And_Connect");
    int (*pppp_connect_break)(const char *) = (int (*)(const char *))dlsym(so, "PPPP_Connect_Break");
    int (*pppp_force_close)(int) = (int (*)(int))dlsym(so, "PPPP_ForceClose");
    pppp_write_fn pppp_write = (pppp_write_fn)dlsym(so, "PPPP_Write");
    pppp_read_fn pppp_read = (pppp_read_fn)dlsym(so, "PPPP_Read");
    if (!pppp_initialize || !pppp_deinitialize || !pppp_connect || !pppp_wakeup_connect || !pppp_connect_break || !pppp_force_close || !pppp_write || !pppp_read) return 21;

    int init_rc = pppp_initialize(init_string, 12);
    log_str("PPPP_Initialize_rc_hex="); log_hex32((uint32_t)init_rc);
    if (init_rc != 0) return 30;
    initialized = 1;

    handle_value = wakeup ? pppp_wakeup_connect(did, flag, udp_port, server, device_key) : pppp_connect(did, flag, udp_port, server, device_key);
    log_str("PPPP_Connect_rc_hex="); log_hex32((uint32_t)handle_value);
    if (handle_value < 0) { result_code = 40; goto cleanup; }

    int write1_rc = pppp_write(handle_value, 0, unit1, (int)unit1_len);
    int write2_rc = pppp_write(handle_value, 0, initial_start_unit, (int)unit2_len);
    if (write2_rc >= 0) live_started = 1;
    int write3_rc = pppp_write(handle_value, 0, unit3, (int)unit3_len);
    log_str("PPPP_Write_4881_rc_hex="); log_hex32((uint32_t)write1_rc);
    log_str("PPPP_Write_9029_rc_hex="); log_hex32((uint32_t)write2_rc);
    log_str("PPPP_Write_768_rc_hex="); log_hex32((uint32_t)write3_rc);
    if (write1_rc < 0 || write2_rc < 0 || write3_rc < 0) { result_code = 50; goto cleanup; }

    int read_size = 8;
    int rc = pppp_read(handle_value, 0, response, &read_size, -1);
    if (rc < 0 || read_size != 8) { result_code = 60; goto cleanup; }
    uint32_t command_data_size = be32(response + 4);
    if (response[1] != 3 || command_data_size < 40 || command_data_size > MAX_UNIT - 8) { result_code = 61; goto cleanup; }
    read_size = (int)command_data_size;
    rc = pppp_read(handle_value, 0, response + 8, &read_size, -1);
    if (rc < 0 || read_size != (int)command_data_size) { result_code = 62; goto cleanup; }
    uint32_t response_version = response[0], response_command = be16(response + 8), response_number = be16(response + 10), auth_result = be32(response + 16);
    log_str("tnp_response_version="); log_u32(response_version);
    log_str("tnp_response_command="); log_u32(response_command);
    log_str("tnp_response_command_number="); log_u32(response_number);
    log_str("tnp_auth_result="); log_u32(auth_result);
    if (response_version != TNP_VERSION || response_command != CMD_SET_RESOLUTION_RESP || response_number != 1 || auth_result != 0) { result_code = 63; goto cleanup; }
    log_str("phase3g_tnp_auth=PASS\n");

    reader_ctx audio = {pppp_read, handle_value, 1, 2, 0, 0};
    reader_ctx iframe = {pppp_read, handle_value, 2, 1, 0, 0};
    reader_ctx pframe = {pppp_read, handle_value, 3, 1, 0, 0};
    refresh_ctx refresh = {pppp_write, handle_value, refresh_start_unit, unit2_len, refresh_audio_unit, unit3_len};
    pthread_t ta = 0, ti = 0, tp = 0, tr = 0;
    int ca = pthread_create(&ta, 0, reader_main, &audio);
    int ci = pthread_create(&ti, 0, reader_main, &iframe);
    int cp = pthread_create(&tp, 0, reader_main, &pframe);
    if (ca || ci || cp) { result_code = 71; stop_requested = 1; goto cleanup_threads; }
    int cr = pthread_create(&tr, 0, refresh_main, &refresh);
    if (cr) { result_code = 73; stop_requested = 1; goto cleanup_threads; }
    log_str("phase3g_media_readers=STARTED\n");

    {
        unsigned char stop_byte = 0;
        long stop_read = sys_read(0, &stop_byte, 1);
        (void)stop_read;
        normal_stop = 1;
        stop_requested = 1;
    }

cleanup_threads:
    stop_requested = 1;
    if (handle_value >= 0 && live_started) {
        int stop_rc = pppp_write(handle_value, 0, stop_unit, (int)stop_len);
        log_str("PPPP_Write_767_rc_hex="); log_hex32((uint32_t)stop_rc);
    }
    if (handle_value >= 0) {
        int break_rc = pppp_connect_break(did);
        log_str("PPPP_Connect_Break_rc_hex="); log_hex32((uint32_t)break_rc);
        int close_rc = pppp_force_close(handle_value);
        log_str("PPPP_ForceClose_rc_hex="); log_hex32((uint32_t)close_rc);
    }
    if (tr) pthread_join(tr, 0);
    if (ta) pthread_join(ta, 0);
    if (ti) pthread_join(ti, 0);
    if (tp) pthread_join(tp, 0);
    log_str("channel1_records="); log_u32(audio.emitted);
    log_str("channel2_records="); log_u32(iframe.emitted);
    log_str("channel3_records="); log_u32(pframe.emitted);
    if (result_code == 1) {
        if (!normal_stop && (audio.rc || iframe.rc || pframe.rc)) result_code = 72;
        else result_code = 0;
    }
    handle_value = -1;
    live_started = 0;

cleanup:
    stop_requested = 1;
    if (handle_value >= 0 && live_started) {
        int stop_rc = pppp_write(handle_value, 0, stop_unit, (int)stop_len);
        log_str("PPPP_Write_767_rc_hex="); log_hex32((uint32_t)stop_rc);
    }
    if (handle_value >= 0) {
        int break_rc = pppp_connect_break(did);
        log_str("PPPP_Connect_Break_rc_hex="); log_hex32((uint32_t)break_rc);
        int close_rc = pppp_force_close(handle_value);
        log_str("PPPP_ForceClose_rc_hex="); log_hex32((uint32_t)close_rc);
    }
    if (initialized) {
        int deinit_rc = pppp_deinitialize();
        log_str("PPPP_DeInitialize_rc_hex="); log_hex32((uint32_t)deinit_rc);
        if (deinit_rc != 0 && result_code == 0) result_code = 82;
    }
    if (result_code == 0) { log_str("phase3g_av_stream=PASS\n"); return 0; }
    log_str("phase3g_av_stream=FAIL\n");
    return result_code;
}

#include <stdarg.h>
#include <stdio.h>

int __android_log_print(int priority, const char *tag, const char *fmt, ...) {
    (void)priority;
    if (tag != NULL && *tag != '\0') {
        fprintf(stderr, "[android-log:%s] ", tag);
    } else {
        fprintf(stderr, "[android-log] ");
    }

    va_list args;
    va_start(args, fmt);
    int result = vfprintf(stderr, fmt, args);
    va_end(args);
    fputc('\n', stderr);
    return result;
}

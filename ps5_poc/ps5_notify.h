#ifndef PS5_NOTIFY_H
#define PS5_NOTIFY_H

#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <stddef.h>

typedef struct {
    char unused[45];
    char message[3075];
} ps5_notify_request_t;

#ifdef __PROSPERO__
int sceKernelSendNotificationRequest(int device, ps5_notify_request_t *req, size_t size, int blocking);
#else
static inline int sceKernelSendNotificationRequest(int device, ps5_notify_request_t *req, size_t size, int blocking) {
    (void)device; (void)size; (void)blocking;
    if (req) printf("[PS5 NOTIFY] %s\n", req->message);
    return 0;
}
#endif

static inline void ps5_notify(const char *fmt, ...) {
    ps5_notify_request_t req;
    memset(&req, 0, sizeof(req));
    va_list args;
    va_start(args, fmt);
    vsnprintf(req.message, sizeof(req.message) - 1, fmt, args);
    va_end(args);
    sceKernelSendNotificationRequest(0, &req, sizeof(req), 0);
}

#endif

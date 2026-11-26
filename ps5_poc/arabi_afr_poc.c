/*
 * PS5 Arabi POC 1 (v1.1): Universal AFR Path Resolver & Diagnostic Probe with Notifications
 * Target: PS5 Firmware 5.50 (Orbis OS / etaHEN)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include "ps5_notify.h"

#define MODS_ROOT "/data/arabi_mods"
#define LOG_FILE  "/data/arabi_poc/afr_poc.log"

static char g_title_id[32] = "GENERIC";

static void afr_log(const char *msg) {
    FILE *fp = fopen(LOG_FILE, "a");
    if (!fp) return;
    fprintf(fp, "%s\n", msg);
    fclose(fp);
}

int afr_resolve_path(const char *orig_path, char *out_path, size_t out_len) {
    if (!orig_path || orig_path[0] == '\0') return 0;

    const char *rel = NULL;
    if (strncmp(orig_path, "/app0/", 6) == 0) {
        rel = orig_path + 6;
    } else if (strncmp(orig_path, "app0:", 5) == 0) {
        rel = orig_path + 5;
        if (*rel == '/') rel++;
    } else {
        return 0;
    }

    snprintf(out_path, out_len, "%s/%s/%s", MODS_ROOT, g_title_id, rel);

    struct stat st;
    if (stat(out_path, &st) == 0 && S_ISREG(st.st_mode)) {
        char buf[1200];
        snprintf(buf, sizeof(buf), "[AFR HIT] %s -> %s (%lld bytes)",
                 orig_path, out_path, (long long)st.st_size);
        afr_log(buf);
        return 1;
    }
    return 0;
}

int main(void) {
    ps5_notify("PS5 Arabi AFR Test: Started!\nChecking /data/arabi_mods permissions...");
    mkdir("/data/arabi_poc", 0777);
    mkdir(MODS_ROOT, 0777);
    mkdir(MODS_ROOT "/POC_TEST", 0777);

    FILE *tf = fopen(MODS_ROOT "/POC_TEST/test_lang.txt", "w");
    if (!tf) {
        afr_log("[FAIL] Cannot write to /data/arabi_mods/POC_TEST/test_lang.txt");
        ps5_notify("PS5 Arabi AFR ERROR:\nCannot write to /data/arabi_mods!");
        return 1;
    }
    fprintf(tf, "ARABI_POC_REDIRECT_OK\n");
    fclose(tf);

    snprintf(g_title_id, sizeof(g_title_id), "POC_TEST");
    char resolved[1024] = {0};
    if (afr_resolve_path("/app0/test_lang.txt", resolved, sizeof(resolved))) {
        afr_log("[PASS] AFR path resolver & /data/arabi_mods R/W verified on PS5.");
        ps5_notify("PS5 Arabi AFR PASS!\nMods folder ready:\n%s\nLog: %s", MODS_ROOT, LOG_FILE);
        return 0;
    }

    afr_log("[FAIL] AFR path resolver did not match expected override file.");
    ps5_notify("PS5 Arabi AFR ERROR:\nRedirect path check failed!\nSee: %s", LOG_FILE);
    return 1;
}

/*
 * PS5 Arabi Hub v5.0 — ULTIMATE UNIVERSAL EDITION (FW 5.50 / etaHEN + ShadowMountPlus)
 * Works on ALL PS5 & PS4 games in ANY format:
 *   - PS5 ShadowMountPlus (.exfat / .ffpkg / .ffpfsc / Dump Folders)
 *   - PS4 & PS5 Installed FPKGs (.pkg) via live Kernel unionfs Auto-Mounter!
 *   - Permanent Auto-Updating Web Dashboard (loaded live from GitHub in iPhone Safari)
 *   - Zero-Corruption: Never modifies original game files; 100% reversible in 1 tap.
 */

#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/param.h>
#include <sys/mount.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/uio.h>
#include <unistd.h>

#include "dashboard_html.h"

#define BACKPORTS_ROOT "/data/homebrew/backports"
#define UE_PAK_MAGIC 0x5A6F12E1U
#define IOVEC_ENTRY(x) { (x) ? (void *)(x) : NULL, (x) ? strlen(x) + 1 : 0 }
#define IOVEC_SIZE(x)  (sizeof(x) / sizeof(struct iovec))

typedef struct {
    char unused[45];
    char message[3075];
} ps5_notify_t;

int sceKernelSendNotificationRequest(int, ps5_notify_t *, size_t, int) __attribute__((weak));

static void ps5_notify(const char *msg) {
    if (!sceKernelSendNotificationRequest) return;
    ps5_notify_t req;
    memset(&req, 0, sizeof(req));
    strncpy(req.message, msg, sizeof(req.message) - 1);
    sceKernelSendNotificationRequest(0, &req, sizeof(req), 0);
}

typedef struct {
    int ok;
    char title_id[32];
    char mount_path[512];
    char game_format[64];
    char fs_type[32];
    int unionfs_active;
    char engine[32];
    char pak_full[768];
    char pak_rel[512];
    char patch_rel[512];
    int ue_ver;
    int encrypted;
    uint64_t pak_size;
    uint64_t index_offset;
    uint64_t index_size;
    int patch_installed;
    int total_files;
} ScanInfo;

static ScanInfo g_scan;
static char g_last_mounted_key[256] = {0};

static void send_all(int fd, const void *buf, size_t len) {
    const uint8_t *p = (const uint8_t *)buf;
    size_t sent = 0;
    while (sent < len) {
        ssize_t n = send(fd, p + sent, len - sent, 0);
        if (n <= 0) break;
        sent += (size_t)n;
    }
}

static void send_http(int fd, int code, const char *ctype, const void *body, size_t len) {
    char hdr[512];
    int hlen = snprintf(
        hdr, sizeof(hdr),
        "HTTP/1.1 %d %s\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %zu\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "Connection: close\r\n\r\n",
        code, code == 200 ? "OK" : "Error", ctype, len
    );
    send_all(fd, hdr, (size_t)hlen);
    if (body && len > 0) send_all(fd, body, len);
}

static void send_json(int fd, int code, const char *json) {
    send_http(fd, code, "application/json; charset=utf-8", json, strlen(json));
}

static void mkdir_p(const char *path) {
    char tmp[768];
    strncpy(tmp, path, sizeof(tmp) - 1);
    tmp[sizeof(tmp) - 1] = 0;
    for (char *p = tmp + 1; *p; p++) {
        if (*p == '/') {
            *p = 0;
            mkdir(tmp, 0777);
            chmod(tmp, 0777);
            *p = '/';
        }
    }
    mkdir(tmp, 0777);
    chmod(tmp, 0777);
}

static int dir_has_files(const char *path) {
    DIR *d = opendir(path);
    if (!d) return 0;
    struct dirent *e;
    int found = 0;
    while ((e = readdir(d)) != NULL) {
        if (strcmp(e->d_name, ".") == 0 || strcmp(e->d_name, "..") == 0) continue;
        found = 1;
        break;
    }
    closedir(d);
    return found;
}

static void rm_rf(const char *path) {
    DIR *d = opendir(path);
    if (!d) {
        unlink(path);
        return;
    }
    struct dirent *e;
    while ((e = readdir(d)) != NULL) {
        if (strcmp(e->d_name, ".") == 0 || strcmp(e->d_name, "..") == 0) continue;
        char sub[768];
        snprintf(sub, sizeof(sub), "%s/%s", path, e->d_name);
        struct stat st;
        if (stat(sub, &st) == 0 && S_ISDIR(st.st_mode)) rm_rf(sub);
        else unlink(sub);
    }
    closedir(d);
    rmdir(path);
}

/*
 * Mounts /data/homebrew/backports/<TID> as a transparent unionfs overlay
 * on top of a running game's mount path (PS4 FPKG or PS5 FPKG/App).
 * Returns: 1 = newly mounted, 2 = already unionfs, 0 = no patch dir, -errno = error.
 */
static int try_mount_unionfs(const char *tid, const char *dst_mnt) {
    char bp_dir[512];
    snprintf(bp_dir, sizeof(bp_dir), "%s/%s", BACKPORTS_ROOT, tid);
    if (!dir_has_files(bp_dir)) return 0;

    struct statfs sfs;
    if (statfs(dst_mnt, &sfs) != 0) return -errno;
    if (strstr(sfs.f_mntfromname, BACKPORTS_ROOT) != NULL) return 2;

    struct iovec iov[] = {
        IOVEC_ENTRY("fstype"),   IOVEC_ENTRY("unionfs"),
        IOVEC_ENTRY("from"),     IOVEC_ENTRY(bp_dir),
        IOVEC_ENTRY("fspath"),   IOVEC_ENTRY(dst_mnt),
        IOVEC_ENTRY("copymode"), IOVEC_ENTRY("transparent"),
        IOVEC_ENTRY("notime"),   IOVEC_ENTRY(NULL),
        IOVEC_ENTRY("fnodup"),   IOVEC_ENTRY(NULL)
    };
    if (nmount(iov, IOVEC_SIZE(iov), 0) == 0) {
        return 1;
    }
    return -errno;
}

/*
 * Fast background poller called every ~200ms in the main select() loop.
 * Automatically activates Arabic unionfs overlay the instant ANY patched
 * PS4 FPKG or PS5 game launches!
 */
static void poll_auto_mount(void) {
    /* 1. Check /mnt/sandbox/<PPSA|CUSA>*_000/app0 */
    DIR *d = opendir("/mnt/sandbox");
    if (d) {
        struct dirent *e;
        while ((e = readdir(d)) != NULL) {
            if ((strncmp(e->d_name, "PPSA", 4) == 0 || strncmp(e->d_name, "CUSA", 4) == 0) && strlen(e->d_name) >= 9) {
                char tid[16];
                memcpy(tid, e->d_name, 9);
                tid[9] = 0;
                char app0[512];
                snprintf(app0, sizeof(app0), "/mnt/sandbox/%s/app0", e->d_name);
                struct stat st;
                if (stat(app0, &st) == 0 && S_ISDIR(st.st_mode)) {
                    int rc = try_mount_unionfs(tid, app0);
                    if (rc == 1) {
                        char key[256];
                        snprintf(key, sizeof(key), "%s:%s", tid, app0);
                        if (strcmp(g_last_mounted_key, key) != 0) {
                            strncpy(g_last_mounted_key, key, sizeof(g_last_mounted_key) - 1);
                            char msg[128];
                            snprintf(msg, sizeof(msg), "PS5 Arabi Hub: Arabic Patch Active (%s)!", tid);
                            ps5_notify(msg);
                        }
                    }
                }
            }
        }
        closedir(d);
    }

    /* 2. Check /mnt/sandbox/pfsmnt/CUSA*-app0* (PS4 FPKGs) */
    d = opendir("/mnt/sandbox/pfsmnt");
    if (d) {
        struct dirent *e;
        while ((e = readdir(d)) != NULL) {
            if (strncmp(e->d_name, "CUSA", 4) == 0 && strlen(e->d_name) >= 9 && strstr(e->d_name, "app0")) {
                char tid[16];
                memcpy(tid, e->d_name, 9);
                tid[9] = 0;
                char full[512];
                snprintf(full, sizeof(full), "/mnt/sandbox/pfsmnt/%s", e->d_name);
                struct stat st;
                if (stat(full, &st) == 0 && S_ISDIR(st.st_mode)) {
                    int rc = try_mount_unionfs(tid, full);
                    if (rc == 1) {
                        char key[256];
                        snprintf(key, sizeof(key), "%s:%s", tid, full);
                        if (strcmp(g_last_mounted_key, key) != 0) {
                            strncpy(g_last_mounted_key, key, sizeof(g_last_mounted_key) - 1);
                            char msg[128];
                            snprintf(msg, sizeof(msg), "PS5 Arabi Hub: PS4 FPKG Arabic Active (%s)!", tid);
                            ps5_notify(msg);
                        }
                    }
                }
            }
        }
        closedir(d);
    }
}

static int probe_ue_pak(const char *pak_path, ScanInfo *info) {
    int fd = open(pak_path, O_RDONLY);
    if (fd < 0) return 0;
    struct stat st;
    if (fstat(fd, &st) != 0 || st.st_size < 256) {
        close(fd);
        return 0;
    }
    info->pak_size = (uint64_t)st.st_size;
    uint8_t tail[256];
    if (pread(fd, tail, sizeof(tail), st.st_size - (off_t)sizeof(tail)) != (ssize_t)sizeof(tail)) {
        close(fd);
        return 0;
    }
    close(fd);

    for (int off = (int)sizeof(tail) - 44; off >= 0; off--) {
        uint32_t magic;
        memcpy(&magic, tail + off, 4);
        if (magic == UE_PAK_MAGIC) {
            uint32_t ver = 0;
            uint64_t idx_off = 0, idx_sz = 0;
            memcpy(&ver, tail + off + 4, 4);
            memcpy(&idx_off, tail + off + 8, 8);
            memcpy(&idx_sz, tail + off + 16, 8);
            uint8_t enc = (off >= 1) ? tail[off - 1] : 0;
            if (ver >= 3 && ver <= 12 && idx_off < info->pak_size && idx_sz > 0 && idx_sz < 128ULL * 1024ULL * 1024ULL) {
                info->ue_ver = (int)ver;
                info->encrypted = (enc != 0);
                info->index_offset = idx_off;
                info->index_size = idx_sz;
                return 1;
            }
        }
    }
    return 0;
}

static void walk_and_detect(const char *base, const char *rel, ScanInfo *info, FILE *tree_fp) {
    char dirpath[768];
    if (rel[0]) snprintf(dirpath, sizeof(dirpath), "%s/%s", base, rel);
    else snprintf(dirpath, sizeof(dirpath), "%s", base);

    DIR *d = opendir(dirpath);
    if (!d) return;
    struct dirent *e;
    while ((e = readdir(d)) != NULL) {
        if (e->d_name[0] == '.') continue;
        char sub_rel[512];
        if (rel[0]) snprintf(sub_rel, sizeof(sub_rel), "%s/%s", rel, e->d_name);
        else snprintf(sub_rel, sizeof(sub_rel), "%s", e->d_name);
        char full[768];
        snprintf(full, sizeof(full), "%s/%s", base, sub_rel);

        struct stat st;
        if (stat(full, &st) != 0) continue;
        if (S_ISDIR(st.st_mode)) {
            walk_and_detect(base, sub_rel, info, tree_fp);
        } else {
            info->total_files++;
            if (tree_fp) {
                fprintf(tree_fp, "%llu\t%s\n", (unsigned long long)st.st_size, sub_rel);
            }
            size_t nlen = strlen(e->d_name);
            if (nlen > 4 && strcasecmp(e->d_name + nlen - 4, ".pak") == 0) {
                if ((uint64_t)st.st_size > info->pak_size) {
                    if (probe_ue_pak(full, info)) {
                        strncpy(info->pak_full, full, sizeof(info->pak_full) - 1);
                        strncpy(info->pak_rel, sub_rel, sizeof(info->pak_rel) - 1);
                        strncpy(info->engine, "Unreal Engine", sizeof(info->engine) - 1);
                        const char *slash = strrchr(sub_rel, '/');
                        if (slash) {
                            size_t dlen = (size_t)(slash - sub_rel);
                            snprintf(info->patch_rel, sizeof(info->patch_rel), "%.*s/pakchunk0-ps5_999_p.pak", (int)dlen, sub_rel);
                        } else {
                            snprintf(info->patch_rel, sizeof(info->patch_rel), "pakchunk0-ps5_999_p.pak");
                        }
                    } else if (!info->engine[0] && strstr(sub_rel, "re_chunk")) {
                        strncpy(info->engine, "RE Engine", sizeof(info->engine) - 1);
                    }
                }
            } else if (nlen > 4 && strcasecmp(e->d_name + nlen - 4, ".rpf") == 0) {
                if (!info->engine[0]) strncpy(info->engine, "Rockstar RAGE", sizeof(info->engine) - 1);
            } else if (strcmp(e->d_name, "globalgamemanagers") == 0 || strcmp(e->d_name, "resources.assets") == 0 ||
                       (nlen > 7 && strcasecmp(e->d_name + nlen - 7, ".bundle") == 0)) {
                if (!info->engine[0]) strncpy(info->engine, "Unity", sizeof(info->engine) - 1);
            }
        }
    }
    closedir(d);
}

static int run_scan(ScanInfo *info) {
    memset(info, 0, sizeof(*info));

    DIR *d = opendir("/mnt/sandbox");
    if (d) {
        struct dirent *e;
        while ((e = readdir(d)) != NULL) {
            if ((strncmp(e->d_name, "PPSA", 4) == 0 || strncmp(e->d_name, "CUSA", 4) == 0) && strlen(e->d_name) >= 9) {
                char app0[512];
                snprintf(app0, sizeof(app0), "/mnt/sandbox/%s/app0", e->d_name);
                struct stat st;
                if (stat(app0, &st) == 0 && S_ISDIR(st.st_mode)) {
                    memcpy(info->title_id, e->d_name, 9);
                    info->title_id[9] = 0;
                    strncpy(info->mount_path, app0, sizeof(info->mount_path) - 1);
                    strncpy(info->game_format, strncmp(info->title_id, "CUSA", 4) == 0 ? "PS4 Sandbox" : "PS5 ShadowMount/App", sizeof(info->game_format) - 1);
                    break;
                }
            }
        }
        closedir(d);
    }

    if (!info->title_id[0]) {
        d = opendir("/mnt/sandbox/pfsmnt");
        if (d) {
            struct dirent *e;
            while ((e = readdir(d)) != NULL) {
                if (strncmp(e->d_name, "CUSA", 4) == 0 && strstr(e->d_name, "app0")) {
                    char full[512];
                    snprintf(full, sizeof(full), "/mnt/sandbox/pfsmnt/%s", e->d_name);
                    struct stat st;
                    if (stat(full, &st) == 0 && S_ISDIR(st.st_mode)) {
                        memcpy(info->title_id, e->d_name, 9);
                        info->title_id[9] = 0;
                        strncpy(info->mount_path, full, sizeof(info->mount_path) - 1);
                        strncpy(info->game_format, "PS4 FPKG (.pkg)", sizeof(info->game_format) - 1);
                        break;
                    }
                }
            }
            closedir(d);
        }
    }

    if (!info->title_id[0]) return 0;

    struct statfs sfs;
    if (statfs(info->mount_path, &sfs) == 0) {
        strncpy(info->fs_type, sfs.f_fstypename, sizeof(info->fs_type) - 1);
        info->unionfs_active = (strstr(sfs.f_mntfromname, BACKPORTS_ROOT) != NULL);
    } else {
        strncpy(info->fs_type, "unknown", sizeof(info->fs_type) - 1);
    }

    mkdir_p("/data/arabi_hub");
    FILE *tfp = fopen("/data/arabi_hub/file_tree.txt", "w");
    walk_and_detect(info->mount_path, "", info, tfp);
    if (tfp) fclose(tfp);

    if (!info->engine[0]) strncpy(info->engine, "Generic/Custom", sizeof(info->engine) - 1);

    char bp_dir[512];
    snprintf(bp_dir, sizeof(bp_dir), "%s/%s", BACKPORTS_ROOT, info->title_id);
    info->patch_installed = dir_has_files(bp_dir);
    info->ok = 1;
    return 1;
}

static void stream_file(int cfd, const char *path, const char *ctype) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) {
        send_json(cfd, 404, "{\"ok\":false,\"error\":\"File not found\"}");
        return;
    }
    struct stat st;
    if (fstat(fd, &st) != 0) {
        close(fd);
        send_json(cfd, 500, "{\"ok\":false,\"error\":\"stat failed\"}");
        return;
    }
    char hdr[256];
    int hlen = snprintf(
        hdr, sizeof(hdr),
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %llu\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "Connection: close\r\n\r\n",
        ctype, (unsigned long long)st.st_size
    );
    send_all(cfd, hdr, (size_t)hlen);
    uint8_t chunk[32768];
    ssize_t n;
    while ((n = read(fd, chunk, sizeof(chunk))) > 0) {
        send_all(cfd, chunk, (size_t)n);
    }
    close(fd);
}

static void handle_extract_bundle(int cfd) {
    if (!g_scan.ok && !run_scan(&g_scan)) {
        send_json(cfd, 404, "{\"ok\":false,\"error\":\"No running game found\"}");
        return;
    }
    if (g_scan.pak_full[0] && g_scan.index_size > 0) {
        int fd = open(g_scan.pak_full, O_RDONLY);
        if (fd < 0) {
            send_json(cfd, 500, "{\"ok\":false,\"error\":\"Cannot open pak\"}");
            return;
        }
        uint64_t sz = g_scan.index_size;
        char hdr[256];
        int hlen = snprintf(
            hdr, sizeof(hdr),
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: application/octet-stream\r\n"
            "Content-Length: %llu\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "Connection: close\r\n\r\n",
            (unsigned long long)sz
        );
        send_all(cfd, hdr, (size_t)hlen);
        uint8_t chunk[32768];
        uint64_t left = sz;
        off_t cur = (off_t)g_scan.index_offset;
        while (left > 0) {
            size_t to_read = left > sizeof(chunk) ? sizeof(chunk) : (size_t)left;
            ssize_t n = pread(fd, chunk, to_read, cur);
            if (n <= 0) break;
            send_all(cfd, chunk, (size_t)n);
            cur += n;
            left -= (uint64_t)n;
        }
        close(fd);
    } else {
        stream_file(cfd, "/data/arabi_hub/file_tree.txt", "text/plain; charset=utf-8");
    }
}

static void url_decode(const char *src, char *dst, size_t max_len) {
    size_t di = 0;
    for (size_t i = 0; src[i] && di + 1 < max_len; i++) {
        if (src[i] == '%' && src[i + 1] && src[i + 2]) {
            char hex[3] = {src[i + 1], src[i + 2], 0};
            dst[di++] = (char)strtol(hex, NULL, 16);
            i += 2;
        } else if (src[i] == '+') {
            dst[di++] = ' ';
        } else {
            dst[di++] = src[i];
        }
    }
    dst[di] = 0;
}

static void get_query_param(const char *url, const char *key, char *out, size_t out_len) {
    out[0] = 0;
    const char *q = strchr(url, '?');
    if (!q) return;
    char pat[64];
    snprintf(pat, sizeof(pat), "%s=", key);
    const char *p = strstr(q + 1, pat);
    if (!p) return;
    p += strlen(pat);
    const char *end = strchr(p, '&');
    char raw[512];
    size_t len = end ? (size_t)(end - p) : strlen(p);
    if (len >= sizeof(raw)) len = sizeof(raw) - 1;
    memcpy(raw, p, len);
    raw[len] = 0;
    url_decode(raw, out, out_len);
}

static void handle_client(int cfd) {
    char req[8192];
    ssize_t n = recv(cfd, req, sizeof(req) - 1, 0);
    if (n <= 0) return;
    req[n] = 0;

    char method[16] = {0}, url[1024] = {0};
    sscanf(req, "%15s %1023s", method, url);

    if (strcmp(method, "OPTIONS") == 0) {
        send_http(cfd, 200, "text/plain", "", 0);
        return;
    }
    if (strcmp(url, "/") == 0) {
        send_http(cfd, 200, "text/html; charset=utf-8", DASHBOARD_HTML, DASHBOARD_HTML_LEN);
        return;
    }
    if (strncmp(url, "/api/scan", 9) == 0) {
        if (!run_scan(&g_scan)) {
            send_json(cfd, 200, "{\"ok\":false,\"error\":\"لم يتم العثور على لعبة شغّالة. افتح اللعبة أولاً ثم أعد الفحص.\"}");
            return;
        }
        char out[2048];
        snprintf(
            out, sizeof(out),
            "{\"ok\":true,\"title_id\":\"%s\",\"mount_path\":\"%s\",\"game_format\":\"%s\","
            "\"fs_type\":\"%s\",\"unionfs_active\":%s,\"engine\":\"%s\","
            "\"pak_rel\":\"%s\",\"patch_rel\":\"%s\",\"ue_ver\":%d,\"encrypted\":%s,"
            "\"pak_size\":%llu,\"index_size\":%llu,\"total_files\":%d,\"patch_installed\":%s}",
            g_scan.title_id, g_scan.mount_path, g_scan.game_format,
            g_scan.fs_type, g_scan.unionfs_active ? "true" : "false", g_scan.engine,
            g_scan.pak_rel, g_scan.patch_rel, g_scan.ue_ver,
            g_scan.encrypted ? "true" : "false",
            (unsigned long long)g_scan.pak_size,
            (unsigned long long)g_scan.index_size,
            g_scan.total_files,
            g_scan.patch_installed ? "true" : "false"
        );
        send_json(cfd, 200, out);
        return;
    }
    if (strncmp(url, "/api/mount_now", 14) == 0) {
        if (!run_scan(&g_scan)) {
            send_json(cfd, 200, "{\"ok\":false,\"status\":\"no_game\"}");
            return;
        }
        int rc = try_mount_unionfs(g_scan.title_id, g_scan.mount_path);
        char out[512];
        snprintf(
            out, sizeof(out),
            "{\"ok\":%s,\"rc\":%d,\"title_id\":\"%s\",\"mount_path\":\"%s\",\"status\":\"%s\"}",
            (rc > 0) ? "true" : "false", rc, g_scan.title_id, g_scan.mount_path,
            rc == 1 ? "mounted" : (rc == 2 ? "already_mounted" : (rc == 0 ? "no_patch" : strerror(-rc)))
        );
        send_json(cfd, 200, out);
        return;
    }
    if (strncmp(url, "/api/file_tree", 14) == 0) {
        if (!g_scan.ok) run_scan(&g_scan);
        stream_file(cfd, "/data/arabi_hub/file_tree.txt", "text/plain; charset=utf-8");
        return;
    }
    if (strncmp(url, "/api/read_file", 14) == 0) {
        if (!g_scan.ok) run_scan(&g_scan);
        char rel[512];
        get_query_param(url, "rel", rel, sizeof(rel));
        if (!rel[0] || strstr(rel, "..")) {
            send_json(cfd, 400, "{\"ok\":false,\"error\":\"Invalid path\"}");
            return;
        }
        char full[768];
        snprintf(full, sizeof(full), "%s/%s", g_scan.mount_path, rel);
        stream_file(cfd, full, "application/octet-stream");
        return;
    }
    if (strncmp(url, "/api/extract_bundle", 19) == 0) {
        handle_extract_bundle(cfd);
        return;
    }
    if (strncmp(url, "/api/uninstall", 14) == 0) {
        char tid[32];
        get_query_param(url, "title_id", tid, sizeof(tid));
        if (strlen(tid) < 9 || strstr(tid, "..")) {
            send_json(cfd, 400, "{\"ok\":false,\"error\":\"Invalid title_id\"}");
            return;
        }
        char bp_dir[512];
        snprintf(bp_dir, sizeof(bp_dir), "%s/%s", BACKPORTS_ROOT, tid);
        rm_rf(bp_dir);
        g_last_mounted_key[0] = 0;
        send_json(cfd, 200, "{\"ok\":true}");
        return;
    }
    if (strncmp(url, "/api/install", 12) == 0 && strcmp(method, "POST") == 0) {
        char tid[32], rel_path[512];
        get_query_param(url, "title_id", tid, sizeof(tid));
        get_query_param(url, "rel_path", rel_path, sizeof(rel_path));
        if (strlen(tid) < 9 || !rel_path[0] || strstr(tid, "..") || strstr(rel_path, "..")) {
            send_json(cfd, 400, "{\"ok\":false,\"error\":\"Invalid install path\"}");
            return;
        }
        size_t content_len = 0;
        const char *cl = strcasestr(req, "Content-Length:");
        if (cl) content_len = (size_t)strtoull(cl + 15, NULL, 10);
        const char *body_start = strstr(req, "\r\n\r\n");
        if (!body_start || content_len == 0) {
            send_json(cfd, 400, "{\"ok\":false,\"error\":\"Empty body\"}");
            return;
        }
        body_start += 4;
        size_t already = (size_t)((req + n) - body_start);

        char full_dst[768], dir_dst[768];
        snprintf(full_dst, sizeof(full_dst), "%s/%s/%s", BACKPORTS_ROOT, tid, rel_path);
        strncpy(dir_dst, full_dst, sizeof(dir_dst) - 1);
        dir_dst[sizeof(dir_dst) - 1] = 0;
        char *sl = strrchr(dir_dst, '/');
        if (sl) *sl = 0;
        mkdir_p(dir_dst);

        int fd = open(full_dst, O_WRONLY | O_CREAT | O_TRUNC, 0666);
        if (fd < 0) {
            send_json(cfd, 500, "{\"ok\":false,\"error\":\"Cannot write destination file\"}");
            return;
        }
        size_t written = 0;
        if (already > 0) {
            size_t w0 = already > content_len ? content_len : already;
            write(fd, body_start, w0);
            written += w0;
        }
        uint8_t buf[32768];
        while (written < content_len) {
            ssize_t r = recv(cfd, buf, sizeof(buf), 0);
            if (r <= 0) break;
            size_t w = (size_t)r;
            if (written + w > content_len) w = content_len - written;
            write(fd, buf, w);
            written += w;
        }
        close(fd);
        chmod(full_dst, 0666);

        char ok_json[1024];
        snprintf(ok_json, sizeof(ok_json), "{\"ok\":true,\"bytes\":%zu,\"path\":\"%s\"}", written, full_dst);
        send_json(cfd, 200, ok_json);
        return;
    }

    send_json(cfd, 404, "{\"ok\":false,\"error\":\"Not found\"}");
}

int main(void) {
    int sfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sfd < 0) {
        ps5_notify("PS5 Arabi Hub: socket() failed!");
        return 1;
    }
    int opt = 1;
    setsockopt(sfd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    setsockopt(sfd, SOL_SOCKET, SO_REUSEPORT, &opt, sizeof(opt));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);

    int bound_port = 0;
    for (int port = 8899; port <= 8905; port++) {
        addr.sin_port = htons((uint16_t)port);
        if (bind(sfd, (struct sockaddr *)&addr, sizeof(addr)) == 0) {
            bound_port = port;
            break;
        }
    }
    if (!bound_port) {
        char emsg[128];
        snprintf(emsg, sizeof(emsg), "PS5 Arabi Hub: bind failed errno=%d (%s)", errno, strerror(errno));
        ps5_notify(emsg);
        close(sfd);
        return 1;
    }
    listen(sfd, 8);
    char okmsg[128];
    snprintf(okmsg, sizeof(okmsg), "PS5 Arabi Hub v5 UNIVERSAL READY!\nhttp://172.20.10.10:%d", bound_port);
    ps5_notify(okmsg);

    while (1) {
        fd_set rfds;
        FD_ZERO(&rfds);
        FD_SET(sfd, &rfds);
        struct timeval tv;
        tv.tv_sec = 0;
        tv.tv_usec = 50000; /* 200ms auto-mount poll interval */

        int sel = select(sfd + 1, &rfds, NULL, NULL, &tv);
        if (sel > 0 && FD_ISSET(sfd, &rfds)) {
            int cfd = accept(sfd, NULL, NULL);
            if (cfd >= 0) {
                handle_client(cfd);
                close(cfd);
            }
        }
        poll_auto_mount();
    }
    close(sfd);
    return 0;
}

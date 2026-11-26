/*
 * PS5 Arabi POC 2 (v1.1): Universal Running-Game Scanner & Selective Language/Font Extractor
 * Target: PS5 Firmware 5.50 (Orbis OS / etaHEN / elfldr) via ps5-payload-sdk
 * Features live PS5 on-screen notifications for start, game name, paths, extraction progress, and errors.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include "ps5_notify.h"

#define PFSMNT_DIR      "/mnt/sandbox/pfsmnt"
#define OUT_ROOT        "/data/arabi_poc"
#define MAX_EXTRACT_MB  150ULL
#define MAX_EXTRACT_B   (MAX_EXTRACT_MB * 1024ULL * 1024ULL)
#define MAX_TOTAL_B     (350ULL * 1024ULL * 1024ULL)

typedef struct {
    uint64_t total_files;
    uint64_t total_bytes;
    uint64_t matched_files;
    uint64_t matched_bytes;
    uint64_t extracted_files;
    uint64_t extracted_bytes;
    uint64_t skipped_large;
} ScanStats;

static void to_lower_copy(const char *src, char *dst, size_t max_len) {
    size_t i = 0;
    for (; src[i] && i + 1 < max_len; i++) {
        dst[i] = (char)tolower((unsigned char)src[i]);
    }
    dst[i] = '\0';
}

static int ends_with(const char *str, const char *suffix) {
    size_t slen = strlen(str);
    size_t suflen = strlen(suffix);
    if (suflen > slen) return 0;
    return strcmp(str + slen - suflen, suffix) == 0;
}

static int mkdir_p(const char *path) {
    char tmp[1024];
    snprintf(tmp, sizeof(tmp), "%s", path);
    size_t len = strlen(tmp);
    if (len == 0) return -1;
    if (tmp[len - 1] == '/') tmp[len - 1] = '\0';
    for (char *p = tmp + 1; *p; p++) {
        if (*p == '/') {
            *p = '\0';
            mkdir(tmp, 0777);
            *p = '/';
        }
    }
    return mkdir(tmp, 0777) == 0 || errno == EEXIST ? 0 : -1;
}

/* Reads game title from PS5 param.json or PS4 param.sfo if accessible */
static void read_game_name(const char *mount_path, const char *title_id, char *out_name, size_t out_len) {
    snprintf(out_name, out_len, "%s", title_id);

    /* Try PS5 sce_sys/param.json first */
    char json_path[1024];
    snprintf(json_path, sizeof(json_path), "%s/sce_sys/param.json", mount_path);
    FILE *fp = fopen(json_path, "rb");
    if (fp) {
        char buf[16384];
        size_t n = fread(buf, 1, sizeof(buf) - 1, fp);
        fclose(fp);
        buf[n] = '\0';
        const char *k = strstr(buf, "\"titleName\"");
        if (k) {
            const char *colon = strchr(k, ':');
            if (colon) {
                const char *q1 = strchr(colon, '"');
                if (q1) {
                    const char *q2 = strchr(q1 + 1, '"');
                    if (q2 && q2 > q1 + 1) {
                        size_t tlen = (size_t)(q2 - (q1 + 1));
                        if (tlen >= out_len) tlen = out_len - 1;
                        memcpy(out_name, q1 + 1, tlen);
                        out_name[tlen] = '\0';
                        return;
                    }
                }
            }
        }
    }

    /* Try PS4 sce_sys/param.sfo */
    char sfo_path[1024];
    snprintf(sfo_path, sizeof(sfo_path), "%s/sce_sys/param.sfo", mount_path);
    fp = fopen(sfo_path, "rb");
    if (fp) {
        uint8_t sfo[16384];
        size_t n = fread(sfo, 1, sizeof(sfo), fp);
        fclose(fp);
        if (n >= 20 && sfo[0] == 0x00 && sfo[1] == 'P' && sfo[2] == 'S' && sfo[3] == 'F') {
            uint32_t key_off = (uint32_t)sfo[8] | ((uint32_t)sfo[9] << 8) | ((uint32_t)sfo[10] << 16) | ((uint32_t)sfo[11] << 24);
            uint32_t data_off = (uint32_t)sfo[12] | ((uint32_t)sfo[13] << 8) | ((uint32_t)sfo[14] << 16) | ((uint32_t)sfo[15] << 24);
            uint32_t count = (uint32_t)sfo[16] | ((uint32_t)sfo[17] << 8) | ((uint32_t)sfo[18] << 16) | ((uint32_t)sfo[19] << 24);
            for (uint32_t i = 0; i < count && (20 + (i + 1) * 16) <= n; i++) {
                size_t e = 20 + i * 16;
                uint16_t k_rel = (uint16_t)sfo[e] | ((uint16_t)sfo[e + 1] << 8);
                uint32_t d_len = (uint32_t)sfo[e + 4] | ((uint32_t)sfo[e + 5] << 8) | ((uint32_t)sfo[e + 6] << 16) | ((uint32_t)sfo[e + 7] << 24);
                uint32_t d_rel = (uint32_t)sfo[e + 12] | ((uint32_t)sfo[e + 13] << 8) | ((uint32_t)sfo[e + 14] << 16) | ((uint32_t)sfo[e + 15] << 24);
                if (key_off + k_rel < n && strcmp((const char *)(sfo + key_off + k_rel), "TITLE") == 0) {
                    if (data_off + d_rel < n && d_len > 0) {
                        size_t avail = n - (data_off + d_rel);
                        size_t copy_n = d_len < avail ? d_len : avail;
                        if (copy_n >= out_len) copy_n = out_len - 1;
                        memcpy(out_name, sfo + data_off + d_rel, copy_n);
                        out_name[copy_n] = '\0';
                        return;
                    }
                }
            }
        }
    }
}

static int is_localization_or_font(const char *rel_path) {
    char low[1024];
    to_lower_copy(rel_path, low, sizeof(low));

    if (ends_with(low, ".ttf") || ends_with(low, ".otf") ||
        ends_with(low, ".fnt") || ends_with(low, ".ufont") ||
        ends_with(low, ".bdf")) {
        return 1;
    }

    if (ends_with(low, ".locres") || ends_with(low, ".locmeta") ||
        ends_with(low, ".po") || ends_with(low, ".mo") ||
        ends_with(low, ".loc") || ends_with(low, ".lng") ||
        ends_with(low, ".strings") || ends_with(low, ".srt") ||
        ends_with(low, ".sub")) {
        return 1;
    }

    int has_loc_hint = (
        strstr(low, "localiz") != NULL ||
        strstr(low, "/loc/") != NULL ||
        strstr(low, "lang") != NULL ||
        strstr(low, "string") != NULL ||
        strstr(low, "text") != NULL ||
        strstr(low, "font") != NULL ||
        strstr(low, "subtitl") != NULL ||
        strstr(low, "dialog") != NULL ||
        strstr(low, "english") != NULL ||
        strstr(low, "_en.") != NULL ||
        strstr(low, "/en/") != NULL
    );

    if (has_loc_hint) {
        if (ends_with(low, ".json") || ends_with(low, ".xml") ||
            ends_with(low, ".csv") || ends_with(low, ".txt") ||
            ends_with(low, ".ini") || ends_with(low, ".bin") ||
            ends_with(low, ".dat") || ends_with(low, ".bundle") ||
            ends_with(low, ".assets") || ends_with(low, ".pak") ||
            ends_with(low, ".ipk") || ends_with(low, ".uasset")) {
            return 1;
        }
    }

    if (ends_with(low, "resources.assets") || ends_with(low, "catalog.bin") ||
        ends_with(low, "catalog.json")) {
        return 1;
    }

    return 0;
}

static int copy_file(const char *src, const char *dst) {
    char dst_dir[1024];
    snprintf(dst_dir, sizeof(dst_dir), "%s", dst);
    char *slash = strrchr(dst_dir, '/');
    if (slash) {
        *slash = '\0';
        mkdir_p(dst_dir);
    }

    FILE *in = fopen(src, "rb");
    if (!in) return -1;
    FILE *out = fopen(dst, "wb");
    if (!out) {
        fclose(in);
        return -1;
    }

    uint8_t buf[65536];
    size_t n;
    int err = 0;
    while ((n = fread(buf, 1, sizeof(buf), in)) > 0) {
        if (fwrite(buf, 1, n, out) != n) {
            err = -1;
            break;
        }
    }
    fclose(in);
    fclose(out);
    return err;
}

static void walk_dir(
    const char *root,
    const char *rel,
    const char *extract_root,
    FILE *report_fp,
    int *first_entry,
    ScanStats *stats
) {
    char full_dir[1024];
    if (rel[0]) {
        snprintf(full_dir, sizeof(full_dir), "%s/%s", root, rel);
    } else {
        snprintf(full_dir, sizeof(full_dir), "%s", root);
    }

    DIR *d = opendir(full_dir);
    if (!d) return;

    struct dirent *ent;
    while ((ent = readdir(d)) != NULL) {
        if (strcmp(ent->d_name, ".") == 0 || strcmp(ent->d_name, "..") == 0) continue;

        char child_rel[1024];
        char child_full[1024];
        if (rel[0]) {
            snprintf(child_rel, sizeof(child_rel), "%s/%s", rel, ent->d_name);
        } else {
            snprintf(child_rel, sizeof(child_rel), "%s", ent->d_name);
        }
        snprintf(child_full, sizeof(child_full), "%s/%s", root, child_rel);

        struct stat st;
        if (stat(child_full, &st) != 0) continue;

        if (S_ISDIR(st.st_mode)) {
            walk_dir(root, child_rel, extract_root, report_fp, first_entry, stats);
        } else if (S_ISREG(st.st_mode)) {
            stats->total_files++;
            stats->total_bytes += (uint64_t)st.st_size;

            if (is_localization_or_font(child_rel)) {
                stats->matched_files++;
                stats->matched_bytes += (uint64_t)st.st_size;

                int extracted = 0;
                if ((uint64_t)st.st_size <= MAX_EXTRACT_B &&
                    (stats->extracted_bytes + (uint64_t)st.st_size) <= MAX_TOTAL_B) {
                    char dst_path[1024];
                    snprintf(dst_path, sizeof(dst_path), "%s/%s", extract_root, child_rel);
                    if (copy_file(child_full, dst_path) == 0) {
                        extracted = 1;
                        stats->extracted_files++;
                        stats->extracted_bytes += (uint64_t)st.st_size;
                    }
                } else {
                    stats->skipped_large++;
                }

                fprintf(report_fp, "%s\n    {\"path\": \"%s\", \"size\": %llu, \"extracted\": %s}",
                        (*first_entry) ? "" : ",",
                        child_rel,
                        (unsigned long long)st.st_size,
                        extracted ? "true" : "false");
                *first_entry = 0;
            }
        }
    }
    closedir(d);
}

static int find_mounted_game(char *out_mount, size_t mount_len, char *out_title_id, size_t tid_len) {
    DIR *d = opendir(PFSMNT_DIR);
    if (!d) return -1;

    struct dirent *ent;
    int found = 0;
    while ((ent = readdir(d)) != NULL) {
        if (strncmp(ent->d_name, "CUSA", 4) == 0 || strncmp(ent->d_name, "PPSA", 4) == 0) {
            if (strstr(ent->d_name, "-app0-patch0-union") != NULL) {
                snprintf(out_mount, mount_len, "%s/%s", PFSMNT_DIR, ent->d_name);
                snprintf(out_title_id, tid_len, "%.9s", ent->d_name);
                found = 1;
                break;
            } else if (!found && strstr(ent->d_name, "-app0") != NULL) {
                snprintf(out_mount, mount_len, "%s/%s", PFSMNT_DIR, ent->d_name);
                snprintf(out_title_id, tid_len, "%.9s", ent->d_name);
                found = 1;
            }
        }
    }
    closedir(d);
    return found ? 0 : -1;
}

int main(void) {
    ps5_notify("PS5 Arabi Scanner: Started!\nChecking running game in /mnt/sandbox/pfsmnt...");
    mkdir_p(OUT_ROOT);

    char mount_path[512] = {0};
    char title_id[32] = {0};

    FILE *log_fp = fopen(OUT_ROOT "/scanner.log", "w");
    if (!log_fp) {
        ps5_notify("PS5 Arabi ERROR:\nCannot write to /data/arabi_poc/scanner.log");
        return 1;
    }

    if (find_mounted_game(mount_path, sizeof(mount_path), title_id, sizeof(title_id)) != 0) {
        fprintf(log_fp, "FAIL: No running PS4 (CUSA*) or PS5 (PPSA*) game found in %s\n", PFSMNT_DIR);
        fclose(log_fp);
        ps5_notify("PS5 Arabi ERROR:\nNo running game found!\nLaunch a game FIRST, then send payload.");
        return 1;
    }

    char game_name[128] = {0};
    read_game_name(mount_path, title_id, game_name, sizeof(game_name));

    ps5_notify("Game Detected:\n%s (%s)\nMount: %s\nScanning language & font files...",
               game_name, title_id, mount_path);

    char extract_dir[512];
    char report_path[512];
    snprintf(extract_dir, sizeof(extract_dir), "%s/extracted/%s", OUT_ROOT, title_id);
    snprintf(report_path, sizeof(report_path), "%s/scan_%s.json", OUT_ROOT, title_id);
    mkdir_p(extract_dir);

    FILE *rfp = fopen(report_path, "w");
    if (!rfp) {
        fprintf(log_fp, "FAIL: Cannot write report %s\n", report_path);
        fclose(log_fp);
        ps5_notify("PS5 Arabi ERROR:\nCannot create report file:\n%s", report_path);
        return 1;
    }

    ScanStats stats;
    memset(&stats, 0, sizeof(stats));
    int first_entry = 1;

    fprintf(rfp, "{\n  \"game_name\": \"%s\",\n  \"title_id\": \"%s\",\n  \"mount_path\": \"%s\",\n  \"files\": [",
            game_name, title_id, mount_path);
    walk_dir(mount_path, "", extract_dir, rfp, &first_entry, &stats);
    fprintf(rfp, "\n  ],\n");
    fprintf(rfp, "  \"summary\": {\n");
    fprintf(rfp, "    \"total_files\": %llu,\n", (unsigned long long)stats.total_files);
    fprintf(rfp, "    \"total_bytes\": %llu,\n", (unsigned long long)stats.total_bytes);
    fprintf(rfp, "    \"matched_files\": %llu,\n", (unsigned long long)stats.matched_files);
    fprintf(rfp, "    \"matched_bytes\": %llu,\n", (unsigned long long)stats.matched_bytes);
    fprintf(rfp, "    \"extracted_files\": %llu,\n", (unsigned long long)stats.extracted_files);
    fprintf(rfp, "    \"extracted_bytes\": %llu,\n", (unsigned long long)stats.extracted_bytes);
    fprintf(rfp, "    \"skipped_large\": %llu\n", (unsigned long long)stats.skipped_large);
    fprintf(rfp, "  }\n}\n");
    fclose(rfp);

    fprintf(log_fp, "PASS: Scanned %s (%s)\n", game_name, title_id);
    fprintf(log_fp, "Mount: %s\n", mount_path);
    fprintf(log_fp, "Total game files: %llu (%.2f MB)\n",
            (unsigned long long)stats.total_files, (double)stats.total_bytes / (1024.0 * 1024.0));
    fprintf(log_fp, "Matched loc/font: %llu (%.2f MB)\n",
            (unsigned long long)stats.matched_files, (double)stats.matched_bytes / (1024.0 * 1024.0));
    fprintf(log_fp, "Extracted safely: %llu (%.2f MB)\n",
            (unsigned long long)stats.extracted_files, (double)stats.extracted_bytes / (1024.0 * 1024.0));
    fprintf(log_fp, "Extracted folder: %s\n", extract_dir);
    fprintf(log_fp, "Report saved to: %s\n", report_path);
    fclose(log_fp);

    ps5_notify("PS5 Arabi DONE! (%s)\nExtracted %llu files (%.1f MB)\nSaved in: %s",
               game_name,
               (unsigned long long)stats.extracted_files,
               (double)stats.extracted_bytes / (1024.0 * 1024.0),
               extract_dir);
    return 0;
}

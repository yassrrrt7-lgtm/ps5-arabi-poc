/*
 * PS5 Arabi Universal Extractor v2.1
 * Target: PS5 Firmware 5.50 (Orbis OS / etaHEN / ShadowMount+) via ps5-payload-sdk
 *
 * New in v2.1:
 * - Automatically extracts BOTH UE4 v10/v11 Primary Index (.index.bin) AND FullDirectoryIndex (.fulldir.bin)
 *   so ALL internal filenames + exact byte offsets of 200,000+ files are retrieved in ~11 MB instead of 22+ GB!
 * - Supports /data/arabi_poc/extract_ranges.txt (format: <rel_pak_path>|<offset>|<size>|<out_name>)
 *   to extract ONLY exact language/font byte slices from any huge .pak file with ZERO 2x storage!
 */

#define _FILE_OFFSET_BITS 64
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
#define SANDBOX_DIR     "/mnt/sandbox"
#define OUT_ROOT        "/data/arabi_poc"
#define MAX_INDEX_B     (32ULL * 1024ULL * 1024ULL)
#define UE_PAK_MAGIC    0x5A6F12E1U

typedef struct {
    uint64_t total_files;
    uint64_t total_bytes;
    uint64_t pak_found;
    uint64_t extracted_files;
    uint64_t extracted_bytes;
} ScanStats;

static uint32_t rd_u32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static int32_t rd_i32(const uint8_t *p) {
    return (int32_t)rd_u32(p);
}

static uint64_t rd_u64(const uint8_t *p) {
    return (uint64_t)rd_u32(p) | ((uint64_t)rd_u32(p + 4) << 32);
}

static void to_lower_copy(const char *src, char *dst, size_t max_len) {
    size_t i = 0;
    for (; src[i] && i + 1 < max_len; i++) dst[i] = (char)tolower((unsigned char)src[i]);
    dst[i] = '\0';
}

static int ends_with(const char *str, const char *suffix) {
    size_t slen = strlen(str), suflen = strlen(suffix);
    return (suflen <= slen) && (strcmp(str + slen - suflen, suffix) == 0);
}

static int mkdir_p(const char *path) {
    char tmp[1024];
    snprintf(tmp, sizeof(tmp), "%s", path);
    size_t len = strlen(tmp);
    if (len == 0) return -1;
    if (tmp[len - 1] == '/') tmp[len - 1] = '\0';
    for (char *p = tmp + 1; *p; p++) {
        if (*p == '/') { *p = '\0'; mkdir(tmp, 0777); *p = '/'; }
    }
    return mkdir(tmp, 0777) == 0 || errno == EEXIST ? 0 : -1;
}

static int dir_exists(const char *path) {
    struct stat st;
    return (stat(path, &st) == 0 && S_ISDIR(st.st_mode));
}

static void read_game_name(const char *mount_path, const char *title_id, char *out_name, size_t out_len) {
    snprintf(out_name, out_len, "%s", title_id);
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
            const char *q1 = colon ? strchr(colon, '"') : NULL;
            const char *q2 = q1 ? strchr(q1 + 1, '"') : NULL;
            if (q2 && q2 > q1 + 1) {
                size_t tlen = (size_t)(q2 - (q1 + 1));
                if (tlen >= out_len) tlen = out_len - 1;
                memcpy(out_name, q1 + 1, tlen);
                out_name[tlen] = '\0';
            }
        }
    }
}

static int copy_slice(FILE *fp, uint64_t offset, uint64_t size, const char *dst_path) {
    char dst_dir[1024];
    snprintf(dst_dir, sizeof(dst_dir), "%s", dst_path);
    char *slash = strrchr(dst_dir, '/');
    if (slash) { *slash = '\0'; mkdir_p(dst_dir); }

    if (fseeko(fp, (off_t)offset, SEEK_SET) != 0) return -1;
    FILE *out = fopen(dst_path, "wb");
    if (!out) return -1;

    uint8_t buf[65536];
    uint64_t rem = size;
    while (rem > 0) {
        size_t chunk = rem > sizeof(buf) ? sizeof(buf) : (size_t)rem;
        size_t n = fread(buf, 1, chunk, fp);
        if (n == 0) break;
        if (fwrite(buf, 1, n, out) != n) { fclose(out); return -1; }
        rem -= n;
    }
    fclose(out);
    return (rem == 0) ? 0 : -1;
}

static int inspect_and_extract_pak(
    const char *pak_full_path, const char *pak_rel_path,
    const char *extract_root, FILE *log_fp, ScanStats *stats
) {
    FILE *fp = fopen(pak_full_path, "rb");
    if (!fp) return -1;
    if (fseeko(fp, 0, SEEK_END) != 0) { fclose(fp); return -1; }
    off_t fsize = ftello(fp);
    if (fsize < 64) { fclose(fp); return -1; }

    size_t tail_len = (fsize > 512) ? 512 : (size_t)fsize;
    uint8_t tail[512];
    if (fseeko(fp, fsize - (off_t)tail_len, SEEK_SET) != 0 ||
        fread(tail, 1, tail_len, fp) != tail_len) { fclose(fp); return -1; }

    int magic_pos = -1;
    for (int i = (int)tail_len - 24; i >= 0; i--) {
        if (rd_u32(tail + i) == UE_PAK_MAGIC) { magic_pos = i; break; }
    }
    if (magic_pos < 0) { fclose(fp); return -1; }

    uint32_t version = rd_u32(tail + magic_pos + 4);
    uint64_t idx_offset = rd_u64(tail + magic_pos + 8);
    uint64_t idx_size = rd_u64(tail + magic_pos + 16);
    int encrypted = (magic_pos >= 1) ? (tail[magic_pos - 1] != 0) : 0;

    const char *base_name = strrchr(pak_rel_path, '/');
    base_name = base_name ? (base_name + 1) : pak_rel_path;

    fprintf(log_fp, "[PAK] %s | v%u | Enc=%s | Index=%.2f MB\n",
            pak_rel_path, version, encrypted ? "YES" : "NO", (double)idx_size / (1024.0 * 1024.0));

    if (idx_size == 0 || idx_size > MAX_INDEX_B || (off_t)(idx_offset + idx_size) > fsize) {
        fclose(fp);
        return -1;
    }

    char out_idx[1024];
    snprintf(out_idx, sizeof(out_idx), "%s/%s.index.bin", extract_root, base_name);
    if (copy_slice(fp, idx_offset, idx_size, out_idx) == 0) {
        stats->extracted_files++;
        stats->extracted_bytes += idx_size;
    }

    /* For UE4 v10/v11 unencrypted primary index, also extract FullDirectoryIndex! */
    if (!encrypted && version >= 10) {
        uint8_t hdr[256];
        size_t hlen = idx_size < sizeof(hdr) ? (size_t)idx_size : sizeof(hdr);
        if (fseeko(fp, (off_t)idx_offset, SEEK_SET) == 0 && fread(hdr, 1, hlen, fp) == hlen) {
            size_t pos = 0;
            int32_t slen = rd_i32(hdr + pos); pos += 4;
            size_t str_bytes = (slen >= 0) ? (size_t)slen : (size_t)(-slen * 2);
            if (pos + str_bytes + 16 < hlen) {
                pos += str_bytes;
                pos += 4; /* NumEntries */
                pos += 8; /* PathHashSeed */
                uint32_t has_ph = rd_u32(hdr + pos); pos += 4;
                if (has_ph && pos + 36 < hlen) pos += 36; /* offset(8)+size(8)+sha1(20) */
                if (pos + 20 <= hlen) {
                    uint32_t has_fd = rd_u32(hdr + pos); pos += 4;
                    if (has_fd && pos + 16 <= hlen) {
                        uint64_t fd_off = rd_u64(hdr + pos);
                        uint64_t fd_size = rd_u64(hdr + pos + 8);
                        if (fd_size > 0 && fd_size <= MAX_INDEX_B && (off_t)(fd_off + fd_size) <= fsize) {
                            char out_fd[1024];
                            snprintf(out_fd, sizeof(out_fd), "%s/%s.fulldir.bin", extract_root, base_name);
                            if (copy_slice(fp, fd_off, fd_size, out_fd) == 0) {
                                stats->extracted_files++;
                                stats->extracted_bytes += fd_size;
                                fprintf(log_fp, "[PAK] Extracted FullDirectoryIndex: %.2f MB -> %s\n",
                                        (double)fd_size / (1024.0 * 1024.0), out_fd);
                                ps5_notify("PAK FullDir Extracted!\n%s\nFilenames: %.2f MB saved!",
                                           base_name, (double)fd_size / (1024.0 * 1024.0));
                            }
                        }
                    }
                }
            }
        }
    }

    fclose(fp);
    return 0;
}

static void process_extract_ranges(const char *mount_path, const char *extract_root, FILE *log_fp, ScanStats *stats) {
    FILE *rf = fopen(OUT_ROOT "/extract_ranges.txt", "r");
    if (!rf) return;

    char line[1024];
    int count = 0;
    while (fgets(line, sizeof(line), rf)) {
        char *nl = strpbrk(line, "\r\n");
        if (nl) *nl = '\0';
        if (line[0] == '\0' || line[0] == '#') continue;

        char *p1 = strchr(line, '|');
        char *p2 = p1 ? strchr(p1 + 1, '|') : NULL;
        char *p3 = p2 ? strchr(p2 + 1, '|') : NULL;
        if (!p1 || !p2 || !p3) continue;
        *p1 = *p2 = *p3 = '\0';

        const char *rel_pak = line;
        uint64_t off = strtoull(p1 + 1, NULL, 10);
        uint64_t sz = strtoull(p2 + 1, NULL, 10);
        const char *out_name = p3 + 1;

        char full_pak[1024], dst[1024];
        snprintf(full_pak, sizeof(full_pak), "%s/%s", mount_path, rel_pak);
        snprintf(dst, sizeof(dst), "%s/slices/%s", extract_root, out_name);

        FILE *fp = fopen(full_pak, "rb");
        if (fp) {
            if (copy_slice(fp, off, sz, dst) == 0) {
                count++;
                stats->extracted_files++;
                stats->extracted_bytes += sz;
                fprintf(log_fp, "[SLICE] Extracted %s (%llu bytes)\n", out_name, (unsigned long long)sz);
            }
            fclose(fp);
        }
    }
    fclose(rf);
    if (count > 0) {
        ps5_notify("PS5 Arabi Slices DONE!\nExtracted %d target files!", count);
    }
}

static void walk_dir(const char *root, const char *rel, const char *extract_root, FILE *all_fp, FILE *log_fp, ScanStats *stats) {
    char full_dir[1024];
    if (rel[0]) snprintf(full_dir, sizeof(full_dir), "%s/%s", root, rel);
    else snprintf(full_dir, sizeof(full_dir), "%s", root);

    DIR *d = opendir(full_dir);
    if (!d) return;

    struct dirent *ent;
    while ((ent = readdir(d)) != NULL) {
        if (strcmp(ent->d_name, ".") == 0 || strcmp(ent->d_name, "..") == 0) continue;
        char child_rel[1024], child_full[1024];
        if (rel[0]) snprintf(child_rel, sizeof(child_rel), "%s/%s", rel, ent->d_name);
        else snprintf(child_rel, sizeof(child_rel), "%s", ent->d_name);
        snprintf(child_full, sizeof(child_full), "%s/%s", root, child_rel);

        struct stat st;
        if (stat(child_full, &st) != 0) continue;

        if (S_ISDIR(st.st_mode)) {
            walk_dir(root, child_rel, extract_root, all_fp, log_fp, stats);
        } else if (S_ISREG(st.st_mode)) {
            stats->total_files++;
            stats->total_bytes += (uint64_t)st.st_size;
            if (all_fp) fprintf(all_fp, "%llu\t%s\n", (unsigned long long)st.st_size, child_rel);

            char low[1024];
            to_lower_copy(child_rel, low, sizeof(low));
            if (ends_with(low, ".pak")) {
                stats->pak_found++;
                inspect_and_extract_pak(child_full, child_rel, extract_root, log_fp, stats);
            }
        }
    }
    closedir(d);
}

static int find_mounted_game(char *out_mount, size_t mount_len, char *out_title_id, size_t tid_len) {
    DIR *d = opendir(PFSMNT_DIR);
    if (d) {
        struct dirent *ent;
        int found = 0;
        while ((ent = readdir(d)) != NULL) {
            if (strncmp(ent->d_name, "CUSA", 4) == 0 || strncmp(ent->d_name, "PPSA", 4) == 0) {
                if (strstr(ent->d_name, "-app0-patch0-union") != NULL) {
                    snprintf(out_mount, mount_len, "%s/%s", PFSMNT_DIR, ent->d_name);
                    snprintf(out_title_id, tid_len, "%.9s", ent->d_name);
                    closedir(d);
                    return 0;
                } else if (!found && strstr(ent->d_name, "-app0") != NULL) {
                    snprintf(out_mount, mount_len, "%s/%s", PFSMNT_DIR, ent->d_name);
                    snprintf(out_title_id, tid_len, "%.9s", ent->d_name);
                    found = 1;
                }
            }
        }
        closedir(d);
        if (found) return 0;
    }

    d = opendir(SANDBOX_DIR);
    if (d) {
        struct dirent *ent;
        while ((ent = readdir(d)) != NULL) {
            if (strncmp(ent->d_name, "PPSA", 4) == 0 || strncmp(ent->d_name, "CUSA", 4) == 0) {
                char candidate[1024];
                snprintf(candidate, sizeof(candidate), "%s/%s/app0", SANDBOX_DIR, ent->d_name);
                if (dir_exists(candidate)) {
                    snprintf(out_mount, mount_len, "%s", candidate);
                    snprintf(out_title_id, tid_len, "%.9s", ent->d_name);
                    closedir(d);
                    return 0;
                }
            }
        }
        closedir(d);
    }
    return -1;
}

int main(void) {
    ps5_notify("PS5 Arabi v2.1: Started!\nExtracting PAK Index + FullDir...");
    mkdir_p(OUT_ROOT);

    char mount_path[512] = {0}, title_id[32] = {0};
    FILE *log_fp = fopen(OUT_ROOT "/scanner.log", "w");
    if (!log_fp) return 1;

    if (find_mounted_game(mount_path, sizeof(mount_path), title_id, sizeof(title_id)) != 0) {
        fprintf(log_fp, "FAIL: No running game found.\n");
        fclose(log_fp);
        ps5_notify("PS5 Arabi ERROR:\nNo running game found!");
        return 1;
    }

    char game_name[128] = {0};
    read_game_name(mount_path, title_id, game_name, sizeof(game_name));

    char extract_dir[512], all_files_path[512];
    snprintf(extract_dir, sizeof(extract_dir), "%s/extracted/%s", OUT_ROOT, title_id);
    snprintf(all_files_path, sizeof(all_files_path), "%s/all_files_%s.txt", OUT_ROOT, title_id);
    mkdir_p(extract_dir);

    FILE *afp = fopen(all_files_path, "w");
    ScanStats stats;
    memset(&stats, 0, sizeof(stats));

    walk_dir(mount_path, "", extract_dir, afp, log_fp, &stats);
    process_extract_ranges(mount_path, extract_dir, log_fp, &stats);
    if (afp) fclose(afp);

    fprintf(log_fp, "PASS v2.1: %s (%s) | Extracted %llu files (%.2f MB)\n",
            game_name, title_id, (unsigned long long)stats.extracted_files,
            (double)stats.extracted_bytes / (1024.0 * 1024.0));
    fclose(log_fp);

    ps5_notify("PS5 Arabi v2.1 DONE! (%s)\nExtracted: %llu files (%.1f MB)\nDir: %s",
               game_name, (unsigned long long)stats.extracted_files,
               (double)stats.extracted_bytes / (1024.0 * 1024.0), extract_dir);
    return 0;
}

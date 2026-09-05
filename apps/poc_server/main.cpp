/*
 * poc_server -- read the market-data streams of the mktdata_poc bitstream
 * from Linux userspace.
 *
 * Carries the continuous FIFO dumpers that used to live in mktdata_poc_test
 * (which is now, like mktdata_poc_bm/_rtos, just the three self-tests).
 *
 * Commands:
 *   debug   - continuously poll axi_fifo_debug, hex-dump frames (Ctrl-C stops).
 *   mdebug  - same for axi_fifo_mdebug.
 *   cmd     - same for axi_fifo_cmd.
 *   poll    - poll FIFOs concurrently, one thread per FIFO. With no extra
 *             args, all three; otherwise the named subset, e.g.
 *             "poll debug mdebug".
 *   reset   - pulse the NI IP reset (axi_gpio_1: 0 -> 1 -> 0) and exit.
 *
 * Runs as root (needs /dev/uioN).
 */

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <dirent.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/mman.h>
#include <unistd.h>

/* ---- Address map (matches vivado/mktdata_poc.tcl) ---- */
#define ADDR_FIFO_MDEBUG_CTRL   0x80050000UL
#define ADDR_FIFO_MDEBUG_DATA   0x80060000UL
#define ADDR_FIFO_DEBUG_CTRL    0x80070000UL
#define ADDR_FIFO_DEBUG_DATA    0x80080000UL
#define ADDR_GPIO_1             0x80090000UL
#define ADDR_FIFO_CMD_CTRL      0x800A0000UL
#define ADDR_FIFO_CMD_DATA      0x800B0000UL
#define MAP_SIZE                0x10000UL

/* ---- AXI GPIO v2.0 ---- */
#define GPIO_DATA   0x00    /* channel 1 data register */

/* Idle backoff for the FIFO pollers (us). */
#define POLL_IDLE_US 200

/* ---- AXI4-Stream FIFO (PG080) ---- */
#define FIFO_ISR    0x00
#define FIFO_RDFR   0x18
#define FIFO_RDFO   0x1C
#define FIFO_RLR    0x24
#define FIFO_SRR    0x28

#define FIFO_AXI4_RDFD  0x1000

#define FIFO_RESET_MAGIC  0xA5

/* ---- Helpers ---- */

static int read_hex(const char *path, unsigned long *out)
{
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    int n = fscanf(f, "%lx", out);
    fclose(f);
    return (n == 1) ? 0 : -1;
}

static int find_uio_for(unsigned long addr, char *out, size_t outlen)
{
    DIR *d = opendir("/sys/class/uio");
    if (!d) return -1;
    struct dirent *de;
    while ((de = readdir(d)) != NULL) {
        if (strncmp(de->d_name, "uio", 3) != 0) continue;
        char p[256];
        unsigned long a = 0;
        snprintf(p, sizeof(p), "/sys/class/uio/%s/maps/map0/addr", de->d_name);
        if (read_hex(p, &a) < 0) continue;
        if (a == addr) {
            snprintf(out, outlen, "/dev/%s", de->d_name);
            closedir(d);
            return 0;
        }
    }
    closedir(d);
    return -1;
}

static volatile uint32_t *map_uio(unsigned long addr, const char *label, int *out_fd)
{
    char dev[64];
    if (find_uio_for(addr, dev, sizeof(dev)) < 0) {
        fprintf(stderr, "  %-22s: NO UIO at 0x%08lx\n", label, addr);
        return nullptr;
    }
    int fd = open(dev, O_RDWR | O_SYNC);
    if (fd < 0) { perror(dev); return nullptr; }
    void *p = mmap(nullptr, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (p == MAP_FAILED) { perror("mmap"); close(fd); return nullptr; }
    printf("  %-22s: %s @ 0x%08lx\n", label, dev, addr);
    *out_fd = fd;
    return static_cast<volatile uint32_t *>(p);
}

static inline void w32(volatile uint32_t *base, uint32_t off, uint32_t v) {
    base[off / 4] = v;
    asm volatile("dsb sy" ::: "memory");
}
static inline uint32_t r32(volatile uint32_t *base, uint32_t off) {
    asm volatile("dsb sy" ::: "memory");
    return base[off / 4];
}

/* ---- FIFO pollers ---- */

static volatile sig_atomic_t g_stop = 0;

static void on_sigint(int sig)
{
    (void)sig;
    g_stop = 1;
}

static void install_sigint(void)
{
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = on_sigint;
    sigaction(SIGINT, &sa, nullptr);
}

static std::mutex g_print_lock;

struct poller {
    const char         *tag;    /* "DEBUG" / "MDEBUG" / "CMD" */
    volatile uint32_t  *ctrl;   /* PG080 control (S_AXI) base */
    volatile uint32_t  *data;   /* PG080 data (S_AXI_FULL) base */
};

/* Format one frame as a hex dump and emit it atomically. Bytes are printed
 * in wire order: on a little-endian AXI4 read of the 64-bit RDFD, the first
 * byte on the stream is the LSB of the word. */
static void print_frame(const char *tag, unsigned frame,
                        const std::vector<uint64_t> &words,
                        uint32_t len, int partial)
{
    std::string buf;
    buf.reserve(64 + ((size_t)len + 7) / 8 * 32);
    char line[64];

    snprintf(line, sizeof(line), "[%s] frame %u (%u bytes)%s:\n",
             tag, frame, len, partial ? " (partial)" : "");
    buf += line;
    for (uint32_t off = 0; off < len; off += 8) {
        uint32_t n = (len - off < 8) ? (len - off) : 8;
        snprintf(line, sizeof(line), "  %04x: ", off);
        buf += line;
        for (uint32_t i = 0; i < n; i++) {
            snprintf(line, sizeof(line), "%02x",
                     (unsigned)((words[off / 8] >> (8 * i)) & 0xff));
            buf += line;
        }
        buf += '\n';
    }

    std::lock_guard<std::mutex> lock(g_print_lock);
    fputs(buf.c_str(), stdout);
    fflush(stdout);
}

/* Poll one RX-only PG080 FIFO until g_stop. Also usable as a thread entry. */
static void fifo_poller(poller *p)
{
    volatile uint32_t *ctrl = p->ctrl;
    volatile uint64_t *d64  = reinterpret_cast<volatile uint64_t *>(p->data);

    /* RX-only core reset: SRR + RDFR, then clear sticky ISR. No TX regs. */
    w32(ctrl, FIFO_SRR, FIFO_RESET_MAGIC);
    usleep(1000);
    w32(ctrl, FIFO_RDFR, FIFO_RESET_MAGIC);
    usleep(1000);
    w32(ctrl, FIFO_ISR, 0xFFFFFFFFu);

    {
        std::lock_guard<std::mutex> lock(g_print_lock);
        printf("[%s] polling (post-reset RDFO=%u)\n", p->tag, r32(ctrl, FIFO_RDFO));
        fflush(stdout);
    }

    unsigned frame = 0;
    int warned_no_tlast = 0;

    while (!g_stop) {
        if (r32(ctrl, FIFO_RDFO) == 0) {
            usleep(POLL_IDLE_US);
            continue;
        }

        /* RLR is valid only once a complete (TLAST-terminated) frame is in
         * the FIFO; reading it pops the next frame's byte length. */
        uint32_t rlr = r32(ctrl, FIFO_RLR);
        if (rlr == 0) {
            if (!warned_no_tlast) {
                fprintf(stderr, "[%s] words present but no complete frame "
                                "(stream without TLAST?)\n", p->tag);
                warned_no_tlast = 1;
            }
            usleep(POLL_IDLE_US);
            continue;
        }
        warned_no_tlast = 0;

        uint32_t len     = rlr & 0x7FFFFFFFu;
        int      partial = (rlr >> 31) & 1;
        uint32_t nwords  = (len + 7) / 8;

        /* Sanity: a frame can't exceed the RX FIFO (512 x 64-bit words).
         * An implausible RLR means we've lost sync -- reset and resync. */
        if (len == 0 || len > 4096) {
            fprintf(stderr, "[%s] implausible RLR=0x%08x -- resetting RX FIFO\n",
                    p->tag, rlr);
            w32(ctrl, FIFO_RDFR, FIFO_RESET_MAGIC);
            usleep(1000);
            w32(ctrl, FIFO_ISR, 0xFFFFFFFFu);
            continue;
        }

        std::vector<uint64_t> words(nwords);
        for (uint32_t i = 0; i < nwords; i++) {
            asm volatile("dsb sy" ::: "memory");
            words[i] = d64[FIFO_AXI4_RDFD / 8];
        }

        frame++;
        print_frame(p->tag, frame, words, len, partial);
    }
}

/* Map a poller's ctrl+data UIOs; returns 0 on success. */
static int map_poller(poller *p, const char *tag,
                      unsigned long ctrl_addr, unsigned long data_addr)
{
    char label[32];
    int fd_c, fd_d;
    p->tag = tag;
    snprintf(label, sizeof(label), "axi_fifo_%s (ctrl)", tag);
    p->ctrl = map_uio(ctrl_addr, label, &fd_c);
    snprintf(label, sizeof(label), "axi_fifo_%s (data)", tag);
    p->data = map_uio(data_addr, label, &fd_d);
    if (!p->ctrl || !p->data) {
        fprintf(stderr, "axi_fifo_%s not found -- was the kria app rebuilt and "
                        "reloaded with the new device-tree overlay?\n", tag);
        return -1;
    }
    return 0;
}

static int cmd_poll_one(const char *tag, unsigned long ctrl_addr,
                        unsigned long data_addr)
{
    printf("Opening UIOs:\n");
    poller p;
    if (map_poller(&p, tag, ctrl_addr, data_addr) < 0) return 1;

    install_sigint();
    printf("Polling %s. Press Ctrl-C to stop.\n", tag);
    fifo_poller(&p);
    printf("\nStopped.\n");
    return 0;
}

/* The pollable FIFOs, by command-line name. */
static const struct {
    const char    *name;   /* lower-case, as typed on the command line */
    const char    *tag;    /* upper-case, as printed in frame dumps */
    unsigned long  ctrl;
    unsigned long  data;
} g_fifos[] = {
    { "debug",  "DEBUG",  ADDR_FIFO_DEBUG_CTRL,  ADDR_FIFO_DEBUG_DATA  },
    { "mdebug", "MDEBUG", ADDR_FIFO_MDEBUG_CTRL, ADDR_FIFO_MDEBUG_DATA },
    { "cmd",    "CMD",    ADDR_FIFO_CMD_CTRL,    ADDR_FIFO_CMD_DATA    },
};
#define N_FIFOS ((int)(sizeof(g_fifos) / sizeof(g_fifos[0])))

/* poll [debug] [mdebug] [cmd] -- no names means all of them. */
static int cmd_poll(int nsel, char **sel)
{
    int pick[N_FIFOS] = { 0 };

    if (nsel == 0) {
        for (int i = 0; i < N_FIFOS; i++) pick[i] = 1;
    } else {
        for (int s = 0; s < nsel; s++) {
            int i;
            for (i = 0; i < N_FIFOS; i++)
                if (strcmp(sel[s], g_fifos[i].name) == 0) { pick[i] = 1; break; }
            if (i == N_FIFOS) {
                fprintf(stderr, "unknown FIFO '%s' (expected debug, mdebug or cmd)\n",
                        sel[s]);
                return 2;
            }
        }
    }

    printf("Opening UIOs:\n");
    poller p[N_FIFOS];
    int n = 0;
    for (int i = 0; i < N_FIFOS; i++) {
        if (!pick[i]) continue;
        if (map_poller(&p[n], g_fifos[i].tag, g_fifos[i].ctrl, g_fifos[i].data) < 0)
            return 1;
        n++;
    }

    install_sigint();
    printf("Polling");
    for (int i = 0; i < n; i++) printf("%s%s", i ? "+" : " ", p[i].tag);
    printf(". Press Ctrl-C to stop.\n");

    if (n == 1) {           /* no point spawning a thread for one FIFO */
        fifo_poller(&p[0]);
        printf("\nStopped.\n");
        return 0;
    }

    std::vector<std::thread> threads;
    threads.reserve(n);
    for (int i = 0; i < n; i++)
        threads.emplace_back(fifo_poller, &p[i]);
    for (auto &t : threads) t.join();
    printf("\nStopped.\n");
    return 0;
}

/* ---- Command: reset (pulse the NI IP reset via axi_gpio_1) ---- */

static int cmd_reset(void)
{
    printf("Opening UIOs:\n");
    int fd_g1;
    volatile uint32_t *gpio1 = map_uio(ADDR_GPIO_1, "axi_gpio_1", &fd_g1);
    if (!gpio1) {
        fprintf(stderr, "axi_gpio_1 not found -- was the kria app rebuilt and "
                        "reloaded with the new device-tree overlay?\n");
        return 1;
    }

    printf("Pulsing NI IP reset (axi_gpio_1 -> ctrlind_17_ip_reset): 0");
    w32(gpio1, GPIO_DATA, 0);
    usleep(1000);
    printf(" -> 1");
    w32(gpio1, GPIO_DATA, 1);
    usleep(1000);
    printf(" -> 0\n");
    w32(gpio1, GPIO_DATA, 0);
    usleep(1000);
    printf("NI IP reset done.\n");
    return 0;
}

/* ---- main ---- */

static void usage(const char *argv0)
{
    fprintf(stderr,
        "Usage: %s <command>\n"
        "  debug    continuously poll axi_fifo_debug and hex-dump frames\n"
        "  mdebug   continuously poll axi_fifo_mdebug and hex-dump frames\n"
        "  cmd      continuously poll axi_fifo_cmd and hex-dump frames\n"
        "  poll [debug] [mdebug] [cmd]\n"
        "           poll the named FIFOs (default: all three), one thread per FIFO\n"
        "  reset    pulse the NI IP reset (axi_gpio_1: 0 -> 1 -> 0) and exit\n",
        argv0);
}

int main(int argc, char **argv)
{
    if (argc < 2) { usage(argv[0]); return 2; }

    if (strcmp(argv[1], "poll") == 0)   return cmd_poll(argc - 2, argv + 2);
    if (argc != 2) { usage(argv[0]); return 2; }

    if (strcmp(argv[1], "reset") == 0)  return cmd_reset();
    if (strcmp(argv[1], "debug") == 0)
        return cmd_poll_one("DEBUG",  ADDR_FIFO_DEBUG_CTRL,  ADDR_FIFO_DEBUG_DATA);
    if (strcmp(argv[1], "mdebug") == 0)
        return cmd_poll_one("MDEBUG", ADDR_FIFO_MDEBUG_CTRL, ADDR_FIFO_MDEBUG_DATA);
    if (strcmp(argv[1], "cmd") == 0)
        return cmd_poll_one("CMD",    ADDR_FIFO_CMD_CTRL,    ADDR_FIFO_CMD_DATA);

    usage(argv[0]);
    return 2;
}

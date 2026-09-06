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
 *   serve   - poll like `poll`, but broadcast every frame to TCP subscribers
 *             as NDJSON instead of hex-dumping. Wire-compatible with
 *             scripts/fifo_server.py (same protocol, same JSON shape), so
 *             scripts/fifo_subscribe.py works against either.
 *             serve [--port 5555] [--bind 0.0.0.0] [--fifos cmd debug mdebug]
 *   reset   - pulse the NI IP reset (axi_gpio_1: 0 -> 1 -> 0) and exit.
 *
 * serve protocol: client connects, sends one line -- e.g. "SUBSCRIBE cmd
 * debug" ("SUBSCRIBE *" or an empty line means all) -- gets a hello line
 * {"hello":...,"subscribed":[...]}, then NDJSON frames forever:
 *
 *   {"fifo":"CMD","frame":3,"ts":1699.123,"len":16,"partial":false,
 *    "data":"beefbeef00000000..."}
 *
 * The pollers drain the FIFOs continuously whether or not anyone is
 * subscribed; slow subscribers are dropped-from, not waited-for (per-client
 * queue, frames are discarded for that client when it falls behind).
 *
 * Runs as root (needs /dev/uioN).
 */

#include <atomic>
#include <cctype>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <memory>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <vector>

#include <arpa/inet.h>
#include <dirent.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/time.h>
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

/* Per-subscriber frame queue before dropping (matches fifo_server.py). */
#define QUEUE_MAX 4096

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

/* ---- Broker: fan frames out to per-subscriber queues (serve mode) ---- */

static volatile sig_atomic_t g_stop = 0;

struct Client {
    int                      fd;
    std::set<std::string>    names;   /* subscribed lower-case fifo names */
    std::mutex               m;
    std::condition_variable  cv;
    std::deque<std::string>  q;       /* pending NDJSON lines */
};

struct Broker {
    std::mutex                            m;
    std::vector<std::shared_ptr<Client>>  subs;

    void add(std::shared_ptr<Client> c) {
        std::lock_guard<std::mutex> lock(m);
        subs.push_back(std::move(c));
    }
    void remove(const std::shared_ptr<Client> &c) {
        std::lock_guard<std::mutex> lock(m);
        for (auto it = subs.begin(); it != subs.end(); ++it)
            if (*it == c) { subs.erase(it); break; }
    }
    /* Queue one line for every subscriber of `name`; drop it for clients
     * that are QUEUE_MAX behind (slow client, never wait for it). */
    void publish(const std::string &name, const std::string &line) {
        std::lock_guard<std::mutex> lock(m);
        for (auto &c : subs) {
            if (!c->names.count(name)) continue;
            std::lock_guard<std::mutex> cl(c->m);
            if (c->q.size() >= QUEUE_MAX) continue;
            c->q.push_back(line);
            c->cv.notify_one();
        }
    }
};

/* ---- FIFO pollers ---- */

static void on_sigstop(int sig)
{
    (void)sig;
    g_stop = 1;
}

static void install_sigstop(void)
{
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = on_sigstop;
    sigaction(SIGINT, &sa, nullptr);
    sigaction(SIGTERM, &sa, nullptr);
}

static std::mutex g_print_lock;

struct poller {
    const char         *name;   /* "debug" / "mdebug" / "cmd" (subscriptions) */
    const char         *tag;    /* "DEBUG" / "MDEBUG" / "CMD" (output) */
    volatile uint32_t  *ctrl;   /* PG080 control (S_AXI) base */
    volatile uint32_t  *data;   /* PG080 data (S_AXI_FULL) base */
    Broker             *broker; /* nullptr = hex-dump to stdout instead */
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

/* Build the NDJSON line fifo_server.py emits for one frame. All values are
 * machine-generated (no JSON escaping needed). */
static std::string json_frame(const char *tag, unsigned frame,
                              const std::vector<uint64_t> &words,
                              uint32_t len, int partial)
{
    struct timeval tv;
    gettimeofday(&tv, nullptr);
    double ts = (double)tv.tv_sec + (double)tv.tv_usec / 1e6;

    std::string out;
    out.reserve(96 + (size_t)len * 2);
    char head[128];
    snprintf(head, sizeof(head),
             "{\"fifo\":\"%s\",\"frame\":%u,\"ts\":%.6f,\"len\":%u,"
             "\"partial\":%s,\"data\":\"",
             tag, frame, ts, len, partial ? "true" : "false");
    out += head;
    static const char hexd[] = "0123456789abcdef";
    for (uint32_t i = 0; i < len; i++) {
        uint8_t b = (uint8_t)((words[i / 8] >> (8 * (i % 8))) & 0xff);
        out += hexd[b >> 4];
        out += hexd[b & 0xf];
    }
    out += "\"}\n";
    return out;
}

/* Poll one RX-only PG080 FIFO until g_stop. Emits to the broker in serve
 * mode, to stdout otherwise. Also usable as a thread entry. */
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
        if (p->broker)
            p->broker->publish(p->name, json_frame(p->tag, frame, words, len, partial));
        else
            print_frame(p->tag, frame, words, len, partial);
    }
}

/* Map a poller's ctrl+data UIOs; returns 0 on success. */
static int map_poller(poller *p, const char *name, const char *tag,
                      unsigned long ctrl_addr, unsigned long data_addr)
{
    char label[32];
    int fd_c, fd_d;
    p->name = name;
    p->tag = tag;
    p->broker = nullptr;
    snprintf(label, sizeof(label), "axi_fifo_%s (ctrl)", name);
    p->ctrl = map_uio(ctrl_addr, label, &fd_c);
    snprintf(label, sizeof(label), "axi_fifo_%s (data)", name);
    p->data = map_uio(data_addr, label, &fd_d);
    if (!p->ctrl || !p->data) {
        fprintf(stderr, "axi_fifo_%s not found -- was the kria app rebuilt and "
                        "reloaded with the new device-tree overlay?\n", name);
        return -1;
    }
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

static int fifo_index(const char *name)
{
    for (int i = 0; i < N_FIFOS; i++)
        if (strcmp(name, g_fifos[i].name) == 0) return i;
    return -1;
}

static int cmd_poll_one(int fi)
{
    printf("Opening UIOs:\n");
    poller p;
    if (map_poller(&p, g_fifos[fi].name, g_fifos[fi].tag,
                   g_fifos[fi].ctrl, g_fifos[fi].data) < 0) return 1;

    install_sigstop();
    printf("Polling %s. Press Ctrl-C to stop.\n", p.tag);
    fifo_poller(&p);
    printf("\nStopped.\n");
    return 0;
}

/* poll [debug] [mdebug] [cmd] -- no names means all of them. */
static int cmd_poll(int nsel, char **sel)
{
    int pick[N_FIFOS] = { 0 };

    if (nsel == 0) {
        for (int i = 0; i < N_FIFOS; i++) pick[i] = 1;
    } else {
        for (int s = 0; s < nsel; s++) {
            int i = fifo_index(sel[s]);
            if (i < 0) {
                fprintf(stderr, "unknown FIFO '%s' (expected debug, mdebug or cmd)\n",
                        sel[s]);
                return 2;
            }
            pick[i] = 1;
        }
    }

    printf("Opening UIOs:\n");
    poller p[N_FIFOS];
    int n = 0;
    for (int i = 0; i < N_FIFOS; i++) {
        if (!pick[i]) continue;
        if (map_poller(&p[n], g_fifos[i].name, g_fifos[i].tag,
                       g_fifos[i].ctrl, g_fifos[i].data) < 0)
            return 1;
        n++;
    }

    install_sigstop();
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

/* ---- serve: NDJSON/TCP broadcast, wire-compatible with fifo_server.py ---- */

/* Read one \n-terminated line (the SUBSCRIBE request) from fd. */
static int read_line(int fd, std::string &out)
{
    out.clear();
    char c;
    while (out.size() < 1024) {
        ssize_t r = recv(fd, &c, 1, 0);
        if (r <= 0) return -1;
        if (c == '\n') return 0;
        if (c != '\r') out += c;
    }
    return 0;
}

static int send_all(int fd, const std::string &s)
{
    size_t off = 0;
    while (off < s.size()) {
        ssize_t w = send(fd, s.data() + off, s.size() - off, MSG_NOSIGNAL);
        if (w <= 0) return -1;
        off += (size_t)w;
    }
    return 0;
}

/* Serve one subscriber: parse its request, register with the broker, then
 * forward queued lines until it disconnects (send fails) or g_stop. */
static void client_thread(Broker *broker, std::shared_ptr<Client> c,
                          std::string peer, const std::set<std::string> &available)
{
    /* Request: "SUBSCRIBE cmd debug" / "SUBSCRIBE *" / "" (30 s to send it). */
    struct timeval tmo = { 30, 0 };
    setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &tmo, sizeof(tmo));
    std::string req;
    if (read_line(c->fd, req) < 0) { close(c->fd); return; }

    bool star = false;
    std::set<std::string> names;
    char *tokens = strdup(req.c_str());
    int first = 1;
    for (char *t = strtok(tokens, " \t"); t; t = strtok(nullptr, " \t")) {
        std::string w(t);
        for (auto &ch : w) ch = (char)tolower((unsigned char)ch);
        if (first && w == "subscribe") { first = 0; continue; }
        first = 0;
        if (w == "*") star = true;
        else if (available.count(w)) names.insert(w);
    }
    free(tokens);
    if (names.empty() || star) names = available;
    c->names = names;

    /* Stuck-client guard: a peer that stops reading fails the send after 10 s
     * instead of wedging this thread (fifo_server.py just blocks there). */
    tmo = { 10, 0 };
    setsockopt(c->fd, SOL_SOCKET, SO_SNDTIMEO, &tmo, sizeof(tmo));

    std::string hello = "{\"hello\": \"mktdata_poc fifo_server\", \"subscribed\": [";
    int i = 0;
    for (auto &n : names) {          /* std::set iterates sorted */
        if (i++) hello += ", ";
        hello += "\"" + n + "\"";
    }
    hello += "]}\n";
    if (send_all(c->fd, hello) < 0) { close(c->fd); return; }

    {
        std::lock_guard<std::mutex> lock(g_print_lock);
        printf("[server] %s subscribed to [", peer.c_str());
        i = 0;
        for (auto &n : names) printf("%s'%s'", i++ ? ", " : "", n.c_str());
        printf("]\n");
        fflush(stdout);
    }
    broker->add(c);

    bool alive = true;
    while (alive && !g_stop) {
        std::deque<std::string> batch;
        {
            std::unique_lock<std::mutex> lock(c->m);
            c->cv.wait_for(lock, std::chrono::seconds(1),
                           [&] { return !c->q.empty() || g_stop; });
            batch.swap(c->q);
        }
        for (auto &line : batch)
            if (send_all(c->fd, line) < 0) { alive = false; break; }
    }

    broker->remove(c);
    close(c->fd);
    std::lock_guard<std::mutex> lock(g_print_lock);
    printf("[server] %s disconnected\n", peer.c_str());
    fflush(stdout);
}

/* serve [--port N] [--bind ADDR] [--fifos name...] */
static int cmd_serve(int argc, char **argv)
{
    int port = 5555;
    const char *bind_addr = "0.0.0.0";
    int pick[N_FIFOS] = { 0 };
    int any_picked = 0;

    for (int a = 0; a < argc; a++) {
        if (strcmp(argv[a], "--port") == 0 && a + 1 < argc) {
            port = atoi(argv[++a]);
        } else if (strcmp(argv[a], "--bind") == 0 && a + 1 < argc) {
            bind_addr = argv[++a];
        } else if (strcmp(argv[a], "--fifos") == 0) {
            while (a + 1 < argc && argv[a + 1][0] != '-') {
                int i = fifo_index(argv[++a]);
                if (i < 0) {
                    fprintf(stderr, "unknown FIFO '%s' (expected debug, mdebug or cmd)\n",
                            argv[a]);
                    return 2;
                }
                pick[i] = any_picked = 1;
            }
        } else {
            fprintf(stderr, "serve: unknown argument '%s'\n", argv[a]);
            return 2;
        }
    }
    if (!any_picked)
        for (int i = 0; i < N_FIFOS; i++) pick[i] = 1;

    /* Never freed: detached client threads may outlive cmd_serve's return. */
    Broker *broker = new Broker();

    printf("Opening UIOs:\n");
    static poller p[N_FIFOS];
    std::set<std::string> available;
    int n = 0;
    for (int i = 0; i < N_FIFOS; i++) {
        if (!pick[i]) continue;
        if (map_poller(&p[n], g_fifos[i].name, g_fifos[i].tag,
                       g_fifos[i].ctrl, g_fifos[i].data) < 0)
            return 1;
        p[n].broker = broker;
        available.insert(g_fifos[i].name);
        n++;
    }

    int srv = socket(AF_INET, SOCK_STREAM, 0);
    if (srv < 0) { perror("socket"); return 1; }
    int one = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in sa;
    memset(&sa, 0, sizeof(sa));
    sa.sin_family = AF_INET;
    sa.sin_port = htons((uint16_t)port);
    if (inet_pton(AF_INET, bind_addr, &sa.sin_addr) != 1) {
        fprintf(stderr, "bad --bind address '%s'\n", bind_addr);
        return 2;
    }
    if (bind(srv, (struct sockaddr *)&sa, sizeof(sa)) < 0) { perror("bind"); return 1; }
    if (listen(srv, 8) < 0) { perror("listen"); return 1; }

    install_sigstop();
    std::vector<std::thread> pollers;
    pollers.reserve(n);
    for (int i = 0; i < n; i++)
        pollers.emplace_back(fifo_poller, &p[i]);

    printf("[server] listening on %s:%d (fifos:", bind_addr, port);
    int i = 0;
    for (auto &nm : available) printf("%s %s", i++ ? "," : "", nm.c_str());
    printf("). Ctrl-C to stop.\n");
    fflush(stdout);

    while (!g_stop) {
        struct pollfd pfd = { srv, POLLIN, 0 };
        int pr = poll(&pfd, 1, 1000);
        if (pr <= 0) continue;
        struct sockaddr_in ca;
        socklen_t cl = sizeof(ca);
        int cfd = accept(srv, (struct sockaddr *)&ca, &cl);
        if (cfd < 0) continue;
        char ip[INET_ADDRSTRLEN] = "?";
        inet_ntop(AF_INET, &ca.sin_addr, ip, sizeof(ip));
        char peer[64];
        snprintf(peer, sizeof(peer), "%s:%u", ip, (unsigned)ntohs(ca.sin_port));
        auto c = std::make_shared<Client>();
        c->fd = cfd;
        std::thread(client_thread, broker, c, std::string(peer), available).detach();
    }

    close(srv);
    for (auto &t : pollers) t.join();
    /* Detached client threads notice g_stop within their 1 s cv timeout (or
     * their 10 s send timeout); give them a moment before process teardown. */
    usleep(1200 * 1000);
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
        "  serve [--port 5555] [--bind 0.0.0.0] [--fifos cmd debug mdebug]\n"
        "           poll and broadcast frames as NDJSON to TCP subscribers\n"
        "           (wire-compatible with scripts/fifo_server.py)\n"
        "  reset    pulse the NI IP reset (axi_gpio_1: 0 -> 1 -> 0) and exit\n",
        argv0);
}

int main(int argc, char **argv)
{
    if (argc < 2) { usage(argv[0]); return 2; }

    if (strcmp(argv[1], "poll") == 0)   return cmd_poll(argc - 2, argv + 2);
    if (strcmp(argv[1], "serve") == 0)  return cmd_serve(argc - 2, argv + 2);
    if (argc != 2) { usage(argv[0]); return 2; }

    if (strcmp(argv[1], "reset") == 0)  return cmd_reset();
    int fi = fifo_index(argv[1]);
    if (fi >= 0) return cmd_poll_one(fi);

    usage(argv[0]);
    return 2;
}

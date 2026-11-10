/* poc_mon -- drive the axis_mon counters (vivado/ip/axis_mon.v) through
 * axi_gpio_mon at 0x80120000 on the KR260.
 *
 *   sudo ./poc_mon id              print the block id (0x4D4F4E32 MON2 = LabVIEW-IP bitstream,
 *                                  0x4D4F4E33 MON3 = pure-RTL bitstream, 8 extra counters)
 *   sudo ./poc_mon sink on|off     1 = TREADY always asserted to the NI IP, records dropped
 *   sudo ./poc_mon clear           zero every counter (both clock domains)
 *   sudo ./poc_mon snap            snapshot and print every counter as "name value" lines
 *   sudo ./poc_mon show            print the previous snapshot again
 *   sudo ./poc_mon start [sink]    = sink on (optional) + clear
 *   sudo ./poc_mon stop            = snap, then sink off
 *
 * Switch sink mode only while nothing is being parsed: flipping it mid-record
 * hands axis_dw_cmd a partial record. See axis_mon.v for the register map.
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <inttypes.h>
#include <sys/mman.h>

#define ADDR_GPIO_MON 0x80120000UL
#define MAP_SIZE      0x10000UL
#define GPIO_DATA     0x0000      /* ch1: ctrl (output)  */
#define GPIO2_DATA    0x0008      /* ch2: status (input) */

#define CTRL_SINK  (1u << 0)
#define CTRL_CLEAR (1u << 1)
#define CTRL_SNAP  (1u << 2)
#define CTRL_SEL(n) ((uint32_t)(n) << 8)

#define MON_ID2 0x4D4F4E32u         /* "MON2": vivado/ip/axis_mon.v (LabVIEW IP bitstream) */
#define MON_ID3 0x4D4F4E33u         /* "MON3": vivado_rtl/ip/axis_mon_w.v (pure-RTL bitstream), sel 17.. added */
#define NREGS2 17
#define NREGS3 25
static unsigned nregs = NREGS2;

static const char *names[NREGS3] = {
    "records", "beats", "stall_cycles", "seq_gaps", "bad_len", "lat_max_ticks",
    "unsupported", "bad_magic", "fwd_records", "rx_frames", "rx_bad", "rx_beats",
    "first_seq", "last_seq", "flags", "id", "lat_min_ticks",
    "frames_pass", "frames_filtered", "frames_trunc", "frames_dropped", "hdr_records",
    "msg_trunc", "dbg_dropped", "pitch_seq_gaps" };

static int find_uio_for(unsigned long addr, char *out, size_t outlen)
{
    DIR *d = opendir("/sys/class/uio");
    if (!d) return -1;
    struct dirent *de;
    while ((de = readdir(d))) {
        if (strncmp(de->d_name, "uio", 3) != 0) continue;
        char p[256]; snprintf(p, sizeof p, "/sys/class/uio/%s/maps/map0/addr", de->d_name);
        FILE *f = fopen(p, "r"); if (!f) continue;
        unsigned long a = 0; int ok = fscanf(f, "%lx", &a) == 1; fclose(f);
        if (ok && a == addr) { snprintf(out, outlen, "/dev/%s", de->d_name); closedir(d); return 0; }
    }
    closedir(d);
    return -1;
}

static volatile uint32_t *g;
static uint32_t ctrl;     /* shadow of ch1; sink bit persists across invocations in hardware,
                             so read it back at start */

static inline void w32(uint32_t off, uint32_t v) { g[off / 4] = v; asm volatile("dsb sy" ::: "memory"); }
static inline uint32_t r32(uint32_t off) { asm volatile("dsb sy" ::: "memory"); return g[off / 4]; }

static void set_ctrl(uint32_t v) { ctrl = v; w32(GPIO_DATA, v); }
static void pulse(uint32_t bit) { set_ctrl(ctrl & ~bit); set_ctrl(ctrl | bit); set_ctrl(ctrl & ~bit); }
/* MON3 refreshes `status` through a clock-domain handshake (~100 ns); read until two
 * consecutive reads agree so a read that races the refresh is never returned. */
static uint32_t sel(unsigned n)
{
    set_ctrl((ctrl & ~CTRL_SEL(31)) | CTRL_SEL(n));
    uint32_t a = r32(GPIO2_DATA);
    for (int i = 0; i < 8; i++) { uint32_t b = r32(GPIO2_DATA); if (b == a) break; a = b; }
    return a;
}

static void print_all(void)
{
    for (unsigned i = 0; i < nregs; i++) {
        uint32_t v = sel(i);
        if (i == 15) printf("%s 0x%08x\n", names[i], v);
        else if (i == 5 || i == 16) printf("%s %" PRId32 "\n", names[i], (int32_t)v);   /* signed latencies */
        else printf("%s %" PRIu32 "\n", names[i], v);
    }
    printf("sink %u\n", ctrl & CTRL_SINK ? 1u : 0u);
}

static int do_snap(void)
{
    pulse(CTRL_SNAP);
    for (int i = 0; i < 1000; i++) {           /* RX-domain copy needs a few 156 MHz cycles */
        if ((sel(14) & 1u) == 0) { print_all(); return 0; }
        usleep(10);
    }
    fprintf(stderr, "snapshot never completed (flags bit0 stuck) -- RX clock stopped? link down?\n");
    print_all();
    return 3;
}

int main(int argc, char **argv)
{
    if (argc < 2) { fprintf(stderr, "usage: poc_mon id|sink on|off|clear|snap|show|start [sink]|stop\n"); return 1; }
    char dev[64];
    if (find_uio_for(ADDR_GPIO_MON, dev, sizeof dev) < 0) { fprintf(stderr, "no UIO device maps axi_gpio_mon (0x%lx) -- app loaded? dtbo has the node?\n", ADDR_GPIO_MON); return 2; }
    int fd = open(dev, O_RDWR | O_SYNC);
    if (fd < 0) { perror(dev); return 2; }
    g = mmap(NULL, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (g == MAP_FAILED) { perror("mmap"); return 2; }

    ctrl = r32(GPIO_DATA) & CTRL_SINK;          /* keep the sink state, drop stale pulse/sel bits */
    set_ctrl(ctrl);
    uint32_t id = sel(15);
    if (id == MON_ID3) nregs = NREGS3;
    else if (id != MON_ID2) { fprintf(stderr, "axi_gpio_mon answers but id = 0x%08x, expected 0x%08x (MON2) or 0x%08x (MON3) -- wrong bitstream?\n", id, MON_ID2, MON_ID3); return 2; }

    const char *cmd = argv[1];
    if (!strcmp(cmd, "id")) { printf("id 0x%08x sink %u\n", id, ctrl & CTRL_SINK ? 1u : 0u); return 0; }
    if (!strcmp(cmd, "sink")) {
        if (argc < 3) { fprintf(stderr, "sink on|off\n"); return 1; }
        set_ctrl(!strcmp(argv[2], "on") ? (ctrl | CTRL_SINK) : (ctrl & ~CTRL_SINK));
        printf("sink %u\n", ctrl & CTRL_SINK ? 1u : 0u); return 0;
    }
    if (!strcmp(cmd, "clear")) { pulse(CTRL_CLEAR); return 0; }
    if (!strcmp(cmd, "snap"))  return do_snap();
    if (!strcmp(cmd, "show"))  { print_all(); return 0; }
    if (!strcmp(cmd, "start")) {
        if (argc > 2 && !strcmp(argv[2], "sink")) set_ctrl(ctrl | CTRL_SINK);
        pulse(CTRL_CLEAR);
        printf("sink %u\n", ctrl & CTRL_SINK ? 1u : 0u); return 0;
    }
    if (!strcmp(cmd, "stop")) { int rc = do_snap(); set_ctrl(ctrl & ~CTRL_SINK); return rc; }
    fprintf(stderr, "unknown command %s\n", cmd);
    return 1;
}

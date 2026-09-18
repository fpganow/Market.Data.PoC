/*
 * poc_inject -- push one Ethernet frame into the NI market-data IP on the KR260
 * without any external 10G traffic source.
 *
 * Path:  DDR --axi_dma_0 MM2S--> tx_data_fifo --> axis2xgmii --> xxv_ethernet TX
 *        --(PCS local loopback, MODE_REG bit 31)--> xxv RX --> xgmii2axis
 *        --lv stream--> NI IP (DEBUG/CMD/MDEBUG FIFOs)  and  --zy stream--> S2MM --> DDR
 *
 * The S2MM capture proves the frame came back through the RX PCS; the NI IP's
 * output is read separately with `poc_server poll`.
 *
 * axi_dma_0 is SG mode with 32-bit addressing (DDR_LOW only), so the single
 * 4 KiB page holding the tx buffer, rx buffer and both BDs must have a physical
 * address below 2 GiB. Runs as root (UIO + /proc/self/pagemap).
 *
 * Usage: poc_inject <frame.hex> [--no-loopback] [--repeat N] [--gap-us U]
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <inttypes.h>
#include <sys/mman.h>

#define ADDR_DMA0   0x80020000UL
#define ADDR_XXV    0x80030000UL
#define MAP_SIZE    0x10000UL

/* xxv_ethernet AXI4-Lite (from the generated *_axi4lite_reg.h) */
#define XXV_GT_RESET_REG        0x0000
#define XXV_RESET_REG           0x0004
#define XXV_MODE_REG            0x0008
#define XXV_MODE_LOCAL_LOOPBACK (1u << 31)
#define XXV_CONF_TX_REG1        0x000C
#define XXV_CONF_RX_REG1        0x0014
#define XXV_TICK_REG            0x0020
#define XXV_STAT_TX_STATUS      0x0400
#define XXV_STAT_RX_STATUS      0x0404
#define XXV_STAT_RX_BLOCK_LOCK  0x040C
#define XXV_STAT_TX_TOTAL_PKTS  0x0700
#define XXV_STAT_RX_TOTAL_PKTS  0x0808
#define XXV_STAT_RX_GOOD_PKTS   0x0810

/* AXI DMA (PG021), SG mode */
#define DMA_MM2S_DMACR   0x00
#define DMA_MM2S_DMASR   0x04
#define DMA_MM2S_CURDESC 0x08
#define DMA_MM2S_TAILDESC 0x10
#define DMA_S2MM_DMACR   0x30
#define DMA_S2MM_DMASR   0x34
#define DMA_S2MM_CURDESC 0x38
#define DMA_S2MM_TAILDESC 0x40
#define DMA_DMACR_RS     (1u << 0)
#define DMA_DMACR_RESET  (1u << 2)
#define DMA_DMASR_HALTED (1u << 0)
#define DMA_DMASR_IDLE   (1u << 1)
#define DMA_DMASR_ERR_MASK 0x770u

#define BD_NXTDESC     0x00
#define BD_BUFADDR     0x08
#define BD_CONTROL     0x18
#define BD_STATUS      0x1C
#define BD_CTRL_SOF    (1u << 27)
#define BD_CTRL_EOF    (1u << 26)
#define BD_LEN_MASK    0x03FFFFFFu
#define BD_STS_CMPLT   (1u << 31)

#define TX_OFF   0x000
#define RX_OFF   0x800
#define BD_MM2S  0xF00
#define BD_S2MM  0xF40
#define RX_MAX   (BD_MM2S - RX_OFF)   /* 1792 B */
#define TX_MAX   (RX_OFF - TX_OFF)    /* 2048 B */

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

static volatile uint32_t *map_uio(unsigned long addr, const char *label)
{
    char dev[64];
    if (find_uio_for(addr, dev, sizeof dev) < 0) {
        fprintf(stderr, "no UIO device maps 0x%08lx (%s) -- is the dtso updated and the app loaded?\n", addr, label);
        return NULL;
    }
    int fd = open(dev, O_RDWR | O_SYNC);
    if (fd < 0) { perror(dev); return NULL; }
    void *p = mmap(NULL, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (p == MAP_FAILED) { perror("mmap"); return NULL; }
    printf("  %-16s: %s @ 0x%08lx\n", label, dev, addr);
    return (volatile uint32_t *)p;
}

static inline void w32(volatile uint32_t *b, uint32_t off, uint32_t v) { b[off / 4] = v; asm volatile("dsb sy" ::: "memory"); }
static inline uint32_t r32(volatile uint32_t *b, uint32_t off) { asm volatile("dsb sy" ::: "memory"); return b[off / 4]; }

static void dcache_clean(const void *p0, size_t len)
{
    for (uintptr_t p = (uintptr_t)p0 & ~63ul; p < (uintptr_t)p0 + len; p += 64) asm volatile("dc cvac, %0" :: "r"(p) : "memory");
    asm volatile("dsb sy" ::: "memory");
}
static void dcache_inval(const void *p0, size_t len)
{
    asm volatile("dsb sy" ::: "memory");
    for (uintptr_t p = (uintptr_t)p0 & ~63ul; p < (uintptr_t)p0 + len; p += 64) asm volatile("dc civac, %0" :: "r"(p) : "memory");
    asm volatile("dsb sy" ::: "memory");
}

static int virt_to_phys(void *va, uint64_t *pa)
{
    int fd = open("/proc/self/pagemap", O_RDONLY);
    if (fd < 0) { perror("/proc/self/pagemap"); return -1; }
    long pg = sysconf(_SC_PAGESIZE);
    uint64_t e = 0;
    if (pread(fd, &e, 8, ((uintptr_t)va / pg) * 8) != 8) { close(fd); return -1; }
    close(fd);
    if (!(e & (1ULL << 63))) return -1;
    uint64_t pfn = e & ((1ULL << 55) - 1);
    if (!pfn) { fprintf(stderr, "pagemap PFN=0 -- run as root\n"); return -1; }
    *pa = pfn * pg + ((uintptr_t)va % pg);
    return 0;
}

/* One locked 4 KiB page with PA < 2 GiB (axi_dma_0 has 32-bit addresses).
 * On the K26 the upper 2 GiB of DDR sits above 4 GiB and the allocator hands
 * user pages out from there first, so single-page attempts never land low.
 * Instead map one big populated region, scan its pagemap for the first page
 * below 2 GiB, lock that page and release the rest. */
static void *alloc_low_page(uint64_t *pa_out)
{
    long pg = sysconf(_SC_PAGESIZE);
    size_t sizes[] = { 512ul << 20, 1024ul << 20, 1536ul << 20, 2048ul << 20, 2560ul << 20 };
    for (size_t si = 0; si < sizeof sizes / sizeof sizes[0]; si++) {
        size_t sz = sizes[si];
        uint8_t *reg = mmap(NULL, sz, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_POPULATE, -1, 0);
        if (reg == MAP_FAILED) { fprintf(stderr, "mmap %zu MiB: %s\n", sz >> 20, strerror(errno)); continue; }
        int fd = open("/proc/self/pagemap", O_RDONLY);
        if (fd < 0) { perror("/proc/self/pagemap"); munmap(reg, sz); return NULL; }
        size_t npages = sz / pg;
        uint64_t *ents = malloc(npages * 8);
        ssize_t got = pread(fd, ents, npages * 8, ((uintptr_t)reg / pg) * 8);
        close(fd);
        long found = -1; uint64_t pa = 0;
        for (size_t i = 0; got > 0 && i < (size_t)got / 8; i++) {
            uint64_t e = ents[i];
            if (!(e & (1ULL << 63))) continue;
            uint64_t pfn = e & ((1ULL << 55) - 1);
            if (pfn && pfn * pg < 0x80000000ULL) { found = (long)i; pa = pfn * pg; break; }
        }
        free(ents);
        if (found < 0) { munmap(reg, sz); fprintf(stderr, "  no page below 2 GiB in a %zu MiB region\n", sz >> 20); continue; }
        uint8_t *page = reg + (size_t)found * pg;
        if (mlock(page, pg) != 0) { perror("mlock"); munmap(reg, sz); return NULL; }
        /* Release everything except our page (keeps the VA/PA of that page). */
        if (found > 0) munmap(reg, (size_t)found * pg);
        if ((size_t)found + 1 < npages) munmap(page + pg, sz - ((size_t)found + 1) * pg);
        memset(page, 0, pg);
        uint64_t pa2 = 0;
        if (virt_to_phys(page, &pa2) != 0 || pa2 != pa) { fprintf(stderr, "low page moved (0x%" PRIx64 " -> 0x%" PRIx64 ")\n", pa, pa2); return NULL; }
        printf("  low DMA page found after scanning %zu MiB: PA=0x%08" PRIx64 "\n", sz >> 20, pa);
        *pa_out = pa;
        return page;
    }
    fprintf(stderr, "could not find a page below 2 GiB\n");
    return NULL;
}

static int load_hex(const char *path, uint8_t *buf, size_t max)
{
    FILE *f = fopen(path, "r"); if (!f) { perror(path); return -1; }
    size_t n = 0; int c, hi = -1;
    while ((c = fgetc(f)) != EOF) {
        int v;
        if (c >= '0' && c <= '9') v = c - '0';
        else if (c >= 'a' && c <= 'f') v = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') v = c - 'A' + 10;
        else continue;
        if (hi < 0) hi = v; else { if (n < max) buf[n++] = (uint8_t)(hi << 4 | v); hi = -1; }
    }
    fclose(f);
    return (int)n;
}

static int dma_wait(volatile uint32_t *dma, uint32_t sr, const char *name, int timeout_ms)
{
    for (int i = 0; i < timeout_ms * 10; i++) {
        uint32_t s = r32(dma, sr);
        if (s & DMA_DMASR_ERR_MASK) { printf("  %s SR=0x%08x ERROR\n", name, s); return -1; }
        if (s & DMA_DMASR_IDLE) return 0;
        usleep(100);
    }
    printf("  %s timeout, SR=0x%08x\n", name, r32(dma, sr));
    return 1;
}

int main(int argc, char **argv)
{
    if (argc < 2) { fprintf(stderr, "usage: %s <frame.hex> [--no-loopback] [--repeat N] [--gap-us U]\n", argv[0]); return 2; }
    int loopback = 1, repeat = 1, gap_us = 1000, rx_only = 0, rx_wait_ms = 500;
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--no-loopback")) loopback = 0;          /* leave MODE_REG as is */
        else if (!strcmp(argv[i], "--loopback-off")) loopback = -1;   /* clear the bit */
        else if (!strcmp(argv[i], "--rx-only")) { rx_only = 1; rx_wait_ms = 8000; }
        else if (!strcmp(argv[i], "--rx-wait-ms") && i + 1 < argc) rx_wait_ms = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--repeat") && i + 1 < argc) repeat = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--gap-us") && i + 1 < argc) gap_us = atoi(argv[++i]);
    }

    printf("Opening UIOs:\n");
    volatile uint32_t *xxv = map_uio(ADDR_XXV, "xxv_ethernet_0");
    volatile uint32_t *dma = map_uio(ADDR_DMA0, "axi_dma_0");
    if (!xxv || !dma) return 1;

    uint64_t pa; uint8_t *page = alloc_low_page(&pa);
    if (!page) return 1;
    uint8_t *tx = page + TX_OFF, *rx = page + RX_OFF, *bdm = page + BD_MM2S, *bds = page + BD_S2MM;
    int flen = load_hex(argv[1], tx, TX_MAX);
    if (flen <= 0) return 1;
    printf("  frame %d bytes from %s; page PA=0x%08" PRIx64 "\n", flen, argv[1], pa);
    printf("  dst %02x:%02x:%02x:%02x:%02x:%02x  src %02x:%02x:%02x:%02x:%02x:%02x  type %02x%02x\n",
           tx[0], tx[1], tx[2], tx[3], tx[4], tx[5], tx[6], tx[7], tx[8], tx[9], tx[10], tx[11], tx[12], tx[13]);

    /* --- XXV PCS/PMA: local loopback and link status --- */
    printf("xxv regs: GT_RESET=0x%08x RESET=0x%08x CONF_TX=0x%08x CONF_RX=0x%08x\n",
           r32(xxv, XXV_GT_RESET_REG), r32(xxv, XXV_RESET_REG), r32(xxv, XXV_CONF_TX_REG1), r32(xxv, XXV_CONF_RX_REG1));
    printf("xxv before: MODE=0x%08x TXSTAT=0x%08x RXSTAT=0x%08x BLOCK_LOCK=0x%08x\n",
           r32(xxv, XXV_MODE_REG), r32(xxv, XXV_STAT_TX_STATUS), r32(xxv, XXV_STAT_RX_STATUS), r32(xxv, XXV_STAT_RX_BLOCK_LOCK));
    if (loopback < 0) {
        w32(xxv, XXV_MODE_REG, r32(xxv, XXV_MODE_REG) & ~XXV_MODE_LOCAL_LOOPBACK);
        usleep(200000);
        printf("xxv loopback OFF: MODE=0x%08x BLOCK_LOCK=0x%08x (cable RX)\n", r32(xxv, XXV_MODE_REG), r32(xxv, XXV_STAT_RX_BLOCK_LOCK));
    } else if (loopback) {
        w32(xxv, XXV_MODE_REG, r32(xxv, XXV_MODE_REG) | XXV_MODE_LOCAL_LOOPBACK);
        int lock = 0;
        for (int i = 0; i < 2000; i++) { if (r32(xxv, XXV_STAT_RX_BLOCK_LOCK) & 1) { lock = 1; break; } usleep(1000); }
        printf("xxv loopback on: MODE=0x%08x BLOCK_LOCK=0x%08x RXSTAT=0x%08x %s\n",
               r32(xxv, XXV_MODE_REG), r32(xxv, XXV_STAT_RX_BLOCK_LOCK), r32(xxv, XXV_STAT_RX_STATUS),
               lock ? "(locked)" : "(NO block lock)");
    }
    w32(xxv, XXV_TICK_REG, 1); usleep(1000);
    uint32_t tx0 = r32(xxv, XXV_STAT_TX_TOTAL_PKTS), rx0 = r32(xxv, XXV_STAT_RX_TOTAL_PKTS), rxg0 = r32(xxv, XXV_STAT_RX_GOOD_PKTS);

    /* --- DMA reset --- */
    w32(dma, DMA_MM2S_DMACR, DMA_DMACR_RESET); w32(dma, DMA_S2MM_DMACR, DMA_DMACR_RESET);
    for (int i = 0; i < 10000 && ((r32(dma, DMA_MM2S_DMACR) | r32(dma, DMA_S2MM_DMACR)) & DMA_DMACR_RESET); i++) ;
    printf("dma after reset: MM2S CR=0x%08x SR=0x%08x  S2MM CR=0x%08x SR=0x%08x\n",
           r32(dma, DMA_MM2S_DMACR), r32(dma, DMA_MM2S_DMASR), r32(dma, DMA_S2MM_DMACR), r32(dma, DMA_S2MM_DMASR));

    int rx_ok = 0, tx_ok = 0;
    for (int n = 0; n < repeat; n++) {
        /* S2MM first: one BD, whole rx buffer. */
        memset(bds, 0, 64); memset(rx, 0, RX_MAX);
        *(volatile uint32_t *)(bds + BD_NXTDESC) = (uint32_t)(pa + BD_S2MM);
        *(volatile uint32_t *)(bds + BD_BUFADDR) = (uint32_t)(pa + RX_OFF);
        *(volatile uint32_t *)(bds + BD_CONTROL) = RX_MAX & BD_LEN_MASK;
        dcache_clean(bds, 64); dcache_inval(rx, RX_MAX);
        w32(dma, DMA_S2MM_CURDESC, (uint32_t)(pa + BD_S2MM));
        w32(dma, DMA_S2MM_DMACR, DMA_DMACR_RS);
        w32(dma, DMA_S2MM_TAILDESC, (uint32_t)(pa + BD_S2MM));

        if (rx_only) {
            printf("  rx-only: waiting up to %d ms for a frame on S2MM (zy stream)...\n", rx_wait_ms);
            int r = dma_wait(dma, DMA_S2MM_DMASR, "S2MM", rx_wait_ms);
            dcache_inval(bds, 64); dcache_inval(rx, RX_MAX);
            uint32_t st = *(volatile uint32_t *)(bds + BD_STATUS), got = st & BD_LEN_MASK;
            if (r == 0 && (st & BD_STS_CMPLT)) {
                rx_ok++; tx_ok++;
                printf("  [%d] S2MM got %u B: ", n, got); for (int i = 0; i < 48 && i < (int)got; i++) printf("%02x", rx[i]); printf("\n");
            } else printf("  [%d] nothing received (BD status=0x%08x)\n", n, st);
            continue;
        }
        /* MM2S: the frame, SOF|EOF. */
        memset(bdm, 0, 64);
        *(volatile uint32_t *)(bdm + BD_NXTDESC) = (uint32_t)(pa + BD_MM2S);
        *(volatile uint32_t *)(bdm + BD_BUFADDR) = (uint32_t)(pa + TX_OFF);
        *(volatile uint32_t *)(bdm + BD_CONTROL) = ((uint32_t)flen & BD_LEN_MASK) | BD_CTRL_SOF | BD_CTRL_EOF;
        dcache_clean(tx, TX_MAX); dcache_clean(bdm, 64);
        w32(dma, DMA_MM2S_CURDESC, (uint32_t)(pa + BD_MM2S));
        w32(dma, DMA_MM2S_DMACR, DMA_DMACR_RS);
        w32(dma, DMA_MM2S_TAILDESC, (uint32_t)(pa + BD_MM2S));

        int t = dma_wait(dma, DMA_MM2S_DMASR, "MM2S", 500);
        dcache_inval(bdm, 64);
        printf("  MM2S SR=0x%08x BD status=0x%08x (cmplt=%u, %u bytes)\n", r32(dma, DMA_MM2S_DMASR),
               *(volatile uint32_t *)(bdm + BD_STATUS), (*(volatile uint32_t *)(bdm + BD_STATUS)) >> 31,
               *(volatile uint32_t *)(bdm + BD_STATUS) & BD_LEN_MASK);
        if (t == 0) tx_ok++;
        int r = dma_wait(dma, DMA_S2MM_DMASR, "S2MM", 500);
        dcache_inval(bds, 64); dcache_inval(rx, RX_MAX);
        uint32_t st = *(volatile uint32_t *)(bds + BD_STATUS);
        uint32_t got = st & BD_LEN_MASK;
        if (r == 0 && (st & BD_STS_CMPLT)) {
            rx_ok++;
            int same = (got >= (uint32_t)flen) && memcmp(tx, rx, flen) == 0;
            printf("  [%d] TX %d B -> S2MM got %u B%s%s\n", n, flen, got,
                   same ? " (matches TX frame" : " (DIFFERS from TX",
                   got == (uint32_t)flen ? ")" : got == (uint32_t)flen + 4 ? ", +4 = FCS kept)" : ")");
            if (n == 0) { printf("  rx[0..31]:"); for (int i = 0; i < 32 && i < (int)got; i++) printf(" %02x", rx[i]); printf("\n"); }
        } else {
            printf("  [%d] TX %s; S2MM BD status=0x%08x (no frame received back)\n", n, t == 0 ? "ok" : "FAILED", st);
        }
        if (gap_us) usleep(gap_us);
    }

    w32(xxv, XXV_TICK_REG, 1); usleep(1000);
    printf("xxv stats delta: TX total %u, RX total %u, RX good %u\n",
           r32(xxv, XXV_STAT_TX_TOTAL_PKTS) - tx0, r32(xxv, XXV_STAT_RX_TOTAL_PKTS) - rx0, r32(xxv, XXV_STAT_RX_GOOD_PKTS) - rxg0);
    printf("done: %d/%d transmitted, %d/%d looped back to S2MM\n", tx_ok, repeat, rx_ok, repeat);
    return (tx_ok == repeat) ? 0 : 1;
}

/* xxv_stats -- snapshot the XXV 10G MAC's frame counters on the KR260.
 *
 * Usage: sudo ./xxv_stats
 *
 * Writes TICK_REG, which latches the statistics counters into the STAT_*
 * registers and clears them (PG210), then prints the latched values, i.e.
 * the counts accumulated SINCE THE PREVIOUS TICK. Call it once before a run
 * (discard the output) and once after: the second output is the run's count.
 * Register offsets and the UIO lookup are the same as poc_inject.c.
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

#define ADDR_XXV    0x80030000UL
#define MAP_SIZE    0x10000UL
#define XXV_TICK_REG            0x0020
#define XXV_STAT_RX_BLOCK_LOCK  0x040C
#define XXV_STAT_TX_TOTAL_PKTS  0x0700
#define XXV_STAT_RX_TOTAL_PKTS  0x0808
#define XXV_STAT_RX_GOOD_PKTS   0x0810

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

static inline void w32(volatile uint32_t *b, uint32_t off, uint32_t v) { b[off / 4] = v; asm volatile("dsb sy" ::: "memory"); }
static inline uint32_t r32(volatile uint32_t *b, uint32_t off) { asm volatile("dsb sy" ::: "memory"); return b[off / 4]; }
static uint64_t r64(volatile uint32_t *b, uint32_t off) { return (uint64_t)r32(b, off) | ((uint64_t)r32(b, off + 4) << 32); }

int main(void)
{
    char dev[64];
    if (find_uio_for(ADDR_XXV, dev, sizeof dev) < 0) { fprintf(stderr, "no UIO device maps xxv_ethernet_0 -- app loaded?\n"); return 2; }
    int fd = open(dev, O_RDWR | O_SYNC);
    if (fd < 0) { perror(dev); return 2; }
    volatile uint32_t *xxv = mmap(NULL, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (xxv == MAP_FAILED) { perror("mmap"); return 2; }
    w32(xxv, XXV_TICK_REG, 1); usleep(1000);
    printf("xxv since previous tick: RX total %" PRIu64 " RX good %" PRIu64 " TX total %" PRIu64 " BLOCK_LOCK 0x%08x\n",
           r64(xxv, XXV_STAT_RX_TOTAL_PKTS), r64(xxv, XXV_STAT_RX_GOOD_PKTS), r64(xxv, XXV_STAT_TX_TOTAL_PKTS),
           r32(xxv, XXV_STAT_RX_BLOCK_LOCK));
    return 0;
}

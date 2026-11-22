/*
 * Stress test for the MinGW build of NVHR's allocator (with Second Wind's counters).
 * Runs NVHR's heaps without the game: several threads allocate, check, resize and free random sizes,
 * and every block's contents are checked before it's freed. Then the counters must add up again.
 *
 * Build: see build.sh. Run: wine stress_test.exe [seconds]
 */
#include <stdio.h>
#include <windows.h>

#include "main/heap_replacer.h"

#include <stdlib.h>

#define THREADS 4
#define SLOTS 1500

struct slot
{
    unsigned char *p;
    size_t size;
    unsigned seed;
};

static volatile LONG errors, ops;
static struct sheap *seen[THREADS];
static DWORD stop_at;

static unsigned rnd(unsigned *s)
{
    *s = *s * 1103515245u + 12345u;
    return *s >> 8;
}

static size_t pick_size(unsigned *s)
{
    unsigned r = rnd(s) % 1000u;
    if (r < 900u)
        return 1u + rnd(s) % 3584u;                      /* pools */
    if (r < 995u)
        return 3585u + rnd(s) % (1024u * 1024u);           /* dheap */
    if (r < 999u)
        return 1024u * 1024u + rnd(s) % (15u * 1024u * 1024u); /* dheap, big cells */
    return 17u * 1024u * 1024u + rnd(s) % (8u * 1024u * 1024u); /* straight to Windows */
}

/* write a pattern at the ends and a few points inside; check() reads the same points */
static void mark(struct slot *sl)
{
    size_t n = sl->size, step = n / 8u + 1u;
    for (size_t i = 0; i + 1 < n; i += step) /* the last byte has its own mark */
        sl->p[i] = (unsigned char)(sl->seed + i);
    sl->p[n - 1] = (unsigned char)(sl->seed ^ 0x5A);
}

static int check(struct slot *sl, size_t n)
{
    size_t step = sl->size / 8u + 1u;
    for (size_t i = 0; i + 1 < n && i + 1 < sl->size; i += step)
        if (sl->p[i] != (unsigned char)(sl->seed + i))
            return 0;
    if (n == sl->size && sl->p[n - 1] != (unsigned char)(sl->seed ^ 0x5A))
        return 0;
    return 1;
}

static DWORD WINAPI worker(LPVOID arg)
{
    unsigned s = (unsigned)(size_t)arg * 7919u + 1u;
    struct slot *slots = calloc(SLOTS, sizeof(struct slot));
    struct sheap *mine = sheap_get_thread_local();
    seen[(size_t)arg] = mine;
    while (GetTickCount() < stop_at)
    {
        /* every 64th round: the thread's scrap heap (the per-thread storage the MinGW build had to fix) */
        if ((rnd(&s) & 63u) == 0u)
        {
            struct slot st[24];
            int k = 1 + (int)(rnd(&s) % 24u);
            if (sheap_get_thread_local() != mine)
            {
                InterlockedIncrement(&errors);
                printf("scrap heap changed within one thread\n");
            }
            for (int i = 0; i < k; i++)
            {
                st[i].size = 1u + rnd(&s) % (96u * 1024u);
                st[i].seed = rnd(&s);
                st[i].p = sheap_alloc(mine, NULL, st[i].size, 4);
                if (!st[i].p)
                {
                    InterlockedIncrement(&errors);
                    printf("scrap alloc failed\n");
                    k = i;
                    break;
                }
                mark(&st[i]);
            }
            for (int i = k - 1; i >= 0; i--)
            {
                if (!check(&st[i], st[i].size))
                {
                    InterlockedIncrement(&errors);
                    printf("scrap block corrupted (%u)\n", (unsigned)st[i].size);
                }
                sheap_free(mine, NULL, st[i].p);
            }
            InterlockedIncrement(&ops);
            continue;
        }
        struct slot *sl = &slots[rnd(&s) % SLOTS];
        unsigned op = rnd(&s) % 10u;
        if (!sl->p)
        {
            sl->size = pick_size(&s);
            sl->seed = rnd(&s);
            /* v3: half the big ones come from the reserve, to test it from several threads at once */
            sl->p = NULL;
            if (sl->size > 16u * 1024u * 1024u && (op & 2u))
                sl->p = sw_res_alloc(sl->size);
            if (!sl->p)
                sl->p = (op & 1u) ? hr_calloc(1, sl->size) : hr_malloc(sl->size);
            if (!sl->p)
            {
                InterlockedIncrement(&errors);
                printf("alloc of %u failed\n", (unsigned)sl->size);
                continue;
            }
            if ((op & 1u) && !sw_res_owns(sl->p) && (sl->p[0] || sl->p[sl->size - 1]))
            {
                InterlockedIncrement(&errors);
                printf("calloc not zeroed (%u)\n", (unsigned)sl->size);
            }
            mark(sl);
        }
        else
        {
            if (!check(sl, sl->size))
            {
                InterlockedIncrement(&errors);
                printf("corrupted block of %u at %p\n", (unsigned)sl->size, sl->p);
            }
            if (op < 3u)
            {
                /* realloc keeps the old contents (v3: big blocks too; NVHR 4.3 lost those) */
                size_t nsz = pick_size(&s);
                unsigned char *np = hr_realloc(sl->p, nsz);
                if (!np)
                {
                    InterlockedIncrement(&errors);
                    printf("realloc to %u failed\n", (unsigned)nsz);
                    continue;
                }
                size_t keep = nsz < sl->size ? nsz : sl->size;
                sl->p = np;
                if (!check(sl, keep))
                {
                    InterlockedIncrement(&errors);
                    printf("realloc lost data (%u -> %u)\n", (unsigned)sl->size, (unsigned)nsz);
                }
                sl->size = nsz;
                mark(sl);
            }
            else
            {
                hr_free(sl->p);
                sl->p = NULL;
            }
        }
        InterlockedIncrement(&ops);
    }
    for (int i = 0; i < SLOTS; i++)
        if (slots[i].p)
        {
            if (!check(&slots[i], slots[i].size))
                InterlockedIncrement(&errors);
            hr_free(slots[i].p);
        }
    free(slots);
    return 0;
}

/*
 * v3: fill the whole address space (reserved, not committed, so it costs no RAM) the way an hour of
 * play does, then ask for the game's pair of 85.3 MB blocks. Windows has no gap, so both must come
 * from the reserve; a third can't fit and must fail cleanly. Then free them and do it again, to check
 * the reserve is reusable and hands out zeroed memory.
 */
#define GAME_BIG 89478640u
static void probe_test(const char *when);
static void full_test(void)
{
    static void *filler[70000];
    size_t nf = 0, step;
    unsigned char *a, *b, *c;
    int round;
    for (step = 64u * 1024u * 1024u; step >= 64u * 1024u; step /= 2u)
        while (nf < 70000 && (filler[nf] = VirtualAlloc(NULL, step, MEM_RESERVE, PAGE_NOACCESS)))
            nf++;
    printf("full_test: address space filled with %u placeholders\n", (unsigned)nf);
    probe_test("address space full");
    for (round = 0; round < 2; round++)
    {
        long hits = sw_res_hits;
        a = round ? hr_calloc(1, GAME_BIG) : hr_malloc(GAME_BIG);
        b = hr_malloc(GAME_BIG);
        if (!a || !b || !sw_res_owns(a) || !sw_res_owns(b) || sw_res_hits != hits + 2)
        {
            errors++;
            printf("full_test round %d: the 85 MB pair didn't come from the reserve (%p %p)\n", round, a, b);
        }
        if (a && round && (a[0] || a[GAME_BIG / 2u] || a[GAME_BIG - 1u]))
        {
            errors++;
            printf("full_test: calloc from the reserve not zeroed\n");
        }
        if (a && b)
        {
            memset(a, 0xA5, GAME_BIG);
            memset(b, 0x5A, GAME_BIG);
            if (a[GAME_BIG - 1u] != 0xA5 || b[0] != 0x5A || hr_mem_size(a) != GAME_BIG)
            {
                errors++;
                printf("full_test: reserve blocks overlap or misreport their size\n");
            }
        }
        c = hr_malloc(GAME_BIG);
        if (c)
        {
            errors++;
            printf("full_test: a third 85 MB block fit; the test didn't fill the address space\n");
            hr_free(c);
        }
        if (b && hr_realloc(b, GAME_BIG + 8u * 1024u * 1024u) != NULL)
        {
            errors++;
            printf("full_test: realloc beyond the reserve should fail\n");
        }
        else if (b && b[0] != 0x5A)
        {
            errors++;
            printf("full_test: failed realloc damaged the old block\n");
        }
        hr_free(a);
        hr_free(b);
        if (sw_res_used_bytes != 0)
        {
            errors++;
            printf("full_test: reserve not empty after freeing (%ld)\n", sw_res_used_bytes);
        }
    }
    while (nf)
        VirtualFree(filler[--nf], 0, MEM_RELEASE);
}

/*
 * v4: the dheap give-back runs against the workers the whole time, as hard as it can: it hands back
 * every empty block over and over while they allocate and free. A block given back while something
 * still lived in it would show up as a corrupted block (the workers check every byte) or a crash.
 */
static volatile LONG giver_rounds, giver_blocks;
static DWORD WINAPI giver(LPVOID arg)
{
    (void)arg;
    while ((LONG)(stop_at - GetTickCount()) > 0)
    {
        giver_blocks += (LONG)sw_dheap_give_back(giver_rounds & 1);
        giver_rounds++;
        Sleep(giver_rounds & 7 ? 0 : 1);
    }
    return 0;
}

/* v4: the probe must find what Windows will really give: that size fits, 64 KB more doesn't */
static void probe_test(const char *when)
{
    size_t largest = sw_probe_largest();
    void *p = largest ? VirtualAlloc(NULL, largest, MEM_RESERVE, PAGE_NOACCESS) : NULL;
    void *q = VirtualAlloc(NULL, largest + SW_PROBE_STEP, MEM_RESERVE, PAGE_NOACCESS);
    struct sw_va va;
    sw_va_scan(&va);
    printf("probe (%s): largest %.1f MB (the map says %.1f)\n", when, SW_MB(largest), SW_MB(va.largest_free));
    if ((largest && !p) || q)
    {
        errors++;
        printf("probe (%s) is wrong: %p %p\n", when, p, q);
    }
    if (p)
        VirtualFree(p, 0, MEM_RELEASE);
    if (q)
        VirtualFree(q, 0, MEM_RELEASE);
}

int main(int argc, char **argv)
{
    int secs = argc > 1 ? atoi(argv[1]) : 60;
    HANDLE th[THREADS];
    setvbuf(stdout, NULL, _IONBF, 0);
    log_file = stdout;
    nlock_init(&log_lock);
    mheap_init(&m);
    dheap_init(&d);
    sw_reserve_init();
    sw_log = fopen("secondwind-heap-test.log", "w");
    sw_start_tick = GetTickCount();

    /* NVHR 4.3 said 0 for a direct (>16 MB) block, so realloc copied nothing; v3 sizes it */
    {
        unsigned char *big = hr_malloc(20u * 1024u * 1024u);
        big[0] = 42;
        if (hr_mem_size(big) < 20u * 1024u * 1024u)
        {
            errors++;
            printf("hr_mem_size of a 20 MB block: %u\n", (unsigned)hr_mem_size(big));
        }
        big = hr_realloc(big, 24u * 1024u * 1024u);
        if (big[0] != 42)
        {
            errors++;
            printf("realloc of a 20 MB block lost its contents\n");
        }
        hr_free(big);
    }

    probe_test("at start");
    sw_give_back = !getenv("NOGIVE");
    stop_at = GetTickCount() + (DWORD)secs * 1000u;
    for (int i = 0; i < THREADS; i++)
        th[i] = CreateThread(NULL, 0, worker, (LPVOID)(size_t)i, 0, NULL);
    HANDLE gt = getenv("NOGIVE") ? NULL : CreateThread(NULL, 0, giver, NULL, 0, NULL);
    WaitForMultipleObjects(THREADS, th, TRUE, INFINITE);
    if (gt)
        WaitForSingleObject(gt, INFINITE);
    printf("give-back: %ld rounds against the workers, %ld blocks handed back\n", giver_rounds, giver_blocks);
    if (!giver_blocks)
    {
        errors++;
        printf("give-back never handed a block back during the stress run\n");
    }
    /* everything is freed now: every block is empty, so all must go back, and the dheap must still work */
    sw_dheap_give_back(1);
    for (size_t i = 0; i < DHEAP_BLOCK_COUNT; i++)
    {
        struct cnode *n;
        size_t cells = 0, biggest = 0, used = 0;
        if (!d.block_desc[i].addr)
            continue;
        for (n = clist_get_head(&d.addr_list[i]); n != &d.addr_list[i].tail; n = n->next)
        {
            struct mcell *c = get_mcell(n, addr_node);
            cells++;
            if (c->desc.size > biggest)
                biggest = c->desc.size;
        }
        for (size_t k = 0; k < DHEAP_CELLS_PER_BLOCK; k++)
            used += d.used_cells[i][k] != NULL;
        if (!used)
        {
            errors++;
            printf("give-back: block %u has nothing in use but wasn't handed back\n", (unsigned)i);
        }
        if (getenv("DIAG"))
            printf("  block %u: %u free cells, biggest %u KB, used cells %u, addr_array[0] %p\n", (unsigned)i,
                   (unsigned)cells, (unsigned)(biggest >> 10), (unsigned)used, (void *)d.addr_array[i][0]);
    }
    printf("give-back: after freeing everything, %u dheap block(s) left, holding the scrap heaps (%ld KB)\n",
           (unsigned)sw_dheap_blocks(), sw_dheap_used_bytes / 1024);
    {
        size_t before = sw_dheap_blocks();
        void *x = dheap_malloc(&d, 1u * 1024u * 1024u), *y = dheap_malloc(&d, 64u * 1024u);
        if (!x || !y || dheap_mem_size(&d, x) < 1u * 1024u * 1024u)
        {
            errors++;
            printf("give-back: the dheap didn't make a new block afterwards\n");
        }
        dheap_free(&d, x);
        dheap_free(&d, y);
        sw_dheap_give_back(0); /* first minute: only noted */
        if (sw_dheap_blocks() < before)
        {
            errors++;
            printf("give-back: a block went back the first time it was seen empty\n");
        }
        x = dheap_malloc(&d, DHEAP_BLOCK_SIZE); /* a whole block: only a new one has that much free */
        dheap_free(&d, x);
        before = sw_dheap_blocks();
        sw_dheap_give_back(0);
        if (sw_dheap_blocks() != before)
        {
            errors++;
            printf("give-back: a block went back the first time it was seen empty\n");
        }
        sw_dheap_give_back(0); /* still empty a minute later: goes back */
        if (sw_dheap_blocks() != before - 1u)
        {
            errors++;
            printf("give-back: a block empty for two checks wasn't handed back\n");
        }
    }

    for (int i = 0; i < THREADS; i++)
        for (int j = i + 1; j < THREADS; j++)
            if (seen[i] == seen[j])
            {
                errors++;
                printf("two threads got the same scrap heap: thread-local storage is broken\n");
            }
    full_test();
    sw_summary(1, 1);
    sw_stop();
    printf("ops=%ld errors=%ld reserve used %ld times\n", ops, errors, sw_res_hits);
    printf("after freeing everything: pools in use, dheap in use and big must all be 0 (see log)\n");
    return errors ? 1 : 0;
}

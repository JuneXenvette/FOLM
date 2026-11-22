/* folm-memwatch: how full is a 32-bit game's 4 GB address space? Read-only.
 *
 * Runs in the game's own Wine (same prefix, same wineserver), finds the game by its exe name and,
 * every INTERVAL seconds, walks its address space with VirtualQueryEx (the Windows view, so Wine's
 * own reservations for space the game hasn't asked for yet count as free, as they should). Prints one
 * line per sample to stdout:
 *
 *   mem used=<MB> commit=<MB> reserve=<MB> free=<MB> largest=<MB> image=<MB> mapped=<MB> private=<MB>
 *
 * used = commit + reserve (what the game can no longer get), free = the rest of its 4 GB,
 * largest = the biggest single free block (a big texture needs one piece this size), image = programs
 * and DLLs, mapped = mapped files and shared memory (graphics), private = the game's own memory.
 * Prints "gone" and exits when the game exits, "waiting" while it hasn't started.
 *
 * Build: i686-w64-mingw32-gcc -O2 -s -o folm-memwatch.exe memwatch.c
 * Usage: folm-memwatch.exe FalloutNV.exe [interval seconds]
 */
#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static DWORD find_pid(const char *exe)
{
    DWORD pid = 0;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32 pe;
    if (snap == INVALID_HANDLE_VALUE)
        return 0;
    pe.dwSize = sizeof(pe);
    if (Process32First(snap, &pe)) {
        do {
            if (_stricmp(pe.szExeFile, exe) == 0) {
                pid = pe.th32ProcessID;
                break;
            }
        } while (Process32Next(snap, &pe));
    }
    CloseHandle(snap);
    return pid;
}

#define MB(x) ((unsigned)((x) >> 20))

static int sample(HANDLE h)
{
    unsigned long long commit = 0, reserve = 0, free_ = 0, largest = 0, image = 0, mapped = 0, priv = 0;
    unsigned long long addr = 0x10000, top = 0x100000000ULL;   /* a 4GB-patched game can use all 4 GB */
    MEMORY_BASIC_INFORMATION mbi;
    while (addr < top) {
        if (VirtualQueryEx(h, (LPCVOID)(ULONG_PTR)addr, &mbi, sizeof(mbi)) != sizeof(mbi))
            break;
        unsigned long long size = mbi.RegionSize;
        if (!size)
            break;
        if (mbi.State == MEM_FREE) {
            free_ += size;
            if (size > largest)
                largest = size;
        } else {
            if (mbi.State == MEM_COMMIT)
                commit += size;
            else
                reserve += size;
            if (mbi.Type == MEM_IMAGE)
                image += size;
            else if (mbi.Type == MEM_MAPPED)
                mapped += size;
            else
                priv += size;
        }
        addr = (unsigned long long)(ULONG_PTR)mbi.BaseAddress + size;
    }
    if (addr == 0x10000)
        return 0;                                   /* couldn't read it at all */
    if (addr < top)                                 /* the rest past the last region is free */
        free_ += top - addr, largest = (top - addr > largest) ? top - addr : largest;
    printf("mem used=%u commit=%u reserve=%u free=%u largest=%u image=%u mapped=%u private=%u\n",
           MB(commit + reserve), MB(commit), MB(reserve), MB(free_), MB(largest), MB(image), MB(mapped), MB(priv));
    fflush(stdout);
    return 1;
}

int main(int argc, char **argv)
{
    const char *exe = argc > 1 ? argv[1] : "FalloutNV.exe";
    int interval = argc > 2 ? atoi(argv[2]) : 5;
    int waited = 0;
    if (interval < 1)
        interval = 1;
    for (;;) {
        DWORD pid = find_pid(exe);
        if (!pid) {
            printf("waiting\n");
            fflush(stdout);
            if ((waited += interval) > 600)         /* the game never started */
                return 1;
            Sleep(interval * 1000);
            continue;
        }
        HANDLE h = OpenProcess(PROCESS_QUERY_INFORMATION | SYNCHRONIZE, FALSE, pid);
        if (!h) {
            printf("error cannot open the game (%lu)\n", GetLastError());
            fflush(stdout);
            return 2;
        }
        for (;;) {
            if (WaitForSingleObject(h, 0) == WAIT_OBJECT_0) {
                printf("gone\n");
                fflush(stdout);
                CloseHandle(h);
                return 0;
            }
            if (!sample(h)) {
                printf("error cannot read the game's memory\n");
                fflush(stdout);
            }
            Sleep(interval * 1000);
        }
    }
}

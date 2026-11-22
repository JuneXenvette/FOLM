/* Lets NVHR's MSVC source build with MinGW (gcc) unchanged. Second Wind, GPL-2.0 like NVHR. */
#pragma once
#ifdef __GNUC__
#define __assume(x) do { if (!(x)) __builtin_unreachable(); } while (0)
#define HR_THREAD_LOCAL __thread
#else
#define HR_THREAD_LOCAL __declspec(thread)
#endif

/* The game calls these hooks as C++ methods (this in ECX). NVHR is built with MSVC's /Gr (__fastcall
   is the default for everything), and the dummy `edx` parameter takes the second register. GCC has no
   such default, so each function the game calls directly is marked; the rest only call each other. */
#define HR_GAMECALL __fastcall


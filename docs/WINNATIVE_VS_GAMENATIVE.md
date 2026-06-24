# WinNative vs GameNative — Deep Research

**Date:** 2026-06-24

## Summary

GameNative (our current base) and WinNative are **both Winlator/Pluvia derivatives**, but they've diverged significantly:

| | GameNative | WinNative |
|---|---|---|
| Stars | 8,263 | 349 |
| Package | app.gamenative / com.winlator | com.winlator.cmod / com.winnative.cmod |
| Build | Gradle Kotlin DSL | Gradle Groovy DSL |
| Kotlin files | ~752 | ~247 |
| Modular structure | Flat | feature/ + runtime/ + shared/ + rust/ |
| Native CMake | Commented out (pre-built .so) | Enabled (FetchContent for zstd/xz) |
| Rust code | None | wn-steam-tools |
| NTSync | No | Yes |
| PerformanceRecorder | No | Yes |
| Branding flavors | legacy/modern/XR | Standard/Ludashi/PUBG |

## What WinNative has that we don't
1. Rust-based Steam tools
2. NTSync (kernel Wine sync speedup)
3. PerformanceRecorder (FPS tracking)
4. Modular architecture (cleaner separation)
5. CMake FetchContent (pulls deps at build time)
6. Cross-compile scripts for audio_plugin + sysvshm
7. More actively developed (commits every 1-2 days)

## Migration path
1. Fork WinNative as new base
2. Port Aurora's 6 helpers (change import paths from com.winlator.core to com.winlator.cmod.runtime)
3. Port C++ libraries (unaffected — pure native)
4. Switch CI from Kotlin DSL to Groovy DSL
5. Add Rust toolchain to CI
6. ~2-3 days mechanical work

## Recommendation
Test current APK first. If Mali fallback works on real device, we have a product.
Switch to WinNative base when ready — its modular structure will make Aurora integration cleaner.

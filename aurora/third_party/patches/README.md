# Third-party patches

This directory documents patches needed for third-party libraries that we
haven't applied yet (because they only matter for certain build targets).
When we cross-compile for those targets, apply the patch first.

---

## basis_universal: Android API < 24 build failure

**Upstream issue:** https://github.com/BinomialLLC/basis_universal/issues/271
**Affects:** Building basisu for Android API < 24 (Android 7.0)
**Severity:** Blocker for Android targets below API 24
**Status:** Open as of v2_1_0r (2026-04-26)

### Problem

`encoder/basisu_enc.cpp` uses `ftello()`, which is only available in Android
NDK API 24+. Building for API 21+ (Android 5.0+) fails with:
```
error: use of undeclared identifier 'ftello'
```

### Why we care

Aurora targets Android 10+ (API 21+). The on-device transcoder needs to
build for API 21+ to support the widest range of devices.

### Workaround

Define `ftello` as `ftell` when targeting Android API < 24. The cleanest
way is to patch `encoder/basisu_enc.cpp` directly (since CMakeLists.txt
overrides CMAKE_CXX_FLAGS, the upstream reporter's CMake approach doesn't
work).

### Patch to apply (when we cross-compile for Android)

Add to `encoder/basisu_enc.cpp` after the includes:

```cpp
#if defined(__ANDROID__) && __ANDROID_API__ < 24
    #define ftello(f) ftell(f)
#endif
```

### Test

After applying, build for `android-21` target and verify `basisu` binary
links cleanly. There's no functional difference between `ftell` and
`ftello` for files < 2GB (which is all textures).

---

## meshoptimizer

No patches needed. v1.1 builds cleanly on Linux, macOS, Android, iOS.

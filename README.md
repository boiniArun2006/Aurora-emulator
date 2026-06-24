<div align="center">

# Aurora

### PC Gaming on Android

</div>

---

## What is Aurora?

Aurora is a PC-game emulator for Android, forked from [GameNative](https://github.com/utkarshdalal/GameNative) (which is itself a Winlator/Pluvia derivative). It runs Windows x86/x64 games via Box64, Wine, and DXVK.

### What makes Aurora different from Winlator/Mobox?

**Mali GPU support.** Other emulators don't work on Mali GPUs because the Mali Vulkan driver has bugs that crash DXVK. Aurora applies DXVK config workarounds that prevent 4 crash-causing Vulkan extensions from being requested. This is the main reason to use Aurora instead of Winlator.

### What works

- **Base emulator**: Box64 + Wine + DXVK + audio + X server + input controls
- **Mali GPU workaround**: DXVK config prevents crashes on Mali Valhall/Immortalis GPUs
- **Per-game shader cache**: Second launch has less stutter (DXVK state cache is stored per-game)
- **Auto-dependency installer**: Detects and silently installs VC++/DirectX/PhysX/.NET from `_CommonRedist/`
- **Component manager**: Download newer Box64/DXVK/Proton/VKD3D builds from a 134-entry community manifest
- **.wcp file import**: Install Proton 11 beta builds and other community packages
- **Aurora settings tab**: View engine status in per-game config

### What's in progress (infrastructure built, not yet functional)

These features have code compiled into the APK but don't produce benefits for real games yet:

- **Texture transcoder**: Converts KTX2→ASTC via Basis Universal. Real games ship .dds, not .ktx2 — needs a PC-side pre-encoding tool to be useful.
- **Mesh simplifier**: Simplifies .obj meshes via QEM. Real games ship .fbx/.nif, not .obj — needs additional format parsers.
- **File prefetcher**: Markov model infrastructure is wired but the C library that logs file accesses doesn't exist yet.
- **Cloud shader sync**: Local cache works, cloud upload/download hooks are wired but no backend is deployed.
- **Mali Vulkan layer**: The sanitizer .so compiles and deploys to imagefs, but runtime verification on a real Mali device hasn't been done yet.

### Installation

Download the latest APK from [Releases](https://github.com/boiniArun2006/Aurora-emulator/releases).

Requirements: Android 8.0+, ARM64 device, Adreno 6xx+ or Mali Valhall+ GPU.

### How to use

1. Put your game files in a folder on your phone
2. Open Aurora → Library → tap **+** to add a custom game
3. Select the folder containing your game
4. Aurora auto-detects the .exe and installs any bundled redistributables
5. Tap **Play**

### GPU compatibility

| GPU | Status |
|---|---|
| Adreno 6xx/7xx/8xx | Full support (Turnip driver) |
| Mali Valhall (G57/G77/G610) | Works with Aurora Mali workarounds |
| Mali Immortalis (G720) | Works with Aurora Mali workarounds |
| Mali Bifrost (G52/G72) | Limited — may still crash on some games |
| PowerVR | Not supported |

### Building from source

```bash
git clone https://github.com/boiniArun2006/Aurora-emulator.git
cd Aurora-emulator/android
./gradlew assembleModernDebug
```

Requires: Android Studio, JDK 17, Android SDK 35, NDK 27, CMake 3.22.

## Credits

- [GameNative](https://github.com/utkarshdalal/GameNative) — the open-source base
- [Box64](https://github.com/ptitSeb/box64) by ptitSeb — x86/x64→ARM64 translator
- [Wine](https://www.winehq.org/) — Win32 API translation
- [DXVK](https://github.com/doitsujin/dxvk) — D3D→Vulkan
- [Basis Universal](https://github.com/BinomialLLC/basis_universal) — texture transcoding
- [meshoptimizer](https://github.com/zeux/meshoptimizer) — mesh simplification

## License

MIT

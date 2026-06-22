# Aurora — Hybrid PC-Game Emulator for Android

A modular, AOT-preprocessing emulator architecture targeting mid/low-end
Android devices, including Mali GPU devices that current emulators
(Winlator, Mobox) fail on.

## Quick Start

```bash
# 1. Set up third-party dependencies (clones + builds basis_universal + meshoptimizer)
bash scripts/setup_third_party.sh

# 2. Run Phase 1 PoC (AOT Texture Transcoder)
python3 src/texture_engine/aot_texture_transcoder.py test --quality fast

# 3. Run Phase 2 PoC (AOT Mesh Simplifier)
python3 src/mesh_engine/aot_mesh_simplifier.py
```

## Prerequisites

- **Python 3.10+** (for the PoC scripts; the actual emulator runtime will be C++)
- **C++17 compiler** (g++ 11+, clang 14+, or MSVC 2022+)
- **CMake 3.15+** (basis_universal requires it for `cxx_std_17`)
- **Git** (for cloning third-party deps)
- **Pillow** Python package: `pip3 install Pillow`

### Linux (Debian/Ubuntu)

```bash
sudo apt-get install -y build-essential cmake python3 python3-pip python3-venv
pip3 install Pillow
```

### macOS

```bash
xcode-select --install
brew install cmake python@3
pip3 install Pillow
```

### Windows

Install [Visual Studio Build Tools 2022](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022) (with C++ workload),
[CMake](https://cmake.org/download/), [Python 3.10+](https://www.python.org/downloads/), and Git. Then:

```powershell
pip install Pillow
```

## Status

| Phase | Status | Description |
|---|---|---|
| 0 | Done | Project setup, git repo, folder structure |
| 1 | Done | AOT Texture Transcoder (Basis Universal, BCn→KTX2/UASTC→ASTC) |
| 1.5 | Done | GitHub Actions CI (auto-rebuilds deps + runs PoC tests on every push) |
| 2 | Done | Mesh Simplification Engine (Garland-QEM via meshoptimizer) |
| 3 | Next | Loader Engine with predictive prefetching |
| 4 | Pending | Shader cache infrastructure design |
| 5 | Pending | Orchestration layer tying engines together |
| 6 | Pending | Mali Vulkan sanitizer shim |
| 7 | Pending | Integration with Box64 + Wine + DXVK |
| 8 | Pending | Android APK wrapper |

See `PROJECT_STATE.md` for full status, `worklog.md` for chronological log.

## Architecture

```
PC game (x86 + D3D + BCn textures)
        ↓  [AOT preprocessing on install]
    Aurora Preprocessor:
      - Texture Engine: BCn → KTX2/UASTC (supercompressed)
      - Mesh Engine:    Simplify meshes via QEM at multiple LODs
      - Shader Engine:  Pre-compile D3D shader bytecode → SPIR-V
      - Loader Engine:  Build predictive prefetch profile
        ↓
    Mobile-optimized game bundle
        ↓  [Runtime on Android]
    Aurora Runtime:
      - Box64 (fork):          x86-64 → ARM64 translation (with AOT mode)
      - Wine:                   Win32 API translation
      - DXVK (fork):            D3D → Vulkan (with Mali sanitizer shim)
      - Turnip / PanVK:         Vulkan driver for Adreno / Mali
      - Basis Transcoder:       KTX2/UASTC → ASTC (library call, microseconds)
      - FSR 1/2/3:              Frame upscaling (free fps boost)
```

## Repository Layout

```
aurora/
├── PROJECT_STATE.md          ← Handoff doc — read first in any new session
├── README.md                  ← You are here
├── LICENSE                    ← MIT
├── .github/workflows/ci.yml   ← GitHub Actions: rebuilds deps + runs PoCs on push
├── src/
│   ├── texture_engine/
│   │   └── aot_texture_transcoder.py   ← Phase 1 PoC (working)
│   └── mesh_engine/
│       └── aot_mesh_simplifier.py      ← Phase 2 PoC (working)
├── third_party/
│   ├── MANIFEST.txt           ← Pinned versions of all third-party deps
│   ├── patches/README.md      ← Documented patches to apply (e.g. for Android)
│   ├── basis_universal/       ← Binomial LLC, Apache-2.0, pinned to v2_1_0r
│   └── meshoptimizer/         ← Arseny Kapoulkine, MIT, pinned to v1.1
├── tests/
│   ├── texture_engine_input/  ← Generated synthetic test textures
│   ├── texture_engine_output/ ← KTX2/ASTC outputs + pipeline_results.json
│   └── mesh_engine_output/    ← OBJ LODs + mesh_pipeline_results.json
├── scripts/
│   └── setup_third_party.sh   ← Rebuilds all deps from MANIFEST.txt
└── worklog.md                 ← Chronological log of every session
```

## Phase 1: AOT Texture Transcoder

### What it does

PC games ship textures in BCn format (BC1/BC3/BC5/BC7) which mobile GPUs
can't read directly. The AOT pipeline:

1. **On install (slow, ~3 sec per 1024×1024 texture):** Encodes source
   texture to KTX2 container with UASTC codec, supercompressed with Zstd.
2. **At load time (fast, microseconds per block):** Transcodes KTX2/UASTC
   to ASTC 4x4 (mobile GPU native format).

### Validated results

- **9.70x compression** vs raw RGBA (9.4 MB raw → 970 KB KTX2/UASTC)
- AOT encode: ~3 sec per 1024×1024 texture (one-time cost)
- Transcode (PoC mode): ~1 sec per texture (production: microseconds/block)

### Algorithm references

- **Basis Universal v2.10** by Binomial LLC — the reference encoder/transcoder
- **ASTC** by Nystad et al., SIGGRAPH 2012 — the mobile GPU native format

## Phase 2: AOT Mesh Simplifier

### What it does

PC game meshes ship at full LOD0 detail (often 100k+ triangles per asset).
The AOT pipeline simplifies them at multiple LOD levels so low-end devices
can pick the right detail level at runtime based on screen-space size.

1. **On install (~6ms per LOD level for a 16k-tri mesh):** Simplifies the
   mesh to 50% / 25% / 10% of original triangle count using QEM.
2. **At load time:** Picks appropriate LOD based on screen distance.
3. **Vertex fetch optimization:** Reorders vertices for GPU cache efficiency
   and compacts the vertex buffer (removes unused vertices).

### Validated results

| LOD | Target | Actual triangles | Error | Time |
|---|---|---|---|---|
| LOD0 | 100% | 16,384 | — | — |
| LOD1 | 50% | 8,192 | 0.07% | 6.5ms |
| LOD2 | 25% | 4,096 | 0.11% | 5.7ms |
| LOD3 | 10% | 1,639 | 0.34% | 5.3ms |

### Algorithm references

- **Garland & Heckbert 1997**, "Surface Simplification Using Quadric Error
  Metrics" — the classical QEM algorithm.
- **meshoptimizer v1.1** by Arseny Kapoulkine — extends QEM with attribute-
  aware error metric, lockable vertices, topology preservation. Used by AAA
  games (Horizon Zero Dawn PC port, Call of Duty, etc.)

## CI

GitHub Actions runs on every push to `main` and on every PR:

1. Spins up a clean Ubuntu 22.04 runner
2. Installs build deps (cmake, python3, Pillow)
3. Caches `basis_universal` and `meshoptimizer` source + build
4. Runs `scripts/setup_third_party.sh`
5. Verifies `basisu` binary + `libmeshoptimizer.so`
6. Runs Phase 1 PoC + Phase 2 PoC
7. Validates outputs (3 KTX2 + 3 ASTC files, 4+ LOD levels)
8. Uploads `pipeline_results.json` as artifact (14-day retention)

Badge: https://github.com/boiniArun2006/Aurora-emulator-smpl/actions/workflows/ci.yml/badge.svg

## License

- Aurora code: **MIT** (see `LICENSE`)
- Third-party (each keeps its own license):
  - Basis Universal v2_1_0r: Apache-2.0 (Binomial LLC)
  - meshoptimizer v1.1: MIT (Arseny Kapoulkine)
  - Future: Box64 (MIT), Wine (LGPL-2.1), DXVK (zlib/libpng), FEX-Emu (MIT)

## Contributing

This is an early-stage research project. If you want to contribute, please:

1. Read `PROJECT_STATE.md` first to understand current status
2. Read `worklog.md` to see what's been done
3. Open an issue to discuss what you want to work on
4. All PRs must pass CI (GitHub Actions runs automatically)

## Acknowledgments

- **Binomial LLC** for Basis Universal — the gold standard for portable
  GPU texture compression
- **Arseny Kapoulkine** for meshoptimizer — production-grade mesh
  processing used by AAA games
- **ptitSeb** for Box86/Box64 — the x86→ARM translators that make Android
  PC emulation possible at all
- **doitsujin** for DXVK — the D3D→Vulkan translation layer
- **Collabora** for Panfrost/Panthor — the open-source Mali drivers

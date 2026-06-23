# Aurora — Auto-Installer Framework Research

**Compiled:** 2026-06-22
**Sources:**
- GameNative source code (`app/src/main/java/app/gamenative/utils/preInstallSteps/`)
- Web research: Steam/GOG exe detection, Wine winetricks, Proton protontricks
- Winlator `installable_components/` pattern

This documents how Aurora will auto-detect the main game .exe and auto-install
dependencies (VC++ redist, DirectX, PhysX, .NET, OpenAL, XNA Framework).

---

## 1. The Problem

When a user downloads a game (especially non-Steam: GOG, Epic, direct download),
they get a folder with multiple .exe files:

```
Skyrim/
├── SkyrimLauncher.exe          <- this is the launcher, not the game
├── TESV.exe                    <- this is the actual game
├── SkyrimVR.exe                <- VR variant
├── _CommonRedist/
│   ├── DirectX/
│   │   └── DXSETUP.exe         <- DirectX installer
│   ├── vcredist/
│   │   └── 2013/vcredist_x64.exe
│   └── PhysX/
│       └── PhysX_setup.exe
├── SkyrimSE.exe                <- Special Edition (don't confuse with original)
└── data/...
```

A user looking at this has NO IDEA which exe to launch. Worse: even if they
pick the right one, the game may need DirectX 9, VC++ 2013, PhysX — none of
which are installed in Wine by default.

**The framework needs to:**
1. Auto-detect the main game .exe (not the launcher, not the installer)
2. Auto-detect required redistributables in `_CommonRedist/`
3. Install them silently into the Wine prefix before first launch
4. Skip if already installed (idempotent — marker files)
5. Handle edge cases: installers (.msi), GOG install scripts, Epic prerequisites

---

## 2. How GameNative solves it (the gold standard)

GameNative has a `PreInstallStep` interface with these implementations:

| Step | What it installs | Detection method |
|---|---|---|
| `VcRedistStep` | Visual C++ Redistributables (2005-2019, x86+x64) | Scans `_CommonRedist/vcredist/` and `_CommonRedist/MSVC*/` |
| `PhysXStep` | NVIDIA PhysX | Scans `_CommonRedist/PhysX/` for .msi or .exe |
| `OpenALStep` | OpenAL audio library | Scans for `oalinst.exe` |
| `XnaFrameworkStep` | Microsoft XNA Framework | Scans for `xnafx40_redist.msi` |
| `UbisoftConnectStep` | Ubisoft Connect launcher | Scans for `UbisoftConnectInstaller.exe` |
| `GogScriptInterpreterStep` | GOG install scripts | Detects GOG game via `goggame-*.info` files |

### Architecture (from GameNative)

```kotlin
interface PreInstallStep {
    val marker: Marker  // e.g. VCREDIST_INSTALLED - idempotency check

    fun appliesTo(container, gameSource, gameDirPath): Boolean
    // Returns true if this step should run (typically: marker not yet present)

    fun buildCommand(container, appId, gameSource, gameDir, gameDirPath): String?
    // Returns a shell command string like:
    //   "A:\\_CommonRedist\\vcredist\\2013\\vcredist_x64.exe /install /passive /norestart"
    // Multiple installers are joined with " & " (Windows command separator)
}
```

### How VcRedistStep works (concrete example)

GameNative has a hardcoded map of **38 known VC++ installer paths** (Windows paths):

```kotlin
val vcRedistMap: Map<String, String> = mapOf(
    "A:\\_CommonRedist\\vcredist\\2005\\vcredist_x86.exe" to "/Q",
    "A:\\_CommonRedist\\vcredist\\2013\\vcredist_x64.exe" to "/install /passive /norestart",
    "A:\\_CommonRedist\\MSVC2017\\VC_redist.x86.exe" to "/install /passive /norestart",
    // ... 35 more entries
)
```

At install time:
1. For each `(winPath, args)` in the map, translate `A:\_CommonRedist\...` → host path `_CommonRedist/...`
2. If the host file exists, queue `(winPath, args)` for execution
3. Join all queued installers with ` & ` (Windows shell AND)
4. Wine executes the command, installing all detected redistributables
5. Write marker file `VCREDIST_INSTALLED` so it doesn't run again

### Marker-based idempotency

```kotlin
object VcRedistStep : PreInstallStep {
    override val marker: Marker = Marker.VCREDIST_INSTALLED

    override fun appliesTo(container, gameSource, gameDirPath): Boolean {
        return !MarkerUtils.hasMarker(gameDirPath, Marker.VCREDIST_INSTALLED)
    }
}
```

After successful install, `MarkerUtils.addMarker(gameDirPath, Marker.VCREDIST_INSTALLED)`
writes an empty file `<gameDir>/.aurora_markers/VCREDIST_INSTALLED`. Next time
the step runs, `appliesTo()` returns false → skipped.

---

## 3. Main game .exe detection (the harder problem)

GameNative assumes the user picks the exe (via Steam/GOG/Epic integration that
knows the right exe). For Aurora's case (user dragged in a zip), we need to
auto-detect. Heuristics, in priority order:

### Heuristic 1: Manifest files (highest confidence)
- `goggame-*.info` (GOG) — contains `playTask` with the exe path
- `steam_appid.txt` (Steam) — look up exe via Steam API
- `*_installscript.vdf` (Steam install script) — lists `Run Process` exe

### Heuristic 2: Known launcher exclusion
Filter out common non-game exes by name:
- `setup.exe`, `install.exe`, `uninstall.exe`, `unins000.exe` (installers)
- `launcher.exe`, `config.exe`, `settings.exe` (config tools)
- `dxsetup.exe`, `vcredist_*.exe`, `physx_setup.exe` (redistributables)
- `*_crash_reporter.exe`, `error_reporter.exe` (debug tools)

### Heuristic 3: File size + PE header analysis
- The main game exe is almost always the largest non-installer .exe in the root
- Parse the PE header (DOS header `MZ` + PE signature `PE\0\0`) to confirm it's a valid 32/64-bit Windows exe
- Parse the PE optional header to get the **subsystem** field — `IMAGE_SUBSYSTEM_WINDOWS_GUI` (2) = game; `IMAGE_SUBSYSTEM_WINDOWS_CUI` (3) = console app (probably not the game)
- Parse the PE version resource (`VS_FIXEDFILEINFO`) — game exes have `FileDescription` like "The Witcher 3", `ProductName` like "The Witcher 3: Wild Hunt"

### Heuristic 4: References in other files
- If `goggame-*.info`, `*.vdf`, or `*.ini` reference an .exe by name, that's likely the game

### Heuristic 5: Last resort — ask the user
If multiple candidates remain, show a list with file sizes and PE version info;
let the user pick. This is what Lutris does.

---

## 4. Aurora's auto-installer framework design

```
src/auto_installer/
├── exe_detector.py           # Main .exe detection (heuristics 1-5)
├── pre_install_step.py       # Base class (mirrors GameNative's PreInstallStep)
├── marker_utils.py           # Idempotency markers
├── pe_parser.py              # PE header parser (subsystem, version info)
├── manifest_parser.py        # GOG/Steam manifest parser
├── steps/
│   ├── vcredist_step.py      # VC++ redists (port GameNative's 38-entry map)
│   ├── directx_step.py       # DirectX June 2010 redist
│   ├── physx_step.py         # NVIDIA PhysX
│   ├── dotnet_step.py        # .NET Framework 4.x
│   ├── openal_step.py        # OpenAL
│   ├── xna_step.py           # XNA Framework
│   └── gog_script_step.py    # GOG install scripts
└── auto_installer_poc.py     # PoC test
```

### Integration with orchestrator

The auto-installer runs as a preprocessing step BEFORE the game launches:
1. User drags in a game folder / zip
2. `exe_detector.py` finds the main .exe (with user confirmation if ambiguous)
3. Each `PreInstallStep.appliesTo()` is checked — returns true if not yet installed
4. Applicable steps' `buildCommand()` returns Wine commands
5. Wine runs each command (silent install flags)
6. Marker files written for each successful step
7. Aurora's Phase 1-4 AOT preprocessing runs on the game's textures/meshes
8. Game launches via Box64 + Wine

---

## 5. What to port from GameNative

GameNative's `preInstallSteps/` is **MIT-licensed** — we can port directly:

| GameNative file | Aurora port | Notes |
|---|---|---|
| `PreInstallStep.kt` | `pre_install_step.py` | Translate Kotlin interface → Python ABC |
| `VcRedistStep.kt` | `steps/vcredist_step.py` | Port the 38-entry vcRedistMap verbatim |
| `PhysXStep.kt` | `steps/physx_step.py` | Port MSI + exe detection |
| `OpenALStep.kt` | `steps/openal_step.py` | |
| `XnaFrameworkStep.kt` | `steps/xna_step.py` | |
| `UbisoftConnectStep.kt` | `steps/ubisoft_step.py` | |
| `GogScriptInterpreterStep.kt` | `steps/gog_script_step.py` | |
| `MarkerUtils.kt` | `marker_utils.py` | Idempotency markers |

Aurora-specific additions (not in GameNative):
- `DirectXStep` — DirectX 9/10/11 redist (DXSETUP.exe)
- `DotNetStep` — .NET Framework 4.5-4.8 (dotnetfx.exe)
- Better `exe_detector.py` (GameNative relies on Steam/GOG integration; we need pure heuristic detection since users drag in zips)

---

## 6. Concrete implementation plan

### Phase A: Port from GameNative (1-2 days)
1. Port `PreInstallStep` interface → Python ABC
2. Port `MarkerUtils` (simple file-based markers)
3. Port `VcRedistStep` (the 38-entry map is the value)
4. Port `PhysXStep`, `OpenALStep`, `XnaFrameworkStep`

### Phase B: Aurora-specific steps (1-2 days)
5. Add `DirectXStep` — scan for `DXSETUP.exe`, `_CommonRedist/DirectX/`
6. Add `DotNetStep` — scan for `dotnetfx*.exe`, NDP installers
7. Add `GogScriptStep` — handle GOG's `goggame-*.info` install tasks

### Phase C: Main .exe detector (2-3 days)
8. PE header parser (`pe_parser.py`) — DOS header, PE signature, subsystem, version resource
9. Manifest parser (`manifest_parser.py`) — GOG `.info`, Steam `.vdf`
10. Heuristic chain in `exe_detector.py` — manifest → exclusion → size → PE info → ask user
11. PoC test with real game folder structures

### Phase D: Integration (1 day)
12. Wire auto-installer into the Phase 5 orchestrator as a new component
13. Add `AutoInstallerComponent` that runs all applicable `PreInstallStep`s before launch
14. Update CI to test the auto-installer

**Total estimate: ~5-7 days of work for a robust auto-installer.**

---

## 7. References

- GameNative `PreInstallStep.kt` — `reference_repos/GameNative/app/src/main/java/app/gamenative/utils/preInstallSteps/`
- GameNative `VcRedistStep.kt` — 38-entry VC++ installer map
- WineHQ — winetricks and protontricks for installing redistributables
- Microsoft PE Format spec — https://learn.microsoft.com/en-us/windows/win32/debug/pe-format
- GOG Manifest format — `goggame-<id>.info` JSON files
- Steam Install Script format — `.vdf` KeyValues files

# Aurora — Audio Architecture Research

**Compiled:** 2026-06-22
**Sources:**
- GameNative source code (`ALSAClient.java`, `PulseAudioComponent.java`)
- Winlator `android_alsa/` (C source for ALSA Android bridge)
- Web research: Android AAudio vs OpenSL ES, Wine audio drivers

This documents how Aurora will handle audio. The good news: GameNative already
solved this — we just port their approach.

---

## 1. The Problem

Wine games expect to talk to one of:
- **WinMM** (old Windows multimedia API — oldest games)
- **DirectSound** (DirectX audio — most 2000s games)
- **WASAPI** (Windows Audio Session API — modern games, Vista+)

Wine translates these to a backend: ALSA, PulseAudio, OSS, or PipeWire.

On Android, the situation is messy:
- **Android has NO ALSA, PulseAudio, or PipeWire** in userspace
- Android has **AAudio** (modern, low-latency, Android 8+) and **OpenSL ES** (older)
- Wine can't talk to AAudio directly

**The bridge:** Wine → ALSA → ALSA server (in userspace) → Android AAudio
                        OR
                     Wine → PulseAudio → PulseAudio server (in userspace) → Android AAudio

---

## 2. How GameNative solves it (proven, working)

GameNative ships TWO audio paths, both as `EnvironmentComponent`s:

### Path 1: ALSA + ALSAClient (for old games, simpler)

```
Wine game (WinMM/DirectSound)
    |
    v (Wine's ALSA driver)
ALSA server (in-userspace, GameNative's android_alsa/ C code)
    |
    v (Unix domain socket)
ALSAClient (Java, in app process)
    |
    v
Android AudioTrack (Android's audio output API)
    |
    v
Speaker
```

**Key files:**
- `winlator/android_alsa/module_pcm_android_aserver.c` — ALSA PCM plugin
- `winlator/android_alsa/alsa.conf` — ALSA config that loads the plugin
- `GameNative/app/src/main/java/com/winlator/alsaserver/ALSAClient.java` — Java audio bridge

**ALSAClient features:**
- Configurable latency (`latencyMillis`, default 40ms; GameNative's Container default is 144ms for stability)
- Format support: U8, S16LE, S16BE, FLOATLE, FLOATBE
- Performance mode (0=normal, 1=low-latency, 2=high-latency)
- Volume control (0.0-1.0)
- SysV shared memory for zero-copy audio buffer (uses `SysVSharedMemoryComponent`)

### Path 2: PulseAudio (for modern games, more compatible)

```
Wine game (WinMM/DirectSound/WASAPI)
    |
    v (Wine's PulseAudio driver)
PulseAudio server (in-userspace, GameNative's libpulseaudio.so)
    |
    v (PulseAudio's AAudio sink module)
Android AAudio
    |
    v
Speaker
```

**Key files:**
- `GameNative/app/src/main/java/com/winlator/xenvironment/components/PulseAudioComponent.java`
- Sink name: `"AAudioSink"` (PulseAudio's AAudio output module)
- Suspend strategy: timer-based (120s timeout → unload module to save CPU; quick resume → no reload)

**PulseAudioComponent features:**
- Two suspend modes:
  - `suspend-via-thread` (default): SIGSTOP/SIGCONT the pulseaudio process
  - `suspend-via-pactl` (power-saving): `pactl unload module` after 120s
- Low-latency mode toggle
- Volume control via `pactl set-sink-volume`
- Performance mode (matches ALSAClient's 0/1/2)
- Auto-kills orphaned pulseaudio processes on start

---

## 3. When to use which path

| Game type | Recommended path | Why |
|---|---|---|
| Old games (pre-2005, DirectSound 7) | ALSA | Simpler, less overhead, ALSAClient handles old formats well |
| Modern games (WASAPI, XAudio2) | PulseAudio | PulseAudio emulates WASAPI better |
| Games with audio crackling on ALSA | PulseAudio | PulseAudio's resampler can fix sample-rate mismatches |
| Games that need audio capture (mic) | PulseAudio | PulseAudio has full duplex; ALSA path is output-only |
| Default (unknown game) | PulseAudio | More compatible, handles edge cases |

**GameNative's default:** `DEFAULT_AUDIO_DRIVER = "pulseaudio"` (Container.java)

---

## 4. Audio latency and crackling (the real-world pain)

This is what users complain about. Causes and fixes:

### Cause 1: Buffer underruns (most common)
**Symptom:** Crackling/popping on loud sounds or transitions
**Cause:** Audio buffer too small → Wine writes audio slower than Android plays it
**Fix:** Increase `latencyMillis` (default 40ms → 144ms for stability; old games like Unreal Gold need 90ms+)

### Cause 2: Sample rate mismatch
**Symptom:** Constant low-level hiss + occasional pops
**Cause:** Game outputs 44100 Hz, Android device native is 48000 Hz → resampling artifacts
**Fix:** PulseAudio's resampler handles this better than ALSAClient

### Cause 3: Android audio focus loss
**Symptom:** Audio cuts out when notification arrives, doesn't come back
**Cause:** Android pauses AudioTrack when another app takes audio focus
**Fix:** GameNative's `ALSAClient` handles this via `AudioManager.OnAudioFocusChangeListener` — re-requests focus

### Cause 4: CPU spike during game frame
**Symptom:** Audio stutters when game does heavy work (loading, complex scene)
**Cause:** Audio thread starved because game thread hogs CPU
**Fix:** PulseAudio runs in its own process (better isolation); ALSAClient runs in app process (worse isolation)

### Cause 5: Box64 JIT compile pause
**Symptom:** Audio stutters for first few minutes, then smooth
**Cause:** Box64 is compiling hot paths; CPU is busy
**Fix:** Aurora's Phase 4 shader cache + Phase 3 prefetcher reduce this; eventually go away

---

## 5. Aurora's audio architecture (ported from GameNative)

```
src/audio_engine/
├── audio_component.py           # EnvironmentComponent wrapper (Phase 7)
├── alsa_client.py               # Port of GameNative's ALSAClient.java
├── pulseaudio_component.py      # Port of GameNative's PulseAudioComponent.java
├── audio_options.py             # Latency, performance mode, volume config
└── audio_poc.py                 # PoC test
```

### What to port from GameNative (MIT-licensed, direct port OK):

| GameNative file | Aurora port | Notes |
|---|---|---|
| `ALSAClient.java` | `alsa_client.py` | Port AudioTrack usage; use Python's `pyaudio` or call Android AudioTrack via JNI in production |
| `PulseAudioComponent.java` | `pulseaudio_component.py` | Port suspend/resume logic |
| `ALSAClientConnectionHandler.java` | (in alsa_client.py) | Unix socket handler |
| `android_alsa/module_pcm_android_aserver.c` | (bundle as-is) | C code, no port needed — just compile |
| `android_alsa/alsa.conf` | (bundle as-is) | ALSA config |
| `android_alsa/CMakeLists.txt` | (bundle as-is) | Build config |

### Aurora-specific audio additions:

1. **Auto-driver selection** — pick ALSA vs PulseAudio based on game's audio API:
   - Detect DirectSound/WASAPI in PE imports → use PulseAudio
   - Detect WinMM only → use ALSA (simpler, less overhead)
   - Unknown → default to PulseAudio

2. **Auto-latency tuning** — start at 144ms, automatically reduce if no underruns for 5 minutes:
   - Reduces audio lag in rhythm games
   - Falls back to 144ms if underruns detected

3. **Audio prefetcher integration** (with Phase 3) — during level transitions, preload next level's audio chunks into the PulseAudio buffer to avoid first-frame silence

---

## 6. Why we should NOT reinvent audio

GameNative's audio stack is **battle-tested** by thousands of users:
- ALSAClient handles 5 audio formats, 3 performance modes, audio focus, SysV shared memory
- PulseAudioComponent handles suspend/resume, process management, power saving
- The C ALSA plugin (`module_pcm_android_aserver.c`) is non-trivial — would take weeks to reimplement
- GameNative's defaults (144ms latency, PulseAudio default) are tuned by community

**Aurora's audio work = port GameNative's code, add auto-driver-selection + auto-latency-tuning.**
NOT "build from scratch." That would be a 3-month project for no gain.

---

## 7. Concrete implementation plan

### Phase A: Port ALSA path (2-3 days)
1. Port `ALSAClient.java` → Python (PoC) / JNI (production)
2. Bundle `android_alsa/` C code as-is (compile via NDK in Phase 8)
3. Test with a DirectSound game (e.g. old Half-Life)

### Phase B: Port PulseAudio path (2-3 days)
4. Port `PulseAudioComponent.java` → Python (PoC) / Kotlin (production)
5. Bundle `libpulseaudio.so` + AAudio sink module (from GameNative's pre-built)
6. Test with a WASAPI game (e.g. Witcher 3)

### Phase C: Aurora-specific features (2-3 days)
7. Auto-driver-selection (detect PE imports → pick driver)
8. Auto-latency-tuning (start 144ms, reduce if stable)
9. Audio prefetcher integration with Phase 3

### Phase D: Integration (1 day)
10. Wire into Phase 5 orchestrator as `AudioComponent`
11. Already stubbed in `src/orchestrator/components/audio.py` — replace stub with real port
12. Update CI

**Total estimate: ~7-10 days for a robust audio stack.**

---

## 8. References

- GameNative `ALSAClient.java` — `reference_repos/GameNative/app/src/main/java/com/winlator/alsaserver/`
- GameNative `PulseAudioComponent.java` — `reference_repos/GameNative/app/src/main/java/com/winlator/xenvironment/components/`
- Winlator `android_alsa/` — `reference_repos/winlator/android_alsa/` (C source)
- Android AAudio docs — https://developer.android.com/ndk/guides/audio/aaudio/aaudio
- Wine audio drivers — https://wiki.winehq.org/Sound
- Android low-latency audio — https://developer.android.com/games/sdk/low-latency-audio

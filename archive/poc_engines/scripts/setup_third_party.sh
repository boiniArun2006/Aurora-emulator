#!/usr/bin/env bash
# Setup third-party dependencies for Aurora
# Reads third_party/MANIFEST.txt and clones/builds each dependency.
set -euo pipefail

AURORA_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
THIRD_PARTY_DIR="$AURORA_ROOT/third_party"
MANIFEST="$THIRD_PARTY_DIR/MANIFEST.txt"

# Locate cmake: try PATH first, then common pip-install locations
CMAKE_BIN="${CMAKE:-}"
if [[ -z "$CMAKE_BIN" ]]; then
    if command -v cmake &>/dev/null; then
        CMAKE_BIN="$(command -v cmake)"
    elif [[ -x "$HOME/.venv/bin/cmake" ]]; then
        CMAKE_BIN="$HOME/.venv/bin/cmake"
    elif [[ -x "$HOME/.local/bin/cmake" ]]; then
        CMAKE_BIN="$HOME/.local/bin/cmake"
    else
        echo "ERROR: cmake not found. Install via 'apt-get install cmake' or 'pip install cmake'."
        exit 1
    fi
fi

# Validate cmake version. basis_universal requires CMake 3.15+ (uses
# target_compile_features with cxx_std_17). meshoptimizer needs 3.0+.
# We check against 3.15 to be safe for both.
CMAKE_VERSION="$("$CMAKE_BIN" --version | head -1 | awk '{print $3}')"
CMAKE_MIN="3.15"
echo "Using cmake: $CMAKE_BIN (version $CMAKE_VERSION, minimum required: $CMAKE_MIN)"

# Compare versions using sort -V (version sort)
if ! printf '%s\n%s\n' "$CMAKE_MIN" "$CMAKE_VERSION" | sort -V -C; then
    echo "ERROR: cmake version $CMAKE_VERSION is older than required $CMAKE_MIN."
    echo "  basis_universal uses cxx_std_17 which requires CMake 3.15+."
    echo "  Upgrade with: apt-get install cmake  OR  pip install --upgrade cmake"
    exit 1
fi

export PATH="$(dirname "$CMAKE_BIN"):$PATH"

if [[ ! -f "$MANIFEST" ]]; then
    echo "ERROR: Manifest not found at $MANIFEST"
    exit 1
fi

echo "=== Aurora third-party setup ==="
echo "Manifest: $MANIFEST"
echo

# Skip comment lines and empty lines
while IFS='|' read -r name repo ref license purpose; do
    # Trim whitespace
    name=$(echo "$name" | xargs)
    repo=$(echo "$repo" | xargs)
    ref=$(echo "$ref" | xargs)
    license=$(echo "$license" | xargs)
    purpose=$(echo "$purpose" | xargs)

    [[ -z "$name" || "$name" == \#* ]] && continue

    dest="$THIRD_PARTY_DIR/$name"
    echo "[$name] $purpose"
    echo "  repo: $repo"
    echo "  ref:  $ref"
    echo "  license: $license"

    if [[ -d "$dest/.git" ]]; then
        echo "  -> already cloned at $dest, skipping clone"
    else
        echo "  -> cloning ref '$ref' to $dest ..."
        # --depth 1: shallow clone (only latest commit, faster)
        # --single-branch: only fetch the named branch (avoids fetching all
        #   remote refs, ~halves clone time)
        # --branch: works for both tags (e.g. 'v2_1_0r') and branches
        git clone --depth 1 --single-branch --branch "$ref" "$repo" "$dest"
    fi
    echo
done < "$MANIFEST"

# Build basis_universal
if [[ -d "$THIRD_PARTY_DIR/basis_universal" ]]; then
    BASISU_BIN="$THIRD_PARTY_DIR/basis_universal/bin/basisu"
    if [[ -x "$BASISU_BIN" ]]; then
        echo "[basis_universal] Binary already exists at $BASISU_BIN, skipping build"
    else
        echo "[basis_universal] Building..."
        cd "$THIRD_PARTY_DIR/basis_universal"
        if [[ ! -d build ]]; then
            mkdir -p build
        fi
        cd build
        cmake .. -DCMAKE_BUILD_TYPE=Release
        make -j"$(nproc)"
        echo "  -> basisu binary at: $BASISU_BIN"
        cd "$AURORA_ROOT"
    fi
fi

# Build meshoptimizer (shared library for Python ctypes bindings).
# Library extension depends on platform - the Python wrapper (aot_mesh_simplifier.py)
# detects this at runtime, but here we just check for any of the possible names.
if [[ -d "$THIRD_PARTY_DIR/meshoptimizer" ]]; then
    # Detect expected library name for this platform
    case "$(uname -s)" in
        Linux*)  MESHOPT_LIBNAME="libmeshoptimizer.so" ;;
        Darwin*) MESHOPT_LIBNAME="libmeshoptimizer.dylib" ;;
        MINGW*|MSYS*|CYGWIN*) MESHOPT_LIBNAME="meshoptimizer.dll" ;;
        *)       MESHOPT_LIBNAME="libmeshoptimizer.so" ;;  # fallback
    esac
    MESHOPT_LIB="$THIRD_PARTY_DIR/meshoptimizer/build/$MESHOPT_LIBNAME"

    if [[ -f "$MESHOPT_LIB" ]]; then
        echo "[meshoptimizer] Shared library already exists at $MESHOPT_LIB, skipping build"
    else
        echo "[meshoptimizer] Building shared library (target: $MESHOPT_LIBNAME)..."
        cd "$THIRD_PARTY_DIR/meshoptimizer"
        if [[ ! -d build ]]; then
            mkdir -p build
        fi
        cd build
        cmake .. -DCMAKE_BUILD_TYPE=Release -DMESHOPT_BUILD_SHARED_LIBS=ON
        make -j"$(nproc)"
        echo "  -> $MESHOPT_LIBNAME at: $MESHOPT_LIB"
        cd "$AURORA_ROOT"
    fi
fi

echo
echo "=== Setup complete ==="

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
echo "Using cmake: $CMAKE_BIN ($("$CMAKE_BIN" --version | head -1))"
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
        # Use --branch for tags/branches (more efficient than fetch+checkout).
        # Works for tags like 'v2_1_0r' and branches like 'master'.
        git clone --depth 1 --branch "$ref" "$repo" "$dest"
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

# Build meshoptimizer (shared library for Python ctypes bindings)
if [[ -d "$THIRD_PARTY_DIR/meshoptimizer" ]]; then
    MESHOPT_SO="$THIRD_PARTY_DIR/meshoptimizer/build/libmeshoptimizer.so"
    if [[ -f "$MESHOPT_SO" ]]; then
        echo "[meshoptimizer] Shared library already exists at $MESHOPT_SO, skipping build"
    else
        echo "[meshoptimizer] Building shared library..."
        cd "$THIRD_PARTY_DIR/meshoptimizer"
        if [[ ! -d build ]]; then
            mkdir -p build
        fi
        cd build
        cmake .. -DCMAKE_BUILD_TYPE=Release -DMESHOPT_BUILD_SHARED_LIBS=ON
        make -j"$(nproc)"
        echo "  -> libmeshoptimizer.so at: $MESHOPT_SO"
        cd "$AURORA_ROOT"
    fi
fi

echo
echo "=== Setup complete ==="

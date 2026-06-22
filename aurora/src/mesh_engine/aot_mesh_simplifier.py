#!/usr/bin/env python3
"""
Aurora Emulator - Phase 2: AOT Mesh Simplifier
================================================

Implements the "Mesh Engine" of Aurora's AOT preprocessing pipeline.
Uses meshoptimizer's QEM-based simplifier (Arseny Kapoulkine, MIT license).

Algorithm reference:
    Garland, M. and Heckbert, P. S. 1997.
    "Surface Simplification Using Quadric Error Metrics."
    Proceedings of the 24th Annual Conference on Computer Graphics.
    https://www.cs.cmu.edu/~garland/Papers/quadrics.pdf

meshoptimizer extends classical QEM with:
    - Attribute-aware error metric (normals, UVs, colors)
    - Lockable vertices (preserve boundary/seams)
    - Topology-preserving edge collapses

Pipeline:
    PC game ships with .obj / .glb / .fbx meshes (full LOD0 detail)
        |
        |  [AOT preprocessing - done ONCE on install]
        v
    Simplify mesh at multiple LOD levels (100%, 70%, 50%, 30%, 10%)
        |
        v
    Package as multi-LOD bundle (e.g., .glb with multiple primitives)
        |
        |  [Runtime on device - pick LOD based on distance/screen size]
        v
    Upload appropriate LOD to GPU

This script is a PoC: generates a synthetic high-poly sphere,
simplifies at 4 LOD levels, reports triangle counts + timing + error.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import time
from ctypes import c_float, c_size_t, c_uint, c_ubyte, POINTER
from dataclasses import dataclass, asdict
from pathlib import Path

# =============================================================================
# Locate meshoptimizer shared library
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MESHOPT_SO = PROJECT_ROOT / "third_party" / "meshoptimizer" / "build" / "libmeshoptimizer.so"

if not MESHOPT_SO.exists():
    raise FileNotFoundError(
        f"meshoptimizer shared library not found at {MESHOPT_SO}. "
        f"Build it: cd third_party/meshoptimizer && mkdir build && cd build && "
        f"cmake .. -DCMAKE_BUILD_TYPE=Release -DMESHOPT_BUILD_SHARED_LIBS=ON && make -j$(nproc)"
    )

_lib = ctypes.CDLL(str(MESHOPT_SO))

# Function signatures (from meshoptimizer.h)
# size_t meshopt_simplify(
#     unsigned int* destination,
#     const unsigned int* indices, size_t index_count,
#     const float* vertex_positions, size_t vertex_count, size_t vertex_positions_stride,
#     size_t target_index_count, float target_error,
#     unsigned int options, float* result_error);
_lib.meshopt_simplify.argtypes = [
    POINTER(c_uint),                   # destination
    POINTER(c_uint), c_size_t,         # indices, index_count
    POINTER(c_float), c_size_t, c_size_t,  # vertices, vertex_count, stride
    c_size_t, c_float,                 # target_index_count, target_error
    c_uint, POINTER(c_float),          # options, result_error
]
_lib.meshopt_simplify.restype = c_size_t

# void meshopt_optimizeVertexFetch(
#     void* destination,
#     unsigned int* indices, size_t index_count,
#     const void* vertices, size_t vertex_count, size_t vertex_size);
_lib.meshopt_optimizeVertexFetch.argtypes = [
    ctypes.c_void_p,
    POINTER(c_uint), c_size_t,
    ctypes.c_void_p, c_size_t, c_size_t,
]
_lib.meshopt_optimizeVertexFetch.restype = None


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class LODResult:
    """Result of simplifying a mesh to one LOD level."""
    lod_name: str
    target_ratio: float          # requested triangle ratio
    actual_index_count: int      # actual triangles * 3 after simplification
    actual_triangle_count: int
    target_error: float          # requested error threshold
    result_error: float          # actual error achieved
    simplify_time_ms: float
    vertex_fetch_optimize_ms: float


@dataclass
class MeshResult:
    source_triangle_count: int
    source_vertex_count: int
    lods: list


# =============================================================================
# Synthetic test mesh: UV sphere (deterministic, no external deps)
# =============================================================================

def generate_uv_sphere(radius: float = 1.0,
                       lat_segments: int = 64,
                       lon_segments: int = 128) -> tuple[list[float], list[int]]:
    """Generate a UV sphere as (vertices, indices).
    vertices: flat list of floats, 6 per vertex (x,y,z, nx,ny,nz) - but meshopt only needs positions.
    For PoC we just produce positions (3 floats per vertex).
    """
    vertices: list[float] = []
    indices: list[int] = []

    for lat in range(lat_segments + 1):
        theta = math.pi * lat / lat_segments  # 0 .. pi
        sin_t = math.sin(theta)
        cos_t = math.cos(theta)
        for lon in range(lon_segments + 1):
            phi = 2 * math.pi * lon / lon_segments  # 0 .. 2pi
            sin_p = math.sin(phi)
            cos_p = math.cos(phi)
            x = radius * sin_t * cos_p
            y = radius * cos_t
            z = radius * sin_t * sin_p
            vertices.extend([x, y, z])

    # Build triangle indices
    def v(lat: int, lon: int) -> int:
        return lat * (lon_segments + 1) + lon

    for lat in range(lat_segments):
        for lon in range(lon_segments):
            a = v(lat, lon)
            b = v(lat + 1, lon)
            c = v(lat + 1, lon + 1)
            d = v(lat, lon + 1)
            indices.extend([a, b, d])
            indices.extend([b, c, d])

    return vertices, indices


# =============================================================================
# Simplification
# =============================================================================

def simplify_mesh(
    vertices: list[float],
    indices: list[int],
    target_ratio: float,
    target_error: float = 0.01,
) -> tuple[list[int], float, float]:
    """
    Simplify a mesh to target_ratio of its original triangle count.
    Returns (new_indices, result_error, time_ms).
    """
    index_count = len(indices)
    vertex_count = len(vertices) // 3

    # Convert to ctypes
    src_indices = (c_uint * index_count)(*indices)
    src_vertices = (c_float * len(vertices))(*vertices)
    dst_indices = (c_uint * index_count)()  # worst case = full index buffer
    result_error = c_float(0.0)

    target_index_count = int(index_count * target_ratio)

    t0 = time.perf_counter()
    actual = _lib.meshopt_simplify(
        dst_indices,
        src_indices, index_count,
        src_vertices, vertex_count, 12,  # stride = 3 floats = 12 bytes
        target_index_count, target_error,
        0,  # options: 0 = safe defaults
        ctypes.byref(result_error),
    )
    t1 = time.perf_counter()

    new_indices = list(dst_indices[:actual])
    return new_indices, result_error.value, (t1 - t0) * 1000.0


def optimize_vertex_fetch(
    vertices: list[float],
    indices: list[int],
) -> float:
    """Run meshopt_optimizeVertexFetch for cache-friendly vertex order. Returns time_ms."""
    index_count = len(indices)
    vertex_count = len(vertices) // 3

    src_indices = (c_uint * index_count)(*indices)
    src_vertices = (c_float * len(vertices))(*vertices)
    dst_vertices = (c_float * len(vertices))()

    t0 = time.perf_counter()
    _lib.meshopt_optimizeVertexFetch(
        dst_vertices,
        src_indices, index_count,
        src_vertices, vertex_count, 12,
    )
    t1 = time.perf_counter()
    return (t1 - t0) * 1000.0


# =============================================================================
# PoC test
# =============================================================================

def run_poc(output_dir: Path):
    print("=== Aurora Emulator - Phase 2 PoC: AOT Mesh Simplifier ===\n")

    # Generate high-poly sphere (typical PC-game hero-asset density)
    print("[1/3] Generating synthetic UV sphere (lat=64, lon=128) ...")
    vertices, indices = generate_uv_sphere(radius=1.0, lat_segments=64, lon_segments=128)
    src_tris = len(indices) // 3
    src_verts = len(vertices) // 3
    print(f"      Vertices: {src_verts:,}")
    print(f"      Triangles: {src_tris:,}")

    # Simplify at 4 LOD levels (typical game LOD chain)
    print(f"\n[2/3] Simplifying to 4 LOD levels (QEM via meshoptimizer) ...")
    lods: list[LODResult] = []
    lod_targets = [
        ("LOD0", 1.00),  # original (no simplification)
        ("LOD1", 0.50),  # 50% of triangles
        ("LOD2", 0.25),  # 25% of triangles
        ("LOD3", 0.10),  # 10% of triangles (mobile low-end target)
    ]
    for name, ratio in lod_targets:
        if ratio >= 1.0:
            lods.append(LODResult(
                lod_name=name, target_ratio=ratio,
                actual_index_count=len(indices), actual_triangle_count=src_tris,
                target_error=0.0, result_error=0.0,
                simplify_time_ms=0.0, vertex_fetch_optimize_ms=0.0,
            ))
            print(f"  {name}: {src_tris:,} tris (no simplification)")
            continue

        new_idx, err, simplify_ms = simplify_mesh(vertices, indices, ratio, target_error=0.01)
        actual_tris = len(new_idx) // 3
        # Optional: re-optimize vertex fetch for runtime cache efficiency
        vfo_ms = optimize_vertex_fetch(vertices, new_idx)
        lods.append(LODResult(
            lod_name=name, target_ratio=ratio,
            actual_index_count=len(new_idx), actual_triangle_count=actual_tris,
            target_error=0.01, result_error=err,
            simplify_time_ms=simplify_ms, vertex_fetch_optimize_ms=vfo_ms,
        ))
        print(f"  {name}: target={int(ratio*100)}% -> {actual_tris:,} tris "
              f"(err={err:.4f}, simplify={simplify_ms:.1f}ms, vfo={vfo_ms:.1f}ms)")

    # Summary
    print(f"\n[3/3] Summary:")
    print(f"  Source:  {src_tris:>8,} triangles, {src_verts:>8,} vertices")
    for lod in lods:
        if lod.target_ratio >= 1.0:
            continue
        ratio_of_src = lod.actual_triangle_count / src_tris
        print(f"  {lod.lod_name}: {lod.actual_triangle_count:>8,} tris  "
              f"({ratio_of_src*100:5.1f}% of src, err={lod.result_error:.4f}, "
              f"time={lod.simplify_time_ms + lod.vertex_fetch_optimize_ms:.1f}ms)")

    print(f"\n  NOTE: On a real device, the appropriate LOD is selected at runtime")
    print(f"  based on screen-space size (distance from camera). Meshopt's QEM")
    print(f"  preserves appearance to the target_error threshold (0.01 = 1% deformation).")

    # Write results JSON
    output_dir.mkdir(parents=True, exist_ok=True)
    result = MeshResult(
        source_triangle_count=src_tris,
        source_vertex_count=src_verts,
        lods=[asdict(l) for l in lods],
    )
    out_path = output_dir / "mesh_pipeline_results.json"
    out_path.write_text(json.dumps(asdict(result), indent=2))
    print(f"\nResults JSON: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Aurora Emulator - AOT Mesh Simplifier (Phase 2 PoC)")
    parser.add_argument("--output_dir", type=Path,
                        default=PROJECT_ROOT / "tests" / "mesh_engine_output")
    args = parser.parse_args()
    run_poc(args.output_dir)


if __name__ == "__main__":
    main()

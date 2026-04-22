#!/usr/bin/env python3
"""
bf_kernelcal_demo.py
====================
Kernelcal spectral diagnostics on the Bobcat Fire (BF) stream-channel
vector time series — AZ site (~-111.265°W, 33.782°N), Tonto National Forest.

Four timestamps (vector MBTiles on deepgis-xr server):
  Aug 02 2020  bf_aug_2020.mbtiles          3,660 polygons
  Oct 03 2020  bf_oct_2020.mbtiles          9,572 polygons
  Dec 20 2020  bf_dec_2020_vector.mbtiles   9,333 polygons
  Feb 15 2021  bf_feb_2021_3d.mbtiles      12,006 polygons

Pipeline per timestamp
----------------------
  1. Decode Mapbox Vector Tile (PBF) polygons from MBTiles (SQLite).
  2. Compute polygon centroids in WGS-84 lon/lat.
  3. Project to a local metric frame (equirectangular, cm-level accuracy).
  4. Deduplicate centroids closer than 0.5 m (tile-boundary artefacts).
  5. Uniform spatial subsample to N_MAX points.
  6. Build symmetric k-NN Gaussian-weighted graph Laplacian (dense, N×N).
  7. Run kernelcal terrain diagnostics:
       spectral_entropy_from_laplacian  →  H[h]        (P1 Remark 7)
       fixed_point_kernel               →  h*(λ)       (P1 Corollary 1)
       fiedler_mode_gap                 →  Δ'          (P1 Corollary 3)
       stability_conservation_tradeoff  →  D_m = −Δ'   (P2 Proposition 1b)
  8. Estimate β₀, β₁ from graph topology.
  9. Print a summary table and physical interpretation.

Usage (remote server)
---------------------
  cd /home/jdas
  python3 dreams-lab-website-server/deepgis-xr/bf_kernelcal_demo.py

Requirements
------------
  numpy, scipy, networkx  (already installed on server)
  kernelcal               at /home/jdas/kernelcal/   (git clone)
"""

from __future__ import annotations

import sys
import math
import gzip
import sqlite3

import numpy as np
from scipy.spatial import cKDTree

# ── kernelcal ──────────────────────────────────────────────────────────────
sys.path.insert(0, '/home/jdas/kernelcal')
from kernelcal.terrain.diagnostics import (
    spectral_entropy_from_laplacian,
    fixed_point_kernel,
    fiedler_mode_gap,
    stability_conservation_tradeoff,
)

# ── CONFIG ──────────────────────────────────────────────────────────────────
DATA_DIR = '/home/jdas/dreams-lab-website-server/deepgis-xr/data'
N_MAX    = 600    # max centroids after subsampling (dense N×N eigendecomp)
K_NN     = 6     # neighbours for graph construction
SIGMA_M  = 8.0   # RBF bandwidth [metres] for edge weights
DEDUP_M  = 0.5   # deduplication radius [metres] (remove tile-boundary duplicates)
MU2      = 2.0   # kernelcal fixed-point parameter μ₂
SIGMA2   = 1.0   # kernelcal fixed-point parameter σ²
TARGET_Z = 20    # preferred tile zoom for centroid extraction

TIMESTAMPS = [
    ('Aug-2020', f'{DATA_DIR}/bf_aug_2020.mbtiles'),
    ('Oct-2020', f'{DATA_DIR}/bf_oct_2020.mbtiles'),
    ('Dec-2020', f'{DATA_DIR}/bf_dec_2020_vector.mbtiles'),
    ('Feb-2021', f'{DATA_DIR}/bf_feb_2021_3d.mbtiles'),
]


# ══════════════════════════════════════════════════════════════════════════════
# MINIMAL MAPBOX VECTOR TILE (MVT / PBF) DECODER
# Handles both packed (wire-2) and unpacked (wire-0) repeated uint32 geometry.
# ══════════════════════════════════════════════════════════════════════════════

def _varint(data: bytes, pos: int) -> tuple[int, int]:
    """Read a base-128 varint from `data` starting at `pos`."""
    result = shift = 0
    while True:
        b = data[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def _zigzag(n: int) -> int:
    """ZigZag decode (protobuf sint32 → int)."""
    return (n >> 1) ^ -(n & 1)


def _decode_geometry(cmds: list[int]) -> list[list[tuple[int, int]]]:
    """
    Decode an MVT geometry command sequence into a list of rings.
    Each ring is a list of (x, y) integer pairs in tile-local coords [0, extent).
    """
    rings, ring, cx, cy = [], [], 0, 0
    i = 0
    while i < len(cmds):
        cmd_int   = cmds[i]; i += 1
        cmd_id    = cmd_int & 0x7
        cmd_count = cmd_int >> 3
        if cmd_id in (1, 2):           # MoveTo / LineTo
            for _ in range(cmd_count):
                cx += _zigzag(cmds[i]); i += 1
                cy += _zigzag(cmds[i]); i += 1
                if cmd_id == 1 and ring:   # MoveTo starts a new ring
                    rings.append(ring); ring = []
                ring.append((cx, cy))
        elif cmd_id == 7:              # ClosePath
            if ring:
                rings.append(ring); ring = []
    if ring:
        rings.append(ring)
    return rings


def _parse_feature(data: bytes) -> list[int]:
    """Parse one MVT Feature protobuf blob; return geometry command list."""
    geom, pos, N = [], 0, len(data)
    while pos < N:
        tag, pos = _varint(data, pos)
        wire = tag & 0x7; field = tag >> 3
        if wire == 0:
            v, pos = _varint(data, pos)
            if field == 4:             # geometry, unpacked varint
                geom.append(v)
        elif wire == 2:
            length, pos = _varint(data, pos)
            blob = data[pos:pos + length]; pos += length
            if field == 4:             # geometry, packed uint32
                ip = 0
                while ip < len(blob):
                    v, ip = _varint(blob, ip)
                    geom.append(v)
        elif wire == 5:
            pos += 4
        elif wire == 1:
            pos += 8
        else:
            break
    return geom


def _parse_layer(data: bytes) -> list[tuple[float, float]]:
    """
    Parse one MVT Layer protobuf blob.
    Returns a list of (fx, fy) fractional centroid coordinates in [0, 1)
    where (0, 0) = NW corner of the tile.
    """
    extent = 4096
    feat_blobs: list[bytes] = []
    pos, N = 0, len(data)
    while pos < N:
        tag, pos = _varint(data, pos)
        wire = tag & 0x7; field = tag >> 3
        if wire == 0:
            v, pos = _varint(data, pos)
            if field == 5:             # extent override
                extent = v
        elif wire == 2:
            length, pos = _varint(data, pos)
            blob = data[pos:pos + length]; pos += length
            if field == 2:             # Feature
                feat_blobs.append(blob)
        elif wire == 5:
            pos += 4
        elif wire == 1:
            pos += 8
        else:
            break

    centroids: list[tuple[float, float]] = []
    for fb in feat_blobs:
        cmds = _parse_feature(fb)
        if not cmds:
            continue
        for ring in _decode_geometry(cmds):
            if ring:
                fx = float(np.mean([pt[0] for pt in ring])) / extent
                fy = float(np.mean([pt[1] for pt in ring])) / extent
                centroids.append((fx, fy))
    return centroids


def _parse_tile(raw: bytes) -> list[tuple[float, float]]:
    """
    Decode one raw MBTiles tile blob (gzip-compressed or bare PBF).
    Returns list of (fx, fy) fractional centroid coords per polygon.
    """
    try:
        raw = gzip.decompress(raw)
    except Exception:
        pass

    centroids: list[tuple[float, float]] = []
    pos, N = 0, len(raw)
    while pos < N:
        tag, pos = _varint(raw, pos)
        wire = tag & 0x7; field = tag >> 3
        if wire == 0:
            _, pos = _varint(raw, pos)
        elif wire == 2:
            length, pos = _varint(raw, pos)
            blob = raw[pos:pos + length]; pos += length
            if field == 3:             # Layer (Tile.layers field number = 3)
                centroids.extend(_parse_layer(blob))
        elif wire == 5:
            pos += 4
        elif wire == 1:
            pos += 8
        else:
            break
    return centroids


# ══════════════════════════════════════════════════════════════════════════════
# TILE COORDINATE MATHS
# MBTiles stores y in TMS convention (y=0 = south).
# MVT y=0 = north within a tile (screen coordinates).
# ══════════════════════════════════════════════════════════════════════════════

def tile_bbox(z: int, x: int, y_tms: int) -> tuple[float, float, float, float]:
    """Return (lon_W, lat_S, lon_E, lat_N) [degrees] for a TMS tile."""
    y_xyz = (1 << z) - 1 - y_tms   # TMS → XYZ (flip y)
    n     = 1 << z
    lon_w = x / n * 360.0 - 180.0
    lon_e = (x + 1) / n * 360.0 - 180.0
    lat_n = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y_xyz / n))))
    lat_s = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y_xyz + 1) / n))))
    return lon_w, lat_s, lon_e, lat_n


# ══════════════════════════════════════════════════════════════════════════════
# CENTROID EXTRACTION FROM MBTILES
# ══════════════════════════════════════════════════════════════════════════════

def extract_centroids(path: str, target_zoom: int = TARGET_Z) -> np.ndarray:
    """
    Extract polygon centroids from a vector MBTiles file in (lon, lat) degrees.
    Prefers tiles at `target_zoom`; falls back to the highest available zoom.
    """
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute('SELECT DISTINCT zoom_level FROM tiles ORDER BY zoom_level DESC')
    zooms = [r[0] for r in cur.fetchall()]
    zoom  = target_zoom if target_zoom in zooms else zooms[0]

    cur.execute(
        'SELECT tile_column, tile_row, tile_data FROM tiles WHERE zoom_level = ?',
        (zoom,)
    )
    rows = cur.fetchall()
    con.close()

    lonlat: list[tuple[float, float]] = []
    for tx, ty_tms, blob in rows:
        lon_w, lat_s, lon_e, lat_n = tile_bbox(zoom, tx, ty_tms)
        span_lon = lon_e - lon_w
        span_lat = lat_n - lat_s
        for fx, fy in _parse_tile(bytes(blob)):
            lon = lon_w + fx * span_lon
            lat = lat_n - fy * span_lat  # MVT y=0 is north
            lonlat.append((lon, lat))

    return np.array(lonlat) if lonlat else np.empty((0, 2))


# ══════════════════════════════════════════════════════════════════════════════
# COORDINATE UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def lonlat_to_metres(lonlat: np.ndarray) -> np.ndarray:
    """Equirectangular projection centred on the dataset. Returns (East, North) [m]."""
    lon0 = lonlat[:, 0].mean()
    lat0 = lonlat[:, 1].mean()
    R    = 6_371_000.0
    cos0 = math.cos(math.radians(lat0))
    E    = (lonlat[:, 0] - lon0) * cos0 * (math.pi / 180.0) * R
    N    = (lonlat[:, 1] - lat0) * (math.pi / 180.0) * R
    return np.column_stack([E, N])


def deduplicate(xy: np.ndarray, radius: float) -> np.ndarray:
    """Remove centroids within `radius` metres of an already-selected point."""
    if len(xy) == 0:
        return xy
    tree = cKDTree(xy)
    kept = np.ones(len(xy), dtype=bool)
    for i in range(len(xy)):
        if not kept[i]:
            continue
        # suppress neighbours (but not self)
        nbrs = tree.query_ball_point(xy[i], radius)
        for j in nbrs:
            if j != i:
                kept[j] = False
    return xy[kept]


def subsample(xy: np.ndarray, n_max: int, seed: int = 42) -> np.ndarray:
    """Uniform random subsample to at most `n_max` points."""
    if len(xy) <= n_max:
        return xy
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(xy), size=n_max, replace=False)
    return xy[idx]


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH CONSTRUCTION
# ══════════════════════════════════════════════════════════════════════════════

def build_laplacian(xy: np.ndarray, k: int, sigma: float) -> np.ndarray:
    """
    Symmetric k-NN Gaussian-weighted graph Laplacian.
    Edge weight w_ij = exp(-d_ij² / 2σ²).
    Returns dense (N, N) Laplacian L = D - A.
    """
    N    = len(xy)
    tree = cKDTree(xy)
    dists, idxs = tree.query(xy, k=k + 1)  # first neighbour is self

    A = np.zeros((N, N))
    for i in range(N):
        for rank in range(1, k + 1):
            j = idxs[i, rank]
            w = math.exp(-dists[i, rank] ** 2 / (2.0 * sigma ** 2))
            A[i, j] += w
            A[j, i] += w          # enforce symmetry

    A = np.minimum(A, 1.0)        # cap at 1 (symmetrisation can double-add)
    return np.diag(A.sum(axis=1)) - A


def betti_from_laplacian(L: np.ndarray) -> tuple[int, int]:
    """
    Estimate β₀ and β₁ from the graph Laplacian spectrum.

    β₀ = dim(kernel of L) = number of connected components.
    β₁ = E - V + β₀  (Euler formula for graphs).
    """
    eigvals = np.linalg.eigvalsh(L)
    beta0   = int(np.sum(np.abs(eigvals) < 1e-6))
    V       = L.shape[0]
    # Number of edges from the off-diagonal structure of A = D - L
    D  = np.diag(L)
    A  = np.diag(D) - L
    E  = int(np.sum(A > 1e-10)) // 2
    beta1   = max(0, E - V + beta0)
    return beta0, beta1


# ══════════════════════════════════════════════════════════════════════════════
# PER-TIMESTAMP ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def analyse_timestamp(label: str, path: str) -> dict | None:
    bar = '─' * 62
    print(f'\n{bar}')
    print(f'  {label}  ▸  {path.split("/")[-1]}')
    print(bar)

    # 1. Extract polygon centroids
    lonlat = extract_centroids(path)
    n_raw  = len(lonlat)
    print(f'  Centroids extracted from tiles : {n_raw}')
    if n_raw < 20:
        print('  [SKIP] Fewer than 20 centroids — cannot build a meaningful graph.')
        return None

    # 2. Project to metres
    xy = lonlat_to_metres(lonlat)

    site_w = xy[:, 0].max() - xy[:, 0].min()
    site_h = xy[:, 1].max() - xy[:, 1].min()
    print(f'  Site extent                    : {site_w:.1f} m (E-W)  ×  {site_h:.1f} m (N-S)')

    # 3. Deduplicate tile-boundary artefacts
    xy = deduplicate(xy, radius=DEDUP_M)
    print(f'  After deduplication (r={DEDUP_M} m)   : {len(xy)} centroids')

    # 4. Subsample
    xy = subsample(xy, N_MAX)
    N  = len(xy)
    print(f'  Subsampled to N                : {N}')

    # 5. Build graph Laplacian
    L = build_laplacian(xy, k=K_NN, sigma=SIGMA_M)
    print(f'  Laplacian built                : {N}×{N}  k={K_NN}  σ={SIGMA_M} m')

    # 6. Betti numbers (β₀, β₁)
    beta0, beta1 = betti_from_laplacian(L)
    print(f'  β₀ (components)               : {beta0}')
    print(f'  β₁ (independent cycles)       : {beta1}')

    # 7. Spectral entropy H[h]
    H = spectral_entropy_from_laplacian(L, tau=1.0)
    print(f'  Spectral entropy H[h]          : {H:.5f} nats')

    # 8. Fixed-point kernel h*(λ)
    h_star, info = fixed_point_kernel(L, mu2=MU2, sigma2=SIGMA2)
    conv_str = 'yes' if info['converged'] else f'NO (r={info["residual"]:.2e})'
    print(f'  Fixed-point h* converged       : {conv_str}  ({info["n_iter"]} iters)')

    # 9. Hessian gap Δ' (stability margin)
    delta_prime = fiedler_mode_gap(h_star, L, mu2=MU2, sigma2=SIGMA2)
    print(f'  Hessian stability margin Δ\'    : {delta_prime:.6f}')

    # 10. Stability–conservation tradeoff D_m
    sct = stability_conservation_tradeoff(h_star, L, mu2=MU2, sigma2=SIGMA2)
    cons_deficit = sct['conservation_deficit']   # mean |D_m|
    cons_holds   = sct['conservation_holds']
    print(f'  Conservation deficit ⟨|D_m|⟩  : {cons_deficit:.6f}  '
          f'(holds={cons_holds}, expected ≈ Δ\')')

    return dict(
        label          = label,
        n_raw          = n_raw,
        N              = N,
        H              = H,
        delta_prime    = delta_prime,
        cons_deficit   = cons_deficit,
        beta0          = beta0,
        beta1          = beta1,
        converged      = info['converged'],
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print()
    print('╔══════════════════════════════════════════════════════════════╗')
    print('║  KERNELCAL  ▸  Bobcat Fire channel network dynamics          ║')
    print('║  Site: -111.265°W, 33.782°N  ▸  Tonto NF, AZ               ║')
    print('║  4 drone orthomosaic timestamps  ▸  Aug 2020 → Feb 2021     ║')
    print('╚══════════════════════════════════════════════════════════════╝')

    results: list[dict] = []
    for label, path in TIMESTAMPS:
        r = analyse_timestamp(label, path)
        if r:
            results.append(r)

    if not results:
        print('\n[ERROR] No timestamps produced valid results.')
        return

    # ── Summary table ──────────────────────────────────────────────────────
    print()
    print('═' * 80)
    print('SUMMARY TABLE')
    print('═' * 80)
    hdr = (f"{'Timestamp':<11} {'N_polys':>8} {'N_graph':>8} "
           f"{'H[h]':>9} {'Δ\'':>10} {'|D_m|':>10} "
           f"{'β₀':>4} {'β₁':>6}")
    print(hdr)
    print('─' * 80)
    for r in results:
        print(f"{r['label']:<11} {r['n_raw']:>8} {r['N']:>8} "
              f"{r['H']:>9.5f} {r['delta_prime']:>10.6f} {r['cons_deficit']:>10.6f} "
              f"{r['beta0']:>4} {r['beta1']:>6}")

    # ── Temporal dynamics ─────────────────────────────────────────────────
    print()
    print('═' * 80)
    print('TEMPORAL DYNAMICS  (Aug 2020 → Feb 2021)')
    print('═' * 80)

    if len(results) >= 2:
        first, last = results[0], results[-1]
        dH    = last['H']           - first['H']
        db1   = last['beta1']       - first['beta1']
        dDp   = last['delta_prime'] - first['delta_prime']
        dNraw = last['n_raw']       - first['n_raw']

        def arrow(x: float) -> str:
            return '▲' if x > 0 else ('▼' if x < 0 else '—')

        print(f"  Polygon count   {arrow(dNraw)}  {first['n_raw']} → {last['n_raw']}  "
              f"  (Δ = {dNraw:+d})")
        print(f"  H[h]            {arrow(dH)}  {first['H']:.5f} → {last['H']:.5f}  "
              f"(Δ = {dH:+.5f})")
        print(f"  Δ' (stab. gap)  {arrow(dDp)}  {first['delta_prime']:.6f} → {last['delta_prime']:.6f}  "
              f"(Δ = {dDp:+.6f})")
        print(f"  β₁ (loops)      {arrow(db1)}  {first['beta1']} → {last['beta1']}  "
              f"  (Δ = {db1:+d})")

    # ── Physical interpretation ────────────────────────────────────────────
    print()
    print('═' * 80)
    print('PHYSICAL INTERPRETATION')
    print('═' * 80)

    Hs     = [r['H']          for r in results]
    Dps    = [r['delta_prime'] for r in results]
    b1s    = [r['beta1']       for r in results]
    Nraws  = [r['n_raw']       for r in results]

    # Spectral entropy trend
    dH_total = Hs[-1] - Hs[0] if len(Hs) > 1 else 0.0
    if dH_total > 0.05:
        print(f'\n  H[h] RISING (+{dH_total:.4f} nats across the series).')
        print('  The channel-network graph is becoming more spectrally diffuse:')
        print('  energy is spreading across more modes as new channel branches,')
        print('  avulsion paths, and debris-jam bypasses are added post-fire.')
    elif dH_total < -0.05:
        print(f'\n  H[h] FALLING ({dH_total:.4f} nats across the series).')
        print('  The network is concentrating into fewer dominant modes:')
        print('  incision or selective pruning is simplifying the channel graph.')
    else:
        print(f'\n  H[h] roughly stable (Δ = {dH_total:.4f} nats).')
        print('  The spectral structure of the network has not changed substantially.')

    # Polygon count trend
    dN = Nraws[-1] - Nraws[0] if len(Nraws) > 1 else 0
    if dN > 0:
        print(f'\n  Polygon count GROWING ({Nraws[0]} → {Nraws[-1]}, +{dN}).')
        print('  More channel-feature segments detected over time: consistent with')
        print('  post-fire sediment mobilisation expanding the active channel network.')
    else:
        print(f'\n  Polygon count SHRINKING ({Nraws[0]} → {Nraws[-1]}, {dN}).')
        print('  Active-channel feature count declining: vegetation recovery or')
        print('  channel consolidation may be reducing the detectable network.')

    # β₁ trend
    db1 = b1s[-1] - b1s[0] if len(b1s) > 1 else 0
    if db1 > 0:
        print(f'\n  β₁ GROWING (Δ = +{db1}).')
        print('  More independent cycles in the channel graph: avulsion, fan-head')
        print('  switching, or debris-jam bypass paths are creating new loop structures.')
        print('  This is the expected topological signature of a network WITHOUT an')
        print('  active optimal controller (no vegetation, no OCN minimisation).')
    elif db1 < 0:
        print(f'\n  β₁ SHRINKING (Δ = {db1}).')
        print('  Fewer cycles: the network is simplifying toward a tree structure,')
        print('  consistent with incision capturing flow and eliminating anastomoses.')
    else:
        print(f'\n  β₁ unchanged across series.')

    # Stability gap trend
    dDp = Dps[-1] - Dps[0] if len(Dps) > 1 else 0.0
    print(f'\n  Stability margin Δ\' {"WIDENING" if dDp > 0 else "NARROWING"}  (Δ = {dDp:+.6f}).')
    print(f'  Conservation deficit |D_m| tracks Δ\' by the Route 3 identity D_m = −Δ\'.')
    print('  A growing Δ\' means the fixed-point kernel is MORE stable but the')
    print('  representation leaks MORE information per step — the channel network')
    print('  is drifting further from the optimal-controller (OCN) condition.')
    print('  This is consistent with a post-fire system WITHOUT an active plant')
    print('  controller maintaining minimum-energy channel topology.')

    print()
    print('  KEY PREDICTION (P4 Hypothesis 2):')
    print('  If vegetation recovers and re-establishes root-strength control,')
    print('  Δ\' should decrease as the Cowan–Farquhar controller re-engages,')
    print('  and β₁ should return toward β₁^abio (the abiotic baseline).')
    print('  Monitoring these two numbers at successive timestamps is a')
    print('  ground-truth test of the topological biosignature on Earth.')

    print()
    print('Done.')


if __name__ == '__main__':
    main()

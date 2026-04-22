# DeepGIS-XR — Examples

Standalone research scripts that use the deepgis-xr data pipeline (MBTiles,
vector tiles, running services) together with the `kernelcal` library.

These are not part of the Django app; they are run directly from the repo
root, with `deepgis-xr` already up (or with read-only access to its data
files).

## Contents

| Script | What it does |
|---|---|
| `bf_kernelcal_demo.py` | Kernelcal spectral diagnostics on the Bobcat Fire (BF) stream-channel vector time series. Reads four MBTiles timestamps, builds centroid graphs, runs `spectral_entropy_from_laplacian`, `fiedler_mode_gap`, etc. |
| `bf_vegetation_segment.py` | Batch vegetation segmentation pipeline using the Grounded-SAM-2 API (`192.168.0.232:5001`). Produces TiledGISLabel-compatible CSVs for import via `manage.py import_rocks_labels`. |

## Requirements

```bash
pip install -r ../requirements.txt         # includes kernelcal via git+https
```

## Usage

```bash
# From repo root
python examples/bf_kernelcal_demo.py
python examples/bf_vegetation_segment.py
```

Input MBTiles paths are hard-coded for the Bobcat Fire site; edit the
module constants at the top of each script to point elsewhere.

## Related

- `kernelcal/examples/` — the upstream kernelcal library ships its own demo
  suite (river-network / terrain diagnostics). These examples are the
  DeepGIS-XR-side drivers that produce inputs for those.
- Refactor plan: `notes/2026-04-22-deepgis-xr-refactoring.md` (in the
  integration manuscript workspace).

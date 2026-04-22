# DeepGIS Topology Server

Standalone **Flask** service for streaming large 3D scenes (terrain tiles,
3D Tiles / B3DM / I3DM / PNTS, GLTF/GLB models) without Cesium Ion
dependency. Lives here — separate from the main Django app in
`deepgis_xr/` — because it has a different runtime, different Dockerfile,
and no ORM dependency.

## Layout

```
services/topology/
├── server.py            # Flask server (was `deepgis_topology_server.py`)
├── prepare_data.py      # Prepare DEMs / 3D models for streaming
├── Dockerfile           # Minimal Flask runtime image
└── README.md            # This file
```

## Run (standalone)

```bash
cd services/topology
pip install -r requirements.txt   # uses the parent requirements
python server.py --port 8092 --data-dir ../../data --cache-dir ../../cache
```

## Run (via docker-compose)

Added as the `topology` service in the root `docker-compose.yml`. Brings
up the Flask app on port 8092 alongside the Django `web` container on
8060 and the `tileserver` on 8091.

```bash
docker-compose up topology
```

## Data preparation

```bash
python prepare_data.py --dem input.tif --output ./data/terrain
python prepare_data.py --model input.glb --output ./data/models
```

## Ports

| Service | Port | Notes |
|---|---|---|
| `web` (Django) | 8060 | main app |
| `tileserver` | 8091 | MBTiles / MVT |
| `topology` | 8092 | this service |

## Why is this separate from Django?

- Pure Flask, no Django ORM — avoids pulling in the whole `deepgis_xr`
  settings/INSTALLED_APPS graph just to serve tiles.
- Different deploy cadence and memory profile (no torch, no SAM models).
- Different Dockerfile base (`python:3.10-slim`) — no CUDA, fast rebuilds.

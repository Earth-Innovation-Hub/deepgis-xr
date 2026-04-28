# DeepGIS-XR

**Demo clip:** 

<a href="https://www.youtube.com/watch?v=Plk7JyJsY7Y" target="_blank" rel="noopener noreferrer">
  <img src="https://img.youtube.com/vi/Plk7JyJsY7Y/0.jpg" alt="DeepGIS-XR Demo Video" style="width:560px;height:315px;">
</a>
<img width="2560" height="1440" alt="image" src="https://github.com/user-attachments/assets/14498bc7-bed7-4662-a181-685945e1244e" />
<img width="2558" height="1433" alt="image" src="https://github.com/user-attachments/assets/6ef67028-e9dd-4a6e-96f1-c0f74da05d37" />
<img width="2556" height="1435" alt="image" src="https://github.com/user-attachments/assets/c06ab8f8-54c3-453f-b112-72a77e8453fa" />
<img width="2560" height="1440" alt="image" src="https://github.com/user-attachments/assets/f5826ed4-589b-4dc2-92bb-5ec85c66a179" />

**Advanced Geospatial Visualization Platform with AI-Powered Analysis**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/django-3.2_LTS-green.svg)](https://www.djangoproject.com/)
[![Cesium](https://img.shields.io/badge/cesium-1.111+-orange.svg)](https://cesium.com/)

DeepGIS-XR is a comprehensive geospatial visualization and analysis platform that combines advanced 3D mapping, AI-powered image analysis, and adaptive sampling systems for Earth and lunar exploration.

---

## 🌟 Key Features

### 🤖 AI-Powered Viewport Analysis
- **Segment Anything Model (SAM)**: Universal image segmentation with no training required
  - Three model sizes: Base (375MB), Large (1.2GB), Huge (2.4GB)
  - Automatic region detection and boundary identification
  - GeoJSON export with polygon simplification
  
- **YOLOv8 Detection**: Ultra-fast real-time object detection
  - Multiple model sizes: Nano, Small, Medium, Large, XLarge
  - 80 COCO object categories
  - Class filtering support
  
- **Grounding DINO**: Open-vocabulary text-based object detection
  - Detect ANY object by describing it in natural language
  - Text prompts like: `"rock . boulder . crater . debris"`
  - Supports remote API deployment for GPU acceleration
  - Ideal for domain-specific detection (geology, archaeology, agriculture)

- **Zero-Shot Object Detection**: Pre-trained COCO model for 80 object categories
  - Detects: person, car, bicycle, truck, bus, animals, and more
  - Confidence-based filtering
  - Class-labeled visualizations

- **Mask2Former**: State-of-the-art instance segmentation
  - More accurate than Zero-Shot for complex scenes
  - Pre-trained on COCO dataset

### 🌍 World Sampler - Adaptive Geospatial Sampling
- **Intelligent Spatial Sampling**: Probabilistic framework for location sampling
- **Adaptive Learning**: Updates distribution based on feedback and rewards
- **Survey Mode**: Cycle through sampled points with automatic navigation
- **Spatial Queries**: Efficient region-based queries and statistics
- **Multiple Initialization Strategies**: Uniform, Gaussian, Gaussian mixture, custom

### 🌙 Moon Viewer
- **Lunar Visualization**: Full Moon globe with LROC QuickMap imagery
- **Apollo Landing Sites**: Historical mission locations
- **Aviation-Style Navigation**: Heading dial, attitude indicator, sun/moon info
- **LOLA Terrain**: High-resolution lunar elevation data
- **Lunar Digital Twin**: Navigational decision support system

### 🌤️ Weather Stations Integration
- **NWS Weather Stations**: Real-time weather data from National Weather Service API
- **Multi-State Support**: Quick load stations from California, Arizona, Colorado, and Nevada
- **Interactive Display**: Temperature labels, weather icons, and detailed popups
- **Auto-Update**: Automatic refresh every 15 minutes for current conditions
- **HUD Integration**: Weather stations accessible via bottom toolbar layer button
- **21 Default Stations**: Pre-configured stations across four western US states

### 🗺️ Advanced Geospatial Features
- **3D Globe Visualization**: CesiumJS-powered Earth and Moon globes
- **3D Buildings Layer**: OpenStreetMap buildings with worldwide coverage
  - Toggle via View panel checkbox or press `B` key
  - Free and open data source (ODbL license)
  - Smart loading: loads once, toggles visibility thereafter
- **Multi-Layer Support**: Raster and vector layer management
- **Tile Server Integration**: Custom tile server for large datasets
- **3D Model Support**: GLB/GLTF model loading and visualization
- **Coordinate Systems**: Support for multiple projections and ellipsolds
- **Drone Navigation**: Fly mode and orbit mode for automated camera movement
- **Measurement Tools**: Distance, area, and height measurement capabilities

### 🔗 Experience URL Sharing
- **Shareable URLs**: Generate URLs that capture complete camera state
- **Camera Parameters**: Position (lon, lat, alt), orientation (heading, pitch, roll)
- **View Mode Preservation**: Remembers 2D, 3D, or Columbus view mode
- **Drone State Capture**: Includes fly distance, speeds, orbit settings
- **Active Mode Restoration**: Restores takeoff, landing, fly, and orbit modes
- **QR Code Generation**: Share experiences via QR codes
- **Keyboard Shortcuts**: Press `S` to share current view

---

## 🚀 Quick Start

### Prerequisites
- Docker and Docker Compose
- NVIDIA GPU (optional, for AI features)
- Python 3.9 (for local development — matches the Docker image)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/Earth-Innovation-Hub/deepgis-xr.git
   cd deepgis-xr
   ```

2. **Start with Docker Compose**
   ```bash
   docker compose up -d
   ```
   Brings up four services by default: `web` (Django + gunicorn, GPU),
   `redis` (Celery broker for the admin-only model-training queue),
   `celery_worker` (single replica, GPU-pinned), and `tileserver`. The
   optional `db` (Postgres 16) service is gated behind a profile —
   bring it up with `docker compose --profile postgres up -d db` and
   follow `docs/migration-sqlite-to-postgres.md` if you're moving off
   the SQLite default.

3. **Access the application**
   - Main application: http://localhost:8060
   - Tile server: http://localhost:8091
   - Topology server (optional): http://localhost:8092

4. **Sync runtime assets** (large MBTiles, models, analysis results)
   ```bash
   bash scripts/sync_assets.sh       # from /mnt/dreamslab-store by default
   ```
   Override the source with `STORE=/path/to/store bash scripts/sync_assets.sh`.

### Local Development Setup

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt              # runtime
   pip install -r requirements-dev.txt          # + pytest, ruff, black, pip-tools
   ```

2. **Run migrations**
   ```bash
   python manage.py migrate
   ```

3. **Start development server**
   ```bash
   python manage.py runserver
   ```

4. **Run tests / lint**
   ```bash
   pytest                    # requires requirements-dev.txt
   ruff check .
   black --check .
   ```

---

## 🏗️ Architecture

### Technology Stack

**Backend:**
- Django 3.2 LTS (Python 3.9 web framework) — migration to 4.2 LTS tracked on roadmap
- Django REST Framework 3.12 (API endpoints)
- gunicorn 23 — production WSGI server in the web container (workers=2,
  threads=4, timeout=600, configurable via `GUNICORN_*` env vars).
  `manage.py runserver` is reserved for local development only.
- SQLite (default; the legacy 1.7 GB dev DB lives at `db.sqlite3`) →
  PostgreSQL 16 (opt-in via `DATABASE_URL`; the compose `db` service is
  gated behind the `postgres` profile, with `dj-database-url` and
  `psycopg2-binary` already in `requirements.txt`). Cutover runbook:
  `docs/migration-sqlite-to-postgres.md`.
- Celery 5.6 + Redis 7 — admin-only model-training task queue
  (`apps/api/v1/views/training.py::train_model_task`). The world sampler
  itself is synchronous; Celery is **not** used for per-viewport requests.
- Twilio + `django-phonenumber-field` (phone-number authentication)
- **Flask** 3.x — separate topology-tile server at `services/topology/`

**Frontend:**
- CesiumJS (3D globe visualization)
- Hand-written ES modules in `staticfiles/web/js/` (no build step)
- Bootstrap (UI components)
- *(Vite build was removed in the Tier-A housekeeping pass — `src/` was empty
  and the pipeline was never wired into `collectstatic`. The bundle-chunking
  plan preserved in the refactoring note will be revisited in Tier D.)*

**AI/ML:**
- Segment Anything Model (SAM) — Meta AI, local in-container inference
  with optional fallback to a remote `sam` service (port 5010)
- Grounding DINO — IDEA Research, remote API (port 5000) with optional
  in-process local fallback when the remote is unreachable
- Grounded-SAM-2 — remote API (port 5001)
- YOLOv8 — Ultralytics, local inference (`ultralytics`)
- Mask2Former — Facebook Research, local inference (`transformers`)
- Mask R-CNN — eight remote Flask services on the GPU host
  (`services/maskrcnn-rocks/` Docker image, one container per family:
  rocks, house, hypolith, litter, roadkill, newlife, brent-moon,
  harish-moon). **Phase-1 of the consolidation** is wired in the
  analyzer dispatch: set `MASKRCNN_API_URL` to a single unified
  container that exposes the full registry and the analyzers route
  there with the correct family `model_id` injected per-request; the
  per-family `MASKRCNN_*_API_URL` vars take precedence when set so
  rollout can be gradual. Detectron2 is no longer installed in the
  web image (it had no in-process callers after the Tier-E cleanup).
- PyTorch 2.5.1 + CUDA 12.1 (deep learning framework)
- `kernelcal` — Kernel Dynamics / MaxCal integration (in progress;
  bind-mount overlays `distinction_game`, `urban`, `fluid` until the
  wheel is published with these subpackages)

**Infrastructure:**
- Docker & Docker Compose (containerization)
- NVIDIA Container Toolkit (GPU pass-through)
- Nginx (reverse proxy, optional)
- TileServer GL (MBTiles → raster/vector tiles)

### Project Structure

```
deepgis-xr/
├── deepgis_xr/                       # Django project
│   ├── apps/
│   │   ├── api/v1/                   # DRF v1 (serializers, urls)
│   │   ├── auth/                     # phone-based auth (Twilio)
│   │   ├── core/                     # core models, admin, image processing
│   │   ├── ml/                       # ML helpers
│   │   ├── tile_catalog/             # Site→Dataset→Timestep→Product registry
│   │   │   ├── models.py, admin.py, serializers.py, views.py, urls.py
│   │   │   └── management/commands/
│   │   │       ├── seed_tile_catalog.py        # idempotent bootstrap
│   │   │       └── validate_tile_catalog.py    # /data.json drift sentry
│   │   └── web/                      # main web app
│   │       ├── views/                       # request handlers (Tier B split)
│   │       │   ├── pages.py, missions.py, auth_ajax.py, ai_reports.py,
│   │       │   ├── training_datasets.py, semi_supervised.py, models_3d.py
│   │       │   └── legacy.py                # remaining un-split handlers
│   │       ├── world_sampler.py             # adaptive spatial sampler
│   │       ├── world_sampler_api/           # sampling + AI viewport API (Tier C split)
│   │       │   ├── core.py, http.py         # helpers + 9 HTTP endpoints
│   │       │   ├── analyzers/               # 7 analyzers + ANALYZER_REGISTRY
│   │       │   └── legacy.py
│   │       ├── urls.py                      # 50+ routes
│   │       ├── admin.py, models.py, middleware/, templates/
│   │       └── management/commands/         # e.g. import_rocks_labels
│   └── settings.py
├── services/
│   └── topology/                     # standalone Flask tile/3D-tiles server
│       ├── server.py                        # (was deepgis_topology_server.py)
│       ├── prepare_data.py
│       └── Dockerfile                       # own runtime, no CUDA
├── examples/                         # kernelcal demos, vegetation segmentation
│   ├── bf_kernelcal_demo.py
│   └── bf_vegetation_segment.py
├── scripts/                          # utility scripts
│   ├── sync_assets.sh                       # pull data/models from lab store
│   ├── optimize_large_glb.py
│   └── grounding_dino_api_client.py
├── staticfiles/web/                  # hand-written JS, CSS, vendor libs
├── static/, media/, stl_models/      # runtime assets (gitignored)
├── data/                             # MBTiles (gitignored)
├── models/                           # ML model weights (gitignored)
├── deepgis_results/                  # AI-analysis outputs (gitignored)
├── GroundingDINO/                    # vendored upstream repo
├── Dockerfile                        # web container (CUDA 12.1, torch 2.5)
├── docker-compose.yml                # web + tileserver (+ topology, optional)
├── requirements.txt                  # pinned runtime deps
├── requirements-dev.txt              # pytest, ruff, black, pip-tools
└── README.md
```

A companion refactoring plan lives in the integration manuscript workspace at
`notes/2026-04-22-deepgis-xr-refactoring.md`. Tiers A–D have all landed
(layer manager, static-tree consolidation, and Cesium FPS work) and Tier E's
forward-compat prep is in; the Tier E version bumps and Tier F are scheduled
on the roadmap below.

---

## 🔌 API Endpoints

### World Sampler API

- `POST /webclient/sampler/initialize` - Initialize new sampler
- `POST /webclient/sampler/sample` - Get sample locations
- `POST /webclient/sampler/update` - Update distribution
- `GET /webclient/sampler/query` - Query spatial region
- `GET /webclient/sampler/statistics` - Get distribution stats
- `POST /webclient/sampler/reset` - Reset sampler
- `GET /webclient/sampler/history` - View sample history

### AI Analysis API

- `POST /webclient/sampler/analyze-viewport` - Analyze viewport with AI
  - **Parameters:**
    - `model_type` — one of (live as of April 2026):
      - **Local inference** (in the web container, GPU/CPU):
        `'sam'`, `'yolov8'`, `'mask2former'`, `'zero_shot'`,
        `'prithvi'`, `'urban_spectral'`
      - **Remote text-prompted** (Flask services on the GPU host):
        `'grounding_dino'`, `'grounded_sam'`
      - **Remote Mask R-CNN families** (one upstream image, eight
        defaults): `'maskrcnn_rocks'`, `'maskrcnn_house'`,
        `'maskrcnn_hypolith'`, `'maskrcnn_litter'`, `'maskrcnn_roadkill'`,
        `'maskrcnn_newlife'`, `'maskrcnn_brent_moon_craters'`,
        `'maskrcnn_harish_moon_craters'`. Set `MASKRCNN_API_URL` to
        consolidate behind a single container with all families served
        from one process; per-family `MASKRCNN_*_API_URL` vars take
        precedence when set so rollout can be gradual.
    - `image`: Base64-encoded viewport image
    - `location`: Camera position metadata
    - **SAM options:**
      - `sam_model`: `'vit_b'`, `'vit_l'`, or `'vit_h'`
      - `min_area`: Minimum segment area in pixels
    - **YOLOv8 options:**
      - `yolo_model`: `'yolov8n'`, `'yolov8s'`, `'yolov8m'`, `'yolov8l'`, `'yolov8x'`
      - `confidence_threshold`: 0.0-1.0
      - `class_filter`: Comma-separated class names (e.g., `"person,car,truck"`)
    - **Grounding DINO / Grounded-SAM options:**
      - `text_prompt`: Dot-separated object descriptions (e.g., `"rock . boulder . crater"`)
      - `box_threshold`: Detection confidence threshold (default: 0.3)
      - `text_threshold`: Text matching threshold (default: 0.25)
    - **Mask R-CNN options** (any `maskrcnn_*` family):
      - `model_id`: explicit checkpoint id from the upstream registry
        (overrides the family default; see
        `services/maskrcnn-rocks/README.md` for the canonical defaults
        per family)
      - `score_threshold`: 0.0-1.0
      - `max_detections`: int (default 100)
    - **Zero-Shot/Mask2Former options:**
      - `confidence_threshold`: 0.0-1.0
  - **Returns:** GeoJSON FeatureCollection with detections, metadata,
    and saved on-host artefact paths.
  - **Graceful degradation contract.** When a remote AI service is
    *unconfigured*, *unreachable*, or *times out*, the endpoint returns
    **HTTP 200** (not 503) with an empty `FeatureCollection` plus:
    - `degraded: true`
    - `unavailable_reason`: one of `"not_configured"`,
      `"connection_error"`, `"timeout"`
    - `device_info.available: false`
    - a `Retry-After` HTTP header (30 s default; 60 s on timeout)

    This keeps the frontend's per-viewport-change poll loop from
    spamming error toasts during transient outages — clients that
    check `response.ok && result.status === 'success'` see a normal
    empty response and continue rendering. Clients that *want* an "AI
    offline" badge can opt in by reading `result.degraded === true`.
    Genuine HTTP 5xx from a *reachable* upstream and unhandled
    exceptions inside the analyzer still surface as 502/500 — those
    are bugs, not unavailability, and they are deliberately not masked.

### Labeling API

- `POST /label/semi-supervised/api/generate-labels/` - Generate assisted labels
- `POST /label/semi-supervised/api/save-labels/` - Save labels
- `GET /label/semi-supervised/api/get-images/` - Get label images

### Tile Catalog API

- `GET /api/v1/tile-catalog/` — hierarchical layer registry consumed
  by the Cesium frontend.

  Returns a JSON tree of `Site → Dataset → Timestep → Product` for
  every active `Product` in the database, denormalised so the
  frontend can render the layer panel without further round-trips.
  Versioned (`"version": 1`); response shape:

  ```json
  {
    "version": 1,
    "generated_at": "2026-04-27T...",
    "sites": [
      { "slug": "phx_wildfire", "name": "Phoenix wildfire site",
        "bounds": [...], "default_zoom": 18,
        "datasets": [
          { "slug": "wildfire_orthos", "kind": "timeseries",
            "timesteps": [
              { "label": "2020-08", "sort_key": "2020-08-02",
                "products": [
                  { "layer_id": "bf_aug_2020_raster", "kind": "orthophoto",
                    "label": "Orthophoto (Aug 2020)", "default_opacity": 0.7 }
                ]}
            ]}
        ]},
      { "slug": "bishop_ca", "...": "..." }
    ]
  }
  ```

  Edited via the Django admin at `/label/admin/tile_catalog/`.
  Bootstrap with `python manage.py seed_tile_catalog`; audit drift
  against `tileserver-gl /data.json` with
  `python manage.py validate_tile_catalog`.

---

## 🧠 AI Viewport Analysis Architecture

The AI Viewport Analysis system supports multiple detection models, including remote API deployment for GPU-intensive models like Grounding DINO.

### System Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                         DeepGIS-XR Frontend                          │
│  AI Viewport Analysis panel — text prompts, sliders, model picker    │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ POST /webclient/sampler/analyze-viewport
                             │ {image, location, model_type, model_id?, …}
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│         DeepGIS-XR Django Backend (gunicorn, GPU-attached)           │
│  apps/web/world_sampler_api/http.py::analyze_viewport()              │
│   └─ analyzers/ANALYZER_REGISTRY[model_type] → dispatches to:        │
│                                                                      │
│      LOCAL inference (in the web container):                         │
│        sam · yolov8 · mask2former · zero_shot ·                      │
│        prithvi · urban_spectral                                      │
│                                                                      │
│      REMOTE inference (Flask services on the GPU host):              │
│        grounding_dino · grounded_sam · sam (remote)                  │
│        maskrcnn_{rocks · house · hypolith · litter ·                 │
│                  roadkill · newlife ·                                │
│                  brent_moon_craters · harish_moon_craters}           │
│                                                                      │
│      Mask R-CNN dispatch (resolve_remote_maskrcnn_url):              │
│        ① if MASKRCNN_*_API_URL set for this family → use it          │
│        ② else if MASKRCNN_API_URL set → use it + inject family       │
│           default into the per-request `model_id` form field         │
│        ③ else → _unavailable_response("not_configured")              │
│                                                                      │
│   On AI-down (not_configured · connection_error · timeout):          │
│      → HTTP 200 + {status:"success", degraded:true,                  │
│                    detections:[], unavailable_reason, …}             │
│        Retry-After: 30s (60s on timeout)                             │
└────────────────────────────┬─────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│     Remote AI host 192.168.0.232 (Flask + CUDA)                      │
│       :5000  grounding_dino       :5006  maskrcnn_roadkill           │
│       :5001  grounded_sam_2       :5007  maskrcnn_newlife            │
│       :5002  maskrcnn_rocks       :5008  maskrcnn_brent_moon         │
│       :5003  maskrcnn_house       :5009  maskrcnn_harish_moon        │
│       :5004  maskrcnn_hypolith    :5010  sam (classic v1)            │
│       :5005  maskrcnn_litter                                         │
│                                                                      │
│       Phase-1 consolidation: collapse :5002–:5009 to ONE container   │
│       on :5002 with all eight weight bundles mounted; legacy direct  │
│       callers preserved by services/maskrcnn-rocks/scripts/          │
│       port_shim.py (Python stdlib, no nginx-lua) which injects the   │
│       correct model_id and proxies to the unified upstream.          │
└──────────────────────────────────────────────────────────────────────┘
```

### Remote AI APIs

GPU-accelerated AI services on dedicated server for open-vocabulary detection and segmentation.

**Grounding DINO** (port 5000): Text-based detection  
![detection_visualization](https://github.com/user-attachments/assets/533490e9-bafd-40a4-bf2f-0204186387b3)

**Grounded-SAM-2** (port 5001): Detection + high-quality segmentation
![segmentation_visualization](https://github.com/user-attachments/assets/161de955-7e61-4827-9ee5-1d36ffc7ca9e)

```bash
# Grounding DINO - Detection only
curl -X POST http://192.168.0.232:5000/api/predict \
    -F "file=@image.jpg" -F "text_prompt=rock . boulder . crater"

# Grounded-SAM-2 - Detection + Segmentation
curl -X POST http://192.168.0.232:5001/detect \
    -F "image=@image.jpg" -F "text_prompt=rock . boulder . crater"

# Python client
./grounding_dino_api_client.py --image viewport.jpg --prompt "rock . boulder"
```

**Example Prompts:** Geology: `"rock . boulder . crater"` | Urban: `"building . car . tree"` | Wildlife: `"animal . bird . nest"`

---

## 🎯 Usage Examples

### AI Viewport Analysis

1. **Navigate to DeepGIS Search** (`/label/3d/search/`)
2. **Open AI Viewport Analysis panel** (brain icon in HUD)
3. **Select analysis type:**
   - **SAM**: Universal segmentation (all regions)
   - **YOLOv8**: Fast real-time detection (80 COCO categories)
   - **Grounding DINO**: Open-vocabulary detection (describe any object)
   - **Zero-Shot**: Pre-trained COCO detection
   - **Mask2Former**: High-accuracy instance segmentation
4. **Configure parameters:**
   - SAM: Model size (Base/Large/Huge), minimum segment area
   - YOLOv8: Model size (Nano to XLarge), confidence, class filter
   - Grounding DINO: Text prompt (e.g., `"rock . crater . boulder"`), thresholds
   - Zero-Shot/Mask2Former: Confidence threshold
5. **Click "Analyze Viewport"**
6. **View results** on map with color-coded polygons and labels

### World Sampler

1. **Initialize sampler** with desired strategy
2. **Sample locations** based on adaptive distribution
3. **Navigate to samples** using survey mode
4. **Update distribution** based on feedback
5. **Query regions** for spatial analysis

### Moon Viewer

1. **Navigate to Moon Viewer** (`/label/3d/moon/`)
2. **Explore lunar surface** with LROC imagery
3. **View Apollo landing sites** and historical locations
4. **Use navigation widgets** for precise control
5. **Adjust camera** with aviation-style controls

### 3D Buildings Layer

1. **Navigate to DeepGIS Search** (`/label/3d/search/`)
2. **Enable buildings**:
   - Click "View" button in HUD toolbar
   - Check "3D Buildings (OSM)" checkbox
   - Or press `B` key to toggle instantly
3. **Best viewed in 3D mode** (press `V` to switch to 3D)
4. **Zoom to urban areas** to see detailed building models
5. **Coverage**: Worldwide, based on OpenStreetMap data quality

### Weather Stations

1. **Navigate to DeepGIS Search** (`/label/3d/search/`)
2. **Click "Weather" button** in the bottom HUD toolbar
3. **Toggle "Show Weather Stations"** to enable
4. **Load stations**:
   - Click "All States" to load all 21 stations (CA, AZ, CO, NV)
   - Or click individual state buttons (CA, AZ, CO, NV) for specific regions
5. **View weather data**: Click on station markers for detailed information
6. **Auto-update**: Stations refresh every 15 minutes automatically

### Experience URL Sharing

1. **Navigate to any view** in DeepGIS Search
2. **Configure your experience**:
   - Set camera position and orientation
   - Choose view mode (2D/3D/Columbus) - press `V` to toggle
   - Enable drone modes (fly, orbit, takeoff, landing)
3. **Share your view**:
   - Press `S` or click the Share button
   - URL is automatically copied to clipboard
4. **Generate QR Code**: Click QR button to display scannable code
5. **URL includes**:
   | Parameter | Description |
   |-----------|-------------|
   | `lon`, `lat`, `alt` | Camera position |
   | `heading`, `pitch`, `roll` | Camera orientation |
   | `viewMode` | 2D, 3D, or Columbus |
   | `flyDist`, `hSpeed`, `vSpeed` | Drone fly settings |
   | `orbRadius`, `orbPitch`, `orbYaw` | Orbit settings |
   | `orbiting`, `flying`, `takeoff`, `landing` | Active mode flags |

### Keyboard Shortcuts

Press `H` to view all shortcuts in-app. Key shortcuts include:

| Key | Action |
|-----|--------|
| `B` | Toggle 3D Buildings |
| `V` | Toggle View Mode (2D/3D/Columbus) |
| `F` | Toggle Full Screen |
| `H` | Show Keyboard Shortcuts Help |
| `S` | Share Current View |
| `Q` | Toggle QR Code |
| `T` | Hide/Show Toolbars |
| `W` | Toggle Wireframe |
| `D` | Drone Fly Forward |
| `U` | Takeoff (Up) |
| `L` | Land |
| `O` | Start Orbit |
| `P` | Pause/Stop Orbit |
| `J` | Toggle Virtual Joysticks |
| `↑` `↓` `←` `→` | Camera Perspectives (N/S/W/E) |
| `ESC` | Stop Orbit / Close Panels |

---

## 🔧 Configuration

### Environment Variables

The full, authoritative list lives in
[`.env.example`](./.env.example). Copy it to `.env` and edit. The
operationally important knobs are:

```bash
# Core (production posture by default)
DEBUG=False
DJANGO_SETTINGS_MODULE=deepgis_xr.settings
SECRET_KEY=                      # generate with: openssl rand -hex 32
ALLOWED_HOSTS=deepgis.org,localhost,127.0.0.1
NVIDIA_VISIBLE_DEVICES=all       # GPU passthrough

# Web — gunicorn (defaults match the Dockerfile CMD)
GUNICORN_WORKERS=2
GUNICORN_THREADS=4
GUNICORN_TIMEOUT=600

# Database — leave unset for the legacy SQLite default; flip to
# `postgres://deepgis:deepgis@db:5432/deepgis` after running
# `docs/migration-sqlite-to-postgres.md`. The bundled `db` service is
# off until you `docker compose --profile postgres up -d db`.
# DATABASE_URL=postgres://deepgis:deepgis@db:5432/deepgis
POSTGRES_DB=deepgis
POSTGRES_USER=deepgis
POSTGRES_PASSWORD=deepgis

# Celery broker / result backend (auto-wired by the redis service)
REDIS_URL=redis://redis:6379/0

# Remote AI services (Flask containers on a separate GPU host)
# Phase-1 consolidation: set this to point all Mask R-CNN families at
# a single upstream container; per-family vars below override it.
# MASKRCNN_API_URL=http://192.168.0.232:5002
GROUNDING_DINO_API_URL=http://192.168.0.232:5000
GROUNDED_SAM_API_URL=http://192.168.0.232:5001
SAM_API_URL=http://192.168.0.232:5010
# MASKRCNN_ROCKS_API_URL=http://192.168.0.232:5002
# … see .env.example for the full eight-family list (5002–5009)
```

### Docker Configuration

The `docker-compose.yml` ships the following services.

**Default (`docker compose up -d`):**

| Service          | Image                       | Role                                                                                      |
|------------------|-----------------------------|-------------------------------------------------------------------------------------------|
| `web`            | built locally (`Dockerfile`)| Django + DRF behind gunicorn (workers=2, threads=4, timeout=600); GPU-attached; runs `manage.py migrate --noinput` once on boot |
| `redis`          | `redis:7-alpine`            | Celery broker + result backend (healthchecked, no host port)                              |
| `celery_worker`  | reuses the `web` image      | Single replica (`--concurrency=1` because the training task takes the whole GPU); waits on `redis` healthcheck |
| `tileserver`     | `maptiler/tileserver-gl`    | Serves MBTiles raster + vector tiles                                                      |

**Optional (profile-gated):**

| Service | Image               | Profile    | Notes                                                                                         |
|---------|---------------------|------------|-----------------------------------------------------------------------------------------------|
| `db`    | `postgres:16-alpine`| `postgres` | Bring up only when you're ready to migrate off SQLite. Runbook: `docs/migration-sqlite-to-postgres.md`. |

**Volume mounts:**

- `dreams_laboratory/scripts` — ML model scripts (read-only)
- `deepgis_results` — AI analysis artefacts (shared with host)
- `redis_data`, `postgres_data` — named volumes for service persistence

### GPU Support

To enable GPU for AI features:
1. Install NVIDIA Docker runtime
2. Uncomment GPU configuration in `docker-compose.yml`
3. Ensure `NVIDIA_VISIBLE_DEVICES=all` is set

---

## 📊 Recent Updates

### April 2026 — Tile catalog: hierarchical layer UX (Tier F)

The flat raster/vector checkbox lists in the layer panel have been
replaced with a hierarchical `Site → Dataset → Timestep → Product`
catalog backed by a new Django app (`apps.tile_catalog`) and a single
`GET /api/v1/tile-catalog/` endpoint. Per the data shape that emerged
from the April tileserver audit — one timeseries site (PHX wildfire,
5 dates) and one single-shot site (Bishop, CA) live today, with
Hawaii / Italy / others queued for activation — the new panel
reorganises the UI around three independent axes:

1. **Site picker (Tier 1).** Pill row at the top of the layers
   panel: each site shows a layer count and a fly-to button.
   Selecting one collapses every other site out of the way.
2. **Time scrubber (Tier 2 timeseries).** For multi-date sites,
   horizontal ticks (one per `Timestep`, sorted by `sort_key`) with
   per-tick coverage dots — small colored dots showing which product
   kinds (orthophoto / vector / 3D mesh / …) exist at that timestep.
   Pin-by-click; prev/next stepper buttons; readout below shows the
   active timestep label.
3. **Product-kind axis (Tier 2).** One master toggle + opacity
   slider per kind. Toggling "orthophoto" on once and scrubbing
   through Aug 2020 → Feb 2021 swaps the underlying tile layer at
   each transition automatically — what used to be five separate
   checkboxes is now one toggle plus a time pin.

Plus three modes that compose with the above:

- **Comparison modes (per-dataset).** A `single | swipe | overlay`
  selector. Swipe uses Cesium's `splitDirection` to render A on the
  left and B on the right of a draggable vertical split; shift-click
  any timestep to move the B pin. Overlay blends both at half opacity
  so spatial differences read visually. Mode selector lives inside
  the timeseries panel because it's per-dataset, not per-site.
- **Viewport filter (global).** A "filter to viewport" switch on the
  top control bar; when on, the panel hides any site whose bounds
  don't intersect the camera viewport, and re-evaluates on every
  `camera.moveEnd`. Day-to-day clutter killer once the catalog grows
  past a handful of sites.
- **Uncategorized layers.** Layers `tileserver-gl` serves that the
  catalog doesn't know about appear in a collapsed "Uncategorized"
  group at the bottom — reachable, but the visual cue is "please
  curate this in the admin." `python manage.py validate_tile_catalog`
  reports drift in both directions for CI / cron use.

Editing happens entirely through the Django admin
(`/label/admin/tile_catalog/`), which uses inline forms so opening a
Site shows its Datasets, opening a Dataset shows its Timesteps, and
so on. Initial bootstrap is `python manage.py seed_tile_catalog`
(idempotent; admin edits survive subsequent runs unless
`--force-update` is passed).

### April 2026 — Ops hardening + graceful AI dispatch (post-Tier-E prep)

- **Ops hardening.** Web container now serves through gunicorn 23
  (workers=2, threads=4, timeout=600 — all `GUNICORN_*` overridable);
  `DEBUG` defaults to `False`; `manage.py migrate --noinput` runs once
  on container start. Compose file ships `redis` (the broker the
  training queue had been quietly assuming) and a single-replica
  `celery_worker` so `train_model_task.delay(…)` actually runs end-to-
  end. Postgres 16 is wired and waiting behind the `postgres` profile
  with `dj-database-url` + `psycopg2-binary` already in
  `requirements.txt`; cutover from the legacy 1.7 GB `db.sqlite3` is
  operator-driven via `docs/migration-sqlite-to-postgres.md` — nothing
  is forced.
- **Graceful AI-down responses.** `analyze-viewport` no longer returns
  hard 503s when a remote AI service is unconfigured / unreachable /
  timing out. New `_unavailable_response(...)` helper (in
  `analyzers/_helpers.py`) returns HTTP 200 with
  `{status:"success", degraded:true, detections:[], unavailable_reason,
  …}` plus a `Retry-After` header (30 s default; 60 s on timeout) so
  the frontend's per-viewport-change poll loop stops spamming error
  toasts during transient outages. Reserved for unavailability only —
  real upstream 5xx and analyzer crashes still surface as 502/500.
- **Unified Mask R-CNN dispatch (phase 1).** The eight
  `MASKRCNN_*_API_URL` services on `:5002–:5009` all run the same
  `services/maskrcnn-rocks/` Docker image with different
  `DEFAULT_MODEL_ID`s. New analyzer dispatch helper
  (`resolve_remote_maskrcnn_url`) prefers a single `MASKRCNN_API_URL`
  when set and injects the family default into the per-request
  `model_id` form field; the per-family vars take precedence so
  rollout is gradual. Backward-compat for legacy direct clients on
  the old port range is provided by
  `services/maskrcnn-rocks/scripts/port_shim.py` — a stdlib-only
  Python proxy (no nginx-lua) that injects the correct `model_id` and
  forwards to the unified upstream. Phase 2 (operator-side) collapses
  to one upstream container with all weight bundles mounted.

### April 2026 — Refactor tiers A–D landed, Tier E prep landed

- **Tier A** — housekeeping (PR #3): fully pinned `requirements.txt`; added
  `requirements-dev.txt`; relocated root `.py` scripts into
  `services/topology/`, `examples/`, `scripts/`; `kernelcal` installed as a
  real dep; `scripts/sync_assets.sh` syncs `data/`/`models/`/`deepgis_results/`
  from `/mnt/dreamslab-store`; dead Vite config removed.
- **Tier B** — views split (PR #4): the 2 633-line `apps/web/views.py`
  monolith is now a `views/` package — `pages`, `missions`, `auth_ajax`,
  `ai_reports`, `training_datasets`, `semi_supervised`, `models_3d` plus a
  shrinking `legacy.py`, with `__init__.py` preserving every public name
  `urls.py` routes to.
- **Tier C** — world-sampler split (PR #5): `world_sampler_api.py` is now a
  package with `core.py` (helpers), `http.py` (9 endpoints), and an
  `analyzers/` subpackage (7 analyzers + 3 shared helpers) exposed through
  an `ANALYZER_REGISTRY`. This unblocks the MaxCal / Model-Kernel Selector
  work in `kernelcal`.
- **Tier D** — frontend layer manager (PR #6): OSM-Buildings double-
  instantiation bug fixed by collapsing two parallel `toggleOSMBuildings`
  paths onto one canonical helper in `cesium-init.js`; a new feature-layer
  registry in `staticfiles/web/js/core/feature-layers.js` normalises
  heterogeneous layer toggles (OSM Buildings, World Terrain, …) behind
  a single `window.FeatureLayers.set(id, enabled)` / `renderToggles(…)`
  API; Tier D3 lifted the OSM-Buildings toggle onto `label_topology`
  via the registry.
- **Tier E prep** — forward-compat cleanups (PR #7): dropped
  `USE_L10N = True` (removed in Django 5.0) and the stale
  `default_app_config` pointer in `apps/auth/__init__.py` (removed in
  4.2, already redundant given `INSTALLED_APPS` lists `AuthConfig`
  directly); removed an unused `shapely.geometry.shape` import in
  `views/legacy.py`. All three edits are no-ops on the current Django
  3.2 / Shapely 1.8 stack and shrink the actual bump commit to a
  four-line `requirements.txt` change.
- **Tier D0** — frontend static-tree consolidation (PR #8): wired
  `BASE_DIR/staticfiles/` into `STATICFILES_DIRS` so Django's finders
  actually resolve `{% static 'web/js/main.js' %}` to the tracked tree.
  Without this, the Tier D frontend work had been sitting in the repo
  but not being served — the app had been falling back to an older,
  untracked `deepgis_xr/apps/web/static/` tree. Orphaned assets
  (`mask2former-corrector.css`/`.js`, `responsive.css`) parked under
  `staticfiles/web/legacy/` with a README.
- **Tier D0.5** — Cesium FPS tuning (PR #8): four FPS sinks removed in
  `cesium-init.js` — globe `enableLighting`, uncapped
  `resolutionScale × devicePixelRatio` on Retina/4K (now capped at 1.5×
  with `?hidpi=1` opt-in), `tileLoadProgressEvent → requestRender`
  spam, and `fxaa` on an already-supersampled scene. 60 FPS restored
  on iGPU / Retina.

### December 2025

- ✅ **3D Buildings Layer**: OpenStreetMap buildings worldwide; toggleable via UI or `B` key; free and open data (ODbL)
- ✅ **Experience URL Sharing**: Complete camera state sharing via URL; supports takeoff/landing/fly/orbit modes; QR code generation
- ✅ **Grounding DINO**: Open-vocabulary detection with text prompts; remote API architecture for GPU servers
- ✅ **Weather Stations**: NWS integration with 21 stations across CA, AZ, CO, NV; HUD toolbar integration; auto-update every 15 min
- ✅ **UI/UX**: HUD toolbar with floating panels; aviation-style navigation widgets; drone fly/orbit modes
- ✅ **AI/ML**: YOLOv8 and Mask2Former integration; SAM optimization; clean viewport capture
- ✅ **Performance**: Memory optimization; improved error handling; duplicate entity prevention
- ✅ **View Mode Switching**: 2D/3D/Columbus view toggle with keyboard shortcut (V key); auto-restore from URL

---

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. **Fork the repository**
2. **Create a feature branch** (`git checkout -b feature/amazing-feature`)
3. **Commit your changes** (`git commit -m 'Add amazing feature'`)
4. **Push to the branch** (`git push origin feature/amazing-feature`)
5. **Open a Pull Request**

### Code Style
- Follow PEP 8 for Python code
- Use ESLint for JavaScript
- Add docstrings to functions and classes
- Include tests for new features

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

DeepGIS‑XR builds on concepts and systems originally developed for the [Oceanographic Decision Support System (ODSS, MBARI)](https://odss.mbari.org/), the [Agricultural Decision Support System (AgDSS, University of Pennsylvania)](https://github.com/Trefo/agdss), the [OpenUAV Project (University of Pennsylvania, Arizona State University)](https://github.com/Open-UAV), and [DeepGIS (Arizona State University)](https://github.com/DREAMS-lab/deepgis). The DeepGIS project acknowledges support from the National Science Foundation, the United States Department of Agriculture, and the National Aeronautics and Space Administration.

### Technology Acknowledgments

- **CesiumJS**: 3D globe visualization
- **Meta AI**: Segment Anything Model
- **IDEA Research**: Grounding DINO open-vocabulary detection
- **Ultralytics**: YOLOv8 real-time detection
- **NASA/GSFC/ASU**: LROC QuickMap lunar imagery
- **COCO Dataset**: Object detection categories

---

## 📧 Contact & Support

- **Repository**: [Earth-Innovation-Hub/deepgis-xr](https://github.com/Earth-Innovation-Hub/deepgis-xr)
- **Issues**: [GitHub Issues](https://github.com/Earth-Innovation-Hub/deepgis-xr/issues)

---

## 🗺️ Roadmap

### ✅ Completed
- [x] Zero-Shot Detection integration
- [x] SAM viewport analysis
- [x] YOLOv8 real-time detection
- [x] Grounding DINO open-vocabulary detection
- [x] Remote AI API integration architecture
- [x] World Sampler adaptive sampling
- [x] Moon viewer with navigation widgets
- [x] Weather stations integration
- [x] HUD toolbar and panel system
- [x] Multi-state weather station support
- [x] Experience URL sharing with full state capture
- [x] QR code generation for mobile sharing
- [x] 2D/3D/Columbus view mode switching
- [x] 3D Buildings layer with OpenStreetMap data

### 🔧 Refactor track (Q2 2026)

Tiers A–C and the Tier-D prep steps (D0, D0.5) have landed. Remaining work
is tracked alongside feature work. See
`notes/2026-04-22-deepgis-xr-refactoring.md` in the integration workspace
for the full plan.

- [x] **Tier A** — housekeeping, pinning, file relocations (PR #3)
- [x] **Tier B** — `apps/web/views.py` → `views/` package of 7 focused
      modules + shrinking `legacy.py` (PR #4)
- [x] **Tier C** — `world_sampler_api.py` → package with `core.py`, `http.py`
      (9 endpoints), `analyzers/` subpackage, and `ANALYZER_REGISTRY`
      (PR #5; unblocks `kernelcal` Threads 1 + 2)
- [x] **Tier D** — frontend layer manager (PR #6): OSM-Buildings
      double-instantiation fixed; feature-layer registry in
      `core/feature-layers.js` with a `window.FeatureLayers` API;
      registry-driven toggles on `label_topology`
- [x] **Tier D0** — `staticfiles/` wired into `STATICFILES_DIRS` so the
      tracked frontend tree is actually served; orphaned assets parked in
      `staticfiles/web/legacy/` (PR #8)
- [x] **Tier D0.5** — Cesium perf pass: four FPS sinks removed in
      `cesium-init.js`; 60 FPS restored on iGPU/Retina (PR #8)
- [~] **Tier E** — Django 3.2 → 4.2 LTS; DRF 3.12 → 3.15; Shapely 1.8 → 2.x.
      Forward-compat prep landed (PR #7); the version bumps are a four-line
      `requirements.txt` change pending container regression sweep. Full
      recon in `TIER_E_MIGRATION_NOTES.md` at the repo root (local-only).
      Django 5.0/5.1 is tracked separately (needs Python 3.10+).
- [ ] **Tier F** — `kernelcal` integration: MaxCal World Sampler, Model-Kernel
      Selector, terrain diagnostics endpoint
- [~] **Tier G — ops hardening + AI dispatch consolidation** (Apr 2026):
      gunicorn + `DEBUG=False` + `redis` + `celery_worker` services
      shipped; Postgres 16 wired behind a `postgres` profile with a
      cutover runbook (`docs/migration-sqlite-to-postgres.md`);
      `_unavailable_response` graceful-degradation contract added to
      `analyze-viewport`; Mask R-CNN dispatch consolidated behind
      `MASKRCNN_API_URL` + per-family fallback + `port_shim.py`.
      **Phase 2** (operator-side, pending): collapse
      `services/maskrcnn-rocks/` to one upstream container with all
      eight weight bundles mounted; SQLite → Postgres data cutover.

### 🔄 Q1 2026 - Near Term
- [ ] **Mars Terrain Viewer**: Extend lunar capabilities to Mars with HiRISE/CTX imagery
- [ ] **Mission Export Formats**: MAVLink waypoint export for drone autopilots
- [ ] **Enhanced Annotation Tools**: Polygon editing, snapping, and undo/redo
- [ ] **Time-Series Layers**: Temporal slider for historical imagery comparison
- [ ] **Geofence Alerts**: Real-time boundary violation notifications
- [ ] **WebXR/VR Support**: Immersive 3D globe exploration with VR headsets
- [ ] **Real-Time Telemetry**: Live drone/vehicle position tracking via MAVLink/ROS
- [ ] **Collaborative Sessions**: Multi-user annotation with real-time sync
- [ ] **Custom Model Training**: Upload datasets and train custom detection models
- [ ] **Advanced Export**: Shapefile, KML, GeoPackage, and Cloud Optimized GeoTIFF
- [ ] **Performance Dashboard**: GPU/memory monitoring and optimization hints

### 🔮 Q1-Q4 2026 - Long Term
- [ ] **CLIP/VLM Semantic Search**: Natural language queries for geospatial features
- [ ] **Autonomous Survey Planning**: AI-optimized flight path generation
- [ ] **Digital Twin Integration**: Real-time sensor fusion and 3D reconstruction
- [ ] **Model Marketplace**: Community-shared detection models and configs
- [ ] **Edge Deployment**: Lightweight inference for embedded/field devices
- [ ] **AR Field Overlay**: Mobile AR for on-site navigation and annotation
- [ ] Integration with Google Earth Engine
- [ ] Integration with OpenTopography and support for point cloud visualization (LAS/LAZ)
- [ ] 3D building/structure modeling from imagery
- [ ] Automated change detection between time periods

---

## ⚠️ Disclaimer

This software is provided "as is" without warranty. Use at your own risk. Intended for research and educational purposes. AI analysis results should be validated independently for critical applications.

---

**Powered by Earth Innovation Hub (Arizona STEAM non-profit corporation)**


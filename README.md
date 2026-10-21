# DeepGIS-XR

**Demo clip:** 

<a href="https://www.youtube.com/watch?v=Plk7JyJsY7Y" target="_blank" rel="noopener noreferrer">
  <img src="https://img.youtube.com/vi/Plk7JyJsY7Y/0.jpg" alt="DeepGIS-XR Demo Video" style="width:560px;height:315px;">
</a>
<img width="2560" height="1440" alt="image" src="https://github.com/user-attachments/assets/14498bc7-bed7-4662-a181-685945e1244e" />
<img width="2558" height="1433" alt="image" src="https://github.com/user-attachments/assets/6ef67028-e9dd-4a6e-96f1-c0f74da05d37" />
<img width="2556" height="1435" alt="image" src="https://github.com/user-attachments/assets/c06ab8f8-54c3-453f-b112-72a77e8453fa" />
<img width="2560" height="1440" alt="image" src="https://github.com/user-attachments/assets/f5826ed4-589b-4dc2-92bb-5ec85c66a179" />

**Geospatial visualization platform with AI-powered analysis and a language-driven camera drone**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/django-5.2_LTS-green.svg)](https://www.djangoproject.com/)
[![Cesium](https://img.shields.io/badge/cesium-1.111-orange.svg)](https://cesium.com/)

DeepGIS-XR is a geospatial visualization and analysis platform for Earth and
lunar exploration. It combines a CesiumJS 3D globe, open-vocabulary AI
detection and segmentation of the current view, adaptive spatial sampling, a
curated tile catalog, and an AI pilot that flies the camera from plain-language
requests. The live site is [deepgis.org/label/3d/search/](https://deepgis.org/label/3d/search/).

---

## 🌟 Key Features

### 🧑‍✈️ AI Pilot (new, October 2026)
A **Pilot** panel on the search page turns requests into camera-drone flights:

- *"orbit around Tempe Town Lake"*
- *"fly to Hayden Library at 200 m, orbit it twice clockwise, then land"*
- *"climb to 1500 m and look at the horizon"*
- *"orbit around Hayden Butte and show geologic features within 5 km"*
- *"show geology around Griffith Park, Los Angeles while orbiting it"*

A language model only chooses the actions and the numbers the user gave
(`goto`, `orbit`, `takeoff`, `land`, `look`, `stop`, `wait`, `show_geology`,
`hide_geology`). Django validates and clamps them, and the page runs them on
the existing drone controls. It never touches a real vehicle. See
[AI Pilot architecture](#-ai-pilot-architecture).

### 🪨 Geology layer
- **Published geologic maps anywhere** (most detailed in the US) via
  [Macrostrat](https://macrostrat.org/): rock units sampled across a circle,
  with age, lithology and the source map citation, plus the geologic map
  draped over the terrain.
- **Curated geology sites** around Phoenix and Tempe (Tempe/Hayden Butte,
  Papago and Barnes Buttes, Hole-in-the-Rock, Camelback Mountain, South
  Mountains, Superstition Mountains, Tempe Town Lake). Each has a description
  sourced from Arizona Geological Survey publications and others, plus
  OpenStreetMap coordinates, in
  `staticfiles/web/geo/tempe-geology.geojson`.

### 🤖 AI Viewport Analysis
Analyze what the camera sees, using remote GPU services:

- **Grounding DINO**: open-vocabulary detection from a text prompt, e.g.
  `"rock . boulder . crater . debris"`. Suited to domain-specific targets
  (geology, archaeology, agriculture).
- **Grounded-SAM-2**: Grounding DINO boxes refined into SAM 2 masks for
  high-quality segmentation of the named objects.
- **Segment Anything (SAM)**: prompt-free segmentation of every region in the
  view, with GeoJSON export and polygon simplification.

Results come back as GeoJSON, drawn on the globe with labels and confidences.

### 🌍 World Sampler: adaptive geospatial sampling
- Probabilistic location sampling that updates from feedback and rewards
- Survey mode that cycles through samples with automatic navigation
- Spatial queries and statistics; uniform, Gaussian, mixture or custom priors

### 🗂️ Tile Catalog
- Hierarchical `Site → Dataset → Timestep → Product` layer panel
- Time scrubber, swipe and overlay comparison, and a filter to the current viewport
- Edited in the Django admin; drift against tileserver-gl checked by a management command

### 🌙 Moon Viewer
- Lunar globe with LROC QuickMap imagery and LOLA terrain
- Apollo landing sites and aviation-style navigation widgets

### 🌤️ Weather Stations
- National Weather Service stations (21 defaults across CA, AZ, CO, NV)
- Temperature labels, icons, popups; refresh every 15 minutes

### 🗺️ Globe, drone and sharing
- **3D globe** (CesiumJS) with 2D, 3D and Columbus views
- **3D buildings** from OpenStreetMap (press `B`)
- **Camera drone**: fly forward, takeoff and land along the local vertical,
  and orbit with adjustable radius, speed, laps, direction, pitch and yaw
- **Measurement tools**, GLB/GLTF models, raster and vector layers
- **Shareable URLs and QR codes** capturing camera and drone state (press `S`)

---

## 🚀 Quick Start

### Prerequisites
- Docker and Docker Compose
- NVIDIA GPU + NVIDIA Container Toolkit (only for the admin model-training worker)
- Python 3.10 for local development (matches the Docker image)
- Reachable Grounding DINO / Grounded-SAM-2 / SAM services for AI analysis
  (optional; the page works without them)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/Earth-Innovation-Hub/deepgis-xr.git
   cd deepgis-xr
   cp .env.example .env    # then edit
   ```

2. **Start with Docker Compose**
   ```bash
   docker compose up -d
   ```
   This starts `web` (Django + gunicorn), `redis`, `celery_worker` and
   `tileserver`. An optional Postgres 16 `db` service is behind a profile:
   `docker compose --profile postgres up -d db`. To move off SQLite, follow
   `docs/migration-sqlite-to-postgres.md`.

3. **Open the application**
   - Main application: http://localhost:8060 (search viewer at `/label/3d/search/`)
   - Tile server: http://localhost:8091
   - Topology server (optional): http://localhost:8092

4. **Sync runtime assets** (large MBTiles, analysis results)
   ```bash
   bash scripts/sync_assets.sh       # from /mnt/dreamslab-store by default
   ```
   Override the source with `STORE=/path/to/store bash scripts/sync_assets.sh`.

### Local Development Setup

```bash
pip install -r requirements.txt              # runtime
pip install -r requirements-dev.txt          # + pytest, ruff, black, pip-tools
python manage.py migrate
python manage.py runserver
```

Tests and lint:

```bash
python manage.py test deepgis_xr.apps.web.tests.test_pilot   # AI pilot (13 tests)
pytest
ruff check .
black --check .
```

In the container, gunicorn runs without `--reload`. After changing Python code
or templates, run `docker restart deepgis-xr-web-1`. After changing `.env`, run
`docker compose up -d --no-deps web` so the new environment is loaded.

---

## 🏗️ Architecture

### Technology Stack

**Backend**
- Django 5.2 LTS (supported through April 2028) on Python 3.10
- Django REST Framework 3.16
- gunicorn 23 in the web container (workers=2, threads=4, timeout=600; all
  `GUNICORN_*` overridable). `runserver` is for local development only.
- SQLite by default; PostgreSQL 16 opt-in via `DATABASE_URL`
  (`dj-database-url`, `psycopg2-binary`)
- Celery 5.6 + Redis 7 for the admin-only model-training queue (not used for
  per-viewport requests)
- Shapely 2.0, GDAL/rasterio/fiona for GIS processing
- Twilio + `django-phonenumber-field` (phone-number authentication)
- Flask 3.x topology-tile server in `services/topology/`

**Frontend**
- CesiumJS 1.111, hand-written ES modules in `staticfiles/web/js/` (no build step)
- Bootstrap UI, HUD toolbar with floating panels
- Geocoding: OpenStreetMap Nominatim, falling back to Cesium Ion

**AI / ML** (inference runs as remote services; the web image ships no model weights)
- Grounding DINO (IDEA Research), remote API, `GROUNDING_DINO_API_URL`
- Grounded-SAM-2, remote API, `GROUNDED_SAM_API_URL`
- Segment Anything (Meta AI), remote API, `SAM_API_URL`
- AI pilot: a language model reached through a read-only MCP server
  (`dreams_mcp_ro` from the DREAMS Lab `dreams_llm_ros2` stack),
  `DEEPGIS_PILOT_MCP_URL`
- PyTorch 2.5.1 + CUDA 12.1 stays in the image only for the admin training task

**Infrastructure**
- Docker image based on `nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04`;
  `.dockerignore` keeps weights, databases and data out of the build context
- TileServer GL (MBTiles → raster/vector tiles)
- Nginx reverse proxy (optional)

### Project Structure

```
deepgis-xr/
├── deepgis_xr/                       # Django project
│   ├── apps/
│   │   ├── api/v1/                   # DRF v1 (serializers, urls)
│   │   ├── auth/                     # phone-based auth (Twilio)
│   │   ├── core/                     # core models, admin, image processing
│   │   ├── ml/                       # ML helpers (admin training)
│   │   ├── tile_catalog/             # Site→Dataset→Timestep→Product registry
│   │   │   └── management/commands/  # seed_tile_catalog, validate_tile_catalog
│   │   └── web/                      # main web app
│   │       ├── views/                # pages, missions, auth_ajax, ai_reports,
│   │       │                         # training_datasets, semi_supervised,
│   │       │                         # models_3d, pilot (AI pilot), legacy
│   │       ├── world_sampler.py      # adaptive spatial sampler
│   │       ├── world_sampler_api/    # sampling + AI viewport API
│   │       │   ├── core.py, http.py  # helpers + HTTP endpoints
│   │       │   └── analyzers/        # ANALYZER_REGISTRY (grounding_dino,
│   │       │                         # grounded_sam, sam, ...)
│   │       ├── tests/test_pilot.py   # AI pilot tests
│   │       ├── templates/web/label_search.html   # search viewer + pilot panel
│   │       ├── urls.py, admin.py, models.py, middleware/
│   │       └── management/commands/
│   └── settings.py
├── services/topology/                # standalone Flask tile/3D-tiles server
├── staticfiles/web/                  # tracked JS, CSS, vendor libs
│   └── geo/tempe-geology.geojson     # curated, sourced geology sites
├── scripts/                          # sync_assets.sh, GLB optimizer, API clients
├── examples/                         # kernelcal demos
├── GroundingDINO/                    # vendored upstream repo
├── static/, media/, data/, deepgis_results/   # runtime assets (gitignored)
├── Dockerfile                        # web image (Ubuntu 22.04, CUDA 12.1, Python 3.10)
├── docker-compose.yml                # web, redis, celery_worker, tileserver (+ db profile)
├── requirements.txt                  # pinned runtime deps
└── requirements-dev.txt              # pytest, ruff, black, pip-tools
```

---

## 🔌 API Endpoints

### AI Pilot

- `POST /label/api/pilot/`: one chat turn. Requires a signed-in session and
  the CSRF token. Rate-limited per user (`DEEPGIS_PILOT_RATE_PER_MIN`,
  default 12).
  - **Body:** `{"message": "...", "view": {lat, lon, height_agl, heading_deg,
    target: {lat, lon}}, "history": [{role, content}, ...]}`
  - **Returns:** `{"reply": "...", "actions": [...], "model": "...",
    "duration_sec": ...}`. Unknown action types and fields are dropped,
    numbers are clamped (heights 5 m to 20 km, radius 20 m to 20 km, speed
    1 to 300 m/s, and so on), and at most 8 actions are returned.
  - **Errors:** 401 `login_required` (with `login_url`), 400 for an empty or
    invalid message, 429 when rate-limited, 503 if the pilot is not
    configured, and 502 if the model is unavailable.

### AI Analysis API

- `POST /webclient/sampler/analyze-viewport`: analyze the current viewport
  - `model_type`: `'grounding_dino'`, `'grounded_sam'` or `'sam'`
  - `image`: Base64-encoded viewport image; `location`: camera metadata
  - **Grounding DINO / Grounded-SAM-2:** `text_prompt` (dot-separated, e.g.
    `"rock . boulder . crater"`), `box_threshold` (default 0.3),
    `text_threshold` (default 0.25)
  - **SAM:** `sam_model` (`'vit_b'`, `'vit_l'`, `'vit_h'`), `min_area` (pixels)
  - **Returns:** a GeoJSON FeatureCollection with detections and metadata
  - **Graceful degradation.** If a remote service is unconfigured,
    unreachable or times out, the endpoint returns **HTTP 200** with an empty
    FeatureCollection and `degraded: true`. It also sets `unavailable_reason`
    (`"not_configured"`, `"connection_error"` or `"timeout"`) and a
    `Retry-After` header (30 s; 60 s on timeout). The frontend's
    per-viewport poll therefore stays quiet during outages. Real upstream 5xx
    responses and analyzer crashes still surface as 502/500.

### World Sampler API

- `POST /webclient/sampler/initialize`: initialize a sampler
- `POST /webclient/sampler/sample`: get sample locations
- `POST /webclient/sampler/update`: update the distribution
- `GET /webclient/sampler/query`: query a spatial region
- `GET /webclient/sampler/statistics`: distribution statistics
- `POST /webclient/sampler/reset`: reset the sampler
- `GET /webclient/sampler/history`: sample history

### Labeling API

- `POST /label/semi-supervised/api/generate-labels/`: generate assisted labels
- `POST /label/semi-supervised/api/save-labels/`: save labels
- `GET /label/semi-supervised/api/get-images/`: get label images

### Tile Catalog API

- `GET /api/v1/tile-catalog/`: the hierarchical layer registry used by the
  Cesium frontend. It returns a versioned JSON tree of
  `Site → Dataset → Timestep → Product` for every active product,
  denormalised so the layer panel needs no further round-trips:

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
        ]}
    ]
  }
  ```

  Edit it in the Django admin at `/label/admin/tile_catalog/`. Bootstrap it
  with `python manage.py seed_tile_catalog`, and check for drift against
  tileserver-gl `/data.json` with `python manage.py validate_tile_catalog`.

---

## 🧑‍✈️ AI Pilot Architecture

```
Browser: /label/3d/search/  ── Pilot panel
  │  POST /label/api/pilot/  {message, current view, recent history}
  ▼
Django: views/pilot.py
  │  signed-in user · CSRF · per-user rate limit
  │  MCP tools/call ask_robot_llm with a JSON schema for {reply, actions}
  ▼
Read-only MCP server (dreams_mcp_ro) ──► language model
  │  returns {reply, actions}
  ▼
Django: keep known action types and fields, clamp every number
  │  {reply, actions, model, duration_sec}
  ▼
Browser: run actions in order on the drone controls
     goto · orbit · takeoff · land · look · stop · wait
     show_geology · hide_geology
```

Design rules:

- **The model labels; code decides.** The model names the action and the
  values the user stated. The page picks every default: orbit radius from the
  place's size, height of about half the radius, about 75 s per lap, and the
  camera aimed at the centre.
- **Place lookup order:** curated geology sites, then OpenStreetMap Nominatim
  (good for parks, peaks and landmarks), then Cesium Ion. Lookups are cached
  per page.
- **Geology cannot be invented.** For `show_geology {place, radius_m}` the
  model picks only the centre and radius (default 5 km). The page then:
  - lists curated sites inside the circle, with distance, type and age;
    clicking a marker shows rock units and source links;
  - samples the Macrostrat geologic map at 15 points, keeps the most detailed
    map at each point, and lists up to 8 units with age, lithology and the
    source map citation;
  - drapes the Macrostrat map tiles at 55% opacity over the area.

  An orbit of the same centre without a radius widens to keep the whole area
  in view.
- **Plans are cancellable.** A new request or the Stop button interrupts the
  current plan. A `stop` action inside a plan halts motion and
  lets the remaining steps (such as `hide_geology`) run.
- **Read-only by construction.** Django holds only the read-only MCP token,
  and that server has commands disabled. Nothing in this path can command a
  vehicle.

Typical latency is about 3 s with a warm model and about 40 s for the first
request after the model has been idle.

---

## 🧠 AI Viewport Analysis Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         DeepGIS-XR Frontend                          │
│  AI Viewport Analysis panel: text prompt, thresholds, model picker   │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ POST /webclient/sampler/analyze-viewport
                             │ {image, location, model_type, …}
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│               DeepGIS-XR Django Backend (gunicorn)                   │
│  apps/web/world_sampler_api/http.py::analyze_viewport()              │
│   └─ analyzers/ANALYZER_REGISTRY[model_type]                         │
│        grounding_dino · grounded_sam · sam   → remote services       │
│                                                                      │
│   On AI-down (not_configured · connection_error · timeout):          │
│      → HTTP 200 + {status:"success", degraded:true, detections:[]}   │
│        Retry-After: 30s (60s on timeout)                             │
└────────────────────────────┬─────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│     Remote AI host (Flask + CUDA)                                    │
│       :5000  Grounding DINO      (GROUNDING_DINO_API_URL)            │
│       :5001  Grounded-SAM-2      (GROUNDED_SAM_API_URL)              │
│       :5010  SAM                 (SAM_API_URL)                       │
└──────────────────────────────────────────────────────────────────────┘
```

**Grounding DINO** (port 5000): text-based detection  
![detection_visualization](https://github.com/user-attachments/assets/533490e9-bafd-40a4-bf2f-0204186387b3)

**Grounded-SAM-2** (port 5001): detection + high-quality segmentation
![segmentation_visualization](https://github.com/user-attachments/assets/161de955-7e61-4827-9ee5-1d36ffc7ca9e)

```bash
# Grounding DINO: detection only
curl -X POST http://<ai-host>:5000/api/predict \
    -F "file=@image.jpg" -F "text_prompt=rock . boulder . crater"

# Grounded-SAM-2: detection + segmentation
curl -X POST http://<ai-host>:5001/detect \
    -F "image=@image.jpg" -F "text_prompt=rock . boulder . crater"

# Python client
python scripts/grounding_dino_api_client.py --image viewport.jpg --prompt "rock . boulder"
```

**Example prompts:** Geology `"rock . boulder . crater"` · Urban
`"building . car . tree"` · Wildlife `"animal . bird . nest"`

---

## 🎯 Usage

### AI Pilot
1. Open DeepGIS Search (`/label/3d/search/`) and sign in (`/label/admin/login/`).
2. Click **Pilot** in the HUD toolbar and type a request. The page switches
   to 3D, runs the plan and logs each step in the panel.
3. Press **Stop** at any time.

### AI Viewport Analysis
1. Open DeepGIS Search and the **AI** panel.
2. Choose **Grounding DINO**, **Grounded-SAM-2** or **SAM**.
3. Set the text prompt and thresholds (Grounding DINO / Grounded-SAM-2), or
   the model size and minimum area (SAM).
4. Click **Analyze Viewport**. Results are drawn as labelled polygons.

### World Sampler
Initialize a sampler, draw samples, step through them in survey mode, update
the distribution from feedback, and query regions.

### Moon Viewer
Open `/label/3d/moon/` for LROC imagery, Apollo sites and aviation-style navigation.

### 3D Buildings
In DeepGIS Search, check **3D Buildings (OSM)** in the **View** panel or press
`B`. This works best in 3D view (`V`).

### Weather Stations
Click **Weather** in the HUD toolbar, enable stations, and load all states or
CA, AZ, CO or NV individually. Click a station for details.

### Experience URL Sharing
Press `S` (or **Share**) to copy a URL for the current view, or **QR** for a code.

| Parameter | Description |
|-----------|-------------|
| `lon`, `lat`, `alt` | Camera position |
| `heading`, `pitch`, `roll` | Camera orientation |
| `viewMode` | 2D, 3D or Columbus |
| `flyDist`, `hSpeed`, `vSpeed` | Drone fly settings |
| `orbRadius`, `orbPitch`, `orbYaw` | Orbit settings |
| `orbiting`, `flying`, `takeoff`, `landing` | Active mode flags |

### Keyboard Shortcuts

Press `H` in the app for the full list.

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
| `P` / Space | Pause/Stop Orbit (Space is ignored while typing) |
| `J` | Toggle Virtual Joysticks |
| `↑` `↓` `←` `→` | Camera Perspectives (N/S/W/E) |
| `ESC` | Stop Orbit / Close Panels |

---

## 🔧 Configuration

### Environment Variables

The authoritative list is [`.env.example`](./.env.example). Copy it to `.env`
and edit it. The important settings are:

```bash
# Core
DEBUG=False
SECRET_KEY=                      # openssl rand -hex 32
ALLOWED_HOSTS=deepgis.org,localhost,127.0.0.1

# gunicorn (defaults match the Dockerfile CMD)
GUNICORN_WORKERS=2
GUNICORN_THREADS=4
GUNICORN_TIMEOUT=600

# Database: unset = SQLite; Postgres after the migration runbook
# DATABASE_URL=postgres://deepgis:deepgis@db:5432/deepgis
REDIS_URL=redis://redis:6379/0

# Remote AI services
GROUNDING_DINO_API_URL=http://<ai-host>:5000
GROUNDED_SAM_API_URL=http://<ai-host>:5001
SAM_API_URL=http://<ai-host>:5010

# AI pilot (optional; the panel shows "not configured" without a token)
DEEPGIS_PILOT_MCP_URL=http://<mcp-host>:8766/mcp
DEEPGIS_PILOT_MCP_TOKEN=         # the READ-ONLY server's token, never a command-enabled one
# DEEPGIS_PILOT_TIMEOUT_SEC=90
# DEEPGIS_PILOT_RATE_PER_MIN=12
```

### Static Files

- Django serves `/label/static/deepgis/` from `STATIC_ROOT` (`./static/`,
  gitignored) only when `DEBUG=True`. With `DEBUG=False`, put Nginx (or
  similar) in front of that path.
- The tracked source is `staticfiles/`. After adding or changing a file
  there, copy it into `STATIC_ROOT` with `python manage.py collectstatic`, or
  copy the single file.
- Avoid directories named `data/` for tracked assets, because `.gitignore`
  excludes them. That is why the geology file lives in `staticfiles/web/geo/`.

### Docker Services

**Default (`docker compose up -d`):**

| Service          | Image                       | Role |
|------------------|-----------------------------|------|
| `web`            | built locally (`Dockerfile`)| Django + DRF behind gunicorn; runs `migrate --noinput` on boot; host port 8060 |
| `redis`          | `redis:7-alpine`            | Celery broker + result backend (healthchecked) |
| `celery_worker`  | reuses the `web` image      | Single replica for the admin training task (GPU) |
| `tileserver`     | `maptiler/tileserver-gl`    | Serves MBTiles raster + vector tiles; host port 8091 |

**Optional:** `db` (`postgres:16-alpine`, profile `postgres`). Runbook:
`docs/migration-sqlite-to-postgres.md`.

The `command:` entries for `web` and `celery_worker` are single-line JSON
arrays on purpose. Multi-line YAML scalars silently dropped the gunicorn flags.

---

## 📊 Recent Updates

### October 2026: AI pilot and geology
- **AI pilot chat** on the search page (`e93397e`): `POST /label/api/pilot/`,
  a read-only MCP model backend, and validated, clamped actions run in the
  browser. The drone controls were fixed along the way:
  - takeoff and land now take a target height and move along the local
    vertical;
  - the orbit start angle is scaled by cos(latitude), so orbits no longer
    jump when they start;
  - a 0° pitch or yaw is no longer replaced by the defaults;
  - Space no longer pauses an orbit while you type.
- **Sourced geology** (`7ee352e`): `show_geology` / `hide_geology` with a
  curated Phoenix/Tempe GeoJSON. Mapped site names resolve before Ion, which
  has no peaks. A redundant `goto` before an orbit is skipped. A `stop` step
  no longer cancels the rest of the plan.
- **Geology anywhere** (`5678038`): OpenStreetMap Nominatim geocoding first,
  Macrostrat geologic-map units with citations, and a draped map overlay.

### April 2026: Django 5.2 LTS and a slimmer image
- **Django 3.2 → 5.2.13 LTS**, DRF 3.12 → 3.16.1, Shapely 1.8 → 2.0,
  django-cors-headers 4.9, phonenumber-field 8.4. The codebase had been
  cleaned of 4.x/5.x deprecations first. `STORAGES` is declared explicitly,
  and `ModelOptimizationMiddleware` was fixed for Django 5's async-mode check.
- **Docker base** Ubuntu 20.04 → 22.04 with native Python 3.10.
  `.dockerignore` cut the build context from about 15 GB to 2 GB. Model
  weights and the ultralytics and segment-anything packages left the web image.
- **Compose** `command:` blocks switched to JSON arrays. gunicorn had been
  starting with its default bind of `127.0.0.1:8000` and no flags.
- **Tile catalog** (Tier F of the layer UX): hierarchical layer panel, time
  scrubber, swipe and overlay comparison, viewport filter, and an
  "Uncategorized" group for layers not yet curated.
- **Ops hardening**: gunicorn, Redis + Celery worker, Postgres behind a
  profile, and the graceful AI-down contract on `analyze-viewport`.
- **Refactor tiers A–E**:
  - views split into a package;
  - the world sampler split into `core`/`http`/`analyzers`;
  - a frontend feature-layer registry;
  - `staticfiles/` wired into the static finders;
  - Cesium FPS fixes (60 FPS restored on iGPU and Retina displays).

### December 2025
- 3D Buildings layer (OSM), experience URL sharing with QR codes, Grounding
  DINO remote API, NWS weather stations, HUD toolbar and drone fly/orbit
  modes, and 2D/3D/Columbus switching.

---

## 🗺️ Roadmap

### ✅ Completed
- [x] SAM viewport analysis; Grounding DINO open-vocabulary detection; Grounded-SAM-2
- [x] Remote AI API architecture with graceful degradation
- [x] World Sampler adaptive sampling
- [x] Moon viewer with navigation widgets
- [x] Weather stations; HUD toolbar and panel system
- [x] Experience URL sharing and QR codes; 2D/3D/Columbus switching
- [x] 3D Buildings layer (OpenStreetMap)
- [x] Hierarchical tile catalog with time scrubber and comparison modes
- [x] Django 5.2 LTS, Python 3.10, Ubuntu 22.04 image
- [x] AI pilot (language-driven camera drone) with sourced geology layer

### 🔧 Next
- [ ] AI pilot: a sign-in path for lab members, persistent rate limiting
      (shared cache), and server-side geocoding with a cache if traffic grows
- [ ] AI pilot: run viewport analysis by request ("find boulders here")
- [ ] SQLite → Postgres data cutover
- [ ] `kernelcal` integration: MaxCal World Sampler, Model-Kernel Selector,
      terrain diagnostics endpoint
- [ ] Mission export to MAVLink waypoints
- [ ] Real-time telemetry (MAVLink/ROS) on the globe
- [ ] WebXR/VR globe exploration
- [ ] Mars terrain viewer (HiRISE/CTX)

### 🔮 Longer term
- [ ] CLIP/VLM semantic search over imagery
- [ ] Autonomous survey planning
- [ ] Digital-twin integration and 3D reconstruction
- [ ] OpenTopography point clouds (LAS/LAZ); Google Earth Engine
- [ ] Automated change detection between time periods

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes and push the branch
4. Open a Pull Request

Follow PEP 8, add docstrings, and include tests for new features.

---

## 📝 License

This project is licensed under the MIT License; see [LICENSE](LICENSE).

---

## 🙏 Acknowledgments

DeepGIS‑XR builds on concepts and systems originally developed for the [Oceanographic Decision Support System (ODSS, MBARI)](https://odss.mbari.org/), the [Agricultural Decision Support System (AgDSS, University of Pennsylvania)](https://github.com/Trefo/agdss), the [OpenUAV Project (University of Pennsylvania, Arizona State University)](https://github.com/Open-UAV), and [DeepGIS (Arizona State University)](https://github.com/DREAMS-lab/deepgis). The DeepGIS project acknowledges support from the National Science Foundation, the United States Department of Agriculture, and the National Aeronautics and Space Administration.

### Technology and data
- **CesiumJS**: 3D globe visualization
- **Meta AI**: Segment Anything (SAM, SAM 2)
- **IDEA Research**: Grounding DINO
- **Macrostrat**: geologic map API and tiles (CC BY 4.0)
- **OpenStreetMap contributors**: Nominatim geocoding, buildings, coordinates (ODbL)
- **Arizona Geological Survey**: geology of the Tempe area
- **NASA/GSFC/ASU**: LROC QuickMap lunar imagery
- **National Weather Service**: weather station data

---

## 📧 Contact & Support

- **Repository**: [Earth-Innovation-Hub/deepgis-xr](https://github.com/Earth-Innovation-Hub/deepgis-xr)
- **Issues**: [GitHub Issues](https://github.com/Earth-Innovation-Hub/deepgis-xr/issues)

---

## ⚠️ Disclaimer

This software is provided "as is" without warranty. Use at your own risk. Intended for research and educational purposes. AI analysis results, and AI-pilot geology listings, should be validated independently for critical applications.

---

**Powered by Earth Innovation Hub (Arizona STEAM non-profit corporation)**

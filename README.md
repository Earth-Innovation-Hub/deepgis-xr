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

DeepGIS-XR is a geospatial visualization and analysis platform for Earth, the
Moon and ten other planetary bodies. It combines a CesiumJS 3D globe,
open-vocabulary AI detection and segmentation of the current view, adaptive
spatial sampling, a curated tile catalog, and an AI pilot that flies the camera
and draws sourced data layers from plain-language requests. Every globe shares
the same HUD, camera drone and pilot.

Live viewers: [Earth](https://deepgis.org/label/3d/search/) ·
[Moon](https://deepgis.org/label/3d/moon/) ·
[Mars](https://deepgis.org/label/3d/planet/mars/) and the other bodies at
`/label/3d/planet/<body>/`.

---

## 🌟 Key Features

### 🧑‍✈️ AI Pilot (new, October 2026)
A **Pilot** panel on every globe turns requests into camera-drone flights and
data layers:

- *"orbit around Tempe Town Lake"*
- *"fly to Hayden Library at 200 m, orbit it twice clockwise, then land"*
- *"climb to 1500 m and look at the horizon"*
- *"orbit around Hayden Butte and show geologic features within 5 km"*
- *"show active faults near Bishop"*
- *"trace the Salt River downstream and show live flow"*
- *"orbit all of Tempe and show surface temperature as a jet colormap"*
- *"sea surface temperature of Monterey Bay"*
- *"show the lidar of the Volcanic Tablelands fault scarps"*
- on the Moon: *"orbit Tycho and show elevation as a colormap"*
- on any globe: *"do a visual analysis of the viewport camera scene and list
  what you observe"*

A language model only chooses the actions and the numbers the user gave
(`goto`, `orbit`, `takeoff`, `land`, `look`, `stop`, `wait`, `show_layer`,
`hide_layer`, `describe_view`). Django validates and clamps them, and the page
runs them on the existing drone controls. It never touches a real vehicle.
`describe_view` sends one frame of the 3D view to the lab's vision model,
which returns a summary and a list of what it sees. Off Earth the
pilot resolves IAU feature names from the USGS Gazetteer of Planetary
Nomenclature and flies at orbiter scale. See
[AI Pilot architecture](#-ai-pilot-architecture).

### 🗺️ Data layers
`show_layer {kind, place, radius_m, colormap}` draws a layer around a place,
lists or summarises what is there in the chat, and cites the source. Every
kind runs through the same steps: fetch from a public source, list, draw,
cite, and hide on request. Layers of different kinds stack.

**Features** (Earth):

| kind | Example request | Source | Coverage |
|---|---|---|---|
| `geology` | "geology around Griffith Park, Los Angeles" | [Macrostrat](https://macrostrat.org/) map units and tiles, plus curated Tempe-area sites | Worldwide, most detailed in the US |
| `faults` | "show active faults near Bishop" | USGS Quaternary Fault and Fold Database | US |
| `flood` | "flood risk around Tempe Town Lake" | FEMA National Flood Hazard Layer | US |
| `fires` | "past fire perimeters within 20 km" | NIFC InterAgency Fire Perimeter History | US |
| `river` | "trace the Salt River downstream and show live flow" | USGS NLDI (NHDPlus) and NWIS live discharge | US |
| `landcover` | "land cover within 5 km" | NLCD 2021 (MRLC) | Contiguous US |
| `soils` | "what soils are under this field?" | USDA NRCS SSURGO via Soil Data Access | US |
| `wildlife` | "wildlife observations around Papago Park" | iNaturalist research-grade observations | Worldwide |
| `trails`, `springs`, `mines` | "trails, springs and mines within 3 km" | OpenStreetMap via Overpass | Worldwide |

**Colour maps** (Earth). Drawn with a legend and readouts in the chat
(centre value, typical range, extremes). Name a colour map to change it:
`jet`, `turbo`, `viridis`, `inferno`, `plasma`, `coolwarm` or `rdylgn`
("rainbow" means jet). By default these cover the whole place; layer radii
may reach 200 km.

| kind | Example request | Source | Coverage |
|---|---|---|---|
| `surface_temp` | "surface temperature over Tempe in jet" | USGS Landsat 8/9 Collection 2 Level-2 surface temperature (30 m), newest clear scene, via Microsoft Planetary Computer | Worldwide land |
| `ndvi` | "how green is Phoenix?" | Copernicus Sentinel-2 L2A NDVI (10 m), every tile of the newest clear pass, via Microsoft Planetary Computer | Worldwide land |
| `humidity`, `air_temp` | "what's the humidity around Tucson" | Open-Meteo current conditions on a 7 × 7 grid | Worldwide |
| `sea_temp` | "sea surface temperature of Monterey Bay" | NASA JPL MUR SST v4.1 (1 km, daily) from NOAA CoastWatch ERDDAP | Global ocean |
| `chlorophyll` | "chlorophyll off Santa Cruz" | NOAA gap-filled VIIRS + OLCI chlorophyll-a (2 km) from NOAA CoastWatch ERDDAP | Global ocean |

**Terrain** (Earth):

| kind | Example request | Source | Coverage |
|---|---|---|---|
| `elevation`, `slope`, `contours` | "Mount Whitney elevation in viridis, then slope and contours" | Cesium World Terrain, coloured on the globe (heights above the WGS84 ellipsoid) | Worldwide |
| `topo_datasets` | "what OpenTopography data is near Bishop?" | OpenTopography catalog: survey footprints and links, with surveys stored on DeepGIS marked | Worldwide |
| `lidar_dem` | "show the lidar of the Volcanic Tablelands" | OpenTopography surveys stored on the server (0.5–1 m): shaded relief coloured by height, with relief and slope figures | Bishop, California area (five surveys) |

**Other bodies.** On the Moon, `elevation`, `slope` and `contours` colour the
globe from the LOLA terrain. Mars and Pluto offer `elevation` from their
colour elevation maps. The remaining bodies have no layers yet.

The two ocean layers and `lidar_dem` are fetched through Django
(see [API endpoints](#-api-endpoints)); every other layer is fetched by the
browser from the public source, with no API keys.

The curated geology sites around Phoenix and Tempe (Tempe/Hayden Butte, Papago
and Barnes Buttes, Hole-in-the-Rock, Camelback Mountain, South Mountains,
Superstition Mountains, Tempe Town Lake) have descriptions sourced from
Arizona Geological Survey publications and others, plus OpenStreetMap
coordinates, in `staticfiles/web/geo/tempe-geology.geojson`.

### 🤖 AI Viewport Analysis
Analyze what the camera sees with one of four models:

- **Segment Anything (SAM)**: prompt-free segmentation of every region in the
  view, with GeoJSON export and polygon simplification. Remote service, with
  a local fallback in the web container when the service is unreachable.
- **YOLOv8**: fast detection of the 80 COCO classes, with an optional class
  filter. Runs in the web container (ultralytics).
- **Grounding DINO**: open-vocabulary detection from a text prompt, e.g.
  `"rock . boulder . crater . debris"`. Suited to domain-specific targets
  (geology, archaeology, agriculture). Remote service.
- **Mask R-CNN rocks** (Earth only): rock instance segmentation from the
  Bishop/Jezero checkpoints. Remote service.

Results come back as GeoJSON, drawn on the globe with labels and confidences.
On Earth, the **SceneGraph** button runs several of these (Mask R-CNN rocks,
Grounding DINO, SAM) on the same frame and fuses them with OSM buildings and
roads into one labelled graph.

### 🌍 World Sampler: adaptive geospatial sampling
- Probabilistic location sampling that updates from feedback and rewards
- Survey mode that cycles through samples with automatic navigation
- Spatial queries and statistics; uniform, Gaussian, mixture or custom priors

### 🗂️ Tile Catalog
- Hierarchical `Site → Dataset → Timestep → Product` layer panel
- Time scrubber, swipe and overlay comparison, and a filter to the current viewport
- Edited in the Django admin; drift against tileserver-gl checked by a management command

### 🌙 Moon and planet viewers
- **Moon** (`/label/3d/moon/`): a true Moon-sized globe with LROC QuickMap
  WAC + NAC imagery, LOLA terrain, a NASA Moon Trek mosaic as fallback, and
  the Apollo landing sites
- **Planets and moons** (`/label/3d/planet/<body>/`): Mars, Mercury, Venus,
  Io, Europa, Ganymede, Callisto, Titan, Pluto and Charon, each on its IAU
  ellipsoid with USGS Astrogeology and NASA Trek imagery
  (`staticfiles/web/js/planet-bodies.js`)
- The same HUD, toolbar, instruments, camera drone and AI pilot as Earth

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
- NVIDIA GPU + NVIDIA Container Toolkit (for YOLOv8, SAM's local fallback
  and the admin model-training worker)
- Python 3.10 for local development (matches the Docker image)
- Reachable SAM / Grounding DINO / Mask R-CNN rocks services for AI analysis
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
python manage.py test deepgis_xr.apps.web.tests   # 54 tests: AI pilot, planet viewer, twin access
docker run --rm -v "$PWD":/w -w /w node:22-alpine node --test 'tests/js/*.test.js'   # planet registry
pytest
ruff check .
black --check .
```

In the container, gunicorn runs without `--reload`, and templates are cached
while `DEBUG=False`. After changing Python code or templates, run
`docker restart deepgis-xr-web-1`. After changing `.env`, run
`docker compose up -d --no-deps web` so the new environment is loaded. See
[Static files](#static-files) after changing anything under `staticfiles/`.

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
- Twilio + `django-phonenumber-field` (phone-number authentication; without
  a Twilio client, phone sign-in is refused unless `DEBUG=True`)
- GDAL (in the image) for the stored lidar endpoint: hillshade and slope
- Flask 3.x topology-tile server in `services/topology/`

**Frontend**
- CesiumJS 1.111, hand-written ES modules in `staticfiles/web/js/` (no build step)
- Bootstrap UI, HUD toolbar with floating panels, shared by every globe:
  template partials in `templates/web/hud/` and scripts in
  `staticfiles/web/js/hud/` (panels, shortcuts, drone, pilot, models, share)
- Geocoding: OpenStreetMap Nominatim, falling back to Cesium Ion

**AI / ML** (the web image ships no model weights; they are fetched on first use)
- Segment Anything (Meta AI), remote API, `SAM_API_URL`; falls back to
  `segment_anything` in the web process, on its GPU, when the API is unreachable
- YOLOv8 (Ultralytics), in the web process
- Grounding DINO (IDEA Research), remote API, `GROUNDING_DINO_API_URL`
- Mask R-CNN rocks, remote API, `MASKRCNN_ROCKS_API_URL`
- AI pilot: a language model reached through a read-only MCP server
  (`dreams_mcp_ro` from the DREAMS Lab `dreams_llm_ros2` stack),
  `DEEPGIS_PILOT_MCP_URL`; its `ask_robot_llm` tool plans and its
  `describe_image` tool (a vision-capable model) answers `describe_view`
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
│   │       │                         # models_3d, pilot (AI pilot + relays),
│   │       │                         # twin_access, legacy
│   │       ├── world_sampler.py      # adaptive spatial sampler
│   │       ├── world_sampler_api/    # sampling + AI viewport API
│   │       │   ├── core.py, http.py  # helpers + HTTP endpoints
│   │       │   └── analyzers/        # per-model analyzers (sam, yolov8,
│   │       │                         # grounding_dino, maskrcnn_rocks, ...)
│   │       ├── tests/                # test_pilot, test_planet, test_twin_access
│   │       ├── templates/web/
│   │       │   ├── label_search.html         # Earth viewer
│   │       │   ├── label_moon_viewer.html    # Moon and planet viewer
│   │       │   └── hud/                      # shared HUD partials
│   │       ├── urls.py, admin.py, models.py, middleware/
│   │       └── management/commands/
│   └── settings.py
├── services/topology/                # standalone Flask tile/3D-tiles server
├── staticfiles/web/                  # tracked JS, CSS, vendor libs
│   ├── js/hud/                       # shared HUD, drone and AI pilot (pilot.js: LAYERS)
│   ├── js/planet-bodies.js           # body registry: radii, imagery, terrain
│   └── geo/                          # tempe-geology.geojson, nomenclature/<body>.json
├── scripts/                          # sync_assets.sh, GLB optimizer, API clients,
│                                     # build_planet_nomenclature.py, topo_pull.py
├── tests/js/                         # node:test cases for the planet registry
├── examples/                         # kernelcal demos
├── GroundingDINO/                    # vendored upstream repo
├── static/, media/, data/, deepgis_results/   # runtime assets (gitignored;
│                                     # stored lidar COGs live in data/topo/)
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
  - **Body:** `{"message": "...", "body": "earth", "view": {lat, lon,
    height_agl, heading_deg, target: {lat, lon}}, "history": [{role, content}, ...]}`.
    `body` is `earth` (default), `moon`, or any id in `planet-bodies.js`;
    it selects the prompt, the layer kinds offered and the limits.
  - **Returns:** `{"reply": "...", "actions": [...], "model": "...",
    "duration_sec": ...}`. Unknown action types, kinds and fields are
    dropped, numbers are clamped (on Earth: heights 5 m to 20 km, orbit
    radius 20 m to 20 km, layer radius up to 200 km, speed 1 to 300 m/s; off
    Earth: heights up to 500 km, speed up to 6 km/s), and at most 8 actions
    are returned. Actions come back in schema key order, and assistant turns
    in `history` are re-cleaned on the server.
  - **Errors:** 401 `login_required` (with `login_url`), 400 for an empty or
    invalid message, 429 when rate-limited, 503 if the pilot is not
    configured, and 502 if the model is unavailable.
- `POST /label/api/pilot/describe/`: the `describe_view` action. Same
  sign-in and CSRF rules; 6 requests/min per user.
  - **Body:** `{"image": "data:image/jpeg;base64,...", "body": "mars",
    "view": {..., pitch_deg}, "question": "..."}`. The image is one JPEG or
    PNG frame of the canvas (the page sends a JPEG at most 1280 px wide),
    up to 3 MB encoded.
  - **Returns:** `{"summary": "...", "observations": ["...", ...], "model":
    "...", "duration_sec": ...}`, at most 12 observations. Expect 15 to 25 s.
  - **Errors:** 401, 400 for a missing or non-image `image`, 429, 503, and
    502 as above.
- `GET /label/api/pilot/ocean/?kind=&south=&north=&west=&east=`: relay for
  the `sea_temp` and `chlorophyll` layers, because NOAA ERDDAP sends no CORS
  headers. Signed-in users only; two allow-listed datasets, so it is not an
  open proxy. Boxes are limited to 10° a side and grids to 160 cells a side;
  results are cached for 3 hours, 20 requests/min per user. Returns
  `{time, lat, lon, values, res, dataset}`.
- `GET /label/api/pilot/topo/?lat=&lon=&radius_m=`: the `lidar_dem` layer
  from the OpenTopography surveys stored in `data/topo/`. Signed-in users
  only. Picks the survey that best covers the circle (moving a request just
  off a survey onto its nearest well-covered ground, up to 30 km), and
  returns one PNG packing height, hillshade, slope and coverage, plus relief
  and slope figures. `?list=1` lists the stored surveys and their bounds.
  20 requests/min per user, cached for 24 hours.

### Viewers and access

- `GET /label/3d/search/`: Earth viewer. `GET /label/3d/moon/`: Moon viewer.
  `GET /label/3d/planet/<body>/`: any body in `planet-bodies.js`.
- `GET /label/api/twin-access/`: 204 for a signed-in member of the
  `twin-pilots` group, 401 when signed out, 403 otherwise. Meant for a
  reverse proxy's `auth_request`, so an external digital-twin panel can
  reuse the DeepGIS sign-in.

### AI Analysis API

- `POST /webclient/sampler/analyze-viewport`: analyze the current viewport
  - `model_type`: `'sam'` (default), `'yolov8'`, `'grounding_dino'` or
    `'maskrcnn_rocks'`; anything else returns 400
  - `image`: Base64-encoded viewport image; `location`: camera metadata
  - **SAM:** `sam_model` (`'vit_b'`, `'vit_l'`, `'vit_h'`), `min_area` (pixels)
  - **YOLOv8:** `yolo_model` (`'yolov8n'` to `'yolov8x'`),
    `confidence_threshold`, `class_filter` (comma-separated COCO names)
  - **Grounding DINO:** `text_prompt` (dot-separated, e.g.
    `"rock . boulder . crater"`), `box_threshold` (default 0.3),
    `text_threshold` (default 0.25)
  - **Mask R-CNN rocks:** `model_id` (blank for the service default),
    `score_threshold` (default 0.5), `max_detections` (default 200)
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
Browser: any viewer (Earth, Moon, planets)  ── Pilot panel
  │  POST /label/api/pilot/  {message, body, current view, recent history}
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
     show_layer {kind} · hide_layer {kind?}
       └─ LAYERS[kind].load() fetches from the public source in the browser
          (or through /label/api/pilot/ocean/ and /topo/), then the page
          draws, lists and cites the result
     describe_view
       └─ wait for tiles, capture the canvas as a JPEG,
          POST /label/api/pilot/describe/ ──► MCP describe_image ──► vision model
          returns {summary, observations}, shown in the chat and kept in history
```

Design rules:

- **The model labels; code decides.** The model names the action and the
  values the user stated. The page picks every default: orbit radius from the
  place's size, height of about half the radius, about 75 s per lap, and the
  camera aimed at the centre.
- **Place lookup order:** curated geology sites, then OpenStreetMap Nominatim
  (good for parks, peaks and landmarks), then Cesium Ion. Off Earth: the
  page's preset sites, then the IAU gazetteer for that body
  (`staticfiles/web/geo/nomenclature/<body>.json`, built by
  `scripts/build_planet_nomenclature.py`). Lookups are cached per page.
- **Layer contents cannot be invented.** For `show_layer {kind, place,
  radius_m}` the model picks only the kind, the centre and the radius; the
  prompt tells it never to describe layer contents in its reply. Django
  accepts only the known kinds (`LAYER_KINDS` on Earth, `PLANET_LAYER_KINDS`
  per body). Each kind in `LAYERS` (in `staticfiles/web/js/hud/pilot.js`)
  has a default radius and a `load()` that returns
  features to draw, an optional imagery overlay, the chat lines and the
  source citations. One runner draws, lists, cites and frames them all, so
  adding a kind adds no prompt rules or server checks beyond its name.
  - `geology` lists curated sites in the circle, samples the Macrostrat map
    at 15 points (the most detailed map at each), lists up to 8 units with
    the source map citation, and drapes the map at 55% opacity.
  - `river` uses `distance_km` (default 50) instead of a radius: it traces the
    NHDPlus flowline downstream and shows gauges that reported discharge in
    the last 12 hours.
  - `landcover` and `soils` drape the NLCD and SSURGO maps; the feature
    layers draw fault lines, flood zones, fire perimeters, observations, OSM
    trails, springs and mines that open details and links when clicked.
  - The colour-map kinds report statistics, not lists: Planetary Computer
    renders the Landsat and Sentinel-2 tiles, and the gridded kinds
    (humidity, air and sea temperature, chlorophyll) are coloured in the
    browser. A colour map named in the message applies even if the model
    leaves it out.
  - `elevation`, `slope` and `contours` colour the globe's own terrain
    (Cesium World Terrain on Earth, LOLA on the Moon); `lidar_dem` colours the
    server's relief image by height and darkens it by hillshade.

  Layers of different kinds stack; `hide_layer` without a kind removes all.
  An orbit of the same centre without a radius widens to keep the area in
  view, and Django moves a `show_layer` ahead of an orbit so it is drawn
  first. A source that fails reports its error and the plan continues.
- **Plans are cancellable.** A new request or the Stop button interrupts the
  current plan. A `stop` action inside a plan halts motion and
  lets the remaining steps (such as `hide_layer`) run.
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
│   └─ analyzers/  (model_type not in VIEWPORT_MODEL_TYPES → 400)      │
│        sam · grounding_dino · maskrcnn_rocks → remote services       │
│        yolov8 (and SAM's fallback)           → web container GPU     │
│                                                                      │
│   On AI-down (not_configured · connection_error · timeout):          │
│      → HTTP 200 + {status:"success", degraded:true, detections:[]}   │
│        Retry-After: 30s (60s on timeout)                             │
└────────────────────────────┬─────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│     Remote AI host (Flask + CUDA)                                    │
│       :5000  Grounding DINO      (GROUNDING_DINO_API_URL)            │
│       :5002  Mask R-CNN rocks    (MASKRCNN_ROCKS_API_URL)            │
│       :5010  SAM                 (SAM_API_URL)                       │
└──────────────────────────────────────────────────────────────────────┘
```

**Grounding DINO** (port 5000): text-based detection  
![detection_visualization](https://github.com/user-attachments/assets/533490e9-bafd-40a4-bf2f-0204186387b3)

```bash
# Grounding DINO: detection only
curl -X POST http://<ai-host>:5000/api/predict \
    -F "file=@image.jpg" -F "text_prompt=rock . boulder . crater"

# Mask R-CNN rocks: list the available checkpoints
curl http://<ai-host>:5002/api/models

# Python client
python scripts/grounding_dino_api_client.py --image viewport.jpg --prompt "rock . boulder"
```

**Example prompts:** Geology `"rock . boulder . crater"` · Urban
`"building . car . tree"` · Wildlife `"animal . bird . nest"`

---

## 🎯 Usage

### AI Pilot
1. Open any viewer (Earth `/label/3d/search/`, Moon `/label/3d/moon/`, or
   `/label/3d/planet/<body>/`) and sign in (`/label/admin/login/`).
2. Click **Pilot** in the HUD toolbar and type a request. The page switches
   to 3D, runs the plan and logs each step in the panel.
3. For a data layer, ask for the kind and place ("flood risk around Tempe
   Town Lake") or say "here" for the point in view. Add a colour map by name
   for colour layers ("in viridis"). Click a drawn feature for details and
   source links. "Hide the faults" removes one layer; "clear all layers"
   removes them all. OpenStreetMap layers can take up to a minute.
4. Ask what is in view ("do a visual analysis of the viewport camera scene
   and list what you observe", or "fly to Olympus Mons and describe what you
   see"). The pilot captures the current frame and lists what the vision
   model sees. Treat the list as a model's reading of the picture, not a
   measurement.
5. Press **Stop** at any time.

### AI Viewport Analysis
1. Open DeepGIS Search and the **AI** panel.
2. Choose **SAM**, **YOLOv8**, **Grounding DINO** or (on Earth)
   **MaskRCNN Rocks**.
3. Set the model size and minimum area (SAM), the model size, confidence and
   class filter (YOLOv8), the text prompt and thresholds (Grounding DINO), or
   the checkpoint, score threshold and detection limit (Mask R-CNN rocks).
4. Click **Analyze Viewport**. Results are drawn as labelled polygons.

### World Sampler
Initialize a sampler, draw samples, step through them in survey mode, update
the distribution from feedback, and query regions.

### Moon and Planet Viewers
Open `/label/3d/moon/` for LROC imagery, LOLA terrain and the Apollo sites, or
`/label/3d/planet/<body>/` (`mars`, `mercury`, `venus`, `io`, `europa`,
`ganymede`, `callisto`, `titan`, `pluto`, `charon`). The HUD, drone widgets,
keyboard shortcuts and AI pilot work as on Earth; ask the pilot to fly to an
IAU-named feature ("fly to Olympus Mons").

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
SAM_API_URL=http://<ai-host>:5010
GROUNDING_DINO_API_URL=http://<ai-host>:5000
MASKRCNN_ROCKS_API_URL=http://<ai-host>:5002

# Host GPU index for the web container (YOLOv8 and SAM's local fallback).
# Use a GPU that is not driving a display or simulator.
DEEPGIS_WEB_GPU=0

# AI pilot (optional; the panel shows "not configured" without a token)
DEEPGIS_PILOT_MCP_URL=http://<mcp-host>:8766/mcp
DEEPGIS_PILOT_MCP_TOKEN=         # the READ-ONLY server's token, never a command-enabled one
# DEEPGIS_PILOT_TIMEOUT_SEC=90
# DEEPGIS_PILOT_RATE_PER_MIN=12
```

### Static Files

- Django serves `/label/static/deepgis/` (and `MEDIA_URL`) from `STATIC_ROOT`
  (`./static/`, gitignored) through `django.views.static.serve`, whatever
  `DEBUG` is, so the app runs with `DEBUG=False` without a separate file
  server. Responses carry `Cache-Control: no-cache`, so browsers revalidate
  and unchanged files come back as 304; this keeps stale and fresh ES modules
  from mixing. An Nginx alias or whitenoise in front would be faster.
- The tracked source is `staticfiles/`. After adding or changing a file
  there, copy it into `STATIC_ROOT` with `python manage.py collectstatic`, or
  copy the single file.
- The viewers load `hud/pilot.js?v=…` with a version tag hard-coded in
  `label_search.html` and `label_moon_viewer.html`. Bump it with every
  `pilot.js` change.
- Avoid directories named `data/` for tracked assets, because `.gitignore`
  excludes them. That is why the geology file lives in `staticfiles/web/geo/`.

### Docker Services

**Default (`docker compose up -d`):**

| Service          | Image                       | Role |
|------------------|-----------------------------|------|
| `web`            | built locally (`Dockerfile`)| Django + DRF behind gunicorn; runs `migrate --noinput` on boot; host port 8060; GPU `DEEPGIS_WEB_GPU` |
| `redis`          | `redis:7-alpine`            | Celery broker + result backend (healthchecked) |
| `celery_worker`  | reuses the `web` image      | Single replica for the admin training task (GPU) |
| `tileserver`     | `maptiler/tileserver-gl`    | Serves MBTiles raster + vector tiles; host port 8091 |

**Optional:** `db` (`postgres:16-alpine`, profile `postgres`). Runbook:
`docs/migration-sqlite-to-postgres.md`.

The `command:` entries for `web` and `celery_worker` are single-line JSON
arrays on purpose. Multi-line YAML scalars silently dropped the gunicorn flags.

---

## 📊 Recent Updates

### October 2026: planets, colour maps and terrain
- **Visual analysis of the view** (`4186fdf`): the pilot's `describe_view`
  action captures the 3D view and asks the lab's vision model, through the
  read-only MCP server's `describe_image` tool, to summarise it and list what
  it sees. Works on Earth, the Moon and every planet viewer.
- **AI panel trimmed** (`4253571`): the AI Viewport Analysis panel offers
  SAM, YOLOv8, Grounding DINO and Mask R-CNN rocks only, and
  `analyze-viewport` rejects other model types. The web container's GPU is
  now set by `DEEPGIS_WEB_GPU`, so SAM's resident fallback model can sit on
  a GPU that isn't rendering.
- **Moon viewer rebuilt** (`c99e2c2`, `66d1fab`): a real Moon-sized globe
  (the old one was Earth-sized with the camera inside it), correctly tiled
  LROC QuickMap imagery, LOLA terrain, and a working fly/orbit drone.
- **Planet viewer** (`6964045`): `/label/3d/planet/<body>/` for ten more
  bodies from one registry (`planet-bodies.js`) with IAU radii, USGS
  Astrogeology and NASA Trek imagery.
- **One HUD everywhere** (`8937bf4`, `a8924e0`, `bcd9962`): Earth's toolbar,
  panels, instruments, shortcuts, camera drone and AI pilot became shared
  partials and modules, so every globe has the same UI. Off Earth the pilot
  uses the IAU gazetteer and orbiter-scale limits.
- **Terrain layers on the Moon, Mars and Pluto** (`6c6b669`).
- **Running with `DEBUG=False`** (`91b40b5`, `6f47702`): static files served
  explicitly with `no-cache`; phone sign-in no longer creates and signs in
  an account for any number when Twilio is not configured.
- **Twin access check** (`1e2f2a5`): `/label/api/twin-access/` for a reverse
  proxy's `auth_request`.
- **Sharper 2D view on HiDPI displays** (`127cd29`) and the Search viewer's
  vestigial sidebar removed (`9024b17`).
- **Colour-map layers** (`6da7dcb`, `63c8820`): Landsat surface temperature,
  Sentinel-2 NDVI, humidity, air temperature, sea surface temperature and
  chlorophyll, with selectable colour maps and the ERDDAP relay. Fixed plans
  coming back empty for follow-up layer requests (key order in history).
- **Terrain and lidar** (`bedde97`): Earth elevation, slope and contours, the
  OpenTopography catalog, and five Bishop-area OpenTopography surveys stored
  on the server (`scripts/topo_pull.py`) behind `/label/api/pilot/topo/`.

### Mid-October 2026: AI pilot and geology
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
- **Data layers**: `show_geology` / `hide_geology` became one
  `show_layer {kind, place, radius_m}` / `hide_layer {kind?}` pair with ten more
  kinds: faults, flood, fires, river (with live USGS flow), landcover, soils,
  wildlife, trails, springs and mines. The action schema now puts `kind`
  before `place`. Under constrained decoding, the model had otherwise
  skipped the place.

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
- [x] Viewport analysis: SAM, YOLOv8, Grounding DINO, Mask R-CNN rocks
- [x] Remote AI API architecture with graceful degradation
- [x] World Sampler adaptive sampling
- [x] Moon viewer with navigation widgets
- [x] Weather stations; HUD toolbar and panel system
- [x] Experience URL sharing and QR codes; 2D/3D/Columbus switching
- [x] 3D Buildings layer (OpenStreetMap)
- [x] Hierarchical tile catalog with time scrubber and comparison modes
- [x] Django 5.2 LTS, Python 3.10, Ubuntu 22.04 image
- [x] AI pilot (language-driven camera drone) with sourced data layers
      (geology, faults, flood zones, fires, rivers, land cover, soils,
      wildlife, trails, springs, mines)
- [x] AI pilot colour-map layers (surface temperature, NDVI, humidity, air
      and sea temperature, chlorophyll) and terrain (elevation, slope,
      contours, OpenTopography catalog, stored lidar)
- [x] Moon and planet viewers (ten more bodies) sharing Earth's HUD, drone
      and AI pilot
- [x] AI pilot visual analysis of the view (`describe_view`)

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
- [ ] Mars high-resolution imagery and terrain (HiRISE/CTX) in the planet viewer
- [ ] Data layers for the remaining bodies

### 🔮 Longer term
- [ ] CLIP/VLM semantic search over imagery
- [ ] Autonomous survey planning
- [ ] Digital-twin integration and 3D reconstruction
- [ ] OpenTopography point clouds (LAS/LAZ) and on-demand DEM pulls beyond
      the stored surveys; Google Earth Engine
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
- **OpenStreetMap contributors**: Nominatim geocoding, buildings, trails,
  springs, mines and coordinates, via Overpass (ODbL)
- **Arizona Geological Survey**: geology of the Tempe area
- **USGS**: Quaternary Fault and Fold Database, NLDI/NHDPlus, NWIS water data
- **FEMA**: National Flood Hazard Layer; **NIFC**: fire perimeter history
- **MRLC**: National Land Cover Database; **USDA NRCS**: SSURGO soils
- **iNaturalist** observers: wildlife observations (each under its own license)
- **NASA/GSFC/ASU**: LROC QuickMap lunar imagery and LOLA terrain;
  **NASA Trek**: Moon and planetary mosaics
- **USGS Astrogeology**: planetary basemaps and the Gazetteer of Planetary
  Nomenclature (IAU)
- **USGS / NASA**: Landsat 8/9 Collection 2 surface temperature;
  **ESA Copernicus**: Sentinel-2; both via **Microsoft Planetary Computer**
- **Open-Meteo**: current weather conditions (CC BY 4.0)
- **NASA JPL** MUR sea surface temperature and **NOAA** chlorophyll-a, via
  **NOAA CoastWatch** ERDDAP
- **OpenTopography**: dataset catalog and lidar/SfM surveys (each cited by
  its DOI in the chat)
- **Cesium**: Cesium World Terrain
- **National Weather Service**: weather station data

---

## 📧 Contact & Support

- **Repository**: [Earth-Innovation-Hub/deepgis-xr](https://github.com/Earth-Innovation-Hub/deepgis-xr)
- **Issues**: [GitHub Issues](https://github.com/Earth-Innovation-Hub/deepgis-xr/issues)

---

## ⚠️ Disclaimer

This software is provided "as is" without warranty. Use at your own risk. Intended for research and educational purposes. AI analysis results and AI-pilot layer listings should be validated independently for critical applications; flood zones in particular are not an official FEMA determination.

---

**Powered by Earth Innovation Hub (Arizona STEAM non-profit corporation)**

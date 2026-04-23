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
   docker-compose up -d
   ```

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
- PostgreSQL (via `psycopg2-binary`) / SQLite (dev)
- Celery 5.6 + Redis (async tasks, world-sampler background jobs)
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
- Segment Anything Model (SAM) — Meta AI, local inference
- Grounding DINO — IDEA Research, remote API (port 5000)
- Grounded-SAM-2 — remote API (port 5001)
- YOLOv8 — Ultralytics, local inference
- Mask R-CNN / Mask2Former — Detectron2, local inference
- PyTorch 2.5.1 + CUDA 12.1 (deep learning framework)
- `kernelcal` — Kernel Dynamics / MaxCal integration (integration in progress)

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
`notes/2026-04-22-deepgis-xr-refactoring.md`. Tiers A–C and the Tier-D0 /
Tier-D0.5 prep steps have landed; the full Tier D layer-manager work plus
Tiers E–F are scheduled on the roadmap below.

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
    - `model_type`: `'sam'`, `'yolov8'`, `'grounding_dino'`, `'zero_shot'`, or `'mask2former'`
    - `image`: Base64-encoded viewport image
    - `location`: Camera position metadata
    - **SAM options:**
      - `sam_model`: `'vit_b'`, `'vit_l'`, or `'vit_h'`
      - `min_area`: Minimum segment area in pixels
    - **YOLOv8 options:**
      - `yolo_model`: `'yolov8n'`, `'yolov8s'`, `'yolov8m'`, `'yolov8l'`, `'yolov8x'`
      - `confidence_threshold`: 0.0-1.0
      - `class_filter`: Comma-separated class names (e.g., `"person,car,truck"`)
    - **Grounding DINO options:**
      - `text_prompt`: Dot-separated object descriptions (e.g., `"rock . boulder . crater"`)
      - `box_threshold`: Detection confidence threshold (default: 0.3)
      - `text_threshold`: Text matching threshold (default: 0.25)
    - **Zero-Shot/Mask2Former options:**
      - `confidence_threshold`: 0.0-1.0
  - **Returns:** GeoJSON with segments/detections, metadata, saved file paths

### Labeling API

- `POST /label/semi-supervised/api/generate-labels/` - Generate assisted labels
- `POST /label/semi-supervised/api/save-labels/` - Save labels
- `GET /label/semi-supervised/api/get-images/` - Get label images

---

## 🧠 AI Viewport Analysis Architecture

The AI Viewport Analysis system supports multiple detection models, including remote API deployment for GPU-intensive models like Grounding DINO.

### System Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DeepGIS-XR Frontend                         │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  AI Viewport Analysis Panel                                   │  │
│  │  ┌────────────────────────────────────────────────────────┐  │  │
│  │  │ Analysis Type: [Grounding DINO (Open Vocab) ▼]         │  │  │
│  │  │ Text Prompt:   [rock . boulder . crater . debris    ]  │  │  │
│  │  │ Box Threshold: [═══════●═══] 0.30                      │  │  │
│  │  │ Text Threshold:[══════●════] 0.25                      │  │  │
│  │  │ [  🧠 Analyze Viewport  ]                              │  │  │
│  │  └────────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ POST /webclient/sampler/analyze-viewport
                               │ {image, location, model_type, text_prompt, ...}
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    DeepGIS-XR Django Backend                        │
│  world_sampler_api.py::analyze_viewport()                          │
│     ├── model_type == 'sam'           → Local SAM inference        │
│     ├── model_type == 'yolov8'        → Local YOLOv8 inference     │
│     ├── model_type == 'grounding_dino'→ Remote API call ──────┐    │
│     ├── model_type == 'zero_shot'     → Local Mask R-CNN      │    │
│     └── model_type == 'mask2former'   → Local Mask2Former     │    │
└──────────────────────────────┬────────────────────────────────│────┘
                               │                                │
                               ▼                                ▼
┌──────────────────────────────────────┐  ┌───────────────────────────┐
│     Local GPU/CPU Processing         │  │  Remote Grounding DINO    │
│  ┌────────────────────────────────┐  │  │  API Server               │
│  │ • SAM (vit_b, vit_l, vit_h)   │  │  │  ┌─────────────────────┐  │
│  │ • YOLOv8 (n, s, m, l, x)      │  │  │  │ POST /predict       │  │
│  │ • Mask R-CNN (COCO)           │  │  │  │ POST /predict_batch │  │
│  │ • Mask2Former (COCO)          │  │  │  │ GET  /health        │  │
│  └────────────────────────────────┘  │  │  └─────────────────────┘  │
└──────────────────────────────────────┘  └───────────────────────────┘
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

```bash
DEBUG=True
DJANGO_SETTINGS_MODULE=deepgis_xr.settings
NVIDIA_VISIBLE_DEVICES=all  # For GPU support

# Remote AI Services (optional - defaults in docker-compose.yml)
# GROUNDING_DINO_API_URL=http://192.168.0.232:5000
```

### Docker Configuration

The `docker-compose.yml` includes:
- **Web service**: Django application with GPU support
- **Tile server**: MapTiler TileServer GL for tile serving
- **Volume mounts**: 
  - `dreams_laboratory/scripts` - ML model scripts
  - `deepgis_results` - AI analysis results (shared with host)

### GPU Support

To enable GPU for AI features:
1. Install NVIDIA Docker runtime
2. Uncomment GPU configuration in `docker-compose.yml`
3. Ensure `NVIDIA_VISIBLE_DEVICES=all` is set

---

## 📊 Recent Updates

### April 2026 — Refactor tiers A–C landed, Tier D in progress

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
- **Tier D0** — frontend static-tree consolidation: collapsed the duplicate
  `deepgis_xr/apps/web/static/web/` tree; `staticfiles/` is now the single
  canonical frontend root. Orphaned assets parked in `staticfiles/web/legacy/`.
- **Tier D0.5** — Cesium FPS tuning (in flight on
  `refactor/tier-d0.5-fps-tuning`): four FPS sinks identified and removed;
  60 FPS restored on iGPU / Retina.

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
- [x] **Tier D0** — collapse the duplicate frontend static tree; `staticfiles/`
      is canonical, orphaned assets parked in `staticfiles/web/legacy/`
- [~] **Tier D0.5** — Cesium perf pass (in progress on
      `refactor/tier-d0.5-fps-tuning`; 60 FPS restored on iGPU/Retina)
- [ ] **Tier D** — real frontend layer manager; fix OSM-Buildings duplication;
      lift 3D-buildings and canopy-height layers to all 3D pages
- [ ] **Tier E** — Django 3.2 → 4.2 LTS → 5.x; DRF 3.12 → 3.15; Shapely 2.x
- [ ] **Tier F** — `kernelcal` integration: MaxCal World Sampler, Model-Kernel
      Selector, terrain diagnostics endpoint

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


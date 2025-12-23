# DeepGIS-XR

<a href="https://www.youtube.com/watch?v=Plk7JyJsY7Y" target="_blank" rel="noopener noreferrer">
  <img src="https://img.youtube.com/vi/Plk7JyJsY7Y/0.jpg" alt="DeepGIS-XR Demo Video" style="width:560px;height:315px;">
</a>

<img width="2558" height="1433" alt="image" src="https://github.com/user-attachments/assets/6ef67028-e9dd-4a6e-96f1-c0f74da05d37" />
<img width="2556" height="1435" alt="image" src="https://github.com/user-attachments/assets/c06ab8f8-54c3-453f-b112-72a77e8453fa" />
<img width="2560" height="1440" alt="image" src="https://github.com/user-attachments/assets/f5826ed4-589b-4dc2-92bb-5ec85c66a179" />

**Advanced Geospatial Visualization Platform with AI-Powered Analysis**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/django-4.0+-green.svg)](https://www.djangoproject.com/)
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
- **Multi-Layer Support**: Raster and vector layer management
- **Tile Server Integration**: Custom tile server for large datasets
- **3D Model Support**: GLB/GLTF model loading and visualization
- **Coordinate Systems**: Support for multiple projections and ellipsoids
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
- Python 3.8+ (for local development)

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

### Local Development Setup

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run migrations**
   ```bash
   python manage.py migrate
   ```

3. **Start development server**
   ```bash
   python manage.py runserver
   ```

---

## 🏗️ Architecture

### Technology Stack

**Backend:**
- Django 4.0+ (Python web framework)
- Django REST Framework (API endpoints)
- PostgreSQL/SQLite (database)
- Celery (async tasks, optional)

**Frontend:**
- CesiumJS (3D globe visualization)
- JavaScript ES6+ (modern frontend)
- Bootstrap (UI components)

**AI/ML:**
- Segment Anything Model (SAM) - Meta AI
- Grounding DINO - Open-vocabulary detection (IDEA Research)
- YOLOv8 - Real-time object detection (Ultralytics)
- Zero-Shot Detection (Mask R-CNN) - COCO pre-trained
- Mask2Former - Instance segmentation
- PyTorch (deep learning framework)

**Infrastructure:**
- Docker & Docker Compose (containerization)
- Nginx (reverse proxy, optional)
- TileServer GL (tile serving)

### Project Structure

```
deepgis-xr/
├── deepgis_xr/              # Django project
│   ├── apps/
│   │   ├── web/             # Web application
│   │   │   ├── world_sampler_api.py  # Sampling & AI APIs
│   │   │   └── views.py     # View handlers
│   │   ├── core/            # Core models
│   │   └── ml/              # ML models
│   └── settings.py          # Django settings
├── staticfiles/             # Static assets
│   └── web/
│       └── js/
│           ├── main.js              # Main application entry
│           ├── world-sampler-ui.js  # World sampler UI logic
│           ├── widgets/
│           │   └── weather-stations.js  # Weather stations widget
│           └── utils/
│               └── nws-weather-stations.js  # NWS API integration
├── docker-compose.yml       # Docker configuration
├── requirements.txt        # Python dependencies
└── README.md              # This file
```

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

### Grounding DINO Remote API Integration

Grounding DINO can be deployed as a separate Docker container for GPU-accelerated inference. This allows running the model on a dedicated GPU server while keeping DeepGIS-XR lightweight.

**Remote API Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/predict` | POST | Single image inference |
| `/predict_batch` | POST | Batch inference with multiple prompts |

**Request format for `/predict`:**

```bash
curl -X POST "http://${GROUNDING_DINO_HOST}:8000/predict" \
    -F "image=@viewport.png" \
    -F "text_prompt=rock . boulder . crater . debris" \
    -F "box_threshold=0.3" \
    -F "text_threshold=0.25" \
    -F "return_annotated_image=true"
```

**Configuration:**

Set the remote API URL in environment variables:
```bash
GROUNDING_DINO_API_URL=http://your-gpu-server:8000
```

### Use Cases for Grounding DINO

| Domain | Text Prompt Example |
|--------|-------------------|
| Lunar/Mars Geology | `"rock . boulder . crater . regolith . debris"` |
| Urban Mapping | `"building . road . car . tree . pedestrian"` |
| Agricultural Analysis | `"crop . field . irrigation . tree . structure"` |
| Disaster Assessment | `"damage . debris . collapsed building . vehicle"` |
| Archaeological Survey | `"structure . artifact . excavation . mound"` |
| Wildlife Monitoring | `"animal . bird . nest . den . tracks"` |

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

---

## 🔧 Configuration

### Environment Variables

```bash
DEBUG=True
DJANGO_SETTINGS_MODULE=deepgis_xr.settings
NVIDIA_VISIBLE_DEVICES=all  # For GPU support

# Remote AI Services (optional)
GROUNDING_DINO_API_URL=http://your-gpu-server:8000  # Remote Grounding DINO API
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

## 📊 Recent Updates (December 2025)

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

### 💡 Community Requested
- [ ] Integration with Google Earth Engine
- [ ] Integration with OpenTopography and support for point cloud visualization (LAS/LAZ)
- [ ] 3D building/structure modeling from imagery
- [ ] Automated change detection between time periods

---

## ⚠️ Disclaimer

This software is provided "as is" without warranty. Use at your own risk. Intended for research and educational purposes. AI analysis results should be validated independently for critical applications.

---

**Powered by Earth Innovation Hub (Arizona STEAM non-profit corporation)**


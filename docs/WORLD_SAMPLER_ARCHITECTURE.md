# World Sampler Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DEEPGIS SEARCH FRONTEND                         │
│                      (Cesium.js 3D Globe Viewer)                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP/REST API
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      DJANGO REST API LAYER                              │
│                   (world_sampler_api.py)                                │
│                                                                          │
│  • /webclient/sampler/initialize  - Initialize sampler                  │
│  • /webclient/sampler/sample      - Get sample locations                │
│  • /webclient/sampler/update      - Submit feedback/scores              │
│  • /webclient/sampler/statistics  - Get statistics                      │
│  • /webclient/sampler/scored      - Get scored locations                │
│  • /webclient/sampler/query       - Query by region                     │
│  • /webclient/sampler/reset       - Reset sampler                       │
└─────────────────────────────────────────────────────────────────────────┘
                    │                               │
                    │                               │
                    ▼                               ▼
    ┌───────────────────────────┐   ┌─────────────────────────────┐
    │   In-Memory Sampler       │   │   PostgreSQL Database       │
    │   (world_sampler.py)      │   │   (Django ORM Models)       │
    │                           │   │                             │
    │  • WorldSampler class     │   │  • SampledLocation          │
    │  • Probabilistic sampling │   │  • SamplingSession          │
    │  • Distribution updates   │   │  • DistributionUpdate       │
    │  • Spatial indexing       │   │                             │
    └───────────────────────────┘   └─────────────────────────────┘
                    │                               │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │      Django Admin Interface   │
                    │      View/Manage Data         │
                    └───────────────────────────────┘
```

## Database Schema (ERD)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SamplingSession                             │
├─────────────────────────────────────────────────────────────────────┤
│ PK  session_id (VARCHAR, UNIQUE)                                    │
│ FK  user_id (nullable) → AUTH_USER_MODEL                            │
│                                                                      │
│     num_points (INTEGER)                                            │
│     initialization_method (VARCHAR)                                 │
│       • uniform                                                     │
│       • gaussian_mixture                                            │
│       • population_weighted                                         │
│                                                                      │
│     lat_range_min, lat_range_max (FLOAT)                           │
│     lon_range_min, lon_range_max (FLOAT)                           │
│     alt_range_min, alt_range_max (FLOAT)                           │
│                                                                      │
│     total_samples (INTEGER)                                         │
│     total_updates (INTEGER)                                         │
│                                                                      │
│     created_at (DATETIME)                                           │
│     updated_at (DATETIME)                                           │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                │ 1:N
                                │
                    ┌───────────┴───────────┐
                    │                       │
                    ▼                       ▼
┌─────────────────────────────────────┐   ┌──────────────────────────────┐
│      SampledLocation               │   │   DistributionUpdate         │
├────────────────────────────────────┤   ├──────────────────────────────┤
│ PK  id (INTEGER, AUTO)             │   │ PK  id (INTEGER, AUTO)       │
│ FK  user_id (nullable) →           │   │ FK  session_id →             │
│     AUTH_USER_MODEL                │   │     SamplingSession          │
│     session_id (VARCHAR)           │   │                              │
│                                    │   │     update_rule (VARCHAR)    │
│ ┌────────────────────────────────┐│   │       • reward               │
│ │ LOCATION DATA                  ││   │       • exploration          │
│ │  latitude (FLOAT)              ││   │       • concentration        │
│ │  longitude (FLOAT)             ││   │       • custom               │
│ │  altitude (FLOAT)              ││   │                              │
│ │  zoom_level (INTEGER 0-28)     ││   │     learning_rate (FLOAT)    │
│ └────────────────────────────────┘│   │     radius (FLOAT, nullable) │
│                                    │   │     parameters (JSONFIELD)   │
│ ┌────────────────────────────────┐│   │                              │
│ │ SCORING DATA                   ││   │     applied_at (DATETIME)    │
│ │  score (FLOAT)                 ││   └──────────────────────────────┘
│ │  weight (FLOAT)                ││                 │
│ └────────────────────────────────┘│                 │ M:N
│                                    │                 │
│     sampled_at (DATETIME)          │◄────────────────┘
│     scored_at (DATETIME, nullable) │     feedback_locations
│     metadata (JSONFIELD)           │
│                                    │
│ INDEXES:                           │
│   • (latitude, longitude)          │
│   • (session_id, sampled_at)       │
│   • (score)                        │
│   • (-sampled_at)                  │
└────────────────────────────────────┘
```

## Data Flow Architecture

### 1. Initialization Flow
```
┌──────────┐    Initialize     ┌──────────┐    Create Session    ┌──────────┐
│          │  ────────────────► │          │  ──────────────────► │          │
│ Frontend │                    │ API      │                      │ Database │
│          │  ◄──────────────── │          │  ◄────────────────── │          │
└──────────┘    Stats           └──────────┘    Session Created   └──────────┘
                                      │
                                      ▼
                              ┌────────────────┐
                              │ WorldSampler   │
                              │ In-Memory      │
                              │ • 1000 points  │
                              │ • Gaussian Mix │
                              └────────────────┘
```

### 2. Sampling Flow
```
┌──────────┐   Request N       ┌──────────┐   Query Sampler     ┌────────────┐
│          │   Samples         │          │   (Probabilistic    │            │
│ Frontend │  ──────────────►  │ API      │   Weighted)         │ WorldSampler│
│          │                   │          │  ─────────────────► │            │
│  Cesium  │                   └──────────┘                     └────────────┘
│  Viewer  │                        │                                  │
│          │                        │ Save to DB                       │
│          │                        ▼                                  │
│          │                   ┌──────────┐                           │
│          │                   │ Database │                           │
│          │                   │          │                           │
│          │                   │ For Each Sample:                     │
│          │                   │ • lat, lon, alt                      │
│          │  ◄──────────────  │ • zoom_level (calculated)            │
│          │   GeoJSON +       │ • weight                             │
│          │   Samples         │ • sampled_at timestamp               │
└──────────┘                   │ • db_id                              │
                               └──────────┘
```

### 3. Scoring/Feedback Flow
```
┌──────────┐                   ┌──────────┐                   ┌──────────┐
│ User     │  Click Sample     │ Frontend │                   │          │
│ Interacts│  ──────────────►  │          │                   │          │
│ with     │                   │ • Select point              │          │
│ Globe    │                   │ • Get camera zoom            │          │
│          │                   │ • Adjust reward slider       │          │
│          │                   │                              │          │
│          │  Submit Feedback  │                              │   API    │
│          │  ──────────────►  │  ──────────────────────────► │          │
│          │                   │  POST /sampler/update        │          │
│          │                   │  {                           │          │
│          │                   │    lat, lon, alt,            │          │
│          │                   │    reward: -1.0 to 1.0,      │          │
│          │                   │    zoom: 20,                 │          │
│          │                   │    weight: 0.001             │          │
│          │                   │  }                           │          │
└──────────┘                   └──────────┘                   └──────────┘
                                                                     │
                                              ┌─────────────────────┼──────────────────────┐
                                              ▼                     ▼                      ▼
                                    ┌──────────────────┐  ┌────────────────┐  ┌──────────────────┐
                                    │ Update/Create    │  │ Create         │  │ Update WorldSampler│
                                    │ SampledLocation  │  │ Distribution   │  │ Weights           │
                                    │                  │  │ Update Record  │  │ (In-Memory)       │
                                    │ • score = reward │  │                │  │                   │
                                    │ • scored_at = now│  │ • rule: reward │  │ • Apply learning  │
                                    │ • zoom_level     │  │ • learning_rate│  │ • Update probs    │
                                    └──────────────────┘  └────────────────┘  └──────────────────┘
```

## Component Architecture

### Frontend Components (world-sampler-ui.js)

```
┌─────────────────────────────────────────────────────────────────────┐
│                      WorldSamplerUI Class                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Core Properties                                              │  │
│  │  • viewer (Cesium.Viewer)                                    │  │
│  │  • currentSamples (Array<Sample>)                            │  │
│  │  • selectedSample (Cesium.Entity)                            │  │
│  │  • sampleDataSource (Cesium.CustomDataSource)                │  │
│  │  • currentSampleIndex (for survey mode)                      │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ UI Sections                                                  │  │
│  │                                                              │  │
│  │  1. Initialize Section                                       │  │
│  │     • Distribution type selector                             │  │
│  │     • Number of points input                                 │  │
│  │     • Initialize button                                      │  │
│  │                                                              │  │
│  │  2. Sample Section                                           │  │
│  │     • Number of samples input                                │  │
│  │     • Sampling method (Weighted/Top-K)                       │  │
│  │     • Sample button                                          │  │
│  │                                                              │  │
│  │  3. Survey Section                                           │  │
│  │     • Point N of M counter                                   │  │
│  │     • Previous/Next buttons                                  │  │
│  │     • Auto-survey slider & start button                      │  │
│  │                                                              │  │
│  │  4. Feedback Section                                         │  │
│  │     • Reward slider (-1.0 to 1.0)                           │  │
│  │     • Learning rate slider                                   │  │
│  │     • Submit feedback button                                 │  │
│  │                                                              │  │
│  │  5. Update Strategy Section                                  │  │
│  │     • Explore button                                         │  │
│  │     • Concentrate button                                     │  │
│  │                                                              │  │
│  │  6. Statistics Section                                       │  │
│  │     • Samples shown / Total sampled                          │  │
│  │     • Updates count / Entropy                                │  │
│  │                                                              │  │
│  │  7. Actions Section                                          │  │
│  │     • Clear samples button                                   │  │
│  │     • Reset sampler button                                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Key Methods                                                  │  │
│  │                                                              │  │
│  │  • initializeSampler()       - Initialize distribution       │  │
│  │  • sampleLocations()         - Request new samples           │  │
│  │  • visualizeSamples(geojson) - Render points on globe        │  │
│  │  • onSampleClick(entity)     - Handle point selection        │  │
│  │  • submitFeedback()          - Submit score to API           │  │
│  │  • getCameraZoomLevel()      - Calculate zoom from altitude  │  │
│  │  • flyToSample(index)        - Navigate to sample point      │  │
│  │  • toggleAutoSurvey()        - Start/stop auto-cycling       │  │
│  │  • navigatePrevious()        - Go to previous sample         │  │
│  │  • navigateNext()            - Go to next sample             │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### Backend Components

```
┌─────────────────────────────────────────────────────────────────────┐
│                      WorldSampler Class                             │
│                    (world_sampler.py)                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Properties:                                                         │
│    • samples: List[SamplePoint]  - All sample points               │
│    • spatial_index: KDTree       - For efficient spatial queries   │
│    • sample_history              - History of sampled points        │
│    • update_history              - History of distribution updates  │
│                                                                      │
│  Initialization Methods:                                             │
│    • _initialize_uniform()        - Uniform random distribution     │
│    • _initialize_gaussian_mixture() - GMM over interesting regions  │
│    • _initialize_population_weighted() - Based on population data   │
│                                                                      │
│  Sampling Methods:                                                   │
│    • sample(n, method='weighted') - Draw n samples                  │
│      - weighted: Probabilistic sampling                             │
│      - top_k: Select highest probability points                     │
│                                                                      │
│  Update Methods:                                                     │
│    • update_weights(rule, feedback_points, **params)                │
│      - reward: Increase prob near positive feedback                 │
│      - exploration: Boost undersampled regions                      │
│      - concentration: Focus on high-value areas                     │
│      - custom: User-defined update function                         │
│                                                                      │
│  Query Methods:                                                      │
│    • query_region(lat, lon, alt, radius) - Spatial query           │
│    • get_statistics() - Compute distribution stats                  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Scoring Mechanism

```
┌────────────────────────────────────────────────────────────────────────┐
│                         Scoring Pipeline                               │
└────────────────────────────────────────────────────────────────────────┘

1. User Interaction:
   ┌─────────────────────────────────────────────────┐
   │ User clicks on sampled point on globe           │
   │ • Point turns cyan (selected)                   │
   │ • Camera maintains current position/zoom        │
   └─────────────────────────────────────────────────┘
                    ↓

2. Feedback Input:
   ┌─────────────────────────────────────────────────┐
   │ User adjusts reward slider                      │
   │ • Range: -1.0 (avoid) to +1.0 (interesting)     │
   │ • Default: 0.0 (neutral)                        │
   │ • Also sets learning rate (how much to adjust)  │
   └─────────────────────────────────────────────────┘
                    ↓

3. Data Collection:
   ┌─────────────────────────────────────────────────┐
   │ Frontend gathers:                               │
   │ • lat, lon, alt (from selected entity)          │
   │ • reward (from slider)                          │
   │ • zoom (calculated from camera altitude)        │
   │ • weight (from entity.sampleWeight)             │
   └─────────────────────────────────────────────────┘
                    ↓

4. API Processing:
   ┌─────────────────────────────────────────────────┐
   │ Backend processes feedback:                     │
   │                                                 │
   │ A. Database Update:                             │
   │    • Find or create SampledLocation             │
   │    • Update score = reward                      │
   │    • Set scored_at = now()                      │
   │    • Store zoom_level                           │
   │                                                 │
   │ B. Distribution Update:                         │
   │    • Create DistributionUpdate record           │
   │    • Link to feedback locations                 │
   │    • Increment session.total_updates            │
   │                                                 │
   │ C. In-Memory Sampler Update:                    │
   │    • Adjust weights in WorldSampler             │
   │    • Apply spatial influence (radius-based)     │
   │    • Use learning rate to control magnitude     │
   └─────────────────────────────────────────────────┘
                    ↓

5. Result:
   ┌─────────────────────────────────────────────────┐
   │ Future samples influenced by feedback:          │
   │ • Positive feedback → higher probability        │
   │ • Negative feedback → lower probability         │
   │ • Spatial smoothing → nearby areas affected     │
   └─────────────────────────────────────────────────┘
```

## Zoom Level Calculation

```
┌──────────────────────────────────────────────────────────────┐
│                   Zoom Level Formula                         │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  zoom = log₂(40,075,000 / altitude_in_meters)               │
│                                                              │
│  Where:                                                      │
│    • 40,075,000 = Earth's circumference in meters           │
│    • altitude = camera height above terrain                  │
│                                                              │
│  Examples:                                                   │
│    • altitude = 300m    → zoom = 17-18 (street level)       │
│    • altitude = 10,000m → zoom = 12    (city level)         │
│    • altitude = 100,000m→ zoom = 8-9   (country level)      │
│                                                              │
│  Clamped to range: [0, 28]                                  │
└──────────────────────────────────────────────────────────────┘
```

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                            Nginx Reverse Proxy                      │
│                          deepgis.org (HTTPS)                        │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
    ┌───────────────────────────┐   ┌───────────────────────────┐
    │  Docker Container 1       │   │  Docker Container 2       │
    │  deepgis-xr_web           │   │  deepgis-xr_tileserver    │
    │                           │   │                           │
    │  • Django App             │   │  • TileServer GL          │
    │  • World Sampler API      │   │  • Raster tile serving    │
    │  • Static file serving    │   │                           │
    │  • PostgreSQL             │   │                           │
    │  • Port 8090              │   │  • Port 80                │
    └───────────────────────────┘   └───────────────────────────┘
```

## Summary Statistics

- **3 Database Models**: SampledLocation, SamplingSession, DistributionUpdate
- **8 API Endpoints**: Initialize, Sample, Update, Query, Statistics, Reset, History, Scored
- **1 Frontend Component**: WorldSamplerUI (1,247 lines)
- **1 Core Algorithm**: WorldSampler class with probabilistic sampling
- **Storage**: (lat, lon, alt, zoom, score, weight) tuples in PostgreSQL
- **Visualization**: Cesium.js 3D globe with interactive markers


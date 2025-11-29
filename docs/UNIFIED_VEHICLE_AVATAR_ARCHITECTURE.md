# Unified Vehicle Avatar Architecture
## Blurring Physical and Digital Twins for Autonomous Data Capture

**Date:** November 29, 2025  
**Concept:** Stream-of-consciousness exploration of unified vehicle representation, data assimilation, and spatial cataloging

---

## Core Concept: The Viewport as Avatar

### The Vision

**The viewport is an avatar** - a unified representation that can be:
- A **real physical vehicle** with cameras, LiDAR, multispectral sensors
- A **PX4 SITL digital twin** running in an OpenUAV container
- A **hybrid entity** combining real and simulated data streams
- A **historical playback** of past missions
- A **synthetic agent** for mission planning and simulation

**Key Insight:** From the DeepGIS-XR interface perspective, there should be **no distinction** between controlling a real drone and a simulated one. The same mission planning, telemetry display, and data capture workflows apply to both.

---

## 1. Unified Vehicle Abstraction Layer

### Current State

**Physical Assets:**
- Real vehicles with MAVROS/ROS2 telemetry
- GPS, IMU, camera, LiDAR sensors
- Live data streams via `DeepGISTelemetryPublisher`

**Digital Twins:**
- PX4 SITL in OpenUAV containers (`openuav:px4-sitl`)
- Container-based simulation environment
- VNC access for visualization
- ROS2 topics for simulated telemetry

**Gap:** These are treated as separate systems with different interfaces.

### Proposed Architecture

```python
# Unified Vehicle Model
class VehicleAvatar(models.Model):
    """Unified representation of physical or simulated vehicle"""
    
    # Identity
    avatar_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    
    # Avatar Type
    AVATAR_TYPES = [
        ('PHYSICAL', 'Physical Vehicle'),
        ('SITL', 'PX4 SITL Digital Twin'),
        ('HYBRID', 'Hybrid (Physical + Simulation)'),
        ('PLAYBACK', 'Historical Playback'),
        ('SYNTHETIC', 'Synthetic Agent'),
    ]
    avatar_type = models.CharField(max_length=20, choices=AVATAR_TYPES)
    
    # Physical Vehicle Link (if applicable)
    physical_vehicle = models.ForeignKey(
        'Vehicle', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='avatars'
    )
    
    # Digital Twin Link (if applicable)
    container = models.ForeignKey(
        'openuav_manager.Container',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vehicle_avatars'
    )
    
    # Unified Telemetry Source
    telemetry_source = models.CharField(max_length=50)  # 'mavros', 'sitl', 'playback', 'synthetic'
    telemetry_namespace = models.CharField(max_length=100, default='/mavros')
    
    # Sensor Configuration
    sensors = models.JSONField(default=dict, help_text="Available sensors and capabilities")
    # Example: {
    #   "cameras": ["rgb", "multispectral"],
    #   "lidar": {"enabled": true, "range": 100},
    #   "gps": {"enabled": true, "accuracy": 1.5}
    # }
    
    # Current State
    current_position = models.JSONField(default=dict)  # {lat, lon, alt, heading}
    current_mode = models.CharField(max_length=50)  # 'MANUAL', 'AUTO', 'GUIDED', etc.
    is_active = models.BooleanField(default=False)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    last_update = models.DateTimeField(auto_now=True)
```

### Unified Interface

**Same API for All Avatar Types:**

```python
# Vehicle Control (works for physical and SITL)
POST /api/vehicle/{avatar_id}/arm
POST /api/vehicle/{avatar_id}/takeoff?altitude=10
POST /api/vehicle/{avatar_id}/mission/upload
GET  /api/vehicle/{avatar_id}/telemetry

# Viewport Capture (works for all)
POST /api/vehicle/{avatar_id}/viewport/capture
POST /api/vehicle/{avatar_id}/viewport/analyze
```

**Implementation:**
- Physical vehicle → Direct MAVROS commands
- SITL digital twin → Commands routed to container's ROS2 topics
- Playback → Time-based data retrieval
- Synthetic → Algorithm-generated responses

---

## 2. Viewport as Sensor Platform

### Current Viewport Capture

**Existing:** `analyze_viewport()` in `world_sampler_api.py`
- Captures Cesium viewport as image
- Analyzes with SAM/Mask2Former/Zero-Shot
- Returns GeoJSON annotations

**Extension:** Viewport as multi-sensor platform

```python
class ViewportCapture(models.Model):
    """Capture from vehicle avatar viewport"""
    
    avatar = models.ForeignKey(VehicleAvatar, on_delete=models.CASCADE)
    capture_type = models.CharField(max_length=50)  # 'rgb', 'multispectral', 'lidar', 'depth'
    
    # Location (from avatar position)
    latitude = models.DecimalField(max_digits=17, decimal_places=14)
    longitude = models.DecimalField(max_digits=17, decimal_places=14)
    altitude = models.FloatField()
    heading = models.FloatField()
    pitch = models.FloatField()
    
    # Sensor Data
    image_data = models.BinaryField(null=True, blank=True)  # RGB image
    multispectral_data = models.JSONField(null=True, blank=True)  # Multi-band data
    lidar_pointcloud = models.CharField(max_length=500, null=True, blank=True)  # Path to PLY/PCD
    depth_map = models.BinaryField(null=True, blank=True)  # Depth image
    
    # AI Analysis Results
    ai_analysis = models.JSONField(null=True, blank=True)  # SAM/Mask2Former results
    annotations = models.ManyToManyField('ImageLabel', blank=True)
    
    # Metadata
    timestamp = models.DateTimeField(auto_now_add=True)
    sensor_config = models.JSONField(default=dict)  # Camera params, LiDAR settings, etc.
```

### Sensor Abstraction

**For Physical Vehicles:**
- RGB camera → Capture from actual camera feed
- Multispectral → Capture from multispectral sensor
- LiDAR → Capture point cloud from LiDAR sensor
- GPS → Use vehicle GPS position

**For SITL Digital Twins:**
- RGB camera → Render from Gazebo/Unreal simulation
- Multispectral → Synthesize from simulated spectral response
- LiDAR → Generate point cloud from simulated environment
- GPS → Use simulated GPS position

**For Playback:**
- All sensors → Retrieve from historical telemetry database

**Key Innovation:** Same API, different data sources.

---

## 3. Data Assimilation & Mesh Synthesis

### Problem Statement

**Current State:**
- Viewport captures produce 2D images with annotations
- GPS telemetry produces paths
- 3D models exist but aren't linked to locations
- No systematic way to build 3D representations from captured data

### Proposed Solution: Spatial Data Catalog

```python
class SpatialDataCatalog(models.Model):
    """Catalog of available data at specific locations"""
    
    # Location (from World Sampler or manual)
    location = models.ForeignKey('SampledLocation', on_delete=models.CASCADE)
    latitude = models.DecimalField(max_digits=17, decimal_places=14)
    longitude = models.DecimalField(max_digits=17, decimal_places=14)
    
    # Available Data Types
    has_rgb_images = models.BooleanField(default=False)
    has_multispectral = models.BooleanField(default=False)
    has_lidar = models.BooleanField(default=False)
    has_3d_model = models.BooleanField(default=False)
    has_annotations = models.BooleanField(default=False)
    has_ai_analysis = models.BooleanField(default=False)
    
    # Data References
    rgb_images = models.ManyToManyField('ViewportCapture', related_name='rgb_catalogs', blank=True)
    multispectral_data = models.ManyToManyField('ViewportCapture', related_name='multispec_catalogs', blank=True)
    lidar_data = models.ManyToManyField('LidarCapture', blank=True)
    models_3d = models.ManyToManyField('Model3D', blank=True)
    annotations = models.ManyToManyField('ImageLabel', blank=True)
    
    # Mesh Synthesis
    synthesized_mesh = models.CharField(max_length=500, null=True, blank=True)  # Path to mesh file
    mesh_method = models.CharField(max_length=50, null=True, blank=True)  # 'photogrammetry', 'lidar', 'ai', 'hybrid'
    mesh_quality = models.CharField(max_length=20, null=True, blank=True)  # 'low', 'medium', 'high'
    
    # Metadata
    data_coverage = models.FloatField(default=0.0, help_text="Percentage of area covered by data")
    last_updated = models.DateTimeField(auto_now=True)
```

### Mesh Synthesis Pipeline

**1. Photogrammetry from Multiple Viewports**
```python
def synthesize_mesh_from_viewports(location_id):
    """Create 3D mesh from multiple viewport captures"""
    catalog = SpatialDataCatalog.objects.get(location_id=location_id)
    
    # Collect all RGB images from different viewpoints
    images = catalog.rgb_images.all()
    
    # Use structure-from-motion (SfM) or neural radiance fields (NeRF)
    # Tools: COLMAP, OpenMVS, Instant-NGP
    
    # Generate mesh
    mesh_path = run_photogrammetry(images)
    
    catalog.synthesized_mesh = mesh_path
    catalog.mesh_method = 'photogrammetry'
    catalog.save()
```

**2. LiDAR Point Cloud to Mesh**
```python
def synthesize_mesh_from_lidar(location_id):
    """Create mesh from LiDAR point cloud"""
    catalog = SpatialDataCatalog.objects.get(location_id=location_id)
    lidar_data = catalog.lidar_data.first()
    
    # Load point cloud (PLY/PCD format)
    pointcloud = load_pointcloud(lidar_data.file_path)
    
    # Mesh reconstruction (Poisson, Delaunay, etc.)
    mesh = reconstruct_mesh(pointcloud)
    
    catalog.synthesized_mesh = mesh_path
    catalog.mesh_method = 'lidar'
    catalog.save()
```

**3. AI-Assisted Mesh Generation**
```python
def synthesize_mesh_with_ai(location_id):
    """Use AI to generate mesh from sparse data"""
    catalog = SpatialDataCatalog.objects.get(location_id=location_id)
    
    # Combine RGB images + depth maps + annotations
    images = catalog.rgb_images.all()
    annotations = catalog.annotations.all()
    
    # Use AI model (e.g., 3D-GAN, Neural Radiance Fields)
    # Leverage annotations to guide mesh generation
    mesh = ai_mesh_generator.generate(
        images=images,
        annotations=annotations,
        location=(catalog.latitude, catalog.longitude)
    )
    
    catalog.synthesized_mesh = mesh_path
    catalog.mesh_method = 'ai'
    catalog.save()
```

**4. Hybrid Approach**
```python
def synthesize_mesh_hybrid(location_id):
    """Combine multiple data sources for best mesh"""
    catalog = SpatialDataCatalog.objects.get(location_id=location_id)
    
    # Use LiDAR for structure, photogrammetry for texture
    # Or: Use AI to fill gaps in LiDAR data
    # Or: Use annotations to guide mesh refinement
    
    mesh = hybrid_mesh_synthesis(
        lidar=catalog.lidar_data.first(),
        images=catalog.rgb_images.all(),
        annotations=catalog.annotations.all()
    )
    
    catalog.synthesized_mesh = mesh_path
    catalog.mesh_method = 'hybrid'
    catalog.save()
```

---

## 4. Cataloging System for World Sampled Locations

### Integration with World Sampler

**Current:** `SampledLocation` model stores sampled points
**Extension:** Link sampled locations to available data

```python
class SampledLocation(models.Model):
    # ... existing fields ...
    
    # Data Catalog Link
    data_catalog = models.OneToOneField(
        'SpatialDataCatalog',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sampled_location'
    )
    
    # Quick Access to Available Data
    @property
    def has_data(self):
        """Check if location has any captured data"""
        if self.data_catalog:
            return (
                self.data_catalog.has_rgb_images or
                self.data_catalog.has_multispectral or
                self.data_catalog.has_lidar or
                self.data_catalog.has_3d_model
            )
        return False
    
    @property
    def data_completeness(self):
        """Percentage of data types available"""
        if not self.data_catalog:
            return 0.0
        
        available = sum([
            self.data_catalog.has_rgb_images,
            self.data_catalog.has_multispectral,
            self.data_catalog.has_lidar,
            self.data_catalog.has_3d_model,
            self.data_catalog.has_annotations,
            self.data_catalog.has_ai_analysis,
        ])
        
        return (available / 6.0) * 100.0
```

### UI Integration

**World Sampler Panel Enhancement:**
- Show data availability indicator for each sampled location
- Color-code locations by data completeness
- Quick access to view available data (images, meshes, annotations)
- "Capture Data" button to trigger viewport capture from vehicle avatar

**Example UI:**
```
┌─────────────────────────────────────┐
│ World Sampler                       │
├─────────────────────────────────────┤
│ 📍 Location 1 (41.55°N, 83.44°W)   │
│   ✅ RGB Images (5)                 │
│   ✅ Annotations (12)                │
│   ⚠️  No LiDAR                      │
│   ⚠️  No 3D Model                   │
│   [View Data] [Capture More]         │
├─────────────────────────────────────┤
│ 📍 Location 2 (41.56°N, 83.45°W)   │
│   ✅ RGB Images (3)                 │
│   ✅ LiDAR Point Cloud               │
│   ✅ 3D Mesh (synthesized)          │
│   [View Data] [Refine Mesh]         │
└─────────────────────────────────────┘
```

---

## 5. Unified Data Flow Architecture

### Data Capture Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    Vehicle Avatar                           │
│  (Physical / SITL / Playback / Synthetic)                  │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ Telemetry + Sensor Data
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              Viewport Capture Service                        │
│  - RGB Camera                                                │
│  - Multispectral                                             │
│  - LiDAR                                                     │
│  - Depth Maps                                                │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ Raw Data
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              AI Analysis Pipeline                            │
│  - SAM Segmentation                                          │
│  - Mask2Former Detection                                     │
│  - Zero-Shot Classification                                  │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ Annotations + Metadata
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              Spatial Data Catalog                            │
│  - Index by Location                                        │
│  - Link Related Data                                         │
│  - Track Data Completeness                                  │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ Triggered or Scheduled
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              Mesh Synthesis Pipeline                         │
│  - Photogrammetry (SfM)                                      │
│  - LiDAR Reconstruction                                      │
│  - AI-Assisted Generation                                    │
│  - Hybrid Methods                                           │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ Synthesized Mesh
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              3D Model Catalog                                 │
│  - Store Mesh Files                                          │
│  - Link to Locations                                         │
│  - Version Control                                           │
│  - Quality Metrics                                           │
└─────────────────────────────────────────────────────────────┘
```

### Data Assimilation Rules

**Automatic Cataloging:**
- When viewport is captured → Create/update `SpatialDataCatalog` entry
- When AI analysis completes → Link annotations to catalog
- When LiDAR data is captured → Update catalog with LiDAR reference
- When mesh is synthesized → Store mesh and update catalog

**Smart Synthesis Triggers:**
- When location has ≥3 RGB images from different angles → Trigger photogrammetry
- When location has LiDAR + RGB images → Trigger hybrid mesh synthesis
- When location has annotations but no mesh → Trigger AI-assisted mesh generation
- When data completeness >80% → Suggest mesh synthesis

---

## 6. Implementation Phases

### Phase 1: Unified Vehicle Avatar (4-6 weeks)

**Goals:**
- Create `VehicleAvatar` model
- Implement unified API for physical and SITL vehicles
- Extend viewport capture to work with avatars
- Test with both physical vehicle and SITL container

**Deliverables:**
- Vehicle avatar abstraction layer
- Unified control API
- Viewport capture from avatars

### Phase 2: Spatial Data Catalog (3-4 weeks)

**Goals:**
- Create `SpatialDataCatalog` model
- Integrate with `SampledLocation`
- Build cataloging UI in World Sampler
- Automatic cataloging from viewport captures

**Deliverables:**
- Data catalog system
- World Sampler integration
- Data availability visualization

### Phase 3: Mesh Synthesis (6-8 weeks)

**Goals:**
- Implement photogrammetry pipeline (COLMAP/OpenMVS)
- Implement LiDAR-to-mesh reconstruction
- Integrate AI mesh generation (optional)
- Build mesh quality assessment

**Deliverables:**
- Mesh synthesis service
- Mesh storage and cataloging
- Quality metrics

### Phase 4: Advanced Features (4-6 weeks)

**Goals:**
- Hybrid mesh synthesis
- Real-time mesh updates
- Mesh versioning
- Integration with Cesium 3D Tiles

**Deliverables:**
- Advanced synthesis methods
- 3D visualization integration

---

## 7. Technical Considerations

### Container Integration

**SITL Digital Twins:**
- Extend `openuav_manager.Container` to support vehicle avatar creation
- Route ROS2 topics from container to unified telemetry system
- Enable viewport capture from Gazebo/Unreal rendering

**Example:**
```python
# Create avatar from SITL container
container = Container.objects.get(name='digital-twin-user123')
avatar = VehicleAvatar.objects.create(
    avatar_id='sitl_001',
    name='SITL Drone 1',
    avatar_type='SITL',
    container=container,
    telemetry_source='sitl',
    telemetry_namespace='/mavros',
    sensors={
        'cameras': ['rgb'],
        'lidar': {'enabled': True, 'range': 100},
        'gps': {'enabled': True}
    }
)
```

### Data Storage

**Large Files:**
- RGB images → Store in media storage, reference in database
- LiDAR point clouds → Store as PLY/PCD files, reference paths
- Meshes → Store as GLTF/GLB/OBJ, reference paths
- Use object storage (S3-compatible) for scalability

**Database:**
- Store metadata and references only
- Use JSON fields for flexible sensor configurations
- Index by location for fast spatial queries

### Performance

**Mesh Synthesis:**
- Run as background tasks (Celery)
- Cache intermediate results
- Support incremental mesh updates
- Use GPU acceleration when available

**Catalog Queries:**
- Spatial indexing for location-based queries
- Materialized views for data completeness metrics
- Cache frequently accessed catalog entries

---

## 8. Use Cases

### Use Case 1: Mission Planning with SITL

1. User creates mission waypoints in DeepGIS-XR
2. User selects SITL digital twin as vehicle avatar
3. Mission is uploaded to SITL container
4. User watches simulated mission execution
5. Viewport captures are taken during simulation
6. Data is cataloged and meshes are synthesized
7. User reviews results before deploying to physical vehicle

### Use Case 2: Hybrid Data Collection

1. Physical vehicle captures RGB images at location
2. SITL digital twin simulates LiDAR scan of same location
3. Both data sources are cataloged under same `SpatialDataCatalog`
4. Hybrid mesh synthesis combines real RGB with simulated LiDAR
5. Result: High-quality mesh with real textures and simulated structure

### Use Case 3: Historical Playback with Mesh Generation

1. User selects historical mission for playback
2. System creates playback avatar
3. Viewport captures are replayed from historical data
4. Mesh synthesis runs on historical captures (if not already done)
5. User can explore 3D reconstruction of past mission

### Use Case 4: World Sampler Data Collection

1. World Sampler generates intelligent sampling locations
2. User selects vehicle avatar (physical or SITL)
3. Mission is auto-generated to visit all sampled locations
4. At each location, viewport captures are taken
5. Data is automatically cataloged
6. Meshes are synthesized when sufficient data is available
7. World Sampler UI shows data completeness for each location

---

## 9. Future Extensions

### Multi-Agent Coordination

- Multiple avatars (physical + SITL) working together
- Coordinated data collection missions
- Shared spatial data catalog
- Collaborative mesh synthesis

### Real-Time Mesh Updates

- Incremental mesh updates as new data arrives
- Live mesh refinement during mission
- Streaming mesh updates to Cesium viewer

### AI-Guided Data Collection

- AI analyzes existing data catalog
- Suggests optimal locations for additional captures
- Recommends sensor types needed for mesh completion
- Auto-generates missions to fill data gaps

### Cloud-Based Mesh Synthesis

- Offload heavy mesh synthesis to cloud compute
- Support for large-scale area reconstruction
- Distributed processing for multiple locations

---

## Conclusion

This architecture blurs the line between physical and simulated vehicles, creating a unified system where:

1. **Vehicle avatars** provide consistent interface regardless of source
2. **Viewport captures** work seamlessly for all avatar types
3. **Spatial data catalog** systematically organizes captured data
4. **Mesh synthesis** creates 3D representations from diverse data sources
5. **World Sampler integration** enables intelligent data collection missions

The result is a powerful platform for autonomous data capture, where physical and digital twins work together to build comprehensive 3D representations of the world.

---

*Document Version: 1.0*  
*Last Updated: November 29, 2025*  
*Status: Conceptual Design*


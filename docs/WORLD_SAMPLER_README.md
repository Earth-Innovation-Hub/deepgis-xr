# World Sampler - Adaptive Geospatial Sampling System

An intelligent spatial sampling system for Earth locations (latitude, longitude, altitude) with adaptive distribution learning.

## 🎯 Overview

The World Sampler provides a probabilistic framework for:
- **Sampling** geospatial locations with customizable distributions
- **Learning** from feedback to focus on areas of interest
- **Exploring** undersampled regions
- **Querying** spatial regions efficiently

Perfect for:
- Geospatial search and discovery
- Active learning for Earth observation
- Adaptive exploration strategies
- Interest-based location recommendations

## 📦 Components

### 1. Core Module (`world_sampler.py`)
- `WorldSampler` class with multiple initialization strategies
- Adaptive update rules (reward, exploration, concentration, custom)
- Spatial indexing for efficient queries
- Statistics and history tracking

### 2. API Endpoints (`world_sampler_api.py`)
RESTful API for Django integration:
- `/webclient/sampler/initialize` - Create new sampler
- `/webclient/sampler/sample` - Get sample locations
- `/webclient/sampler/update` - Update distribution
- `/webclient/sampler/query` - Query spatial region
- `/webclient/sampler/statistics` - Get distribution stats
- `/webclient/sampler/reset` - Reset to initial state
- `/webclient/sampler/history` - View sample history

### 3. Examples (`world_sampler_example.py`)
Comprehensive usage examples demonstrating all features

## 🚀 Quick Start

### Python Usage

```python
from world_sampler import WorldSampler

# Initialize with Gaussian mixture around cities
sampler = WorldSampler(
    num_points=1000,
    initialization='gaussian_mixture',
    seed=42
)

# Sample 10 locations
samples = sampler.sample(n=10, method='weighted')

for s in samples:
    print(f"Lat: {s.lat:.2f}, Lon: {s.lon:.2f}, Alt: {s.alt:.0f}m")
```

### API Usage (JavaScript/Frontend)

```javascript
// Initialize sampler
const initResponse = await fetch('/webclient/sampler/initialize', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        num_points: 1000,
        initialization: 'gaussian_mixture'
    })
});

// Sample 10 locations
const sampleResponse = await fetch('/webclient/sampler/sample', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        n: 10,
        method: 'weighted'
    })
});

const data = await sampleResponse.json();
// data.geojson can be loaded directly into Cesium!
```

## 📊 Initialization Strategies

### 1. Uniform Distribution
```python
sampler = WorldSampler(initialization='uniform')
```
- Equal probability across all regions
- Good for unbiased global exploration

### 2. Gaussian Mixture
```python
sampler = WorldSampler(initialization='gaussian_mixture')
```
- Clusters around interesting locations (cities, landmarks)
- Mount Everest, New York, London, Tokyo, etc.

### 3. Population Weighted
```python
sampler = WorldSampler(initialization='population_weighted')
```
- Biased towards populated areas
- Lower latitudes and coastal regions

## 🎛️ Update Rules

### 1. Reward-Based Learning
```python
# User found interesting locations
feedback = [
    (28.0, 86.9, 8848, 1.0),   # Mount Everest - high reward
    (40.7, -74.0, 10, 0.5),    # New York - medium reward
]

sampler.update_weights(
    'reward',
    feedback_points=feedback,
    learning_rate=0.2,
    radius=100000  # 100km influence radius
)
```

### 2. Exploration Bonus
```python
# Encourage sampling in less-visited areas
sampler.update_weights(
    'exploration',
    exploration_bonus=0.5,
    min_distance=50000  # 50km
)
```

### 3. Concentration
```python
# Focus on high-value areas
sampler.update_weights(
    'concentration',
    feedback_points=high_value_locations,
    concentration_factor=2.0
)
```

### 4. Custom Rules
```python
def custom_rule(sample, params):
    """Favor high altitude northern locations"""
    alt_bonus = 1.0 + (sample.alt / 5000.0) * 0.5
    lat_bonus = 1.0 + (max(0, sample.lat) / 90.0) * 0.5
    return alt_bonus * lat_bonus

sampler.update_weights('custom', update_fn=custom_rule)
```

## 🔍 Spatial Queries

```python
# Find all samples within 200km of Mount Everest
samples = sampler.query_region(
    center_lat=28.0,
    center_lon=86.9,
    center_alt=8848,
    radius=200000  # meters
)

print(f"Found {len(samples)} samples in region")
```

## 📈 Statistics

```python
stats = sampler.get_statistics()

print(f"Total samples: {stats['num_samples']}")
print(f"Weight entropy: {stats['weight_stats']['entropy']:.4f}")
print(f"Spatial coverage: {stats['spatial_coverage']}")
```

## 🌍 Integration with DeepGIS Search

The World Sampler is designed to integrate seamlessly with the DeepGIS Search viewer (`label_search.html`):

### Frontend Integration Example

```javascript
// Add to label_search.html
class SearchController {
    constructor(viewer) {
        this.viewer = viewer;
        this.sampler = new SamplerClient();
    }
    
    async exploreSamples() {
        // Get sample locations
        const response = await this.sampler.sample(10);
        
        // Display on Cesium globe
        const dataSource = await Cesium.GeoJsonDataSource.load(
            response.geojson
        );
        this.viewer.dataSources.add(dataSource);
        
        // Fly to first sample
        const first = response.samples[0];
        this.viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(
                first.lon, first.lat, first.alt + 10000
            )
        });
    }
    
    async provideFeedback(lat, lon, alt, reward) {
        // Update distribution based on user interest
        await this.sampler.update({
            rule: 'reward',
            feedback_points: [{lat, lon, alt, reward}],
            params: {learning_rate: 0.2}
        });
    }
}

// JavaScript API client
class SamplerClient {
    async initialize(config) {
        return await fetch('/webclient/sampler/initialize', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(config)
        }).then(r => r.json());
    }
    
    async sample(n, method='weighted') {
        return await fetch('/webclient/sampler/sample', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({n, method})
        }).then(r => r.json());
    }
    
    async update(config) {
        return await fetch('/webclient/sampler/update', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(config)
        }).then(r => r.json());
    }
    
    async query(lat, lon, alt, radius) {
        return await fetch('/webclient/sampler/query', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({lat, lon, alt, radius})
        }).then(r => r.json());
    }
}
```

## 🧪 Running Examples

```bash
cd /home/jdas/dreams-lab-website-server/deepgis-xr/deepgis_xr/apps/web/
python world_sampler_example.py
```

This will run 8 comprehensive examples demonstrating all features.

## 📚 API Reference

### WorldSampler Class

#### `__init__(num_points, lat_range, lon_range, alt_range, initialization, seed)`
Initialize a new sampler.

#### `sample(n, method='weighted') -> List[SamplePoint]`
Sample n locations from current distribution.

#### `update_weights(rule, feedback_points, **kwargs)`
Update distribution based on feedback.

#### `query_region(center_lat, center_lon, center_alt, radius) -> List[SamplePoint]`
Query samples within radius of center point.

#### `get_statistics() -> Dict`
Get distribution statistics.

#### `reset(keep_history=False)`
Reset to initial state.

### SamplePoint Class

```python
@dataclass
class SamplePoint:
    lat: float      # [-90, 90]
    lon: float      # [-180, 180]
    alt: float      # meters
    weight: float   # probability
    metadata: Dict  # additional info
```

## 🎨 Use Cases

### 1. Geospatial Search
```python
# Initialize around areas of interest
sampler = WorldSampler(initialization='gaussian_mixture')

# User explores and provides feedback
for _ in range(10):
    samples = sampler.sample(5)
    # ... show to user ...
    feedback = get_user_feedback(samples)
    sampler.update_weights('reward', feedback)
```

### 2. Active Learning
```python
# Start uniform
sampler = WorldSampler(initialization='uniform')

# Iteratively sample, label, and update
for iteration in range(100):
    samples = sampler.sample(10)
    labels = get_labels(samples)  # ML model or human
    high_value = [(s.lat, s.lon, s.alt, l) for s, l in zip(samples, labels)]
    sampler.update_weights('concentration', high_value)
```

### 3. Exploration Strategy
```python
# Balance exploration and exploitation
sampler = WorldSampler(initialization='uniform')

for round in range(20):
    # Sample and evaluate
    samples = sampler.sample(5)
    values = evaluate(samples)
    
    # Update: reward good locations
    sampler.update_weights('reward', values, learning_rate=0.2)
    
    # Update: explore new areas
    sampler.update_weights('exploration', exploration_bonus=0.3)
```

## 🔧 Dependencies

```
numpy
scipy
```

Install with:
```bash
pip install numpy scipy
```

## 📝 License

Part of the DeepGIS-XR project.

## 🤝 Contributing

The sampler is designed to be extensible:
- Add new initialization strategies
- Create custom update rules
- Extend spatial indexing
- Add visualization tools

---

**Happy Sampling! 🌍🔍**


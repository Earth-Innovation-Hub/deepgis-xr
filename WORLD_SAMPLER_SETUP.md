# World Sampler - Setup & Usage Guide

## 🚀 Quick Setup

### 1. Install Dependencies

```bash
cd /home/jdas/dreams-lab-website-server/deepgis-xr
pip install numpy scipy
```

### 2. Verify Installation

```bash
python -c "from deepgis_xr.apps.web.world_sampler import WorldSampler; print('✅ World Sampler installed successfully!')"
```

### 3. Run Test Examples

```bash
cd /home/jdas/dreams-lab-website-server/deepgis-xr/deepgis_xr/apps/web/
python world_sampler_example.py
```

## 🌐 Access the Frontend

### Option 1: Via Docker (Recommended)

1. Restart your Docker container:
```bash
cd /home/jdas/dreams-lab-website-server/deepgis-xr
docker-compose restart
```

2. Open in browser:
```
https://deepgis.org/label/3d/search/
```

3. The World Sampler panel will appear on the right side automatically!

### Option 2: Local Development

```bash
cd /home/jdas/dreams-lab-website-server/deepgis-xr
python manage.py runserver 0.0.0.0:8000
```

Then visit: `http://localhost:8000/label/3d/search/`

## 🎮 Using the Interface

### Step 1: Initialize Sampler

1. Choose a distribution type:
   - **Uniform** - Random across globe
   - **Gaussian Mixture** - Clustered around cities (recommended)
   - **Population Weighted** - Biased towards populated areas

2. Set number of points (default: 1000)

3. Click **"Initialize Sampler"**

### Step 2: Sample Locations

1. Set number of samples (e.g., 10)
2. Choose method:
   - **Weighted** - Probabilistic sampling (default)
   - **Top K** - Highest probability locations
3. Click **"Sample Locations"**
4. Yellow numbered markers will appear on the globe!

### Step 3: Provide Feedback

1. **Click** on any yellow marker on the globe
2. Adjust the **Reward Value** slider:
   - `1.0` = Very Interesting
   - `0.5` = Interesting
   - `0.0` = Neutral
   - `-0.5` = Not Interesting
   - `-1.0` = Avoid
3. Set **Learning Rate** (how much to update)
4. Click **"Submit Feedback"**
5. The distribution will adapt to your preferences!

### Step 4: Exploration Strategies

- **Explore** - Encourage sampling in new, unvisited areas
- **Concentrate** - Focus on current high-interest regions

### Step 5: Clear & Reset

- **Clear Samples** - Remove markers from map
- **Reset Sampler** - Start fresh with new distribution

## 📊 Understanding Statistics

- **Samples Shown** - Currently visible markers
- **Total Sampled** - All samples taken in session
- **Updates** - Number of times distribution was updated
- **Entropy** - Distribution diversity (higher = more uniform)

## 🎯 Example Workflow

### Scenario: Finding Interesting Mountain Ranges

1. **Initialize** with "Gaussian Mixture"
2. **Sample** 20 locations
3. **Explore** the globe and click on interesting mountains
4. **Provide feedback** with high reward (0.8 - 1.0)
5. **Sample** again - should show more mountain locations!
6. Use **Concentrate** to focus on mountain regions
7. Continue exploring and refining

### Scenario: Discovering New Locations

1. **Initialize** with "Uniform"
2. **Sample** 15 locations across globe
3. As you visit locations, mark interesting ones
4. Periodically use **Explore** to discover new areas
5. Balance between known interesting spots and new discoveries

## 🐛 Troubleshooting

### Panel Not Appearing?

1. Check browser console (F12) for errors
2. Verify Cesium viewer is loaded
3. Refresh the page

### API Errors?

1. Ensure backend is running:
```bash
docker-compose ps
```

2. Check API endpoints are accessible:
```bash
curl https://deepgis.org/webclient/sampler/statistics
```

### No Markers Visible?

1. Zoom out to see full globe
2. Check "Samples Shown" counter is > 0
3. Try clicking "Home View" button

## 🔧 Advanced Usage

### Custom Update Rule (Python)

```python
from deepgis_xr.apps.web.world_sampler import WorldSampler

sampler = WorldSampler(initialization='uniform')

# Define custom rule
def altitude_preference(sample, params):
    """Prefer high altitude locations"""
    return 1.0 + (sample.alt / 5000.0)

# Apply custom rule
sampler.update_weights('custom', update_fn=altitude_preference)
```

### Querying Specific Regions

```python
# Find samples near Mount Everest
nearby = sampler.query_region(
    center_lat=28.0,
    center_lon=86.9, 
    center_alt=8848,
    radius=200000  # 200km
)

print(f"Found {len(nearby)} samples")
```

### Export Data

```python
# Get all sample history
history = sampler.sample_history

# Export to CSV
import pandas as pd
df = pd.DataFrame([
    {'lat': s.lat, 'lon': s.lon, 'alt': s.alt, 'weight': s.weight}
    for s in history
])
df.to_csv('sample_history.csv', index=False)
```

## 📱 Mobile Support

The interface is responsive but works best on desktop/tablet due to:
- Complex 3D Cesium viewer
- Multiple controls
- Click interactions

## 🎨 Customization

### Change Panel Position

Edit `world-sampler-ui.js`:

```javascript
.world-sampler-panel {
    position: fixed;
    top: 80px;
    right: 20px;  // Change to 'left: 20px' for left side
    width: 320px;
    ...
}
```

### Add Custom Initialization Presets

In the UI, add more `<option>` tags:

```html
<select id="samplerInitType" class="form-control">
    <option value="uniform">Uniform</option>
    <option value="gaussian_mixture">Gaussian Mixture</option>
    <option value="population_weighted">Population Weighted</option>
    <option value="your_custom">Your Custom Preset</option>
</select>
```

Then implement in `world_sampler.py`.

## 🌟 Pro Tips

1. **Start Broad** - Use uniform or Gaussian mixture initially
2. **Give Diverse Feedback** - Mix positive and negative rewards
3. **Balance Exploration** - Don't concentrate too early
4. **Track Entropy** - High entropy = good coverage
5. **Use History** - Review past samples to see patterns

## 📚 Related Files

- **Frontend**: `/static/web/js/world-sampler-ui.js`
- **Backend**: `/apps/web/world_sampler.py`
- **API**: `/apps/web/world_sampler_api.py`
- **URLs**: `/apps/web/urls.py`
- **Template**: `/apps/web/templates/web/label_search.html`

## 🎓 Learning Resources

- Read `WORLD_SAMPLER_README.md` for detailed documentation
- Run `world_sampler_example.py` for Python examples
- Check `world_sampler_api.py` for API reference

---

**Ready to explore the world? 🌍✨**

Visit: https://deepgis.org/label/3d/search/


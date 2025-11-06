# DeepGIS Rock Tiles Configuration

> **Note**: Throughout this documentation, `$PROJECT_ROOT` refers to your project installation directory (e.g., `/path/to/your/project`), and `/path/to/rock-tiles/raw` refers to your tile storage location.

## Overview

High-resolution rock surface imagery served via two methods:
1. **Direct XYZ Tiles**: `rocks.deepgis.org`
2. **TileServer GL**: `mbtiles.deepgis.org`

## Tile Coverage

- **Zoom Levels**: 15-23
- **Total Size**: ~1.2 GB
- **Format**: PNG raster tiles
- **Coordinate System**: Web Mercator (EPSG:3857)
- **Source**: `/path/to/rock-tiles/raw/`

## Architecture

```
Rock Tiles
├── Direct Serving (nginx)
│   └── https://rocks.deepgis.org/{z}/{x}/{y}.png
│
└── TileServer GL (Docker)
    ├── https://mbtiles.deepgis.org/data/rock_tiles_deepgis/
    ├── MBTiles format (compressed)
    └── Built-in viewer & metadata
```

## Setup Instructions

### 1. Direct Tile Serving (nginx)

Added to `/etc/nginx/nginx.conf`:

```nginx
server {
    server_name rocks.deepgis.org;
    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/deepgis.org-0001/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/deepgis.org-0001/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/dhparams.pem;

    location / {
        root /path/to/rock-tiles/raw;
        expires 7d;
        add_header Cache-Control "public, immutable";
        add_header Access-Control-Allow-Origin "*" always;
        sendfile on;
        tcp_nopush on;
    }
}
```

**Test**: `curl -I https://rocks.deepgis.org/23/5892/12745.png`

### 2. TileServer GL Integration

#### Convert XYZ to MBTiles

```bash
cd $PROJECT_ROOT/dreams_laboratory/scripts

python3 convert_rocks_to_mbtiles.py \
    --tiles_dir /path/to/rock-tiles/raw \
    --output /tmp/rock_tiles_deepgis.mbtiles \
    --name "DeepGIS Rock Tiles" \
    --description "High-resolution rock surface imagery (zoom 15-23)"
```

#### Install MBTiles

```bash
# Move to tileserver data directory
mv /tmp/rock_tiles_deepgis.mbtiles $PROJECT_ROOT/deepgis-xr/data/

# Set permissions
chmod 644 $PROJECT_ROOT/deepgis-xr/data/rock_tiles_deepgis.mbtiles
```

#### Configuration

Added to `deepgis-xr/data/config.json`:

```json
"rock_tiles_deepgis": {
  "mbtiles": "rock_tiles_deepgis.mbtiles",
  "type": "raster",
  "serve_data": true,
  "serve_rendered": true,
  "maxzoom": 23,
  "minzoom": 15,
  "defaultzoom": 20,
  "center": [-111.26513, 33.78215, 18],
  "bounds": [-180, -85.0511, 180, 85.0511]
}
```

#### Restart TileServer

```bash
docker restart deepgis-xr_tileserver_1
```

## Usage Examples

### Leaflet.js

```javascript
// Option 1: Direct tiles (faster for single requests)
const directTiles = L.tileLayer('https://rocks.deepgis.org/{z}/{x}/{y}.png', {
    attribution: 'DeepGIS Rock Tiles',
    minZoom: 15,
    maxZoom: 23
});

// Option 2: TileServer GL (with metadata support)
const tileserverTiles = L.tileLayer(
    'https://mbtiles.deepgis.org/data/rock_tiles_deepgis/{z}/{x}/{y}.png',
    {
        attribution: 'DeepGIS Rock Tiles',
        minZoom: 15,
        maxZoom: 23
    }
);

// Add to map
directTiles.addTo(map);
```

### OpenLayers

```javascript
import TileLayer from 'ol/layer/Tile';
import XYZ from 'ol/source/XYZ';

const rockTiles = new TileLayer({
  source: new XYZ({
    url: 'https://rocks.deepgis.org/{z}/{x}/{y}.png',
    minZoom: 15,
    maxZoom: 23
  })
});

map.addLayer(rockTiles);
```

### Cesium (3D Globe)

```javascript
const rockImagery = new Cesium.UrlTemplateImageryProvider({
    url: 'https://rocks.deepgis.org/{z}/{x}/{y}.png',
    minimumLevel: 15,
    maximumLevel: 23,
    credit: 'DeepGIS Rock Tiles'
});

viewer.imageryLayers.addImageryProvider(rockImagery);
```

### Python (rasterio)

```python
import rasterio
from rasterio.io import MemoryFile
import requests

# Fetch a tile
z, x, y = 23, 5892, 12745
url = f'https://rocks.deepgis.org/{z}/{x}/{y}.png'
response = requests.get(url)

# Open as raster
with MemoryFile(response.content) as memfile:
    with memfile.open() as dataset:
        tile_data = dataset.read()
        print(f"Tile shape: {tile_data.shape}")
```

## Access URLs

### Direct XYZ Tiles
- **Pattern**: `https://rocks.deepgis.org/{z}/{x}/{y}.png`
- **Example**: https://rocks.deepgis.org/23/5892/12745.png
- **Viewers**: 
  - Leaflet: https://rocks.deepgis.org/leaflet.html
  - OpenLayers: https://rocks.deepgis.org/openlayers.html
  - Google Maps: https://rocks.deepgis.org/googlemaps.html

### TileServer GL
- **Home**: https://mbtiles.deepgis.org/
- **Rock Tiles Page**: https://mbtiles.deepgis.org/data/rock_tiles_deepgis/
- **Tile Pattern**: `https://mbtiles.deepgis.org/data/rock_tiles_deepgis/{z}/{x}/{y}.png`
- **TileJSON**: https://mbtiles.deepgis.org/data/rock_tiles_deepgis.json
- **Interactive Viewer**: https://mbtiles.deepgis.org/data/rock_tiles_deepgis/#18/33.78215/-111.26513

## Performance Considerations

| Method | Pros | Cons |
|--------|------|------|
| **Direct (rocks.deepgis.org)** | • Fastest for single tiles<br>• No container overhead<br>• Direct filesystem access | • No built-in viewer<br>• No metadata endpoint |
| **TileServer GL** | • Built-in viewer<br>• TileJSON metadata<br>• Better compression<br>• Caching | • Container overhead<br>• Slightly slower |

**Recommendation**: Use **direct tiles** for production mapping applications, **TileServer GL** for exploration and demos.

## File Structure

```
/path/to/rock-tiles/raw/
├── 15/                    # 28 KB
├── 16/                    # 88 KB
├── 17/                    # 324 KB
├── 18/                    # 1.3 MB
├── 19/                    # 4.8 MB
├── 20/                    # 19 MB
├── 21/                    # 72 MB
├── 22/                    # 261 MB
├── 23/                    # 823 MB
├── leaflet.html
├── openlayers.html
├── googlemaps.html
└── tilemapresource.xml

$PROJECT_ROOT/deepgis-xr/data/
└── rock_tiles_deepgis.mbtiles    # ~1.2 GB (compressed)
```

## Maintenance

### Update Tiles

If tiles are updated:

```bash
# 1. Update source tiles
# (tiles will be automatically served via rocks.deepgis.org)

# 2. Regenerate MBTiles
cd $PROJECT_ROOT/dreams_laboratory/scripts
python3 convert_rocks_to_mbtiles.py \
    --tiles_dir /path/to/rock-tiles/raw \
    --output /tmp/rock_tiles_deepgis_new.mbtiles

# 3. Replace old MBTiles
mv /tmp/rock_tiles_deepgis_new.mbtiles \
   $PROJECT_ROOT/deepgis-xr/data/rock_tiles_deepgis.mbtiles

# 4. Restart TileServer
docker restart deepgis-xr_tileserver_1
```

### Check Status

```bash
# Check nginx
systemctl status nginx
curl -I https://rocks.deepgis.org/23/5892/12745.png

# Check TileServer
docker ps | grep tileserver
docker logs deepgis-xr_tileserver_1 --tail 50
curl -I https://mbtiles.deepgis.org/data/rock_tiles_deepgis.json
```

### Troubleshooting

**Tiles not loading (rocks.deepgis.org)**:
```bash
# Check permissions
ls -la /path/to/rock-tiles/raw/23/

# Check nginx config
nginx -t

# Check nginx logs
tail -f /var/log/nginx/error.log
```

**Tiles not in TileServer**:
```bash
# Check if MBTiles exists
ls -lh $PROJECT_ROOT/deepgis-xr/data/rock_tiles_deepgis.mbtiles

# Check container mount
docker inspect deepgis-xr_tileserver_1 | grep Mounts -A 10

# Check inside container
docker exec deepgis-xr_tileserver_1 ls -la /data/ | grep rock

# Validate config
python3 -m json.tool $PROJECT_ROOT/deepgis-xr/data/config.json

# Check logs
docker logs deepgis-xr_tileserver_1
```

## VLM/ML Integration

Rock tiles can be used with Vision-Language Models and machine learning pipelines:

### Extract Embeddings

```python
from dreams_laboratory.scripts.vlm_clip_simple import SimpleCLIPEmbedder

# Initialize CLIP
clip = SimpleCLIPEmbedder()

# Extract embeddings from rock tiles
tile_paths = glob.glob('/path/to/rock-tiles/raw/23/*/*.png')
embeddings = clip.encode_images(tile_paths[:1000])

# Search for rock types
results = clip.text_to_image_search(
    "granite with large crystals",
    embeddings,
    tile_paths[:1000]
)
```

### Semi-Supervised Labeling

Rock tiles can be loaded into the semi-supervised labeling interface:
- **URL**: https://deepgis.org/label/semi-supervised/
- **Features**: Mask2Former + Segment Anything integration
- **Workflow**: Generate labels → Refine → Save to database

## Related Documentation

- [VLM Research Guide](../dreams_laboratory/scripts/VLM_RESEARCH_GUIDE.md)
- [Segmentation Assisted Labeling](../dreams_laboratory/scripts/segmentation_assisted_labeling.py)
- [TileServer GL Docs](README_TOPOLOGY_SERVER.md)

## Contact & Support

- **Repository**: Earth-Innovation-Hub/deepgis-xr
- **Issues**: https://github.com/Earth-Innovation-Hub/deepgis-xr/issues
- **Documentation**: https://deepgis.org/

---

*Last Updated: November 6, 2025*


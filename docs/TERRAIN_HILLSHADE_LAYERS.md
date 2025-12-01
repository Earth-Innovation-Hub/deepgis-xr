# Terrain/DEM and Hillshade Layers - Implementation Analysis

## Overview

The map_label frontend implements terrain visualization through multiple layer types:
- **Terrain/DEM Layer**: Colorized elevation data
- **Hillshade Layer**: Shaded relief visualization
- **Contour Lines Layer**: Elevation contour lines

## Architecture

### 1. UI Controls (HTML)

**Location**: `map_label.html` - Layers Panel (HUD)

**Checkboxes**:
- `terrainLayerToggle` - Toggles Terrain/DEM layer
- `hillshadeLayerToggle` - Toggles Hillshade layer  
- `contourLayerToggle` - Toggles Contour Lines layer

**Settings Panel** (shown when any terrain layer is active):
- `elevationColorScheme` - Dropdown for color scheme selection
  - Options: Terrain, Rainbow, Grayscale, Viridis
- `terrainOpacity` - Slider (0-100%) for terrain layer opacity
- `opacityValue` - Display of current opacity percentage

**Code Location**: Lines 763-803 in `map_label.html`

### 2. Layer Creation Functions

#### `createTerrainLayer(colorScheme)`
**Location**: Lines 1262-1324

**Purpose**: Creates a terrain/DEM layer with configurable color schemes

**Tile Sources**:
- `terrain`: Esri World Terrain Base (default)
  - URL: `https://server.arcgisonline.com/ArcGIS/rest/services/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}`
  - Max Zoom: 13
- `rainbow`: Same as terrain (colorized elevation)
- `grayscale`: Esri World Light Gray Base
  - URL: `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`
  - Max Zoom: 16
- `viridis`: OpenTopoMap
  - URL: `https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png`
  - Max Zoom: 17
  - Subdomains: ['a', 'b', 'c']

**Configuration**:
- Opacity: From `window.globals.terrainSettings.opacity` (default: 0.7)
- zIndex: 2 (above base map, below raster/vector)
- Error handling: Transparent pixel fallback
- Cross-origin: Enabled

#### `createHillshadeLayer()`
**Location**: Lines 1327-1348

**Purpose**: Creates a hillshade (shaded relief) layer

**Tile Source**:
- Esri World Hillshade
- URL: `https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}`
- Max Zoom: 13
- Opacity: 0.5 (fixed)
- zIndex: 1 (below terrain, above base map)

#### `createContourLayer()`
**Location**: Lines 1351-1373

**Purpose**: Creates contour lines layer

**Tile Source**:
- OpenTopoMap (includes contour lines)
- URL: `https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png`
- Max Zoom: 17
- Opacity: 0.6 (fixed)
- zIndex: 3 (above terrain)
- Subdomains: ['a', 'b', 'c']

### 3. Event Handlers

**Location**: Lines 1625-1710

#### Terrain Layer Toggle (Lines 1641-1659)
```javascript
terrainLayerToggle.addEventListener('change', (e) => {
    if (e.target.checked) {
        // Create layer if doesn't exist
        if (!window.globals.currentLayers.terrain) {
            window.globals.currentLayers.terrain = createTerrainLayer(
                window.globals.terrainSettings.colorScheme
            );
        }
        // Add to map
        if (window.globals.currentLayers.terrain) {
            window.globals.currentLayers.terrain.addTo(window.globals.map);
        }
    } else {
        // Remove from map
        if (window.globals.currentLayers.terrain) {
            window.globals.map.removeLayer(window.globals.currentLayers.terrain);
        }
    }
    updateTerrainControlsVisibility();
    maintainLayerOrder();
});
```

#### Hillshade Layer Toggle (Lines 1661-1679)
- Similar pattern to terrain toggle
- Creates `createHillshadeLayer()` if needed
- Adds/removes from map based on checkbox state

#### Contour Layer Toggle (Lines 1681-1699)
- Similar pattern
- Uses `createContourLayer()`

### 4. Settings Controls

#### Color Scheme Selector (Lines 1702-1704)
```javascript
elevationColorScheme.addEventListener('change', (e) => {
    updateTerrainColorScheme(e.target.value);
});
```

**Function**: `updateTerrainColorScheme(scheme)` (Lines 1384-1393)
- Updates `window.globals.terrainSettings.colorScheme`
- Removes old terrain layer
- Creates new layer with selected scheme
- Re-adds to map
- Maintains layer order

#### Opacity Slider (Lines 1706-1710)
```javascript
terrainOpacity.addEventListener('input', (e) => {
    const opacity = parseInt(e.target.value);
    opacityValue.textContent = `${opacity}%`;
    updateTerrainOpacity(opacity);
});
```

**Function**: `updateTerrainOpacity(opacity)` (Lines 1376-1381)
- Converts percentage (0-100) to decimal (0-1)
- Updates `window.globals.terrainSettings.opacity`
- Applies to existing terrain layer via `setOpacity()`

### 5. Layer Ordering

**Function**: `maintainLayerOrder()` (Lines 1396-1416)

**Order** (bottom to top):
1. Base map
2. Hillshade (zIndex: 1)
3. Terrain (zIndex: 2)
4. Raster
5. Contour (zIndex: 3)
6. Vector
7. Drawn items (top)

**Implementation**:
- Uses `bringToBack()` for hillshade
- Uses `bringToFront()` for other layers
- Ensures proper visual stacking

### 6. State Management

**Global State**: `window.globals`

**Properties**:
```javascript
window.globals.currentLayers = {
    terrain: null,      // L.TileLayer instance
    hillshade: null,   // L.TileLayer instance
    contour: null,      // L.TileLayer instance
    raster: null,
    vector: null
};

window.globals.terrainSettings = {
    colorScheme: 'terrain',  // 'terrain', 'rainbow', 'grayscale', 'viridis'
    opacity: 0.7             // 0.0 to 1.0
};
```

### 7. UI Visibility Logic

**Function**: `updateTerrainControlsVisibility()` (Lines 1634-1639)

**Logic**:
- Shows terrain controls panel if ANY terrain-related layer is active
- Checks: `terrainLayerToggle.checked || hillshadeLayerToggle.checked || contourLayerToggle.checked`
- Called whenever any terrain layer toggle changes

## Data Flow

```
User Action
    ↓
Checkbox Toggle (terrainLayerToggle/hillshadeLayerToggle)
    ↓
Event Handler
    ↓
Check if layer exists in window.globals.currentLayers
    ↓
If not exists: Create layer (createTerrainLayer/createHillshadeLayer)
    ↓
Add layer to map (map.addLayer())
    ↓
Update UI visibility (updateTerrainControlsVisibility)
    ↓
Maintain layer order (maintainLayerOrder)
```

## Settings Flow

```
User Changes Color Scheme
    ↓
elevationColorScheme change event
    ↓
updateTerrainColorScheme(scheme)
    ↓
Remove old terrain layer
    ↓
Create new terrain layer with new scheme
    ↓
Add to map
    ↓
maintainLayerOrder()

User Changes Opacity
    ↓
terrainOpacity input event
    ↓
updateTerrainOpacity(value)
    ↓
Update globals.terrainSettings.opacity
    ↓
Apply to existing layer (setOpacity)
```

## Issues & Observations

### 1. **Hillshade Opacity Fixed**
- Hillshade opacity is hardcoded to 0.5 (line 1331)
- No UI control to adjust it
- **Recommendation**: Add opacity slider for hillshade

### 2. **Contour Layer Uses OpenTopoMap**
- Contour layer is actually OpenTopoMap tiles (includes contours)
- Not a pure contour-only layer
- **Note**: This is a limitation of using tile services

### 3. **Color Scheme Limitations**
- Some color schemes (rainbow, viridis) use the same tile source as terrain
- Actual colorization happens server-side by Esri/OpenTopoMap
- Cannot customize color ramps client-side

### 4. **Error Handling**
- All layer creation functions have try-catch blocks
- Tile errors are logged but don't break the UI
- Transparent pixel fallback for missing tiles

### 5. **Layer Lifecycle**
- Layers are created once and reused (stored in `window.globals.currentLayers`)
- When toggled off, layer is removed from map but not destroyed
- When toggled back on, same layer instance is re-added
- **Exception**: Terrain layer is recreated when color scheme changes

## Potential Improvements

1. **Add hillshade opacity control** - Currently fixed at 0.5
2. **Add contour opacity control** - Currently fixed at 0.6
3. **Layer caching** - Consider destroying unused layers to free memory
4. **Custom DEM data** - Support for local/custom DEM tile sources
5. **Elevation query** - Add ability to query elevation at click point
6. **3D terrain** - Consider integration with 3D terrain rendering

## Dependencies

- **Leaflet.js**: Core mapping library
- **L.TileLayer**: For tile-based terrain/hillshade layers
- **External Services**:
  - Esri ArcGIS Online (terrain, hillshade)
  - OpenTopoMap (contour lines, viridis scheme)

## Related Files

- `deepgis-xr/deepgis_xr/apps/web/templates/web/map_label.html` - Main implementation
- `deepgis-xr/staticfiles/scripts/webclient/map_label.js` - Map initialization (no terrain code here)


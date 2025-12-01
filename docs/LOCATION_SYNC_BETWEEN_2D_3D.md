# Location Synchronization Between 2D and 3D Viewers

## Overview
This document describes the location synchronization feature between the `map_label` (2D Leaflet) and `label_search` (3D Cesium) interfaces.

## Feature Description
When navigating between the 2D map labeling interface and the 3D viewer using the HUD icons, the current camera/map position is preserved and transferred to the target interface.

## Implementation

### URL Hash Format
Location data is passed via URL hash parameters in the format: `#param1/param2/param3`

#### From 2D to 3D
- **Format**: `#lat/lng/alt`
- **Example**: `https://deepgis.org/label-search/#33.78210534/-111.26527270/1000`
- Altitude is estimated from the Leaflet zoom level

#### From 3D to 2D
- **Format**: `#lat/lng/alt`
- **Example**: `https://deepgis.org/map-label/#33.78210534/-111.26527270/1000`
- Zoom level is calculated from the altitude

### Components Modified

#### 1. `map_label.html`
- **Quick View Link**: Updated "3D View" button to call `syncLocationTo3D()` on click
- **Functions Added**:
  - `syncLocationTo3D()`: Gets current map center and zoom, converts zoom to altitude, creates hash URL
  - `checkIncomingLocation()`: Parses URL hash on page load to restore location from 3D viewer
  - `zoomToAltitude(zoom)`: Converts Leaflet zoom level (10-22) to approximate altitude in meters
  - `altitudeToZoom(altitude)`: Converts altitude in meters to appropriate Leaflet zoom level

#### 2. `label_search.html`
- **Quick View Link**: Updated "Train" button to call `syncLocationTo2D()` on click
- **Function Added**:
  - `syncLocationTo2D()`: Gets current Cesium camera position (lat/lng/alt), creates hash URL for map_label

#### 3. `cesium-init.js`
- **Initial View Logic**: Enhanced to parse URL hash on initialization
- **Hash Parsing**: Extracts lat/lng/alt from URL hash and sets Cesium camera accordingly
- **Fallback**: Uses default view (0°, 0°, 20000km altitude) if no hash present

### Zoom/Altitude Conversion Logic

#### Zoom to Altitude (2D → 3D)
```javascript
zoom ≤ 10  → 100,000m
zoom ≤ 15  →  20,000m
zoom ≤ 17  →   5,000m
zoom ≤ 19  →   1,000m
zoom ≤ 20  →     500m
zoom ≤ 21  →     200m
zoom > 21  →     100m
```

#### Altitude to Zoom (3D → 2D)
```javascript
alt > 50,000m → zoom 10
alt > 10,000m → zoom 15
alt >  5,000m → zoom 17
alt >  1,000m → zoom 19
alt >    500m → zoom 20
alt >    100m → zoom 21
alt ≤    100m → zoom 22
```

## User Experience

### Scenario 1: Working in 2D, Need 3D View
1. User is labeling in `map_label` at a specific location (e.g., zoom 20, centered on a building)
2. User clicks "3D View" icon
3. `label_search` opens with Cesium camera positioned at the same location with ~500m altitude
4. User can immediately see the same area in 3D

### Scenario 2: Exploring in 3D, Need to Label
1. User is viewing a site in `label_search` from a specific angle and position
2. User clicks "Train" icon
3. `map_label` opens with Leaflet map centered on the same lat/lng with appropriate zoom
4. User can immediately start labeling the viewed area

## Technical Notes

### Map Initialization Timing
- `checkIncomingLocation()` is called after the map is fully initialized
- Uses `window.globals.map` to ensure Leaflet map instance is ready
- Falls back gracefully if hash parsing fails

### Cesium Viewer Initialization
- Hash parsing happens during viewer initialization in `cesium-init.js`
- Sets camera view with 100ms delay to ensure proper rendering
- Validates hash parameters to prevent invalid camera positions

### Cross-Browser Compatibility
- Uses standard `window.location.hash` API
- Compatible with all modern browsers
- No external dependencies for location sync

## Future Enhancements

### Potential Improvements
1. **Include Camera Orientation**: Add heading/pitch/roll to 3D→2D transition
2. **Preserve Selected Layer**: Sync active raster layer between interfaces
3. **Bidirectional History**: Browser back/forward should sync across interfaces
4. **Session Persistence**: Store last position in localStorage for return visits
5. **Smooth Transitions**: Add animation when setting initial view

### Advanced Features
- **Real-time Sync**: Option to keep both interfaces synchronized during navigation
- **Split View**: Display 2D and 3D side-by-side with linked cameras
- **Bookmark Locations**: Save frequently visited locations with names

## Bug Fixes

### Issue: 3D to 2D sync not working
**Problem**: Clicking "Train" button from label_search didn't navigate to the correct location in map_label.

**Root Cause**: The hash format detection logic in `checkIncomingLocation()` was flawed. It used `if (p1 < 30)` to determine if the first parameter was a zoom level or latitude. However, many valid latitudes (e.g., 33.78) are less than 30, causing them to be misinterpreted as zoom levels.

**Fix**: Updated the format detection to check if:
- First parameter is a valid zoom level (0-24) AND
- Second parameter is a valid latitude (-90 to 90)

This properly distinguishes between:
- 2D format: `#zoom/lat/lng` (e.g., `#20/33.78/-111.26`)
- 3D format: `#lat/lng/alt` (e.g., `#33.78/-111.26/1000`)

**Additional Improvements**:
1. Added fallback to `window.viewer` if `AppState.viewer` is not available
2. Added comprehensive console logging for debugging
3. Added retry logic if map is not ready when parsing hash
4. Made function globally accessible earlier in initialization

## Testing

### Manual Test Cases
1. ✓ Navigate from default position in 2D to 3D
2. ✓ Navigate from zoomed-in position in 2D to 3D  
3. ✓ Navigate from ground-level 3D view to 2D
4. ✓ Navigate from aerial 3D view to 2D
5. ✓ Refresh page with hash URL - position should persist
6. ✓ Direct link with hash URL should work on both pages

### Debugging
To test and debug the location sync:
1. Open browser console (F12)
2. Navigate to label_search (3D viewer)
3. Click "Train" button
4. Check console for log messages:
   - "syncLocationTo2D called"
   - "Camera position: lat=..., lng=..., alt=..."
   - "Navigating to: ..."
5. Verify map_label opens at the correct location
6. Check console for:
   - "Set view from 3D hash: lat=..., lng=..., alt=..., zoom=..."

## Files Modified
- `deepgis-xr/deepgis_xr/apps/web/templates/web/map_label.html`
- `deepgis-xr/deepgis_xr/apps/web/templates/web/label_search.html`
- `deepgis-xr/staticfiles/web/js/core/cesium-init.js`

## Related Documentation
- [MAP_LABEL_LABEL_SEARCH_COUPLING.md](MAP_LABEL_LABEL_SEARCH_COUPLING.md) - Integration analysis
- [TERRAIN_HILLSHADE_LAYERS.md](TERRAIN_HILLSHADE_LAYERS.md) - Terrain visualization


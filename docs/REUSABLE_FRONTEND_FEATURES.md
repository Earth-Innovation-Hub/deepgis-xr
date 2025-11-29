# Reusable Frontend Features for Mask2Former Correction Interface

## Overview

This document identifies frontend features from `label.html` and `map_label.html` that can be reused for the Mask2Former correction interface.

---

## 1. Drawing & Editing Tools (from `label.html`)

### Paper.js-based Drawing System

**Location:** `deepgis_xr/apps/web/templates/web/label.html` (lines 1335-1575)

#### Reusable Components:

1. **Tool System Architecture**
   ```javascript
   // Tool activation pattern
   const penTool = new paper.Tool();
   penTool.onMouseDown = function(event) { ... };
   penTool.onMouseDrag = function(event) { ... };
   penTool.onMouseUp = function(event) { ... };
   tool.activate();
   ```

2. **Shape Drawing Tools**
   - **Pen Tool** (lines 1336-1370): Freehand drawing
   - **Polygon Tool** (lines 1372-1414): Click-to-add-points polygon
   - **Rectangle Tool** (lines 1416-1493): Drag-to-draw rectangle
   - **Circle Tool** (lines 1495-1571): Drag-to-draw circle
   - **Remove Tool** (lines 1575-1585): Click-to-delete shapes

3. **Shape Finalization** (line 1247)
   ```javascript
   function finalizeShape(path) {
       path.strokeColor = currentColor;
       path.strokeWidth = 2;
       path.fillColor = globals.blueprintStyle.shapes.fillColor;
       path.data = {
           category: currentCategory,
           color: currentColor,
           createdAt: new Date().getTime()
       };
       addToUndoStack(path);
       return path;
   }
   ```

4. **Undo/Redo System** (lines 1215-1244)
   ```javascript
   function addToUndoStack(path) {
       globals.undos.push(path);
       globals.redos = [];
   }
   
   function undoLastOperation() {
       if (globals.undos.length > 0) {
           const lastItem = globals.undos.pop();
           globals.redos.push(lastItem);
           lastItem.remove();
           paper.view.update();
       }
   }
   ```

5. **Coordinate Conversion** (lines 1271-1293)
   ```javascript
   function getAdjustedPoint(event) {
       const canvas = document.getElementById('canvas');
       const rect = canvas.getBoundingClientRect();
       const scaleX = canvas.width / rect.width;
       const scaleY = canvas.height / rect.height;
       const x = (event.clientX - rect.left) * scaleX;
       const y = (event.clientY - rect.top) * scaleY;
       return paper.view.viewToProject(new paper.Point(x, y));
   }
   ```

**Reuse Strategy:**
- Adapt Paper.js tools for Cesium polygon editing
- Use same undo/redo pattern with Cesium entities
- Convert Paper.js coordinate system to Cesium Cartesian3

---

## 2. Category Selection System (from `label.html`)

**Location:** Lines 199-300 (category list rendering)

### Reusable Components:

1. **Category List UI**
   ```html
   <ul id="categories_coll">
       <li data-category="category_name" style="background-color: rgb(...)">
           <span class="category-name">Category Name</span>
           <span class="category-color" style="background-color: rgb(...)"></span>
       </li>
   </ul>
   ```

2. **Category Selection Handler**
   ```javascript
   $('#categories_coll li').click(function() {
       currentCategory = $(this).data('category');
       currentColor = $(this).find('.category-color').css('background-color');
       // Update UI to show selected category
   });
   ```

**Reuse Strategy:**
- Reuse category selection UI component
- Adapt for changing category of existing predictions
- Use same color coding system

---

## 3. Save Labels Functionality (from `label.html`)

**Location:** Lines 1764-1900

### Reusable Components:

1. **GeoJSON Conversion** (lines 1782-1830)
   ```javascript
   function saveLabels() {
       const features = [];
       
       paper.project.activeLayer.children.forEach(function(child) {
           if (!child.data || !child.data.category) return;
           
           const feature = {
               type: 'Feature',
               geometry: {
                   type: getGeometryType(child),
                   coordinates: getCoordinates(child)
               },
               properties: {
                   category: child.data.category,
                   color: child.data.color,
                   createdAt: child.data.createdAt
               }
           };
           features.push(feature);
       });
       
       const geojson = {
           type: 'FeatureCollection',
           features: features
       };
       
       // Save via API
       fetch('/label/api/save-labels/', {
           method: 'POST',
           body: JSON.stringify({
               image_id: currentImageId,
               labels: geojson,
               user_id: currentUserId
           })
       });
   }
   ```

2. **Geometry Type Detection**
   ```javascript
   function getGeometryType(path) {
       if (path instanceof paper.Path.Rectangle) return 'Polygon';
       if (path instanceof paper.Path.Circle) return 'Polygon';
       if (path.closed) return 'Polygon';
       return 'LineString';
   }
   ```

3. **Coordinate Extraction**
   ```javascript
   function getCoordinates(path) {
       const coords = path.segments.map(seg => [seg.point.x, seg.point.y]);
       if (path.closed) {
           return [coords]; // Polygon format
       }
       return coords; // LineString format
   }
   ```

**Reuse Strategy:**
- Adapt for Cesium entities → GeoJSON conversion
- Use same API endpoint pattern (`save_assisted_labels`)
- Reuse GeoJSON structure for COCO conversion

---

## 4. Map-based Drawing (from `map_label.html`)

**Location:** Lines 1279-1327

### Reusable Components:

1. **Leaflet Draw Integration**
   ```javascript
   const drawControl = new L.Control.Draw({
       edit: {
           featureGroup: window.globals.drawnItems,
           edit: {
               selectedPathOptions: {
                   maintainColor: true,
                   opacity: 0.7,
                   dashArray: '10, 10'
               }
           }
       },
       draw: {
           polygon: {
               allowIntersection: false,
               showArea: true,
               shapeOptions: {
                   color: '#ff0000',
                   fillOpacity: 0.3
               }
           },
           rectangle: { ... },
           circle: { ... }
       }
   });
   ```

2. **Shape Editing Events**
   ```javascript
   window.globals.map.on(L.Draw.Event.CREATED, (e) => {
       const layer = e.layer;
       window.globals.drawnItems.addLayer(layer);
   });
   
   window.globals.map.on(L.Draw.Event.EDITED, (e) => {
       const layers = e.layers;
       layers.eachLayer(function(layer) {
           // Update tooltips, measurements, etc.
       });
   });
   
   window.globals.map.on(L.Draw.Event.DELETED, (e) => {
       const layers = e.layers;
       layers.eachLayer(function(layer) {
           // Cleanup
       });
   });
   ```

**Reuse Strategy:**
- Use Cesium's entity editing instead of Leaflet Draw
- Adapt event pattern for Cesium entity changes
- Reuse shape styling patterns (opacity, color, dash arrays)

---

## 5. UI Components & Styling

### Sidebar Control Panel (from `label.html`)

**Location:** Lines 27-64

```css
.control-sidebar {
    width: 300px;
    padding: 15px;
    background-color: #f8f9fa;
    border-left: 1px solid #e9ecef;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
}

/* Mobile responsive */
@media (max-width: 768px) {
    .control-sidebar {
        position: absolute;
        width: 85%;
        max-width: 320px;
        transform: translateX(100%);
    }
    .control-sidebar.expanded {
        transform: translateX(0);
    }
}
```

**Reuse Strategy:**
- Reuse sidebar layout for correction panel
- Adapt for training dataset selection UI
- Use same mobile-responsive patterns

### Tool Buttons (from `label.html`)

**Location:** Lines 159-169

```html
<div class="tool-buttons">
    <button id="pen_button" class="btn btn-sm btn-outline-primary">Pen</button>
    <button id="polygon_button" class="btn btn-sm btn-outline-primary">Polygon</button>
    <button id="rectangle_button" class="btn btn-sm btn-outline-primary">Rectangle</button>
    <button id="circle_button" class="btn btn-sm btn-outline-primary">Circle</button>
    <button id="remove_button" class="btn btn-sm btn-outline-danger">Remove</button>
    <button id="undo_button" class="btn btn-sm btn-outline-secondary">Undo</button>
</div>
```

**Reuse Strategy:**
- Reuse button styling and layout
- Adapt for prediction correction tools:
  - "Edit Mask"
  - "Change Category"
  - "Delete Prediction"
  - "Add New Annotation"

### Status Messages (from `label_semi_supervised.html`)

**Location:** Lines 183-217

```html
<div id="statusMessage"></div>

<script>
function showStatusMessage(message, type = 'info') {
    const statusEl = document.getElementById('statusMessage');
    statusEl.textContent = message;
    statusEl.className = type;
    statusEl.style.display = 'block';
    
    if (type !== 'loading') {
        setTimeout(() => {
            statusEl.style.display = 'none';
        }, 3000);
    }
}
</script>
```

**Reuse Strategy:**
- Reuse status message component
- Use for training dataset save confirmations
- Show correction progress

---

## 6. Image Loading & Display (from `label.html`)

**Location:** Lines 2174-2345

### Reusable Components:

1. **Image Loading with Paper.js**
   ```javascript
   function drawImageOnCanvas(imagePath, width, height, rotation) {
       const raster = new paper.Raster(imagePath);
       raster.onLoad = function() {
           raster.position = paper.view.center;
           raster.size = new paper.Size(width, height);
           if (rotation) {
               raster.rotate(rotation);
           }
           globals.raster = raster;
           globals.imageLoaded = true;
           paper.view.update();
       };
   }
   ```

2. **Loading Overlay**
   ```javascript
   function showLoadingOverlay(message = "Loading...") {
       if ($('#loading-overlay').length === 0) {
           $('body').append(`
               <div id="loading-overlay">
                   <div class="spinner-border"></div>
                   <div class="loading-text">${message}</div>
               </div>
           `);
       }
   }
   ```

**Reuse Strategy:**
- Adapt for loading Mask2Former prediction images
- Use same loading overlay pattern
- Reuse image display logic (centering, sizing)

---

## 7. Measurement Tools (from `label.html`)

**Location:** Lines 739-1000

### Reusable Components:

1. **Measurement Tool Initialization**
   ```javascript
   function initializeMeasurementTool() {
       const measureTool = new paper.Tool();
       measureTool.onMouseDown = function(event) {
           globals.measureStartPoint = event.point;
           globals.isMeasuring = true;
       };
       measureTool.onMouseDrag = function(event) {
           // Draw measurement line
       };
       measureTool.onMouseUp = function(event) {
           // Calculate and display distance
       };
       return measureTool;
   }
   ```

**Reuse Strategy:**
- Optional: Add measurement tools for mask area calculation
- Useful for validating annotation quality

---

## 8. Category Management (from `label.html`)

**Location:** Lines 199-300

### Reusable Components:

1. **Dynamic Category Loading**
   ```javascript
   function loadCategories() {
       fetch('/api/categories/')
           .then(response => response.json())
           .then(categories => {
               categories.forEach(cat => {
                   const li = $('<li>')
                       .data('category', cat.name)
                       .css('background-color', cat.color)
                       .appendTo('#categories_coll');
               });
           });
   }
   ```

2. **Category Color Display**
   ```javascript
   function getCategoryColor(categoryName) {
       const category = categories.find(c => c.name === categoryName);
       return category ? category.color : '#ff0000';
   }
   ```

**Reuse Strategy:**
- Reuse for displaying prediction categories
- Use for category change dropdown
- Maintain color consistency

---

## 9. Clear/Reset Functionality (from `label.html`)

**Location:** Lines 2363-2383

```javascript
function clearAnnotations() {
    paper.project.activeLayer.children.forEach(function(child) {
        if (child !== globals.raster) {
            child.remove();
        }
    });
    
    globals.undos = [];
    globals.redos = [];
    paper.view.update();
    showSuccessMessage("All annotations cleared");
}
```

**Reuse Strategy:**
- Adapt for "Clear All Corrections" button
- Reset correction state
- Maintain original predictions

---

## 10. Save API Integration Pattern (from `label.html`)

**Location:** Lines 1832-1900

```javascript
function saveLabels() {
    // ... collect features ...
    
    fetch('/label/api/save-labels/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({
            image_id: currentImageId,
            labels: geojson,
            user_id: currentUserId,
            metadata: {
                timeTaken: timeElapsed
            }
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            showSuccessMessage('Labels saved successfully!');
        } else {
            showErrorMessage('Error saving labels: ' + data.message);
        }
    })
    .catch(error => {
        showErrorMessage('Network error: ' + error.message);
    });
}
```

**Reuse Strategy:**
- Use same pattern for `save_assisted_labels()` endpoint
- Add `training_dataset_id` parameter
- Add `source_prediction_id` parameter
- Add `corrections` array

---

## Implementation Recommendations

### High Priority Reuse:

1. **GeoJSON Conversion Logic** (from `saveLabels()`)
   - Directly reusable for Cesium → GeoJSON conversion
   - Minimal adaptation needed

2. **Undo/Redo System**
   - Adapt for Cesium entity undo/redo
   - Same pattern, different storage (entities vs Paper.js paths)

3. **Category Selection UI**
   - Reuse HTML/CSS structure
   - Adapt for category change dropdown

4. **Save API Pattern**
   - Reuse fetch pattern and error handling
   - Extend with training dataset parameters

5. **Status Message System**
   - Directly reusable
   - No changes needed

### Medium Priority Reuse:

6. **Tool Button Layout**
   - Reuse styling and structure
   - Adapt tool names for correction interface

7. **Sidebar Control Panel**
   - Reuse layout and responsive design
   - Adapt content for correction controls

8. **Loading Overlay**
   - Directly reusable
   - Use for prediction loading

### Low Priority / Optional:

9. **Measurement Tools**
   - Optional feature for mask area validation
   - Nice-to-have, not essential

10. **Image Loading Logic**
    - Only if displaying prediction images separately
    - Cesium handles image display differently

---

## Code Reuse Examples

### Example 1: Adapting GeoJSON Conversion

```javascript
// Original (Paper.js)
function getCoordinates(path) {
    const coords = path.segments.map(seg => [seg.point.x, seg.point.y]);
    return path.closed ? [coords] : coords;
}

// Adapted (Cesium)
function cesiumEntityToGeoJSON(entity) {
    const hierarchy = entity.polygon.hierarchy.getValue();
    const coords = hierarchy.map(cartesian => {
        const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
        return [
            Cesium.Math.toDegrees(cartographic.longitude),
            Cesium.Math.toDegrees(cartographic.latitude)
        ];
    });
    
    return {
        type: 'Feature',
        geometry: {
            type: 'Polygon',
            coordinates: [coords]
        },
        properties: {
            category: entity.properties.category.getValue(),
            confidence: entity.properties.confidence.getValue()
        }
    };
}
```

### Example 2: Adapting Undo/Redo

```javascript
// Original (Paper.js)
globals.undos = [];
function addToUndoStack(path) {
    globals.undos.push(path);
}

// Adapted (Cesium)
corrector.undos = [];
function addToUndoStack(entity) {
    // Clone entity state
    const state = {
        id: entity.id,
        polygon: entity.polygon.hierarchy.getValue(),
        properties: {
            category: entity.properties.category.getValue(),
            confidence: entity.properties.confidence.getValue()
        }
    };
    corrector.undos.push(state);
}

function undoLastOperation() {
    if (corrector.undos.length > 0) {
        const state = corrector.undos.pop();
        const entity = corrector.viewer.entities.getById(state.id);
        if (entity) {
            // Restore state
            entity.polygon.hierarchy = state.polygon;
            entity.properties.category = state.properties.category;
            entity.properties.confidence = state.properties.confidence;
        }
    }
}
```

### Example 3: Reusing Save Pattern

```javascript
// Original
fetch('/label/api/save-labels/', {
    method: 'POST',
    body: JSON.stringify({
        image_id: currentImageId,
        labels: geojson
    })
});

// Adapted for corrections
fetch('/label/semi-supervised/api/save-labels/', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCookie('csrftoken')
    },
    body: JSON.stringify({
        image_id: imageInfo.image_id,
        labels: correctedGeojson,
        user_id: getCurrentUserId(),
        training_dataset_id: selectedDatasetId,  // NEW
        source_prediction_id: sessionId,         // NEW
        corrections: correctionsArray            // NEW
    })
})
.then(response => response.json())
.then(data => {
    if (data.success) {
        showStatusMessage('Corrections saved to training dataset!', 'success');
    } else {
        showStatusMessage('Error: ' + data.error, 'error');
    }
});
```

---

## Summary

**Directly Reusable (80%+ code reuse):**
- GeoJSON conversion patterns
- Save API integration pattern
- Status message system
- Loading overlay
- Category selection UI structure
- Sidebar layout and styling

**Adaptable (50-80% code reuse):**
- Undo/redo system
- Tool button layout
- Clear/reset functionality
- Category management

**Conceptual Reuse (20-50% code reuse):**
- Drawing tool architecture
- Measurement tools
- Image loading (different context)

**Total Estimated Reuse:** ~60-70% of frontend code can be adapted from existing label interfaces.


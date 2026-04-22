/**
 * Mask2Former Prediction Corrector
 * Allows users to correct predictions and add to training datasets
 * 
 * Adapts reusable components from label.html and map_label.html
 */

class Mask2FormerCorrector {
    constructor(cesiumViewer) {
        this.viewer = cesiumViewer;
        this.currentSession = null;
        this.currentDataset = null;
        this.predictions = [];
        this.corrections = [];
        this.entities = [];
        this.currentCategory = null;
        this.currentColor = '#ff0000';
        this.selectedIndex = undefined;
        this.editMode = false;
        this.categoryChangeMode = false;
        this.drawMode = false;
        
        // Reuse: Undo/redo system (adapted from label.html lines 1215-1244)
        this.undos = [];
        this.redos = [];
        
        // Reuse: Status message system (from label_semi_supervised.html)
        this.statusMessageEl = null;
        
        // Entity editing state
        this.editingEntity = null;
        this.editHandlers = [];
        
        // Polygon drawing state
        this.drawingPolygon = false;
        this.polygonPoints = [];
        this.tempEntity = null;
    }
    
    /**
     * Load prediction results for correction
     * Uses data from page context or fetches from API
     */
    async loadPrediction(sessionId) {
        try {
            this.showStatusMessage('Loading prediction results...', 'loading');
            
            let geojsonData = null;
            
            // Try to get data from page context first (faster, no API call needed)
            if (window.mask2formerPredictionData && 
                window.mask2formerPredictionData.sessionId === sessionId &&
                window.mask2formerPredictionData.geojson) {
                geojsonData = window.mask2formerPredictionData.geojson;
                console.log('Using prediction data from page context');
            } else {
                // Fallback: Try to load from file system via API
                // Load GeoJSON directly from the session directory
                try {
                    const geojsonPath = `/label/ai-analysis/geojson/${sessionId}/`;
                    const response = await fetch(geojsonPath);
                    if (response.ok) {
                        geojsonData = await response.json();
                        console.log('Loaded prediction data from API');
                    } else {
                        throw new Error(`GeoJSON not found: ${response.statusText}`);
                    }
                } catch (apiError) {
                    console.warn('Could not load from API, trying alternative method:', apiError);
                    // Last resort: Try to construct from session metadata
                    throw new Error(`Could not load prediction data. Please ensure the analysis session exists.`);
                }
            }
            
            if (!geojsonData || !geojsonData.features) {
                throw new Error('No GeoJSON data available');
            }
            
            this.currentSession = sessionId;
            this.predictions = geojsonData.features || [];
            
            if (this.predictions.length === 0) {
                this.showStatusMessage('No predictions found in this session', 'error');
                return;
            }
            
            // Display predictions as editable entities
            this.displayPredictions();
            
            // Show correction UI
            this.showCorrectionPanel();
            
            this.showStatusMessage(`Loaded ${this.predictions.length} predictions`, 'success');
            
        } catch (error) {
            console.error('Error loading prediction:', error);
            this.showStatusMessage('Failed to load prediction results: ' + error.message, 'error');
        }
    }
    
    /**
     * Display predictions on Cesium viewer
     */
    displayPredictions() {
        // Clear existing entities
        this.entities.forEach(e => this.viewer.entities.remove(e));
        this.entities = [];
        
        this.predictions.forEach((feature, index) => {
            const geometry = feature.geometry;
            const properties = feature.properties || {};
            
            // Get color from properties or use default
            const color = properties.color || this.getCategoryColor(properties.category) || '#FF0000';
            
            // Create polygon entity
            const entity = this.viewer.entities.add({
                id: `prediction_${index}`,
                name: `Prediction ${index + 1}: ${properties.category || 'Unknown'}`,
                polygon: {
                    hierarchy: this.geojsonToCesiumCoordinates(geometry),
                    material: Cesium.Color.fromCssColorString(color).withAlpha(0.5),
                    outline: true,
                    outlineColor: Cesium.Color.WHITE,
                    outlineWidth: 2,
                    height: 0,
                    extrudedHeight: 0
                },
                properties: {
                    originalIndex: new Cesium.CallbackProperty(() => index, false),
                    category: new Cesium.CallbackProperty(() => properties.category || 'unknown', false),
                    confidence: new Cesium.CallbackProperty(() => properties.confidence || 1.0, false),
                    originalFeature: feature
                }
            });
            
            this.entities.push(entity);
        });
    }
    
    /**
     * Show correction panel UI
     * Reuses: Sidebar layout from label.html (lines 27-64)
     */
    showCorrectionPanel() {
        // Show Cesium viewer container if it exists
        const container = document.getElementById('cesium-correction-container');
        if (container) {
            container.style.display = 'block';
        }
        
        // Create or show correction panel
        let panel = document.getElementById('correction-panel');
        if (!panel) {
            panel = this.createCorrectionPanel();
            document.body.appendChild(panel);
        }
        panel.style.display = 'block';
    }
    
    /**
     * Create correction panel HTML
     * Reuses: Sidebar layout, tool buttons, category selection UI
     */
    createCorrectionPanel() {
        const panel = document.createElement('div');
        panel.id = 'correction-panel';
        panel.className = 'correction-panel';
        panel.innerHTML = `
            <div class="correction-panel-overlay" onclick="corrector.closePanel()"></div>
            <div class="correction-panel-content">
                <div class="panel-header">
                    <h3><i class="fas fa-edit"></i> Correct Mask2Former Predictions</h3>
                    <button class="close-btn" onclick="corrector.closePanel()">×</button>
                </div>
                <div class="panel-body">
                    <!-- Reuse: Status message system -->
                    <div id="correction-status-message" style="display: none;"></div>
                    
                    <!-- Training Dataset Selection -->
                    <div class="form-group">
                        <label>Training Dataset:</label>
                        <select id="training-dataset-select" class="form-control">
                            <option value="">Select or create dataset...</option>
                        </select>
                        <button class="btn btn-sm btn-primary mt-2" onclick="corrector.createNewDataset()">
                            <i class="fas fa-plus"></i> New Dataset
                        </button>
                    </div>
                    
                    <!-- Reuse: Tool buttons layout (adapted from label.html lines 159-169) -->
                    <div class="tool-buttons">
                        <button class="btn btn-sm btn-outline-success" onclick="corrector.activateDrawMode()">
                            <i class="fas fa-draw-polygon"></i> Draw Polygon
                        </button>
                        <button class="btn btn-sm btn-outline-primary" onclick="corrector.activateEditMode()">
                            <i class="fas fa-edit"></i> Edit Mask
                        </button>
                        <button class="btn btn-sm btn-outline-primary" onclick="corrector.activateCategoryChange()">
                            <i class="fas fa-tag"></i> Change Category
                        </button>
                        <button class="btn btn-sm btn-outline-danger" onclick="corrector.deleteSelected()">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" onclick="corrector.undoLastOperation()">
                            <i class="fas fa-undo"></i> Undo
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" onclick="corrector.redoLastOperation()">
                            <i class="fas fa-redo"></i> Redo
                        </button>
                    </div>
                    
                    <!-- Reuse: Category selection UI (adapted from label.html lines 199-300) -->
                    <div class="section">
                        <h4>Categories</h4>
                        <ul id="categories-list" class="categories-list">
                            <!-- Populated dynamically -->
                        </ul>
                    </div>
                    
                    <!-- Predictions List -->
                    <div class="predictions-list" id="predictions-list">
                        <h4>Predictions (${this.predictions.length})</h4>
                        <!-- Populated dynamically -->
                    </div>
                    
                    <!-- Panel Actions -->
                    <div class="panel-actions">
                        <button class="btn btn-primary" onclick="corrector.saveCorrections()">
                            <i class="fas fa-save"></i> Save Corrections
                        </button>
                        <button class="btn btn-secondary" onclick="corrector.clearAllCorrections()">
                            <i class="fas fa-eraser"></i> Clear All
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        // Load datasets and categories
        this.loadTrainingDatasets();
        this.loadCategories();
        this.populatePredictionsList();
        
        return panel;
    }
    
    /**
     * Load training datasets
     */
    async loadTrainingDatasets() {
        try {
            const response = await fetch('/api/training/datasets/');
            
            // Check if response is actually JSON (not HTML redirect page)
            const contentType = response.headers.get('content-type');
            if (!contentType || !contentType.includes('application/json')) {
                // Likely a redirect to login page or error page
                if (response.status === 401 || response.status === 403) {
                    this.showStatusMessage('Please log in to access training datasets', 'error');
                } else {
                    this.showStatusMessage('Unable to load training datasets', 'error');
                }
                return;
            }
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            if (data.status === 'success') {
                const select = document.getElementById('training-dataset-select');
                if (!select) return;
                
                select.innerHTML = '<option value="">Select or create dataset...</option>';
                
                if (data.datasets && Array.isArray(data.datasets)) {
                    data.datasets.forEach(dataset => {
                        const option = document.createElement('option');
                        option.value = dataset.id;
                        option.textContent = `${dataset.name} (${dataset.num_annotations || 0} annotations)`;
                        select.appendChild(option);
                    });
                }
            } else if (data.error) {
                this.showStatusMessage(`Error: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error loading training datasets:', error);
            // Don't show error message if it's just a JSON parse error (likely auth redirect)
            if (error instanceof SyntaxError && error.message.includes('JSON')) {
                this.showStatusMessage('Please log in to access training datasets', 'error');
            } else {
                this.showStatusMessage('Error loading training datasets: ' + error.message, 'error');
            }
        }
    }
    
    /**
     * Reuse: Category loading (adapted from label.html category management)
     */
    async loadCategories() {
        try {
            const response = await fetch('/webclient/getCategoryInfo');
            const categories = await response.json();
            
            const categoriesList = document.getElementById('categories-list');
            if (!categoriesList) return;
            
            categoriesList.innerHTML = '';
            
            if (Array.isArray(categories)) {
                categories.forEach(cat => {
                    const li = document.createElement('li');
                    li.dataset.category = cat.category_name || cat.name;
                    const color = cat.color || '#ff0000';
                    li.style.backgroundColor = color;
                    li.innerHTML = `
                        <span class="category-name">${cat.category_name || cat.name}</span>
                        <span class="category-color" style="background-color: ${color}"></span>
                    `;
                    li.addEventListener('click', () => {
                        this.currentCategory = cat.category_name || cat.name;
                        this.currentColor = color;
                        // Update UI to show selected category
                        document.querySelectorAll('#categories-list li').forEach(item => {
                            item.classList.remove('selected');
                        });
                        li.classList.add('selected');
                    });
                    categoriesList.appendChild(li);
                });
            }
        } catch (error) {
            console.error('Error loading categories:', error);
        }
    }
    
    /**
     * Populate predictions list
     */
    populatePredictionsList() {
        const list = document.getElementById('predictions-list');
        if (!list) return;
        
        const predictionsDiv = document.createElement('div');
        predictionsDiv.className = 'predictions-items';
        
        this.entities.forEach((entity, index) => {
            const props = entity.properties;
            const item = document.createElement('div');
            item.className = 'prediction-item';
            item.dataset.index = index;
            item.innerHTML = `
                <div class="prediction-info">
                    <strong>Prediction ${index + 1}</strong>
                    <span class="category-badge">${props.category.getValue()}</span>
                    <span class="confidence-badge">${(props.confidence.getValue() * 100).toFixed(1)}%</span>
                </div>
                <button class="btn btn-sm btn-outline-primary" onclick="corrector.selectPrediction(${index})">
                    Select
                </button>
            `;
            item.addEventListener('click', (e) => {
                if (e.target.tagName !== 'BUTTON') {
                    this.selectPrediction(index);
                }
            });
            predictionsDiv.appendChild(item);
        });
        
        // Clear and add new content
        const h4 = list.querySelector('h4');
        list.innerHTML = '';
        if (h4) list.appendChild(h4);
        list.appendChild(predictionsDiv);
    }
    
    /**
     * Select a prediction for editing
     */
    selectPrediction(index) {
        // Stop editing if in edit mode
        if (this.editMode && this.editingEntity) {
            this.stopEditingEntity();
        }
        
        // Highlight selected entity
        this.entities.forEach((e, i) => {
            if (i === index) {
                e.polygon.outlineColor = Cesium.Color.CYAN;
                e.polygon.outlineWidth = 3;
            } else {
                e.polygon.outlineColor = Cesium.Color.WHITE;
                e.polygon.outlineWidth = 2;
            }
        });
        
        this.selectedIndex = index;
        
        // Fly to selected entity
        const entity = this.entities[index];
        if (entity) {
            this.viewer.flyTo(entity);
        }
        
        // Update UI
        document.querySelectorAll('.prediction-item').forEach((item, i) => {
            item.classList.toggle('selected', i === index);
        });
    }
    
    /**
     * Save corrections to training dataset
     * Reuses: Save API pattern from label.html (lines 1832-1900)
     */
    async saveCorrections() {
        const datasetId = document.getElementById('training-dataset-select')?.value;
        if (!datasetId) {
            this.showStatusMessage('Please select a training dataset', 'error');
            return;
        }
        
        this.showStatusMessage('Saving corrections...', 'loading');
        
        // Reuse: GeoJSON conversion pattern (adapted from label.html)
        const correctedFeatures = this.entities.map((entity, index) => {
            const props = entity.properties;
            const hierarchy = entity.polygon.hierarchy.getValue();
            
            // Convert Cesium coordinates back to GeoJSON
            const coordinates = this.cesiumToGeojsonCoordinates(hierarchy);
            
            return {
                type: 'Feature',
                geometry: {
                    type: 'Polygon',
                    coordinates: [coordinates]
                },
                properties: {
                    category: props.category.getValue(),
                    confidence: props.confidence.getValue(),
                    corrected: true,
                    originalIndex: props.originalIndex.getValue()
                }
            };
        });
        
        const geojson = {
            type: 'FeatureCollection',
            features: correctedFeatures
        };
        
        // Get image info from session
        const imageInfo = await this.getImageInfo(this.currentSession);
        
        // Reuse: Save API pattern from label.html (lines 1832-1900)
        try {
            const response = await fetch('/label/semi-supervised/api/save-labels/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCookie('csrftoken')
                },
                body: JSON.stringify({
                    image_id: imageInfo.image_id,
                    labels: geojson,
                    user_id: this.getCurrentUserId(),
                    training_dataset_id: parseInt(datasetId),
                    source_prediction_id: this.currentSession,
                    corrections: this.corrections
                })
            });
            
            const result = await response.json();
            if (result.success) {
                this.showStatusMessage('Corrections saved to training dataset!', 'success');
                setTimeout(() => {
                    this.closePanel();
                }, 2000);
            } else {
                this.showStatusMessage('Error saving corrections: ' + (result.error || 'Unknown error'), 'error');
            }
        } catch (error) {
            this.showStatusMessage('Network error: ' + error.message, 'error');
        }
    }
    
    /**
     * Reuse: Status message system (from label_semi_supervised.html lines 183-217)
     */
    showStatusMessage(message, type = 'info') {
        const statusEl = document.getElementById('correction-status-message');
        if (!statusEl) return;
        
        statusEl.textContent = message;
        statusEl.className = type;
        statusEl.style.display = 'block';
        
        if (type !== 'loading') {
            setTimeout(() => {
                statusEl.style.display = 'none';
            }, 3000);
        }
    }
    
    /**
     * Reuse: Undo/redo system (adapted from label.html lines 1215-1244)
     */
    addToUndoStack(entity) {
        // Clone entity state
        const state = {
            id: entity.id,
            polygon: entity.polygon.hierarchy.getValue(),
            properties: {
                category: entity.properties.category.getValue(),
                confidence: entity.properties.confidence.getValue()
            }
        };
        this.undos.push(state);
        this.redos = []; // Clear redos when new action is performed
    }
    
    undoLastOperation() {
        if (this.undos.length > 0) {
            const state = this.undos.pop();
            const entity = this.viewer.entities.getById(state.id);
            
            if (entity) {
                // Add current state to redo stack
                const currentState = {
                    id: entity.id,
                    polygon: entity.polygon.hierarchy.getValue(),
                    properties: {
                        category: entity.properties.category.getValue(),
                        confidence: entity.properties.confidence.getValue()
                    }
                };
                this.redos.push(currentState);
                
                // Restore previous state
                entity.polygon.hierarchy = state.polygon;
                entity.properties.category = state.properties.category;
                entity.properties.confidence = state.properties.confidence;
            }
        }
    }
    
    redoLastOperation() {
        if (this.redos.length > 0) {
            const state = this.redos.pop();
            const entity = this.viewer.entities.getById(state.id);
            
            if (entity) {
                // Add current state to undo stack
                const currentState = {
                    id: entity.id,
                    polygon: entity.polygon.hierarchy.getValue(),
                    properties: {
                        category: entity.properties.category.getValue(),
                        confidence: entity.properties.confidence.getValue()
                    }
                };
                this.undos.push(currentState);
                
                // Restore state
                entity.polygon.hierarchy = state.polygon;
                entity.properties.category = state.properties.category;
                entity.properties.confidence = state.properties.confidence;
            }
        }
    }
    
    /**
     * Reuse: Clear functionality (adapted from label.html lines 2363-2383)
     */
    clearAllCorrections() {
        if (confirm('Are you sure you want to clear all corrections? This will reset to original predictions.')) {
            // Reset entities to original predictions
            this.entities.forEach((entity, index) => {
                const originalFeature = this.predictions[index];
                if (originalFeature) {
                    entity.polygon.hierarchy = this.geojsonToCesiumCoordinates(originalFeature.geometry);
                    entity.properties.category = originalFeature.properties.category;
                    entity.properties.confidence = originalFeature.properties.confidence || 1.0;
                }
            });
            
            // Clear undo/redo stacks
            this.undos = [];
            this.redos = [];
            
            this.showStatusMessage('All corrections cleared', 'success');
        }
    }
    
    /**
     * Helper: Convert GeoJSON to Cesium coordinates
     */
    geojsonToCesiumCoordinates(geometry) {
        if (geometry.type === 'Polygon') {
            const coords = geometry.coordinates[0];
            return Cesium.Cartesian3.fromDegreesArray(coords.flat());
        }
        return [];
    }
    
    /**
     * Helper: Convert Cesium coordinates to GeoJSON
     */
    cesiumToGeojsonCoordinates(cartesians) {
        return cartesians.map(c => {
            const cartographic = Cesium.Cartographic.fromCartesian(c);
            return [
                Cesium.Math.toDegrees(cartographic.longitude),
                Cesium.Math.toDegrees(cartographic.latitude)
            ];
        });
    }
    
    /**
     * Helper: Get category color
     */
    getCategoryColor(categoryName) {
        // Try to find category in loaded categories
        const categoryEl = document.querySelector(`#categories-list li[data-category="${categoryName}"]`);
        if (categoryEl) {
            return categoryEl.style.backgroundColor || '#ff0000';
        }
        return '#ff0000';
    }
    
    /**
     * Helper: Get CSRF token (reused pattern)
     */
    getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    
    /**
     * Helper: Get current user ID
     */
    getCurrentUserId() {
        // Try to get from Django template context or use default
        return window.currentUserId || 'anonymous';
    }
    
    /**
     * Helper: Get image info from session
     */
    async getImageInfo(sessionId) {
        // This would need to be implemented based on your session storage
        // For now, return a placeholder
        return {
            image_id: null, // Would need to be fetched from session metadata
            image_path: `/deepgis_results/mask2former_results/${sessionId}/query_image.png`
        };
    }
    
    /**
     * Create new training dataset
     */
    async createNewDataset() {
        const name = prompt('Enter dataset name:');
        if (!name) return;
        
        try {
            const response = await fetch('/api/training/datasets/create/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCookie('csrftoken')
                },
                body: JSON.stringify({
                    name: name,
                    description: prompt('Enter description (optional):') || ''
                })
            });
            
            const result = await response.json();
            if (result.status === 'success') {
                this.showStatusMessage('Dataset created successfully!', 'success');
                await this.loadTrainingDatasets();
                // Select the new dataset
                document.getElementById('training-dataset-select').value = result.dataset_id;
            } else {
                this.showStatusMessage('Error creating dataset: ' + result.error, 'error');
            }
        } catch (error) {
            this.showStatusMessage('Network error: ' + error.message, 'error');
        }
    }
    
    /**
     * Close correction panel
     */
    closePanel() {
        // Cleanup editing state
        this.cleanupEditHandlers();
        this.removeEditPoints();
        this.stopEditingEntity();
        this.cancelDrawing();
        this.editMode = false;
        this.categoryChangeMode = false;
        this.drawMode = false;
        
        const panel = document.getElementById('correction-panel');
        if (panel) {
            panel.style.display = 'none';
        }
        
        // Hide Cesium viewer container if it was created for this interface
        const container = document.getElementById('cesium-correction-container');
        if (container && container.style.display !== 'none') {
            container.style.display = 'none';
        }
    }
    
    /**
     * Activate draw mode for creating new polygons
     * Reuses: Polygon drawing pattern from label.html (lines 1372-1414)
     */
    activateDrawMode() {
        if (!this.currentCategory) {
            this.showStatusMessage('Please select a category first from the categories list', 'error');
            return;
        }
        
        this.drawMode = !this.drawMode;
        this.editMode = false;
        this.categoryChangeMode = false;
        
        if (this.drawMode) {
            this.showStatusMessage('Draw mode ON: Click on the map to add polygon points. Right-click to finish polygon.', 'info');
            this.setupDrawHandlers();
        } else {
            this.showStatusMessage('Draw mode OFF', 'info');
            this.cleanupDrawHandlers();
            this.cancelDrawing();
        }
        
        // Update button state
        const btn = document.querySelector('button[onclick="corrector.activateDrawMode()"]');
        if (btn) {
            btn.classList.toggle('active', this.drawMode);
        }
    }
    
    /**
     * Setup handlers for polygon drawing
     */
    setupDrawHandlers() {
        // Clean up existing handlers first
        this.cleanupDrawHandlers();
        
        const clickHandler = new Cesium.ScreenSpaceEventHandler(this.viewer.scene.canvas);
        this.editHandlers.push(clickHandler);
        
        // Left click to add point
        clickHandler.setInputAction((click) => {
            if (!this.drawMode) return;
            
            const cartesian = this.viewer.camera.pickEllipsoid(click.position, this.viewer.scene.globe.ellipsoid);
            if (cartesian) {
                this.addDrawPoint(cartesian);
            }
        }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
        
        // Right click to finish polygon
        clickHandler.setInputAction((click) => {
            if (!this.drawMode || !this.drawingPolygon) return;
            
            if (this.polygonPoints.length >= 3) {
                this.finishDrawingPolygon();
            } else {
                this.showStatusMessage('Polygon needs at least 3 points. Add more points or cancel.', 'error');
            }
        }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);
        
        // Mouse move to show preview
        clickHandler.setInputAction((movement) => {
            if (!this.drawMode || !this.drawingPolygon) return;
            
            const cartesian = this.viewer.camera.pickEllipsoid(movement.endPosition, this.viewer.scene.globe.ellipsoid);
            if (cartesian && this.polygonPoints.length > 0) {
                this.updateDrawPreview(cartesian);
            }
        }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
    }
    
    /**
     * Add a point to the polygon being drawn
     */
    addDrawPoint(cartesian) {
        if (!this.drawingPolygon) {
            // Start new polygon
            this.drawingPolygon = true;
            this.polygonPoints = [];
            this.showStatusMessage('Drawing polygon: Click to add points, right-click to finish', 'info');
        }
        
        // Add point
        this.polygonPoints.push(cartesian);
        
        // Create or update preview entity
        this.updateDrawPreview(cartesian);
        
        // Add visual marker for the point
        this.viewer.entities.add({
            position: cartesian,
            point: {
                pixelSize: 8,
                color: Cesium.Color.YELLOW,
                outlineColor: Cesium.Color.BLACK,
                outlineWidth: 2,
                heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                disableDepthTestDistance: Number.POSITIVE_INFINITY
            }
        });
    }
    
    /**
     * Update the preview polygon as user moves mouse
     */
    updateDrawPreview(currentMousePosition) {
        if (this.polygonPoints.length === 0) return;
        
        // Remove old preview
        if (this.tempEntity) {
            this.viewer.entities.remove(this.tempEntity);
        }
        
        // Create preview with current points + mouse position
        const previewPoints = [...this.polygonPoints, currentMousePosition];
        
        this.tempEntity = this.viewer.entities.add({
            polygon: {
                hierarchy: previewPoints,
                material: Cesium.Color.fromCssColorString(this.currentColor).withAlpha(0.3),
                outline: true,
                outlineColor: Cesium.Color.fromCssColorString(this.currentColor),
                outlineWidth: 2,
                height: 0,
                extrudedHeight: 0
            }
        });
    }
    
    /**
     * Finish drawing the polygon and add it as a new prediction
     */
    finishDrawingPolygon() {
        if (this.polygonPoints.length < 3) {
            this.showStatusMessage('Polygon needs at least 3 points', 'error');
            return;
        }
        
        // Remove preview
        if (this.tempEntity) {
            this.viewer.entities.remove(this.tempEntity);
            this.tempEntity = null;
        }
        
        // Create new entity
        const newEntity = this.viewer.entities.add({
            name: `New Annotation: ${this.currentCategory}`,
            polygon: {
                hierarchy: this.polygonPoints,
                material: Cesium.Color.fromCssColorString(this.currentColor).withAlpha(0.5),
                outline: true,
                outlineColor: Cesium.Color.WHITE,
                outlineWidth: 2,
                height: 0,
                extrudedHeight: 0
            },
            properties: {
                originalIndex: new Cesium.CallbackProperty(() => this.entities.length, false),
                category: new Cesium.CallbackProperty(() => this.currentCategory, false),
                confidence: new Cesium.CallbackProperty(() => 1.0, false),
                isNewAnnotation: true
            }
        });
        
        // Add to entities array
        this.entities.push(newEntity);
        
        // Create corresponding prediction entry
        const newPrediction = {
            type: 'Feature',
            geometry: {
                type: 'Polygon',
                coordinates: [this.cesiumToGeojsonCoordinates(this.polygonPoints)]
            },
            properties: {
                category: this.currentCategory,
                confidence: 1.0,
                isNewAnnotation: true
            }
        };
        this.predictions.push(newPrediction);
        
        // Save to undo stack
        this.addToUndoStack(newEntity);
        
        // Reset drawing state
        this.drawingPolygon = false;
        this.polygonPoints = [];
        
        // Refresh predictions list
        this.populatePredictionsList();
        
        this.showStatusMessage(`New polygon added for category "${this.currentCategory}"`, 'success');
    }
    
    /**
     * Cancel current drawing
     */
    cancelDrawing() {
        // Remove preview
        if (this.tempEntity) {
            this.viewer.entities.remove(this.tempEntity);
            this.tempEntity = null;
        }
        
        // Remove point markers
        this.viewer.entities.values.forEach(entity => {
            if (entity.point && entity.point.color && 
                entity.point.color.getValue && 
                entity.point.color.getValue().equals(Cesium.Color.YELLOW)) {
                // This is a draw point marker, remove it
                this.viewer.entities.remove(entity);
            }
        });
        
        this.drawingPolygon = false;
        this.polygonPoints = [];
    }
    
    /**
     * Cleanup draw handlers
     */
    cleanupDrawHandlers() {
        // Handlers are cleaned up in cleanupEditHandlers
        this.cancelDrawing();
    }
    
    /**
     * Activate edit mode for polygon vertices
     * Click on a polygon to start editing, then drag vertices
     */
    activateEditMode() {
        this.editMode = !this.editMode;
        this.categoryChangeMode = false;
        this.drawMode = false;
        
        if (this.editMode) {
            this.showStatusMessage('Edit mode ON: Click a polygon to edit its vertices. Click again to exit edit mode.', 'info');
            this.setupEditHandlers();
            this.cancelDrawing(); // Cancel any active drawing
        } else {
            this.showStatusMessage('Edit mode OFF', 'info');
            this.cleanupEditHandlers();
            this.editingEntity = null;
        }
        
        // Update button state
        const btn = document.querySelector('button[onclick="corrector.activateEditMode()"]');
        if (btn) {
            btn.classList.toggle('active', this.editMode);
        }
    }
    
    /**
     * Setup handlers for entity editing
     */
    setupEditHandlers() {
        // Clean up existing handlers
        this.cleanupEditHandlers();
        
        // Add click handler to viewer
        const clickHandler = new Cesium.ScreenSpaceEventHandler(this.viewer.scene.canvas);
        this.editHandlers.push(clickHandler);
        
        clickHandler.setInputAction((click) => {
            const pickedObject = this.viewer.scene.pick(click.position);
            
            if (pickedObject && pickedObject.id) {
                const entity = pickedObject.id;
                
                // Check if this is one of our prediction entities
                if (this.entities.includes(entity)) {
                    if (this.editingEntity === entity) {
                        // Already editing this entity, stop editing
                        this.stopEditingEntity();
                    } else {
                        // Start editing this entity
                        this.startEditingEntity(entity);
                    }
                }
            } else if (this.editingEntity) {
                // Clicked on nothing, stop editing
                this.stopEditingEntity();
            }
        }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
        
        // Add double-click to add vertex
        clickHandler.setInputAction((click) => {
            if (this.editingEntity) {
                this.addVertexAtClick(click.position);
            }
        }, Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
    }
    
    /**
     * Start editing an entity
     */
    startEditingEntity(entity) {
        // Stop editing previous entity if any
        if (this.editingEntity && this.editingEntity !== entity) {
            this.stopEditingEntity();
        }
        
        this.editingEntity = entity;
        
        // Get current hierarchy
        const hierarchy = entity.polygon.hierarchy.getValue();
        
        // Create editable points for each vertex
        this.createEditPoints(hierarchy);
        
        // Highlight the entity being edited
        entity.polygon.outlineColor = Cesium.Color.YELLOW;
        entity.polygon.outlineWidth = 4;
        
        this.showStatusMessage('Editing polygon: Drag vertices to move, double-click to add vertex, right-click vertex to delete', 'info');
    }
    
    /**
     * Stop editing current entity
     */
    stopEditingEntity() {
        if (!this.editingEntity) return;
        
        // Remove edit points
        this.removeEditPoints();
        
        // Reset outline
        this.editingEntity.polygon.outlineColor = Cesium.Color.WHITE;
        this.editingEntity.polygon.outlineWidth = 2;
        
        this.editingEntity = null;
    }
    
    /**
     * Create draggable points for editing vertices
     */
    createEditPoints(hierarchy) {
        this.editPoints = [];
        
        hierarchy.forEach((position, index) => {
            const point = this.viewer.entities.add({
                position: position,
                point: {
                    pixelSize: 10,
                    color: Cesium.Color.YELLOW,
                    outlineColor: Cesium.Color.BLACK,
                    outlineWidth: 2,
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                    disableDepthTestDistance: Number.POSITIVE_INFINITY
                },
                properties: {
                    vertexIndex: index
                }
            });
            
            // Make point draggable
            point.position = new Cesium.CallbackProperty(() => {
                return point.position.getValue();
            }, false);
            
            // Add drag handler
            const dragHandler = new Cesium.ScreenSpaceEventHandler(this.viewer.scene.canvas);
            let isDragging = false;
            let startPosition = null;
            
            dragHandler.setInputAction((movement) => {
                if (!isDragging) {
                    const picked = this.viewer.scene.pick(movement.startPosition);
                    if (picked && picked.id === point) {
                        isDragging = true;
                        startPosition = movement.startPosition;
                    }
                }
            }, Cesium.ScreenSpaceEventType.LEFT_DOWN);
            
            dragHandler.setInputAction((movement) => {
                if (isDragging && this.editingEntity) {
                    const cartesian = this.viewer.camera.pickEllipsoid(movement.endPosition, this.viewer.scene.globe.ellipsoid);
                    if (cartesian) {
                        // Update point position
                        point.position = cartesian;
                        
                        // Update polygon hierarchy
                        this.updatePolygonFromEditPoints();
                    }
                }
            }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
            
            dragHandler.setInputAction(() => {
                if (isDragging) {
                    isDragging = false;
                    // Save state to undo stack
                    if (this.editingEntity) {
                        this.addToUndoStack(this.editingEntity);
                    }
                }
            }, Cesium.ScreenSpaceEventType.LEFT_UP);
            
            // Right-click to delete vertex
            dragHandler.setInputAction((click) => {
                const picked = this.viewer.scene.pick(click.position);
                if (picked && picked.id === point && this.editingEntity) {
                    if (this.editPoints.length > 3) { // Keep at least 3 vertices
                        this.removeEditPoint(point);
                    } else {
                        this.showStatusMessage('Polygon must have at least 3 vertices', 'error');
                    }
                }
            }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);
            
            this.editHandlers.push(dragHandler);
            this.editPoints.push(point);
        });
    }
    
    /**
     * Update polygon hierarchy from edit points
     */
    updatePolygonFromEditPoints() {
        if (!this.editingEntity || !this.editPoints) return;
        
        const positions = this.editPoints.map(point => point.position.getValue());
        this.editingEntity.polygon.hierarchy = positions;
    }
    
    /**
     * Remove edit points
     */
    removeEditPoints() {
        if (this.editPoints) {
            this.editPoints.forEach(point => {
                this.viewer.entities.remove(point);
            });
            this.editPoints = [];
        }
    }
    
    /**
     * Remove a single edit point
     */
    removeEditPoint(point) {
        const index = this.editPoints.indexOf(point);
        if (index > -1) {
            this.viewer.entities.remove(point);
            this.editPoints.splice(index, 1);
            this.updatePolygonFromEditPoints();
            this.addToUndoStack(this.editingEntity);
        }
    }
    
    /**
     * Add vertex at click position
     */
    addVertexAtClick(clickPosition) {
        if (!this.editingEntity) return;
        
        const cartesian = this.viewer.camera.pickEllipsoid(clickPosition, this.viewer.scene.globe.ellipsoid);
        if (cartesian) {
            // Find closest edge and insert vertex
            const hierarchy = this.editingEntity.polygon.hierarchy.getValue();
            let closestIndex = 0;
            let minDistance = Number.POSITIVE_INFINITY;
            
            for (let i = 0; i < hierarchy.length; i++) {
                const nextIndex = (i + 1) % hierarchy.length;
                const edgeStart = hierarchy[i];
                const edgeEnd = hierarchy[nextIndex];
                
                // Calculate distance from point to edge
                const distance = this.distanceToLineSegment(cartesian, edgeStart, edgeEnd);
                
                if (distance < minDistance) {
                    minDistance = distance;
                    closestIndex = nextIndex;
                }
            }
            
            // Insert new vertex
            const newPoint = this.viewer.entities.add({
                position: cartesian,
                point: {
                    pixelSize: 10,
                    color: Cesium.Color.YELLOW,
                    outlineColor: Cesium.Color.BLACK,
                    outlineWidth: 2,
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                    disableDepthTestDistance: Number.POSITIVE_INFINITY
                }
            });
            
            this.editPoints.splice(closestIndex, 0, newPoint);
            this.updatePolygonFromEditPoints();
            this.addToUndoStack(this.editingEntity);
        }
    }
    
    /**
     * Calculate distance from point to line segment
     */
    distanceToLineSegment(point, lineStart, lineEnd) {
        const direction = Cesium.Cartesian3.subtract(lineEnd, lineStart, new Cesium.Cartesian3());
        const length = Cesium.Cartesian3.magnitude(direction);
        const normalized = Cesium.Cartesian3.normalize(direction, new Cesium.Cartesian3());
        
        const toPoint = Cesium.Cartesian3.subtract(point, lineStart, new Cesium.Cartesian3());
        const projection = Cesium.Cartesian3.multiplyByScalar(
            normalized,
            Cesium.Cartesian3.dot(toPoint, normalized),
            new Cesium.Cartesian3()
        );
        
        const clamped = Math.max(0, Math.min(length, Cesium.Cartesian3.magnitude(projection)));
        const closest = Cesium.Cartesian3.add(
            lineStart,
            Cesium.Cartesian3.multiplyByScalar(normalized, clamped, new Cesium.Cartesian3()),
            new Cesium.Cartesian3()
        );
        
        return Cesium.Cartesian3.distance(point, closest);
    }
    
    /**
     * Cleanup edit handlers
     */
    cleanupEditHandlers() {
        this.editHandlers.forEach(handler => {
            if (handler && handler.destroy) {
                handler.destroy();
            }
        });
        this.editHandlers = [];
    }
    
    /**
     * Activate category change mode
     */
    activateCategoryChange() {
        if (this.selectedIndex === undefined) {
            this.showStatusMessage('Please select a prediction first by clicking on it in the list', 'error');
            return;
        }
        
        if (!this.currentCategory) {
            this.showStatusMessage('Please select a category from the categories list first', 'error');
            return;
        }
        
        const entity = this.entities[this.selectedIndex];
        if (!entity) {
            this.showStatusMessage('Selected prediction not found', 'error');
            return;
        }
        
        // Save to undo stack
        this.addToUndoStack(entity);
        
        // Change category
        const oldCategory = entity.properties.category.getValue();
        entity.properties.category = this.currentCategory;
        
        // Update color
        const newColor = this.currentColor;
        entity.polygon.material = Cesium.Color.fromCssColorString(newColor).withAlpha(0.5);
        
        // Update name
        entity.name = `Prediction ${this.selectedIndex + 1}: ${this.currentCategory}`;
        
        this.showStatusMessage(`Category changed from "${oldCategory}" to "${this.currentCategory}"`, 'success');
        
        // Refresh predictions list
        this.populatePredictionsList();
    }
    
    /**
     * Delete selected prediction
     */
    deleteSelected() {
        if (this.selectedIndex === undefined) {
            this.showStatusMessage('Please select a prediction first by clicking on it in the list', 'error');
            return;
        }
        
        if (!confirm('Delete this prediction? This action cannot be undone.')) {
            return;
        }
        
        const entity = this.entities[this.selectedIndex];
        
        // Save to undo stack
        this.addToUndoStack(entity);
        
        // Remove from viewer
        this.viewer.entities.remove(entity);
        
        // Remove from array
        this.entities.splice(this.selectedIndex, 1);
        this.predictions.splice(this.selectedIndex, 1);
        
        // Reset selection
        this.selectedIndex = undefined;
        
        // Refresh list
        this.populatePredictionsList();
        
        this.showStatusMessage('Prediction deleted', 'success');
    }
}

// Global instance
let corrector = null;


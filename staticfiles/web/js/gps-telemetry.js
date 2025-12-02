/**
 * GPS Telemetry Path Loader for DeepGIS
 * Loads and displays GPS session paths from the Dreams Laboratory API
 */

class GPSTelemetryLoader {
    constructor(viewer) {
        this.viewer = viewer;
        this.apiBaseUrl = window.location.origin + '/api/telemetry';
        this.loadedEntities = [];
        this.currentSession = null;
        
        // Create UI
        this.createUI();
    }
    
    createUI() {
        // Check if UI already exists in Mission Planner
        if (document.getElementById('gpsSessionSelect')) {
            console.log('GPS Telemetry UI already exists in Mission Planner, skipping creation');
            // UI is already in Mission Planner, just setup event listeners
            this.setupEventListeners();
            this.loadSessions();
            return;
        }
        
        // Fallback: Create standalone GPS Telemetry section if not in World Sampler
        // Find the sidebar or create a container
        const sidebar = document.getElementById('sidebar-wrapper') || document.querySelector('.sidebar-content');
        if (!sidebar) {
            console.error('Could not find sidebar to add GPS telemetry controls');
            return;
        }
        
        // Create GPS Telemetry section
        const gpsSection = document.createElement('div');
        gpsSection.id = 'gpsTelemetrySection'; // Add ID to prevent duplicates
        gpsSection.className = 'layer-group accordion-panel';
        gpsSection.style.border = '2px solid #10b981';
        gpsSection.style.background = 'rgba(16, 185, 129, 0.05)';
        gpsSection.innerHTML = `
            <div class="layer-group-title accordion-header" data-target="gpsTelemetryContent">
                <span><i class="fas fa-satellite"></i> GPS Telemetry Paths</span>
                <i class="fas fa-chevron-down accordion-icon"></i>
            </div>
            <div class="accordion-content" id="gpsTelemetryContent">
            <div class="form-group mb-2">
                <label class="form-label small">Session:</label>
                <select class="form-select form-select-sm" id="gpsSessionSelect">
                    <option value="">Loading sessions...</option>
                </select>
            </div>
            <div class="btn-group-vertical w-100" role="group">
                <button class="btn btn-sm btn-success mb-1" id="loadGPSPathBtn" disabled>
                    <i class="fas fa-route"></i> Load Path
                </button>
                <button class="btn btn-sm btn-info mb-1" id="loadGPSPointsBtn" disabled>
                    <i class="fas fa-map-marker-alt"></i> Load Points
                </button>
                <button class="btn btn-sm btn-warning mb-1" id="flyToPathBtn" disabled>
                    <i class="fas fa-plane"></i> Fly To Path
                </button>
                <button class="btn btn-sm btn-danger" id="clearGPSBtn">
                    <i class="fas fa-trash"></i> Clear All
                </button>
            </div>
                <div id="gpsSessionInfo" class="mt-2 small text-muted" style="display: none; background: rgba(16, 185, 129, 0.1); padding: 8px; border-radius: 4px;"></div>
            </div>
        `;
        
        // Append to the end of sidebar content (safer than insertBefore)
        // Try to find the sidebar-content div or use sidebar directly
        const sidebarContent = sidebar.querySelector('.layer-controls') || sidebar.querySelector('.sidebar-content') || sidebar;
        sidebarContent.appendChild(gpsSection);
        
        // Setup event listeners
        this.setupEventListeners();
        
        // Load sessions
        this.loadSessions();
    }
    
    setupEventListeners() {
        const sessionSelect = document.getElementById('gpsSessionSelect');
        const loadPathBtn = document.getElementById('loadGPSPathBtn');
        const loadPointsBtn = document.getElementById('loadGPSPointsBtn');
        const flyToBtn = document.getElementById('flyToPathBtn');
        const clearBtn = document.getElementById('clearGPSBtn');
        
        sessionSelect.addEventListener('change', (e) => {
            const sessionId = e.target.value;
            const hasSelection = sessionId !== '';
            loadPathBtn.disabled = !hasSelection;
            loadPointsBtn.disabled = !hasSelection;
            flyToBtn.disabled = !hasSelection;
            
            if (hasSelection) {
                this.updateSessionInfo(sessionId);
            } else {
                document.getElementById('gpsSessionInfo').style.display = 'none';
            }
        });
        
        loadPathBtn.addEventListener('click', () => {
            const sessionId = sessionSelect.value;
            if (sessionId) {
                this.loadPath(sessionId);
            }
        });
        
        loadPointsBtn.addEventListener('click', () => {
            const sessionId = sessionSelect.value;
            if (sessionId) {
                this.loadPoints(sessionId);
            }
        });
        
        flyToBtn.addEventListener('click', () => {
            this.flyToPath();
        });
        
        clearBtn.addEventListener('click', () => {
            this.clearAll();
        });
    }
    
    async loadSessions() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/sessions/?has_gps=true`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            const select = document.getElementById('gpsSessionSelect');
            
            if (data.sessions && data.sessions.length > 0) {
                select.innerHTML = '<option value="">Select a session...</option>';
                data.sessions.forEach(session => {
                    const option = document.createElement('option');
                    option.value = session.session_id;
                    const date = new Date(session.start_time).toLocaleString();
                    option.textContent = `${session.asset || 'Unknown'} - ${date} (${session.gps_point_count} points)`;
                    select.appendChild(option);
                });
            } else {
                select.innerHTML = '<option value="">No sessions with GPS data</option>';
            }
        } catch (error) {
            console.error('Error loading GPS sessions:', error);
            const select = document.getElementById('gpsSessionSelect');
            select.innerHTML = '<option value="">Error loading sessions</option>';
        }
    }
    
    async updateSessionInfo(sessionId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/sessions/${sessionId}/path/`);
            if (!response.ok) return;
            
            const data = await response.json();
            const infoDiv = document.getElementById('gpsSessionInfo');
            
            if (data.session_info) {
                const info = data.session_info;
                infoDiv.innerHTML = `
                    <strong>${info.asset || 'Unknown Asset'}</strong><br>
                    Project: ${info.project || 'N/A'}<br>
                    Points: ${info.total_points || 0}<br>
                    Mode: ${info.flight_mode || 'N/A'}
                `;
                infoDiv.style.display = 'block';
            }
        } catch (error) {
            console.error('Error loading session info:', error);
        }
    }
    
    async loadPath(sessionId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/sessions/${sessionId}/path/`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            if (!data.geojson || !data.geojson.features) {
                console.error('No GeoJSON data in response');
                return;
            }
            
            // Find the LineString feature (path)
            const pathFeature = data.geojson.features.find(
                f => f.geometry.type === 'LineString'
            );
            
            if (pathFeature) {
                // Convert coordinates to Cesium format
                const positions = Cesium.Cartesian3.fromDegreesArrayHeights(
                    pathFeature.geometry.coordinates.flat()
                );
                
                // Create path entity
                const pathEntity = this.viewer.entities.add({
                    name: `GPS Path: ${data.session_info.asset || sessionId}`,
                    polyline: {
                        positions: positions,
                        width: 4,
                        material: Cesium.Color.CYAN.withAlpha(0.9),
                        clampToGround: false,
                        heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
                        arcType: Cesium.ArcType.GEODESIC
                    },
                    description: `
                        <table class="table table-sm">
                            <tr><td><strong>Session:</strong></td><td>${data.session_id}</td></tr>
                            <tr><td><strong>Asset:</strong></td><td>${data.session_info.asset || 'N/A'}</td></tr>
                            <tr><td><strong>Project:</strong></td><td>${data.session_info.project || 'N/A'}</td></tr>
                            <tr><td><strong>Points:</strong></td><td>${data.session_info.total_points || 0}</td></tr>
                            <tr><td><strong>Flight Mode:</strong></td><td>${data.session_info.flight_mode || 'N/A'}</td></tr>
                            <tr><td><strong>Start Time:</strong></td><td>${new Date(data.session_info.start_time).toLocaleString()}</td></tr>
                        </table>
                    `
                });
                
                this.loadedEntities.push(pathEntity);
                this.currentSession = data;
                
                console.log('GPS path loaded successfully');
            }
        } catch (error) {
            console.error('Error loading GPS path:', error);
            alert('Error loading GPS path: ' + error.message);
        }
    }
    
    async loadPoints(sessionId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/sessions/${sessionId}/path/`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            if (!data.geojson || !data.geojson.features) {
                return;
            }
            
            // Get all Point features
            const pointFeatures = data.geojson.features.filter(
                f => f.geometry.type === 'Point'
            );
            
            pointFeatures.forEach((feature, index) => {
                const [lon, lat, alt] = feature.geometry.coordinates;
                const props = feature.properties;
                
                const pointEntity = this.viewer.entities.add({
                    name: `GPS Point ${index + 1}`,
                    position: Cesium.Cartesian3.fromDegrees(lon, lat, alt || 0),
                    point: {
                        pixelSize: 6,
                        color: this.getColorForFixType(props.fix_type),
                        outlineColor: Cesium.Color.WHITE,
                        outlineWidth: 1,
                        heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND
                    },
                    label: {
                        text: `${index + 1}`,
                        font: '10pt sans-serif',
                        fillColor: Cesium.Color.WHITE,
                        outlineColor: Cesium.Color.BLACK,
                        outlineWidth: 2,
                        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                        pixelOffset: new Cesium.Cartesian2(0, -20)
                    },
                    description: `
                        <table class="table table-sm">
                            <tr><td><strong>Timestamp:</strong></td><td>${props.timestamp ? new Date(props.timestamp).toLocaleString() : 'N/A'}</td></tr>
                            <tr><td><strong>Altitude:</strong></td><td>${props.altitude ? props.altitude.toFixed(2) + ' m' : 'N/A'}</td></tr>
                            <tr><td><strong>Fix Type:</strong></td><td>${this.getFixTypeName(props.fix_type)}</td></tr>
                            <tr><td><strong>Satellites:</strong></td><td>${props.satellites_visible || 'N/A'}</td></tr>
                            <tr><td><strong>Accuracy (H):</strong></td><td>${props.eph ? props.eph.toFixed(2) + ' m' : 'N/A'}</td></tr>
                            <tr><td><strong>Accuracy (V):</strong></td><td>${props.epv ? props.epv.toFixed(2) + ' m' : 'N/A'}</td></tr>
                            <tr><td><strong>Speed:</strong></td><td>${props.vel_m_s ? props.vel_m_s.toFixed(2) + ' m/s' : 'N/A'}</td></tr>
                        </table>
                    `
                });
                
                this.loadedEntities.push(pointEntity);
            });
            
            console.log(`Loaded ${pointFeatures.length} GPS points`);
        } catch (error) {
            console.error('Error loading GPS points:', error);
            alert('Error loading GPS points: ' + error.message);
        }
    }
    
    flyToPath() {
        if (this.loadedEntities.length === 0) {
            alert('No path loaded. Please load a path first.');
            return;
        }
        
        // Find the path entity (polyline)
        const pathEntity = this.loadedEntities.find(e => e.polyline);
        if (pathEntity) {
            this.viewer.flyTo(pathEntity);
        } else {
            // Fly to all entities
            this.viewer.flyTo(this.loadedEntities);
        }
    }
    
    clearAll() {
        this.loadedEntities.forEach(entity => {
            this.viewer.entities.remove(entity);
        });
        this.loadedEntities = [];
        this.currentSession = null;
        console.log('Cleared all GPS entities');
    }
    
    getColorForFixType(fixType) {
        const colors = {
            0: Cesium.Color.RED,      // No fix
            1: Cesium.Color.ORANGE,   // Dead reckoning
            2: Cesium.Color.YELLOW,   // 2D fix
            3: Cesium.Color.GREEN,    // 3D fix
            4: Cesium.Color.CYAN,     // GPS+DR
            5: Cesium.Color.MAGENTA   // Time only
        };
        return colors[fixType] || Cesium.Color.WHITE;
    }
    
    getFixTypeName(fixType) {
        const names = {
            0: 'No fix',
            1: 'Dead reckoning',
            2: '2D fix',
            3: '3D fix',
            4: 'GPS+DR',
            5: 'Time only'
        };
        return names[fixType] || `Unknown (${fixType})`;
    }
}

// Export for use in main.js or initialize if viewer is available
if (typeof window !== 'undefined') {
    window.GPSTelemetryLoader = GPSTelemetryLoader;
    
    // Auto-initialize when viewer is ready
    if (typeof Cesium !== 'undefined') {
        // Wait for viewer to be initialized
        document.addEventListener('DOMContentLoaded', () => {
            // Check if viewer exists after a short delay
            setTimeout(() => {
                if (window.viewer || window.DeepGISTopology?.viewer) {
                    const viewer = window.viewer || window.DeepGISTopology.viewer;
                    window.gpsTelemetryLoader = new GPSTelemetryLoader(viewer);
                }
            }, 2000);
        });
    }
}


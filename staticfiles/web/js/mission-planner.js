/**
 * Mission Planner for DeepGIS-XR
 * Handles waypoint placement, mission management, and visualization on Cesium map
 */

// Import OpenSky ADS-B Layer dynamically
let OpenSkyADSBLayer = null;

class MissionPlanner {
    constructor(viewer) {
        this.viewer = viewer;
        this.currentMission = null;
        this.waypoints = [];
        this.waypointEntities = [];
        this.pathEntity = null;
        this.isPlacingWaypoint = false;
        this.defaultAltitude = 50.0;
        this.defaultSpeed = null;
        // Authentication removed - no login required
        this.isAuthenticated = true; // Always authenticated
        this.currentUser = null;
        
        // CSRF token
        this.csrftoken = this.getCookie('csrftoken');
        
        // Aircraft tracking
        this.adsbLayer = null;
        this.aircraftTrackingEnabled = false;
        
        // Vehicle tracking
        this.vehicleEntities = new Map(); // Map of vehicle_id -> Cesium entity
        this.vehicleTrackingEnabled = false;
        this.vehicleUpdateInterval = null;
        this.vehicleUpdateTimer = null;
        this.vehicleUpdateInProgress = false; // Prevent overlapping updates
        
        this.init();
    }
    
    async init() {
        this.setupEventListeners();
        // Skip authentication check - always show controls
        this.updateAuthUI();
        await this.loadMissions();
        // Initialize GPS Telemetry if available
        this.initGPSTelemetry();
        // Initialize Vehicle Tracking (merged with GPS Telemetry)
        this.initVehicleTracking();
        // Initialize Aircraft Tracking (ADS-B)
        this.initAircraftTracking();
    }
    
    initGPSTelemetry() {
        // Initialize GPS Telemetry Loader within Mission Planner
        if (!this.viewer) {
            console.warn('[Mission Planner] Viewer not available for GPS Telemetry');
            return;
        }
        
        if (!window.GPSTelemetryLoader) {
            console.warn('[Mission Planner] GPSTelemetryLoader not available');
            return;
        }
        
        // Check if GPS Telemetry UI already exists in Mission Planner
        const gpsSelect = document.getElementById('gpsSessionSelect');
        if (!gpsSelect) {
            console.warn('[Mission Planner] GPS Telemetry UI not found');
            return;
        }
        
        // Check if GPS Telemetry is already initialized
        if (window.gpsTelemetryLoader && window.gpsTelemetryLoader.initializedInMissionPlanner) {
            return; // Already initialized
        }
        
        // Create GPS Telemetry Loader instance
        const gpsLoader = new window.GPSTelemetryLoader(this.viewer);
        
        // Mark as initialized in mission planner to prevent duplicate initialization
        gpsLoader.initializedInMissionPlanner = true;
        window.gpsTelemetryLoader = gpsLoader;
        
        // Override createUI to prevent it from creating its own panel
        // The UI is already created in Mission Planner, so just setup listeners
        gpsLoader.createUI = function() {
            // UI already exists in Mission Planner, just setup event listeners and load sessions
            if (document.getElementById('gpsSessionSelect')) {
                this.setupEventListeners();
                this.loadSessions();
            }
        };
        
        // Setup event listeners and load sessions (UI is already in DOM)
        if (document.getElementById('gpsSessionSelect')) {
            gpsLoader.setupEventListeners();
            gpsLoader.loadSessions();
            console.log('[Mission Planner] GPS Telemetry initialized');
        } else {
            // Wait a bit for DOM to be ready
            setTimeout(() => {
                if (document.getElementById('gpsSessionSelect')) {
                    gpsLoader.setupEventListeners();
                    gpsLoader.loadSessions();
                    console.log('[Mission Planner] GPS Telemetry initialized (delayed)');
                }
            }, 100);
        }
    }
    
    async initAircraftTracking() {
        // Initialize Aircraft Tracking (ADS-B) within Mission Planner
        if (!this.viewer) {
            console.warn('[Mission Planner] Viewer not available for Aircraft Tracking');
            return;
        }
        
        // Check if Aircraft Tracking UI exists
        const toggleCheckbox = document.getElementById('aircraftTrackingToggle');
        if (!toggleCheckbox) {
            console.warn('[Mission Planner] Aircraft Tracking UI not found');
            return;
        }
        
        try {
            // Dynamically import the OpenSky ADS-B Layer
            const module = await import('./utils/opensky-adsb.js');
            OpenSkyADSBLayer = module.OpenSkyADSBLayer || module.default;
            
            // Create ADS-B Layer instance
            this.adsbLayer = new OpenSkyADSBLayer(this.viewer);
            
            // Setup event listeners for aircraft tracking UI
            this.setupAircraftTrackingEvents();
            
            console.log('[Mission Planner] Aircraft Tracking (ADS-B) initialized');
        } catch (error) {
            console.error('[Mission Planner] Failed to initialize Aircraft Tracking:', error);
        }
    }
    
    setupAircraftTrackingEvents() {
        // Toggle aircraft tracking
        const toggleCheckbox = document.getElementById('aircraftTrackingToggle');
        if (toggleCheckbox) {
            toggleCheckbox.addEventListener('change', (e) => {
                this.toggleAircraftTracking(e.target.checked);
            });
        }
        
        // Update interval selector
        const intervalSelect = document.getElementById('aircraftUpdateInterval');
        if (intervalSelect) {
            intervalSelect.addEventListener('change', (e) => {
                const interval = parseInt(e.target.value);
                if (this.aircraftTrackingEnabled && this.adsbLayer) {
                    this.adsbLayer.stop();
                    this.adsbLayer.start(interval);
                    this.showStatus(`Aircraft update interval changed to ${interval}s`, 'info');
                }
            });
        }
        
        // Refresh button
        const refreshBtn = document.getElementById('refreshAircraftBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', async () => {
                if (this.adsbLayer && this.aircraftTrackingEnabled) {
                    refreshBtn.disabled = true;
                    refreshBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Refreshing...';
                    await this.adsbLayer.updateAircraft();
                    this.updateAircraftCount();
                    refreshBtn.disabled = false;
                    refreshBtn.innerHTML = '<i class="fas fa-sync-alt"></i> Refresh Now';
                }
            });
        }
        
        // Clear button
        const clearBtn = document.getElementById('clearAircraftBtn');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                if (this.adsbLayer) {
                    this.adsbLayer.clearAll();
                    this.updateAircraftCount();
                    this.showStatus('Cleared all aircraft', 'info');
                }
            });
        }
    }
    
    toggleAircraftTracking(enabled) {
        if (!this.adsbLayer) {
            this.showStatus('Aircraft tracking not available', 'error');
            return;
        }
        
        const controls = document.getElementById('aircraftTrackingControls');
        const intervalSelect = document.getElementById('aircraftUpdateInterval');
        
        if (enabled) {
            // Show controls
            if (controls) controls.style.display = 'block';
            
            // Get selected interval
            const interval = intervalSelect ? parseInt(intervalSelect.value) : 5;
            
            // Start tracking
            this.adsbLayer.start(interval);
            this.aircraftTrackingEnabled = true;
            
            // Start count update interval
            this.aircraftCountInterval = setInterval(() => {
                this.updateAircraftCount();
            }, 1000);
            
            this.showStatus(`Aircraft tracking enabled (${interval}s updates)`, 'success');
        } else {
            // Stop tracking
            this.adsbLayer.stop();
            this.aircraftTrackingEnabled = false;
            
            // Stop count update
            if (this.aircraftCountInterval) {
                clearInterval(this.aircraftCountInterval);
                this.aircraftCountInterval = null;
            }
            
            // Hide controls
            if (controls) controls.style.display = 'none';
            
            this.showStatus('Aircraft tracking disabled', 'info');
        }
    }
    
    updateAircraftCount() {
        const countEl = document.getElementById('aircraftCount');
        if (countEl && this.adsbLayer) {
            countEl.textContent = this.adsbLayer.getAircraftCount();
        }
    }
    
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
    
    setupEventListeners() {
        // Mission creation
        document.getElementById('createMissionBtn')?.addEventListener('click', () => this.createNewMission());
        
        // Mission selection
        document.getElementById('missionSelect')?.addEventListener('change', (e) => {
            if (e.target.value) {
                this.loadMission(parseInt(e.target.value));
            } else {
                this.clearMission();
            }
        });
        
        // Waypoint placement toggle
        document.getElementById('toggleWaypointPlacement')?.addEventListener('click', () => {
            this.toggleWaypointPlacement();
        });
        
        // Save mission
        document.getElementById('saveMissionBtn')?.addEventListener('click', () => this.saveMission());
        
        // Delete mission
        document.getElementById('deleteMissionBtn')?.addEventListener('click', () => this.deleteMission());
        
        // Clear waypoints
        document.getElementById('clearWaypointsBtn')?.addEventListener('click', () => this.clearWaypoints());
        
        // Default altitude input
        document.getElementById('defaultAltitude')?.addEventListener('change', (e) => {
            this.defaultAltitude = parseFloat(e.target.value) || 50.0;
            if (this.currentMission) {
                // Update mission default altitude
                this.updateMissionParameter('default_altitude', this.defaultAltitude);
            }
        });
        
        // Click handler for waypoint placement
        this.viewer.cesiumWidget.canvas.addEventListener('click', (event) => {
            if (this.isPlacingWaypoint) {
                this.addWaypointAtClick(event);
            }
        });
        
        // Login/logout removed - no authentication required
    }
    
    // ========== AUTHENTICATION ==========
    // Authentication removed - no login required
    
    updateAuthUI() {
        const loginPanel = document.getElementById('missionLoginPanel');
        const controlsPanel = document.getElementById('missionControlsPanel');
        const userInfoBar = document.getElementById('userInfoBar');
        
        // Always show mission controls, hide login panel
            if (loginPanel) loginPanel.style.display = 'none';
            if (controlsPanel) controlsPanel.style.display = 'block';
        if (userInfoBar) userInfoBar.style.display = 'none'; // Hide user info bar
    }
    
    // ========== MISSIONS ==========
    
    async loadMissions() {
        // No authentication check - always allow loading missions
        try {
            const response = await fetch('/label/api/missions/', {
                method: 'GET',
                headers: {
                    'X-CSRFToken': this.csrftoken
                }
            });
            
            if (response.status === 401) {
                // If API requires auth, just show empty list
                console.warn('[Mission Planner] API requires authentication, showing empty list');
                this.populateMissionSelect([]);
                return;
            }
            
            if (!response.ok) {
                throw new Error(`Failed to load missions: ${response.statusText}`);
            }
            
            const data = await response.json();
            this.populateMissionSelect(data.missions || []);
        } catch (error) {
            console.error('Error loading missions:', error);
            // Don't show error to user, just show empty list
            this.populateMissionSelect([]);
        }
    }
    
    populateMissionSelect(missions) {
        const select = document.getElementById('missionSelect');
        if (!select) return;
        
        // Clear existing options except the first one
        while (select.options.length > 1) {
            select.remove(1);
        }
        
        // Add missions
        missions.forEach(mission => {
            const option = document.createElement('option');
            option.value = mission.id;
            option.textContent = `${mission.name} (${mission.num_waypoints} waypoints)`;
            select.appendChild(option);
        });
    }
    
    async createNewMission() {
        // No authentication check - always allow creating missions
        const name = prompt('Enter mission name:');
        if (!name) return;
        
        try {
            const response = await fetch('/label/api/missions/create/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrftoken
                },
                body: JSON.stringify({
                    name: name,
                    description: '',
                    mission_type: 'CUSTOM',
                    default_altitude: this.defaultAltitude,
                    default_speed: this.defaultSpeed,
                    return_to_home: true
                })
            });
            
            if (response.status === 401) {
                this.showStatus('API requires authentication. Mission creation may not work.', 'warning');
                return;
            }
            
            if (!response.ok) {
                throw new Error(`Failed to create mission: ${response.statusText}`);
            }
            
            const data = await response.json();
            this.currentMission = data.mission;
            this.loadMissions(); // Refresh list
            document.getElementById('missionSelect').value = this.currentMission.id;
            this.showStatus('Mission created successfully', 'success');
        } catch (error) {
            console.error('Error creating mission:', error);
            this.showStatus('Error creating mission: ' + error.message, 'error');
        }
    }
    
    async loadMission(missionId) {
        try {
            const response = await fetch(`/label/api/missions/${missionId}/`, {
                method: 'GET',
                headers: {
                    'X-CSRFToken': this.csrftoken
                }
            });
            
            if (!response.ok) {
                throw new Error(`Failed to load mission: ${response.statusText}`);
            }
            
            const data = await response.json();
            this.currentMission = data.mission;
            this.defaultAltitude = this.currentMission.default_altitude;
            this.defaultSpeed = this.currentMission.default_speed;
            
            // Load waypoints
            this.waypoints = data.mission.waypoints.features || [];
            this.displayWaypoints();
            this.updateMissionInfo();
            
            this.showStatus(`Loaded mission: ${this.currentMission.name}`, 'success');
        } catch (error) {
            console.error('Error loading mission:', error);
            this.showStatus('Error loading mission: ' + error.message, 'error');
        }
    }
    
    clearMission() {
        this.currentMission = null;
        this.waypoints = [];
        this.clearWaypointEntities();
        this.updateMissionInfo();
    }
    
    clearWaypointEntities() {
        // Clear displayed waypoint entities from the map
        this.waypointEntities.forEach(entity => {
            this.viewer.entities.remove(entity);
        });
        this.waypointEntities = [];
        
        if (this.pathEntity) {
            this.viewer.entities.remove(this.pathEntity);
            this.pathEntity = null;
        }
    }
    
    toggleWaypointPlacement() {
        // No authentication check - always allow waypoint placement
        if (!this.currentMission) {
            this.showStatus('Please create or select a mission first', 'warning');
            return;
        }
        
        this.isPlacingWaypoint = !this.isPlacingWaypoint;
        const btn = document.getElementById('toggleWaypointPlacement');
        if (btn) {
            if (this.isPlacingWaypoint) {
                btn.classList.add('active');
                btn.innerHTML = '<i class="fas fa-times me-2"></i>Cancel Placement';
                btn.classList.remove('btn-success');
                btn.classList.add('btn-secondary');
                this.showStatus('Click on the map to add waypoints', 'info');
            } else {
                btn.classList.remove('active');
                btn.innerHTML = '<i class="fas fa-map-marker-alt me-2"></i>Add Waypoint';
                btn.classList.remove('btn-secondary');
                btn.classList.add('btn-success');
                this.showStatus('Waypoint placement cancelled', 'info');
            }
        }
    }
    
    addWaypointAtClick(event) {
        if (!this.currentMission) {
            this.showStatus('Please create or select a mission first', 'warning');
            this.isPlacingWaypoint = false;
            return;
        }
        
        // Get clicked position
        const cartesian = this.viewer.camera.pickEllipsoid(
            new Cesium.Cartesian2(event.clientX, event.clientY),
            this.viewer.scene.globe.ellipsoid
        );
        
        if (!cartesian) {
            return; // Clicked on nothing
        }
        
        const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
        const longitude = Cesium.Math.toDegrees(cartographic.longitude);
        const latitude = Cesium.Math.toDegrees(cartographic.latitude);
        const altitude = this.defaultAltitude;
        
        // Add waypoint
        this.addWaypoint(latitude, longitude, altitude);
    }
    
    async addWaypoint(latitude, longitude, altitude) {
        if (!this.currentMission) {
            this.showStatus('Please create or select a mission first', 'warning');
            return;
        }
        
        try {
            const response = await fetch(`/label/api/missions/${this.currentMission.id}/waypoints/add/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrftoken
                },
                body: JSON.stringify({
                    latitude: latitude,
                    longitude: longitude,
                    altitude: altitude,
                    waypoint_type: 'WAYPOINT',
                    speed: this.defaultSpeed
                })
            });
            
            if (!response.ok) {
                throw new Error(`Failed to add waypoint: ${response.statusText}`);
            }
            
            const data = await response.json();
            this.waypoints.push(data.waypoint);
            this.displayWaypoints();
            this.updateMissionInfo();
            this.showStatus('Waypoint added', 'success');
        } catch (error) {
            console.error('Error adding waypoint:', error);
            this.showStatus('Error adding waypoint: ' + error.message, 'error');
        }
    }
    
    displayWaypoints() {
        // Clear existing waypoints
        this.clearWaypointEntities();
        
        if (this.waypoints.length === 0) {
            return;
        }
        
        // Create waypoint entities
        const positions = [];
        this.waypoints.forEach((waypoint, index) => {
            const coords = waypoint.geometry.coordinates;
            const position = Cesium.Cartesian3.fromDegrees(coords[0], coords[1], coords[2] || this.defaultAltitude);
            positions.push(position);
            
            // Create waypoint entity
            const entity = this.viewer.entities.add({
                position: position,
                point: {
                    pixelSize: 10,
                    color: Cesium.Color.YELLOW,
                    outlineColor: Cesium.Color.BLACK,
                    outlineWidth: 2,
                    heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND
                },
                label: {
                    text: `WP${index + 1}`,
                    font: '14px sans-serif',
                    fillColor: Cesium.Color.WHITE,
                    outlineColor: Cesium.Color.BLACK,
                    outlineWidth: 2,
                    style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                    verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                    pixelOffset: new Cesium.Cartesian2(0, -20)
                }
            });
            
            this.waypointEntities.push(entity);
        });
        
        // Create path polyline
        if (positions.length > 1) {
            this.pathEntity = this.viewer.entities.add({
                polyline: {
                    positions: positions,
                    width: 3,
                    material: Cesium.Color.CYAN.withAlpha(0.7),
                    clampToGround: false
                }
            });
        }
    }
    
    async clearWaypoints() {
        if (!this.currentMission) return;
        
        if (!confirm('Are you sure you want to clear all waypoints?')) {
            return;
        }
        
        // Delete all waypoints
        const waypointsToDelete = [...this.waypoints];
        let deletedCount = 0;
        
        for (const waypoint of waypointsToDelete) {
            if (waypoint.properties && waypoint.properties.id) {
                try {
                    const response = await fetch(`/label/api/missions/${this.currentMission.id}/waypoints/${waypoint.properties.id}/remove/`, {
                        method: 'POST',
                        headers: {
                            'X-CSRFToken': this.csrftoken
                        }
                    });
                    
                    if (response.ok) {
                        deletedCount++;
                    }
                } catch (error) {
                    console.error('Error removing waypoint:', error);
                }
            }
        }
        
        // Reload mission to refresh waypoint list
        if (deletedCount > 0) {
            await this.loadMission(this.currentMission.id);
            this.showStatus(`Cleared ${deletedCount} waypoint(s)`, 'success');
        } else {
            this.showStatus('No waypoints to clear', 'warning');
        }
    }
    
    async saveMission() {
        if (!this.currentMission) {
            this.showStatus('No mission selected', 'warning');
            return;
        }
        
        // Mission details are saved automatically when waypoints are added
        // This could be used to update mission metadata
        this.showStatus('Mission saved', 'success');
    }
    
    async deleteMission() {
        if (!this.currentMission) {
            this.showStatus('No mission selected', 'warning');
            return;
        }
        
        if (!confirm(`Are you sure you want to delete mission "${this.currentMission.name}"?`)) {
            return;
        }
        
        try {
            const response = await fetch(`/label/api/missions/${this.currentMission.id}/delete/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.csrftoken
                }
            });
            
            if (!response.ok) {
                throw new Error(`Failed to delete mission: ${response.statusText}`);
            }
            
            this.clearMission();
            this.loadMissions();
            this.showStatus('Mission deleted', 'success');
        } catch (error) {
            console.error('Error deleting mission:', error);
            this.showStatus('Error deleting mission: ' + error.message, 'error');
        }
    }
    
    updateMissionInfo() {
        const infoDiv = document.getElementById('missionInfo');
        if (!infoDiv) return;
        
        if (!this.currentMission) {
            infoDiv.innerHTML = '<small style="color: #94a3b8;">No mission selected</small>';
            return;
        }
        
        infoDiv.innerHTML = `
            <div style="color: #cbd5e1;">
                <strong>${this.currentMission.name}</strong><br>
                <small>Type: ${this.currentMission.mission_type}</small><br>
                <small>Status: ${this.currentMission.status}</small><br>
                <small>Waypoints: ${this.waypoints.length}</small><br>
                <small>Default Altitude: ${this.defaultAltitude}m</small>
            </div>
        `;
    }
    
    async updateMissionParameter(param, value) {
        if (!this.currentMission) return;
        
        try {
            const updateData = {};
            updateData[param] = value;
            
            const response = await fetch(`/label/api/missions/${this.currentMission.id}/update/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrftoken
                },
                body: JSON.stringify(updateData)
            });
            
            if (response.ok) {
                const data = await response.json();
                this.currentMission = { ...this.currentMission, ...data.mission };
            }
        } catch (error) {
            console.error('Error updating mission parameter:', error);
        }
    }
    
    async initVehicleTracking() {
        // Initialize Vehicle Tracking within Mission Planner (merged with GPS Telemetry)
        if (!this.viewer) {
            console.warn('[Mission Planner] Viewer not available for Vehicle Tracking');
            return;
        }
        
        // Check if Vehicle Tracking UI exists
        const toggleCheckbox = document.getElementById('vehicleTrackingToggle');
        if (!toggleCheckbox) {
            console.warn('[Mission Planner] Vehicle Tracking UI not found');
            return;
        }
        
        // Setup event listeners for vehicle tracking UI
        this.setupVehicleTrackingEvents();
        
        // Store reference to GPS telemetry loader for accessing sessions
        this.gpsTelemetryLoader = window.gpsTelemetryLoader;
        
        console.log('[Mission Planner] Vehicle Tracking initialized (using GPS Telemetry data)');
    }
    
    setupVehicleTrackingEvents() {
        // Toggle vehicle tracking
        const toggleCheckbox = document.getElementById('vehicleTrackingToggle');
        if (toggleCheckbox) {
            toggleCheckbox.addEventListener('change', (e) => {
                this.toggleVehicleTracking(e.target.checked);
            });
        }
        
        // Update interval selector
        const intervalSelect = document.getElementById('vehicleUpdateInterval');
        if (intervalSelect) {
            intervalSelect.addEventListener('change', (e) => {
                const interval = parseInt(e.target.value);
                if (this.vehicleTrackingEnabled) {
                    this.stopVehicleTracking();
                    this.startVehicleTracking(interval);
                    this.showStatus(`Vehicle update interval changed to ${interval}s`, 'info');
                }
            });
        }
        
        // Refresh button
        const refreshBtn = document.getElementById('refreshVehiclesBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', async () => {
                if (this.vehicleTrackingEnabled) {
                    refreshBtn.disabled = true;
                    refreshBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Refreshing...';
                    await this.updateVehicles();
                    refreshBtn.disabled = false;
                    refreshBtn.innerHTML = '<i class="fas fa-sync-alt"></i> Refresh Now';
                }
            });
        }
        
        // Clear button
        const clearBtn = document.getElementById('clearVehiclesBtn');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                this.clearAllVehicles();
                this.showStatus('Cleared all vehicles', 'info');
            });
        }
    }
    
    toggleVehicleTracking(enabled) {
        const controls = document.getElementById('vehicleTrackingControls');
        const intervalSelect = document.getElementById('vehicleUpdateInterval');
        
        if (enabled) {
            // Show controls
            if (controls) controls.style.display = 'block';
            
            // Get selected interval
            const interval = intervalSelect ? parseInt(intervalSelect.value) : 5;
            
            // Start tracking
            this.startVehicleTracking(interval);
            this.showStatus('Vehicle tracking enabled', 'success');
        } else {
            // Hide controls
            if (controls) controls.style.display = 'none';
            
            // Stop tracking
            this.stopVehicleTracking();
            this.showStatus('Vehicle tracking disabled', 'info');
        }
    }
    
    startVehicleTracking(intervalSeconds = 5) {
        this.vehicleTrackingEnabled = true;
        this.vehicleUpdateInterval = intervalSeconds * 1000;
        
        // Initial update
        this.updateVehicles();
        
        // Set up periodic updates
        this.vehicleUpdateTimer = setInterval(() => {
            this.updateVehicles();
        }, this.vehicleUpdateInterval);
    }
    
    stopVehicleTracking() {
        this.vehicleTrackingEnabled = false;
        
        if (this.vehicleUpdateTimer) {
            clearInterval(this.vehicleUpdateTimer);
            this.vehicleUpdateTimer = null;
        }
    }
    
    async updateVehicles() {
        if (!this.viewer || !this.vehicleTrackingEnabled) {
            return;
        }
        
        // Prevent overlapping updates
        if (this.vehicleUpdateInProgress) {
            console.log('[Vehicle Tracking] Update already in progress, skipping...');
            return;
        }
        
        this.vehicleUpdateInProgress = true;
        
        try {
            console.log('[Vehicle Tracking] Starting vehicle position update...');
            // Use GPS Telemetry API to get vehicle positions
            const apiBaseUrl = window.location.origin + '/api/telemetry';
            
            // Get all sessions with GPS data
            const sessionsResponse = await fetch(`${apiBaseUrl}/sessions/?has_gps=true`);
            if (!sessionsResponse.ok) {
                throw new Error(`Failed to fetch GPS sessions: ${sessionsResponse.status}`);
            }
            
            const sessionsData = await sessionsResponse.json();
            if (!sessionsData.sessions || sessionsData.sessions.length === 0) {
                // No GPS sessions available
                this.updateVehicleEntities([]);
                this.updateVehicleCount();
                return;
            }
            
            // Group sessions by asset (vehicle name) and get the most recent session for each
            const vehicleSessions = new Map();
            sessionsData.sessions.forEach(session => {
                const asset = session.asset || 'Unknown';
                const existing = vehicleSessions.get(asset);
                
                // Keep the most recent session for each vehicle
                if (!existing || new Date(session.start_time) > new Date(existing.start_time)) {
                    vehicleSessions.set(asset, session);
                }
            });
            
            // For each vehicle, get the last position from its most recent session
            const vehiclePositions = [];
            
            for (const [vehicleName, session] of vehicleSessions.entries()) {
                try {
                    // Get the path data for this session
                    const pathResponse = await fetch(`${apiBaseUrl}/sessions/${session.session_id}/path/`);
                    if (!pathResponse.ok) {
                        console.warn(`Failed to get path for session ${session.session_id}`);
                        continue;
                    }
                    
                    const pathData = await pathResponse.json();
                    if (!pathData.geojson || !pathData.geojson.features) {
                        continue;
                    }
                    
                    // Find the last Point feature (most recent position)
                    const pointFeatures = pathData.geojson.features.filter(
                        f => f.geometry.type === 'Point'
                    );
                    
                    if (pointFeatures.length === 0) {
                        // If no points, try to get last position from LineString
                        const lineFeature = pathData.geojson.features.find(
                            f => f.geometry.type === 'LineString'
                        );
                        if (lineFeature && lineFeature.geometry.coordinates.length > 0) {
                            const lastCoord = lineFeature.geometry.coordinates[lineFeature.geometry.coordinates.length - 1];
                            vehiclePositions.push({
                                vehicle_id: vehicleName,
                                name: vehicleName,
                                current_latitude: lastCoord[1],
                                current_longitude: lastCoord[0],
                                current_altitude: lastCoord[2] || 0,
                                current_heading: 0, // GPS data may not have heading
                                current_speed: 0,
                                last_update: session.start_time,
                                display_color: '#10b981',
                                display_icon: 'car',
                                session_info: pathData.session_info
                            });
                        }
                    } else {
                        // Get the last point (most recent)
                        const lastPoint = pointFeatures[pointFeatures.length - 1];
                        const coords = lastPoint.geometry.coordinates;
                        const properties = lastPoint.properties || {};
                        
                        vehiclePositions.push({
                            vehicle_id: vehicleName,
                            name: vehicleName,
                            current_latitude: coords[1],
                            current_longitude: coords[0],
                            current_altitude: coords[2] || properties.altitude || 0,
                            current_heading: properties.heading || 0,
                            current_speed: properties.speed || 0,
                            last_update: properties.timestamp || session.start_time,
                            display_color: '#10b981',
                            display_icon: 'car',
                            session_info: pathData.session_info
                        });
                    }
                } catch (error) {
                    console.error(`Error getting position for vehicle ${vehicleName}:`, error);
                }
            }
            
            this.updateVehicleEntities(vehiclePositions);
            this.updateVehicleCount();
            console.log(`[Vehicle Tracking] Updated ${vehiclePositions.length} vehicle positions`);
            
        } catch (error) {
            console.error('[Vehicle Tracking] Error updating vehicles from GPS telemetry:', error);
            this.showStatus('Error updating vehicle locations from GPS data', 'error');
        } finally {
            this.vehicleUpdateInProgress = false;
        }
    }
    
    updateVehicleEntities(vehicles) {
        if (!this.viewer) return;
        
        // Remove vehicles that are no longer in the list
        const currentVehicleIds = new Set(vehicles.map(v => v.vehicle_id || v.id));
        for (const [vehicleId, entity] of this.vehicleEntities.entries()) {
            if (!currentVehicleIds.has(vehicleId)) {
                this.viewer.entities.remove(entity);
                this.vehicleEntities.delete(vehicleId);
            }
        }
        
        // Update or create vehicle entities
        vehicles.forEach(vehicle => {
            const vehicleId = vehicle.vehicle_id || vehicle.id;
            const lat = parseFloat(vehicle.current_latitude || vehicle.latitude);
            const lon = parseFloat(vehicle.current_longitude || vehicle.longitude);
            const alt = parseFloat(vehicle.current_altitude || vehicle.altitude || 0);
            const heading = parseFloat(vehicle.current_heading || vehicle.heading || 0);
            
            if (isNaN(lat) || isNaN(lon)) {
                console.warn(`[Vehicle Tracking] Invalid coordinates for vehicle ${vehicleId}`);
                return;
            }
            
            const color = vehicle.display_color || '#10b981';
            const icon = vehicle.display_icon || 'car';
            const name = vehicle.name || vehicleId;
            
            let entity = this.vehicleEntities.get(vehicleId);
            
            if (entity) {
                // Update existing entity
                entity.position = Cesium.Cartesian3.fromDegrees(lon, lat, alt);
                if (entity.billboard) {
                    entity.billboard.rotation = Cesium.Math.toRadians(-heading);
                }
                if (entity.label) {
                    entity.label.text = name;
                }
            } else {
                // Create new entity
                entity = this.viewer.entities.add({
                    id: `vehicle-${vehicleId}`,
                    name: name,
                    position: Cesium.Cartesian3.fromDegrees(lon, lat, alt),
                    billboard: {
                        image: this.getVehicleIcon(icon, color),
                        scale: 1.0,
                        rotation: Cesium.Math.toRadians(-heading),
                        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                        disableDepthTestDistance: Number.POSITIVE_INFINITY
                    },
                    label: {
                        text: name,
                        font: '12pt sans-serif',
                        fillColor: Cesium.Color.fromCssColorString(color),
                        outlineColor: Cesium.Color.BLACK,
                        outlineWidth: 2,
                        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                        pixelOffset: new Cesium.Cartesian2(0, -40),
                        disableDepthTestDistance: Number.POSITIVE_INFINITY
                    },
                    description: this.createVehicleDescription(vehicle)
                });
                
                this.vehicleEntities.set(vehicleId, entity);
            }
        });
    }
    
    getVehicleIcon(iconType, color) {
        // Create a simple SVG icon for the vehicle
        const svg = `
            <svg width="32" height="32" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
                <path d="M16 4 L24 12 L20 12 L20 24 L12 24 L12 12 L8 12 Z" 
                      fill="${color}" 
                      stroke="white" 
                      stroke-width="2"/>
            </svg>
        `;
        return 'data:image/svg+xml;base64,' + btoa(svg);
    }
    
    createVehicleDescription(vehicle) {
        const lastUpdate = vehicle.last_update ? new Date(vehicle.last_update).toLocaleString() : 'Unknown';
        const sessionInfo = vehicle.session_info || {};
        return `
            <div style="font-family: sans-serif; padding: 10px;">
                <h3>${vehicle.name || vehicle.vehicle_id}</h3>
                <p><strong>Last Known Position (from GPS Telemetry)</strong></p>
                <hr style="margin: 8px 0; border-color: #475569;">
                <p><strong>Location:</strong> ${vehicle.current_latitude?.toFixed(6)}, ${vehicle.current_longitude?.toFixed(6)}</p>
                <p><strong>Altitude:</strong> ${vehicle.current_altitude || 0} m</p>
                ${vehicle.current_heading ? `<p><strong>Heading:</strong> ${vehicle.current_heading}°</p>` : ''}
                ${vehicle.current_speed ? `<p><strong>Speed:</strong> ${vehicle.current_speed} m/s</p>` : ''}
                <hr style="margin: 8px 0; border-color: #475569;">
                ${sessionInfo.project ? `<p><strong>Project:</strong> ${sessionInfo.project}</p>` : ''}
                ${sessionInfo.total_points ? `<p><strong>GPS Points:</strong> ${sessionInfo.total_points}</p>` : ''}
                ${sessionInfo.flight_mode ? `<p><strong>Mode:</strong> ${sessionInfo.flight_mode}</p>` : ''}
                ${sessionInfo.start_time ? `<p><strong>Session Start:</strong> ${new Date(sessionInfo.start_time).toLocaleString()}</p>` : ''}
                <p><strong>Last Update:</strong> ${lastUpdate}</p>
            </div>
        `;
    }
    
    updateVehicleCount() {
        const count = this.vehicleEntities.size;
        const countElement = document.getElementById('vehicleCount');
        if (countElement) {
            countElement.textContent = count;
        }
    }
    
    clearAllVehicles() {
        // Remove all vehicle entities
        for (const [vehicleId, entity] of this.vehicleEntities.entries()) {
            this.viewer.entities.remove(entity);
        }
        this.vehicleEntities.clear();
        this.updateVehicleCount();
    }
    
    showStatus(message, type = 'info') {
        // Update status indicator if available
        const statusIndicator = document.getElementById('statusIndicator');
        if (statusIndicator) {
            statusIndicator.textContent = message;
            statusIndicator.className = `status-indicator status-${type}`;
            setTimeout(() => {
                statusIndicator.className = 'status-indicator';
            }, 3000);
        }
        console.log(`[Mission Planner] ${type.toUpperCase()}: ${message}`);
    }
}

// Export for use in other scripts
if (typeof window !== 'undefined') {
    window.MissionPlanner = MissionPlanner;
}

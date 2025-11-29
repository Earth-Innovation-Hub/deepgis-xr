/**
 * Mission Planner for DeepGIS-XR
 * Handles waypoint placement, mission management, and visualization on Cesium map
 */

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
        this.isAuthenticated = false;
        this.currentUser = null;
        
        // CSRF token
        this.csrftoken = this.getCookie('csrftoken');
        
        this.init();
    }
    
    async init() {
        this.setupEventListeners();
        await this.checkAuthStatus();
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
        
        // Login button
        document.getElementById('phoneLoginBtn')?.addEventListener('click', () => this.handleLogin());
        
        // Enter key on phone input
        document.getElementById('phoneNumberInput')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.handleLogin();
            }
        });
        
        // Logout button
        document.getElementById('logoutBtn')?.addEventListener('click', () => this.handleLogout());
    }
    
    // ========== AUTHENTICATION ==========
    
    async checkAuthStatus() {
        try {
            const response = await fetch('/api/auth/status/', {
                method: 'GET',
                headers: {
                    'X-CSRFToken': this.csrftoken
                }
            });
            
            const data = await response.json();
            this.isAuthenticated = data.authenticated;
            this.currentUser = data.authenticated ? data : null;
            
            this.updateAuthUI();
            
            if (this.isAuthenticated) {
                await this.loadMissions();
            }
        } catch (error) {
            console.error('[Mission Planner] Error checking auth status:', error);
            this.isAuthenticated = false;
            this.updateAuthUI();
        }
    }
    
    updateAuthUI() {
        const loginPanel = document.getElementById('missionLoginPanel');
        const controlsPanel = document.getElementById('missionControlsPanel');
        const userInfoBar = document.getElementById('userInfoBar');
        const loggedInUser = document.getElementById('loggedInUser');
        
        if (this.isAuthenticated) {
            // Show mission controls, hide login panel
            if (loginPanel) loginPanel.style.display = 'none';
            if (controlsPanel) controlsPanel.style.display = 'block';
            if (userInfoBar) userInfoBar.style.display = 'block';
            if (loggedInUser && this.currentUser) {
                loggedInUser.textContent = `Logged in as ${this.currentUser.phone || this.currentUser.username}`;
            }
            console.log('[Mission Planner] User authenticated');
        } else {
            // Show login panel, hide mission controls
            if (loginPanel) loginPanel.style.display = 'block';
            if (controlsPanel) controlsPanel.style.display = 'none';
            if (userInfoBar) userInfoBar.style.display = 'none';
            console.log('[Mission Planner] User not authenticated - showing login');
        }
    }
    
    async handleLogin() {
        const phoneInput = document.getElementById('phoneNumberInput');
        const errorDiv = document.getElementById('loginError');
        const successDiv = document.getElementById('loginSuccess');
        const loginBtn = document.getElementById('phoneLoginBtn');
        
        if (!phoneInput) return;
        
        const phoneNumber = phoneInput.value.trim();
        
        // Reset messages
        if (errorDiv) errorDiv.style.display = 'none';
        if (successDiv) successDiv.style.display = 'none';
        
        if (!phoneNumber) {
            if (errorDiv) {
                errorDiv.textContent = 'Please enter a phone number';
                errorDiv.style.display = 'block';
            }
            return;
        }
        
        // Disable button during request
        if (loginBtn) {
            loginBtn.disabled = true;
            loginBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Logging in...';
        }
        
        try {
            const response = await fetch('/api/auth/login/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrftoken
                },
                body: JSON.stringify({ phone_number: phoneNumber })
            });
            
            const data = await response.json();
            
            if (response.ok && data.authenticated) {
                // Login successful
                this.isAuthenticated = true;
                this.currentUser = data;
                
                if (successDiv) {
                    successDiv.textContent = 'Login successful!';
                    successDiv.style.display = 'block';
                }
                
                this.showStatus('Logged in successfully', 'success');
                
                // Update UI after brief delay
                setTimeout(() => {
                    this.updateAuthUI();
                    this.loadMissions();
                }, 500);
                
            } else if (data.status === 'verification_required') {
                // Verification needed (production mode)
                if (successDiv) {
                    successDiv.textContent = data.message || 'Verification code sent. Check your phone.';
                    successDiv.style.display = 'block';
                }
            } else {
                // Error
                if (errorDiv) {
                    errorDiv.textContent = data.error || 'Login failed';
                    errorDiv.style.display = 'block';
                }
            }
        } catch (error) {
            console.error('[Mission Planner] Login error:', error);
            if (errorDiv) {
                errorDiv.textContent = 'Network error. Please try again.';
                errorDiv.style.display = 'block';
            }
        } finally {
            // Re-enable button
            if (loginBtn) {
                loginBtn.disabled = false;
                loginBtn.innerHTML = '<i class="fas fa-sign-in-alt me-2"></i>Login with Phone';
            }
        }
    }
    
    async handleLogout() {
        try {
            const response = await fetch('/api/auth/logout/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.csrftoken
                }
            });
            
            if (response.ok) {
                this.isAuthenticated = false;
                this.currentUser = null;
                this.clearMission();
                this.updateAuthUI();
                this.showStatus('Logged out successfully', 'success');
            }
        } catch (error) {
            console.error('[Mission Planner] Logout error:', error);
            this.showStatus('Error logging out', 'error');
        }
    }
    
    // ========== MISSIONS ==========
    
    async loadMissions() {
        if (!this.isAuthenticated) {
            console.warn('[Mission Planner] Cannot load missions - not authenticated');
            return;
        }
        
        try {
            const response = await fetch('/label/api/missions/', {
                method: 'GET',
                headers: {
                    'X-CSRFToken': this.csrftoken
                }
            });
            
            if (response.status === 401) {
                this.isAuthenticated = false;
                this.updateAuthUI();
                console.warn('[Mission Planner] Session expired. Please log in again.');
                return;
            }
            
            if (!response.ok) {
                throw new Error(`Failed to load missions: ${response.statusText}`);
            }
            
            const data = await response.json();
            this.populateMissionSelect(data.missions);
        } catch (error) {
            console.error('Error loading missions:', error);
            this.showStatus('Error loading missions: ' + error.message, 'error');
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
        if (!this.isAuthenticated) {
            this.showStatus('Please log in to create missions', 'warning');
            return;
        }
        
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
                this.isAuthenticated = false;
                this.updateAuthUI();
                this.showStatus('Session expired. Please log in again.', 'warning');
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
        if (!this.isAuthenticated) {
            this.showStatus('Please log in first', 'warning');
            return;
        }
        
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

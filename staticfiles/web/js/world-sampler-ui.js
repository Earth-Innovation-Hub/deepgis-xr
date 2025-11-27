/**
 * World Sampler Frontend Interface
 * 
 * Integrates adaptive geospatial sampling with Cesium viewer.
 * Provides UI controls for sampling, feedback, and visualization.
 */

class WorldSamplerUI {
    constructor(viewer) {
        this.viewer = viewer;
        this.samplerClient = new SamplerAPIClient();
        this.currentSamples = [];
        this.sampleDataSource = null;
        this.selectedSample = null;
        this.currentSampleIndex = 0;
        this.isAutoSurveyActive = false;
        this.autoSurveyInterval = null;
        
        this.init();
    }
    
    async init() {
        console.log('Initializing World Sampler UI...');
        
        // Create UI panel
        this.createUI();
        
        // Initialize sampler with default settings
        await this.initializeSampler();
        
        // Setup event listeners
        this.setupEventListeners();
        
        console.log('World Sampler UI ready!');
    }
    
    createUI() {
        // Check if UI already exists
        if (document.getElementById('worldSamplerSection')) {
            return;
        }
        
        // Find the sidebar layer-controls container
        const layerControls = document.querySelector('.layer-controls') || 
                             document.querySelector('#sidebar-wrapper .sidebar-content') ||
                             document.querySelector('.sidebar-content');
        
        if (!layerControls) {
            console.warn('[World Sampler] Could not find sidebar container, creating floating widget as fallback');
            // Fallback to old floating widget behavior
            return this.createFloatingUI();
        }
        
        // Create World Sampler as an accordion panel within the sidebar
        const samplerSection = document.createElement('div');
        samplerSection.id = 'worldSamplerSection';
        samplerSection.className = 'layer-group accordion-panel';
        samplerSection.style.border = '2px solid #8b5cf6';
        samplerSection.style.background = 'rgba(139, 92, 246, 0.05)';
        samplerSection.innerHTML = `
                <!-- World Sampler Header (Accordion) -->
                <div class="layer-group-title accordion-header" data-target="worldSamplerContent">
                    <span><i class="fas fa-globe-americas"></i> World Sampler</span>
                    <i class="fas fa-chevron-down accordion-icon"></i>
                </div>
                <div class="accordion-content" id="worldSamplerContent">
                
                <!-- Initialization Section -->
                <div class="sampler-section">
                    <h4 class="accordion-header" data-target="initContent">
                        <span><i class="fas fa-cog"></i> Initialize</span>
                        <i class="fas fa-chevron-down accordion-icon"></i>
                    </h4>
                    <div class="sampler-section-content" id="initContent">
                    <div class="form-group">
                        <label>Distribution Type:</label>
                        <select id="samplerInitType" class="form-control">
                            <option value="uniform">Uniform</option>
                            <option value="gaussian_mixture" selected>Gaussian Mixture</option>
                            <option value="population_weighted">Population Weighted</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Number of Points:</label>
                        <input type="number" id="samplerNumPoints" class="form-control" 
                               value="1000" min="100" max="10000" step="100">
                    </div>
                    <button class="btn btn-primary w-100" id="samplerInitBtn">
                        <i class="fas fa-sync"></i> Initialize Sampler
                    </button>
                    </div>
                </div>
                
                <!-- Sampling Section -->
                <div class="sampler-section">
                    <h4 class="accordion-header" data-target="sampleContent">
                        <span><i class="fas fa-crosshairs"></i> Sample</span>
                        <i class="fas fa-chevron-down accordion-icon"></i>
                    </h4>
                    <div class="sampler-section-content" id="sampleContent">
                    <div class="form-group">
                        <label>Number of Samples:</label>
                        <input type="number" id="samplerNumSamples" class="form-control" 
                               value="10" min="1" max="100">
                    </div>
                    <div class="form-group">
                        <label>Method:</label>
                        <select id="samplerMethod" class="form-control">
                            <option value="weighted" selected>Weighted (Probabilistic)</option>
                            <option value="top_k">Top K (Highest Weights)</option>
                        </select>
                    </div>
                    <button class="btn btn-success w-100" id="samplerSampleBtn">
                        <i class="fas fa-map-marker-alt"></i> Sample Locations
                    </button>
                    </div>
                </div>
                
                <!-- Survey Navigation Section -->
                <div class="sampler-section" id="surveySection" style="display: none;">
                    <h4 class="accordion-header" data-target="surveyContent">
                        <span><i class="fas fa-route"></i> Survey Points</span>
                        <i class="fas fa-chevron-down accordion-icon"></i>
                    </h4>
                    <div class="sampler-section-content expanded" id="surveyContent">
                    <div class="survey-counter" id="surveyCounter">
                        Point <span id="currentPointNum">0</span> of <span id="totalPoints">0</span>
                    </div>
                    <div class="btn-group w-100 mb-2" role="group">
                        <button class="btn btn-primary" id="surveyPrev">
                            <i class="fas fa-chevron-left"></i> Previous
                        </button>
                        <button class="btn btn-primary" id="surveyNext">
                            <i class="fas fa-chevron-right"></i> Next
                        </button>
                    </div>
                    <div class="form-group">
                        <label>Auto-Survey Speed (seconds):</label>
                        <input type="range" id="surveySpeed" class="form-range" 
                               min="2" max="10" step="1" value="5">
                        <span id="surveySpeedValue">5s</span>
                    </div>
                    <button class="btn btn-info w-100 mb-2" id="surveyAutoToggle">
                        <i class="fas fa-play"></i> Start Auto-Survey
                    </button>
                    
                    <!-- Drone Fly Mode Section -->
                    <div class="form-group" style="border-top: 1px solid #475569; padding-top: 12px; margin-top: 12px;">
                        <h5 style="font-size: 13px; color: #60a5fa; margin-bottom: 8px;">
                            <i class="fas fa-drone"></i> Drone Fly Mode
                        </h5>
                        <div class="form-group">
                            <label>Fly Distance (meters):</label>
                            <input type="number" id="droneFlyDistance" class="form-control" 
                                   value="100" min="10" max="1000" step="10">
                        </div>
                        <div class="form-group">
                            <label>Speed (km/h):</label>
                            <input type="number" id="droneFlySpeed" class="form-control" 
                                   value="100" min="25" max="250" step="5">
                            <small class="text-muted" style="font-size: 10px;">Range: 25-250 km/h</small>
                        </div>
                        <button class="btn btn-success w-100" id="droneFlyBtn">
                            <i class="fas fa-paper-plane"></i> Fly Forward 100m @ 100 km/h
                        </button>
                        <small class="text-muted" style="display: block; margin-top: 6px; font-size: 11px;">
                            Flies along current heading, maintaining altitude & orientation
                        </small>
                    </div>
                    </div>
                </div>
                
                <!-- Feedback Section -->
                <div class="sampler-section">
                    <h4 class="accordion-header" data-target="feedbackContent">
                        <span><i class="fas fa-thumbs-up"></i> Feedback</span>
                        <i class="fas fa-chevron-down accordion-icon"></i>
                    </h4>
                    <div class="sampler-section-content" id="feedbackContent">
                    <div class="feedback-info">
                        <small>Click on a sample point on the map, then provide feedback:</small>
                    </div>
                    <div class="form-group">
                        <label>Reward Value:</label>
                        <input type="range" id="samplerReward" class="form-range" 
                               min="-1" max="1" step="0.1" value="1">
                        <div class="reward-value">
                            <span id="samplerRewardValue">1.0</span>
                            <span class="reward-label" id="samplerRewardLabel">Very Interesting</span>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Learning Rate:</label>
                        <input type="range" id="samplerLearningRate" class="form-range" 
                               min="0.1" max="1" step="0.1" value="0.2">
                        <span id="samplerLearningRateValue">0.2</span>
                    </div>
                    <button class="btn btn-warning w-100" id="samplerFeedbackBtn" disabled>
                        <i class="fas fa-star"></i> Submit Feedback
                    </button>
                    </div>
                </div>
                
                <!-- Update Rules Section -->
                <div class="sampler-section">
                    <h4 class="accordion-header" data-target="updateContent">
                        <span><i class="fas fa-sliders-h"></i> Update Strategy</span>
                        <i class="fas fa-chevron-down accordion-icon"></i>
                    </h4>
                    <div class="sampler-section-content" id="updateContent">
                    <div class="btn-group w-100" role="group">
                        <button class="btn btn-outline-primary" id="samplerExplore">
                            <i class="fas fa-compass"></i> Explore
                        </button>
                        <button class="btn btn-outline-primary" id="samplerConcentrate">
                            <i class="fas fa-bullseye"></i> Concentrate
                        </button>
                    </div>
                    </div>
                </div>
                
                <!-- Sampler Statistics Section -->
                <div class="sampler-section">
                    <h4 class="accordion-header" data-target="statsContent">
                        <span><i class="fas fa-chart-bar"></i> Sampler Statistics</span>
                        <i class="fas fa-chevron-down accordion-icon"></i>
                    </h4>
                    <div class="sampler-section-content" id="statsContent">
                    <div class="stats-grid" id="samplerStats">
                        <div class="stat-item">
                            <span class="stat-label">Samples Shown:</span>
                            <span class="stat-value" id="statSamplesShown">0</span>
                        </div>
                        <div class="stat-item">
                            <span class="stat-label">Total Sampled:</span>
                            <span class="stat-value" id="statTotalSampled">0</span>
                        </div>
                        <div class="stat-item">
                            <span class="stat-label">Updates:</span>
                            <span class="stat-value" id="statUpdates">0</span>
                        </div>
                        <div class="stat-item">
                            <span class="stat-label">Entropy:</span>
                            <span class="stat-value" id="statEntropy">-</span>
                        </div>
                    </div>
                    <button class="btn btn-info btn-sm w-100 mt-2" id="samplerRefreshStats">
                        <i class="fas fa-sync"></i> Refresh Stats
                    </button>
                    </div>
                </div>
                
                <!-- Feature Statistics Section (Histogram Chart) -->
                <div class="sampler-section">
                    <h4 class="accordion-header" data-target="featureStatsContent">
                        <span><i class="fas fa-chart-line"></i> Feature Statistics</span>
                        <i class="fas fa-chevron-down accordion-icon"></i>
                    </h4>
                    <div class="sampler-section-content" id="featureStatsContent">
                    <div class="chart-container" style="height: 200px; position: relative;">
                        <canvas id="histogram"></canvas>
                    </div>
                    </div>
                </div>
                
                <!-- GPS Telemetry Section (Vehicle Sampling Paths) -->
                <div class="sampler-section" id="gpsTelemetrySection">
                    <h4 class="accordion-header" data-target="gpsTelemetryContent">
                        <span><i class="fas fa-satellite"></i> GPS Telemetry (Vehicle Paths)</span>
                        <i class="fas fa-chevron-down accordion-icon"></i>
                    </h4>
                    <div class="sampler-section-content" id="gpsTelemetryContent">
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
                </div>
                
                <!-- Actions Section -->
                <div class="sampler-section">
                    <h4 class="accordion-header" data-target="actionsContent">
                        <span><i class="fas fa-tools"></i> Actions</span>
                        <i class="fas fa-chevron-down accordion-icon"></i>
                    </h4>
                    <div class="sampler-section-content" id="actionsContent">
                    <button class="btn btn-secondary w-100 mb-2" id="samplerClear">
                        <i class="fas fa-eraser"></i> Clear Samples
                    </button>
                    <button class="btn btn-danger w-100" id="samplerReset">
                        <i class="fas fa-redo"></i> Reset Sampler
                    </button>
                    </div>
                </div>
                </div>
        `;
        
        // Insert into sidebar (before Statistics section if it exists, otherwise at end)
        const statisticsSection = layerControls.querySelector('.statistics-section');
        if (statisticsSection) {
            layerControls.insertBefore(samplerSection, statisticsSection);
        } else {
            layerControls.appendChild(samplerSection);
        }
        
        // Add styles first
        this.addStyles();
        
        // Initialize accordion functionality after DOM is ready
        setTimeout(() => {
            this.initAccordion();
            // Initialize GPS Telemetry if viewer is available
            this.initGPSTelemetry();
        }, 0);
    }
    
    initGPSTelemetry() {
        // Initialize GPS Telemetry Loader within World Sampler
        if (!this.viewer) {
            console.warn('[World Sampler] Viewer not available for GPS Telemetry');
            return;
        }
        
        if (!window.GPSTelemetryLoader) {
            console.warn('[World Sampler] GPSTelemetryLoader not available');
            return;
        }
        
        // Check if GPS Telemetry UI already exists in World Sampler
        const gpsSection = document.getElementById('gpsTelemetrySection');
        if (!gpsSection) {
            console.warn('[World Sampler] GPS Telemetry section not found in UI');
            return;
        }
        
        // Check if GPS Telemetry is already initialized
        if (window.gpsTelemetryLoader && window.gpsTelemetryLoader.initializedInSampler) {
            return; // Already initialized
        }
        
        // Create GPS Telemetry Loader instance
        const gpsLoader = new window.GPSTelemetryLoader(this.viewer);
        
        // Mark as initialized in sampler to prevent duplicate initialization
        gpsLoader.initializedInSampler = true;
        window.gpsTelemetryLoader = gpsLoader;
        
        // Override createUI to prevent it from creating its own panel
        // The UI is already created in World Sampler, so just setup listeners
        gpsLoader.createUI = function() {
            // UI already exists in World Sampler, just setup event listeners and load sessions
            if (document.getElementById('gpsSessionSelect')) {
                this.setupEventListeners();
                this.loadSessions();
            }
        };
        
        // Setup event listeners and load sessions (UI is already in DOM)
        if (document.getElementById('gpsSessionSelect')) {
            gpsLoader.setupEventListeners();
            gpsLoader.loadSessions();
            console.log('[World Sampler] GPS Telemetry initialized');
        } else {
            // Wait a bit for DOM to be ready
            setTimeout(() => {
                if (document.getElementById('gpsSessionSelect')) {
                    gpsLoader.setupEventListeners();
                    gpsLoader.loadSessions();
                    console.log('[World Sampler] GPS Telemetry initialized (delayed)');
                }
            }, 100);
        }
    }
    
    createFloatingUI() {
        // Fallback: Create floating widget (old behavior)
        const panel = document.createElement('div');
        panel.id = 'worldSamplerPanel';
        panel.className = 'world-sampler-panel';
        panel.innerHTML = `
            <div class="sampler-header">
                <h3><i class="fas fa-globe-americas"></i> World Sampler</h3>
                <button class="btn-minimize" id="samplerMinimize">
                    <i class="fas fa-minus"></i>
                </button>
            </div>
            
            <div class="sampler-content" id="samplerContent">
                <!-- Same content as createUI but wrapped in floating panel -->
            </div>
        `;
        
        document.body.appendChild(panel);
        this.addStyles();
        setTimeout(() => this.initAccordion(), 0);
    }
    
    addStyles() {
        if (document.getElementById('worldSamplerStyles')) {
            return;
        }
        
        const style = document.createElement('style');
        style.id = 'worldSamplerStyles';
        style.textContent = `
            /* World Sampler integrated into sidebar - no floating widget */
            #worldSamplerSection {
                margin-bottom: 15px;
            }
            
            /* Nested sampler sections within World Sampler accordion */
            #worldSamplerSection .sampler-section {
                margin-bottom: 10px;
                margin-top: 10px;
                border: 1px solid rgba(139, 92, 246, 0.3);
                background: rgba(30, 41, 59, 0.3);
            }
            
            #worldSamplerSection .sampler-section h4 {
                font-size: 13px;
                padding: 10px 12px;
            }
            
            #worldSamplerSection .sampler-section-content {
                padding: 12px;
            }
            
            /* Chart container for Feature Statistics */
            #worldSamplerSection .chart-container {
                position: relative;
                height: 200px;
                width: 100%;
                background: rgba(30, 41, 59, 0.3);
                border-radius: 4px;
                padding: 8px;
            }
            
            #worldSamplerSection .chart-container canvas {
                max-height: 200px;
            }
            
            /* Fallback floating widget styles (if sidebar not found) */
            .world-sampler-panel {
                position: fixed;
                top: 80px;
                right: 20px;
                width: 320px;
                background: rgba(30, 41, 59, 0.95);
                border: 1px solid #475569;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
                z-index: 1000;
                max-height: calc(100vh - 100px);
                overflow-y: auto;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            
            .sampler-header {
                background: linear-gradient(135deg, #3b82f6, #8b5cf6);
                padding: 12px 15px;
                border-radius: 8px 8px 0 0;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            
            .sampler-header h3 {
                margin: 0;
                font-size: 16px;
                color: white;
                font-weight: 600;
            }
            
            .btn-minimize {
                background: rgba(255, 255, 255, 0.2);
                border: none;
                color: white;
                width: 28px;
                height: 28px;
                border-radius: 4px;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: background 0.2s;
            }
            
            .btn-minimize:hover {
                background: rgba(255, 255, 255, 0.3);
            }
            
            .sampler-content {
                padding: 15px;
                color: #e2e8f0;
            }
            
            .sampler-content.minimized {
                display: none;
            }
            
            .sampler-section {
                margin-bottom: 8px;
                border-radius: 6px;
                overflow: hidden;
                background: rgba(30, 41, 59, 0.5);
                border: 1px solid #475569;
            }
            
            .sampler-section:last-child {
                margin-bottom: 0;
            }
            
            .sampler-section h4 {
                font-size: 14px;
                margin: 0;
                color: #60a5fa;
                font-weight: 600;
                padding: 12px 15px;
                cursor: pointer;
                user-select: none;
                display: flex;
                justify-content: space-between;
                align-items: center;
                transition: background-color 0.2s ease;
            }
            
            .sampler-section h4:hover {
                background-color: rgba(59, 130, 246, 0.1);
            }
            
            .sampler-section h4.active {
                background-color: rgba(59, 130, 246, 0.15);
            }
            
            .sampler-section h4 .accordion-icon {
                transition: transform 0.3s ease;
                font-size: 0.85rem;
                color: #94a3b8;
            }
            
            .sampler-section h4.active .accordion-icon {
                transform: rotate(180deg);
            }
            
            .sampler-section-content {
                max-height: 0;
                overflow: hidden;
                transition: max-height 0.3s ease-out, padding 0.3s ease-out;
                padding: 0 15px;
            }
            
            .sampler-section-content.expanded {
                max-height: 2000px;
                padding: 15px;
                transition: max-height 0.4s ease-in, padding 0.3s ease-in;
            }
            
            .form-group {
                margin-bottom: 12px;
            }
            
            .form-group label {
                display: block;
                font-size: 12px;
                margin-bottom: 5px;
                color: #cbd5e1;
                font-weight: 500;
            }
            
            .form-control {
                width: 100%;
                padding: 8px;
                background: #1e293b;
                border: 1px solid #475569;
                border-radius: 4px;
                color: #e2e8f0;
                font-size: 13px;
            }
            
            .form-control:focus {
                outline: none;
                border-color: #3b82f6;
            }
            
            .form-range {
                width: 100%;
                accent-color: #3b82f6;
            }
            
            .reward-value {
                display: flex;
                justify-content: space-between;
                margin-top: 5px;
                font-size: 12px;
            }
            
            .reward-value span {
                color: #cbd5e1;
            }
            
            .reward-label {
                font-weight: 600;
                color: #60a5fa;
            }
            
            .btn {
                padding: 8px 12px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 13px;
                font-weight: 500;
                transition: all 0.2s;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 6px;
            }
            
            .btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }
            
            .btn-primary {
                background: #3b82f6;
                color: white;
            }
            
            .btn-primary:hover:not(:disabled) {
                background: #2563eb;
            }
            
            .btn-success {
                background: #10b981;
                color: white;
            }
            
            .btn-success:hover:not(:disabled) {
                background: #059669;
            }
            
            .btn-warning {
                background: #f59e0b;
                color: white;
            }
            
            .btn-warning:hover:not(:disabled) {
                background: #d97706;
            }
            
            .btn-danger {
                background: #ef4444;
                color: white;
            }
            
            .btn-danger:hover:not(:disabled) {
                background: #dc2626;
            }
            
            .btn-secondary {
                background: #64748b;
                color: white;
            }
            
            .btn-secondary:hover:not(:disabled) {
                background: #475569;
            }
            
            .btn-info {
                background: #0ea5e9;
                color: white;
            }
            
            .btn-info:hover:not(:disabled) {
                background: #0284c7;
            }
            
            .btn-outline-primary {
                background: transparent;
                border: 1px solid #3b82f6;
                color: #3b82f6;
            }
            
            .btn-outline-primary:hover {
                background: #3b82f6;
                color: white;
            }
            
            .w-100 {
                width: 100%;
            }
            
            .btn-group {
                display: flex;
                gap: 8px;
            }
            
            .btn-group .btn {
                flex: 1;
            }
            
            .stats-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 10px;
            }
            
            .stat-item {
                background: #1e293b;
                padding: 8px;
                border-radius: 4px;
                border: 1px solid #334155;
            }
            
            .stat-label {
                display: block;
                font-size: 11px;
                color: #94a3b8;
                margin-bottom: 4px;
            }
            
            .stat-value {
                display: block;
                font-size: 16px;
                font-weight: 600;
                color: #60a5fa;
            }
            
            .feedback-info {
                background: #1e293b;
                padding: 8px;
                border-radius: 4px;
                margin-bottom: 12px;
                border-left: 3px solid #f59e0b;
            }
            
            .feedback-info small {
                color: #cbd5e1;
                font-size: 11px;
            }
            
            .survey-counter {
                background: #1e293b;
                padding: 12px;
                border-radius: 6px;
                text-align: center;
                margin-bottom: 12px;
                font-size: 14px;
                font-weight: 600;
                color: #60a5fa;
                border: 2px solid #3b82f6;
            }
            
            .survey-counter span {
                color: #fbbf24;
                font-size: 16px;
            }
            
            .mt-2 {
                margin-top: 8px;
            }
            
            .mb-2 {
                margin-bottom: 8px;
            }
        `;
        
        document.head.appendChild(style);
    }
    
    initAccordion() {
        // Find accordion headers in World Sampler section (either in sidebar or floating panel)
        const samplerContainer = document.getElementById('worldSamplerSection') || 
                                document.getElementById('worldSamplerPanel');
        
        if (!samplerContainer) {
            console.warn('[World Sampler] Container not found for accordion initialization');
            return;
        }
        
        const accordionHeaders = samplerContainer.querySelectorAll('.accordion-header');
        
        accordionHeaders.forEach(header => {
            // Skip if already has event listener
            if (header.dataset.listenerAttached) return;
            header.dataset.listenerAttached = 'true';
            
            header.addEventListener('click', function() {
                const targetId = this.getAttribute('data-target');
                const content = document.getElementById(targetId);
                if (!content) return;
                
                const isExpanded = content.classList.contains('expanded');
                
                // Toggle this panel
                if (isExpanded) {
                    content.classList.remove('expanded');
                    this.classList.remove('active');
                } else {
                    content.classList.add('expanded');
                    this.classList.add('active');
                }
            });
        });
        
        // Expand main World Sampler panel by default
        const mainHeader = samplerContainer.querySelector('.layer-group-title.accordion-header[data-target="worldSamplerContent"]') ||
                          samplerContainer.querySelector('.accordion-header[data-target="initContent"]');
        if (mainHeader) {
            const mainTarget = mainHeader.getAttribute('data-target');
            const mainContent = document.getElementById(mainTarget);
            if (mainContent) {
                mainContent.classList.add('expanded');
                mainHeader.classList.add('active');
            }
        }
    }
    
    setupEventListeners() {
        // Minimize button (only exists in floating widget fallback)
        const minimizeBtn = document.getElementById('samplerMinimize');
        if (minimizeBtn) {
            minimizeBtn.addEventListener('click', () => {
                const content = document.getElementById('samplerContent');
                if (content) {
                    content.classList.toggle('minimized');
                    const icon = document.querySelector('#samplerMinimize i');
                    if (icon) {
                        icon.className = content.classList.contains('minimized') ? 'fas fa-plus' : 'fas fa-minus';
                    }
                }
            });
        }
        
        // Initialize button
        document.getElementById('samplerInitBtn').addEventListener('click', () => {
            this.initializeSampler();
        });
        
        // Sample button
        document.getElementById('samplerSampleBtn').addEventListener('click', () => {
            this.sampleLocations();
        });
        
        // Feedback button
        document.getElementById('samplerFeedbackBtn').addEventListener('click', () => {
            this.submitFeedback();
        });
        
        // Explore button
        document.getElementById('samplerExplore').addEventListener('click', () => {
            this.updateExploration();
        });
        
        // Concentrate button
        document.getElementById('samplerConcentrate').addEventListener('click', () => {
            this.updateConcentration();
        });
        
        // Clear button
        document.getElementById('samplerClear').addEventListener('click', () => {
            this.clearSamples();
        });
        
        // Reset button
        document.getElementById('samplerReset').addEventListener('click', () => {
            this.resetSampler();
        });
        
        // Refresh stats button
        document.getElementById('samplerRefreshStats').addEventListener('click', () => {
            this.updateStatistics();
        });
        
        // Survey navigation buttons
        document.getElementById('surveyPrev').addEventListener('click', () => {
            this.navigateToPreviousSample();
        });
        
        document.getElementById('surveyNext').addEventListener('click', () => {
            this.navigateToNextSample();
        });
        
        // Auto-survey toggle
        document.getElementById('surveyAutoToggle').addEventListener('click', () => {
            this.toggleAutoSurvey();
        });
        
        // Survey speed slider
        document.getElementById('surveySpeed').addEventListener('input', (e) => {
            document.getElementById('surveySpeedValue').textContent = e.target.value + 's';
            
            // If auto-survey is running, restart with new speed
            if (this.isAutoSurveyActive) {
                this.stopAutoSurvey();
                this.startAutoSurvey();
            }
        });
        
        // Drone fly mode button
        document.getElementById('droneFlyBtn').addEventListener('click', () => {
            this.flyDroneMode();
        });
        
        // Update drone fly button text when distance or speed changes
        const updateDroneFlyButton = () => {
            const distance = document.getElementById('droneFlyDistance').value || 100;
            const speed = document.getElementById('droneFlySpeed').value || 100;
            document.getElementById('droneFlyBtn').innerHTML = 
                `<i class="fas fa-paper-plane"></i> Fly Forward ${distance}m @ ${speed} km/h`;
        };
        
        document.getElementById('droneFlyDistance').addEventListener('input', updateDroneFlyButton);
        document.getElementById('droneFlySpeed').addEventListener('input', updateDroneFlyButton);
        
        // Reward slider
        document.getElementById('samplerReward').addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            document.getElementById('samplerRewardValue').textContent = value.toFixed(1);
            
            // Update label
            let label = 'Neutral';
            if (value > 0.7) label = 'Very Interesting';
            else if (value > 0.3) label = 'Interesting';
            else if (value > -0.3) label = 'Neutral';
            else if (value > -0.7) label = 'Not Interesting';
            else label = 'Avoid';
            
            document.getElementById('samplerRewardLabel').textContent = label;
        });
        
        // Learning rate slider
        document.getElementById('samplerLearningRate').addEventListener('input', (e) => {
            document.getElementById('samplerLearningRateValue').textContent = e.target.value;
        });
        
        // Cesium click handler for selecting samples
        const handler = new Cesium.ScreenSpaceEventHandler(this.viewer.scene.canvas);
        handler.setInputAction((click) => {
            const pickedObject = this.viewer.scene.pick(click.position);
            if (Cesium.defined(pickedObject) && pickedObject.id && pickedObject.id.properties) {
                this.selectSample(pickedObject.id);
            }
        }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    }
    
    async initializeSampler() {
        const initType = document.getElementById('samplerInitType').value;
        const numPoints = parseInt(document.getElementById('samplerNumPoints').value);
        
        try {
            const result = await this.samplerClient.initialize({
                num_points: numPoints,
                initialization: initType
            });
            
            console.log('Sampler initialized:', result);
            this.showNotification('Sampler initialized successfully!', 'success');
            await this.updateStatistics();
            
        } catch (error) {
            console.error('Failed to initialize sampler:', error);
            this.showNotification('Failed to initialize sampler', 'error');
        }
    }
    
    async sampleLocations() {
        const n = parseInt(document.getElementById('samplerNumSamples').value);
        const method = document.getElementById('samplerMethod').value;
        
        try {
            const result = await this.samplerClient.sample(n, method);
            
            console.log('Sampled locations:', result);
            this.currentSamples = result.samples;
            
            // Visualize on Cesium
            this.visualizeSamples(result.geojson);
            
            // Update stats
            document.getElementById('statSamplesShown').textContent = result.samples.length;
            await this.updateStatistics();
            
            // Show survey section
            if (result.samples.length > 0) {
                const surveySection = document.getElementById('surveySection');
                surveySection.style.display = 'block';
                // Expand survey section when samples are loaded
                const surveyContent = document.getElementById('surveyContent');
                const surveyHeader = surveySection.querySelector('.accordion-header');
                if (surveyContent && surveyHeader) {
                    surveyContent.classList.add('expanded');
                    surveyHeader.classList.add('active');
                }
                this.currentSampleIndex = 0;
                this.updateSurveyCounter();
            }
            
            this.showNotification(`Sampled ${result.samples.length} locations!`, 'success');
            
        } catch (error) {
            console.error('Failed to sample locations:', error);
            this.showNotification('Failed to sample locations', 'error');
        }
    }
    
    visualizeSamples(geojson) {
        // Remove existing data source
        if (this.sampleDataSource) {
            this.viewer.dataSources.remove(this.sampleDataSource);
        }
        
        // Load new GeoJSON
        Cesium.GeoJsonDataSource.load(geojson, {
            stroke: Cesium.Color.YELLOW,
            fill: Cesium.Color.YELLOW.withAlpha(0.5),
            strokeWidth: 3,
            markerSize: 10,
            markerSymbol: 'circle',
            markerColor: Cesium.Color.YELLOW
        }).then(dataSource => {
            this.sampleDataSource = dataSource;
            this.viewer.dataSources.add(dataSource);
            
            // Customize each entity
            const entities = dataSource.entities.values;
            entities.forEach((entity, index) => {
                entity.billboard = {
                    image: this.createSampleMarker(index + 1),
                    verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                    scale: 1.0
                };
                // Store metadata as simple properties (not Cesium PropertyBag to avoid circular refs)
                entity.sampleIndex = index;
                entity.sampleWeight = geojson.features[index].properties.weight;
                entity.sampleDbId = geojson.features[index].properties.db_id;
            });
            
            // Fly to first sample with zoom level 20 (approximately 300m altitude)
            if (entities.length > 0) {
                const position = entities[0].position.getValue(Cesium.JulianDate.now());
                const cartographic = Cesium.Cartographic.fromCartesian(position);
                
                this.viewer.camera.flyTo({
                    destination: Cesium.Cartesian3.fromRadians(
                        cartographic.longitude,
                        cartographic.latitude,
                        300  // Zoom level 20 ≈ 300m altitude
                    ),
                    duration: 2.0,
                    orientation: {
                        heading: Cesium.Math.toRadians(0),
                        pitch: Cesium.Math.toRadians(-45),  // 45° downward tilt
                        roll: 0.0
                    }
                });
            }
        });
    }
    
    createSampleMarker(number) {
        const canvas = document.createElement('canvas');
        canvas.width = 40;
        canvas.height = 40;
        const ctx = canvas.getContext('2d');
        
        // Draw circle
        ctx.fillStyle = '#fbbf24';
        ctx.beginPath();
        ctx.arc(20, 20, 18, 0, Math.PI * 2);
        ctx.fill();
        
        // Draw border
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 3;
        ctx.stroke();
        
        // Draw number
        ctx.fillStyle = '#1e293b';
        ctx.font = 'bold 16px Arial';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(number, 20, 20);
        
        return canvas.toDataURL();
    }
    
    selectSample(entity) {
        this.selectedSample = entity;
        
        // Highlight selected
        entity.billboard.scale = 1.5;
        entity.billboard.color = Cesium.Color.LIME;
        
        // Enable feedback button
        document.getElementById('samplerFeedbackBtn').disabled = false;
        
        const index = entity.sampleIndex;
        this.showNotification(`Selected sample #${index + 1}`, 'info');
        
        // Fly to selected sample with zoom level 20
        const position = entity.position.getValue(Cesium.JulianDate.now());
        const cartographic = Cesium.Cartographic.fromCartesian(position);
        
        this.viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromRadians(
                cartographic.longitude,
                cartographic.latitude,
                300  // Zoom level 20 ≈ 300m altitude
            ),
            duration: 1.5,
            orientation: {
                heading: Cesium.Math.toRadians(0),
                pitch: Cesium.Math.toRadians(-45),
                roll: 0.0
            }
        });
    }
    
    /**
     * Calculate zoom level from camera altitude
     * Cesium zoom levels roughly follow: altitude = 40075000 / (2^zoom)
     */
    getCameraZoomLevel() {
        const cameraHeight = this.viewer.camera.positionCartographic.height;
        if (cameraHeight <= 0) return 28;
        const zoom = Math.log2(40075000 / cameraHeight);
        return Math.max(0, Math.min(28, Math.round(zoom)));
    }
    
    async submitFeedback() {
        if (!this.selectedSample) {
            this.showNotification('Please select a sample first', 'warning');
            return;
        }
        
        const position = this.selectedSample.position.getValue(Cesium.JulianDate.now());
        const cartographic = Cesium.Cartographic.fromCartesian(position);
        const lat = Cesium.Math.toDegrees(cartographic.latitude);
        const lon = Cesium.Math.toDegrees(cartographic.longitude);
        const alt = cartographic.height;
        
        const reward = parseFloat(document.getElementById('samplerReward').value);
        const learningRate = parseFloat(document.getElementById('samplerLearningRate').value);
        const zoom = this.getCameraZoomLevel();
        
        try {
            const result = await this.samplerClient.update({
                rule: 'reward',
                feedback_points: [{
                    lat, 
                    lon, 
                    alt, 
                    reward,
                    zoom,
                    weight: this.selectedSample.sampleWeight || 1.0
                }],
                params: {learning_rate: learningRate, radius: 100000}
            });
            
            console.log('Feedback submitted:', result);
            this.showNotification(`Feedback saved to DB! (zoom: ${zoom})`, 'success');
            
            // Reset selection
            this.selectedSample.billboard.scale = 1.0;
            this.selectedSample.billboard.color = Cesium.Color.WHITE;
            this.selectedSample = null;
            document.getElementById('samplerFeedbackBtn').disabled = true;
            
            await this.updateStatistics();
            
        } catch (error) {
            console.error('Failed to submit feedback:', error);
            this.showNotification('Failed to submit feedback', 'error');
        }
    }
    
    async updateExploration() {
        try {
            const result = await this.samplerClient.update({
                rule: 'exploration',
                params: {exploration_bonus: 0.5, min_distance: 50000}
            });
            
            console.log('Exploration update applied:', result);
            this.showNotification('Exploration strategy applied!', 'success');
            await this.updateStatistics();
            
        } catch (error) {
            console.error('Failed to update exploration:', error);
            this.showNotification('Failed to update exploration', 'error');
        }
    }
    
    async updateConcentration() {
        if (this.currentSamples.length === 0) {
            this.showNotification('Sample some locations first', 'warning');
            return;
        }
        
        // Use current samples as high-value feedback
        const feedbackPoints = this.currentSamples.slice(0, 5).map(s => ({
            lat: s.lat,
            lon: s.lon,
            alt: s.alt,
            reward: s.weight * 10
        }));
        
        try {
            const result = await this.samplerClient.update({
                rule: 'concentration',
                feedback_points: feedbackPoints,
                params: {concentration_factor: 2.0}
            });
            
            console.log('Concentration update applied:', result);
            this.showNotification('Concentration strategy applied!', 'success');
            await this.updateStatistics();
            
        } catch (error) {
            console.error('Failed to update concentration:', error);
            this.showNotification('Failed to update concentration', 'error');
        }
    }
    
    clearSamples() {
        // Stop auto-survey if running
        this.stopAutoSurvey();
        
        if (this.sampleDataSource) {
            this.viewer.dataSources.remove(this.sampleDataSource);
            this.sampleDataSource = null;
        }
        this.currentSamples = [];
        this.selectedSample = null;
        this.currentSampleIndex = 0;
        
        document.getElementById('samplerFeedbackBtn').disabled = true;
        document.getElementById('statSamplesShown').textContent = '0';
        document.getElementById('surveySection').style.display = 'none';
        
        this.showNotification('Samples cleared', 'info');
    }
    
    async resetSampler() {
        try {
            const result = await this.samplerClient.reset();
            console.log('Sampler reset:', result);
            
            this.clearSamples();
            await this.updateStatistics();
            
            this.showNotification('Sampler reset successfully!', 'success');
            
        } catch (error) {
            console.error('Failed to reset sampler:', error);
            this.showNotification('Failed to reset sampler', 'error');
        }
    }
    
    async updateStatistics() {
        try {
            const result = await this.samplerClient.getStatistics();
            const stats = result.statistics;
            
            document.getElementById('statTotalSampled').textContent = stats.num_samples || 0;
            document.getElementById('statUpdates').textContent = result.history.num_updates || 0;
            document.getElementById('statEntropy').textContent = 
                stats.weight_stats.entropy ? stats.weight_stats.entropy.toFixed(2) : '-';
            
        } catch (error) {
            console.error('Failed to update statistics:', error);
        }
    }
    
    navigateToPreviousSample() {
        if (this.currentSamples.length === 0) return;
        
        this.currentSampleIndex = (this.currentSampleIndex - 1 + this.currentSamples.length) % this.currentSamples.length;
        this.flyToSample(this.currentSampleIndex);
        this.updateSurveyCounter();
    }
    
    navigateToNextSample() {
        if (this.currentSamples.length === 0) return;
        
        this.currentSampleIndex = (this.currentSampleIndex + 1) % this.currentSamples.length;
        this.flyToSample(this.currentSampleIndex);
        this.updateSurveyCounter();
    }
    
    flyToSample(index) {
        if (!this.sampleDataSource || index >= this.currentSamples.length) return;
        
        const entities = this.sampleDataSource.entities.values;
        if (index >= entities.length) return;
        
        const entity = entities[index];
        const sample = this.currentSamples[index];
        
        // Highlight current sample
        entities.forEach((e, i) => {
            if (i === index) {
                e.billboard.scale = 1.3;
                e.billboard.color = Cesium.Color.CYAN;
            } else {
                e.billboard.scale = 1.0;
                e.billboard.color = Cesium.Color.YELLOW;
            }
        });
        
        // Fly to sample
        const position = entity.position.getValue(Cesium.JulianDate.now());
        const cartographic = Cesium.Cartographic.fromCartesian(position);
        
        this.viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromRadians(
                cartographic.longitude,
                cartographic.latitude,
                300  // 300m altitude
            ),
            duration: 1.5,
            orientation: {
                heading: Cesium.Math.toRadians(0),
                pitch: Cesium.Math.toRadians(-45),
                roll: 0.0
            }
        });
        
        // Show sample info
        this.showNotification(
            `Point ${index + 1}: Lat ${sample.lat.toFixed(3)}°, Lon ${sample.lon.toFixed(3)}°`, 
            'info'
        );
    }
    
    /**
     * Drone Fly Mode: Fly forward along current heading for specified distance
     * Maintains current altitude, pitch, and roll while moving forward
     */
    flyDroneMode() {
        const camera = this.viewer.camera;
        const ellipsoid = this.viewer.scene.globe.ellipsoid;
        
        // Get current camera pose
        const currentPosition = camera.positionCartographic;
        const currentLon = Cesium.Math.toDegrees(currentPosition.longitude);
        const currentLat = Cesium.Math.toDegrees(currentPosition.latitude);
        const currentAlt = currentPosition.height;
        const currentHeading = Cesium.Math.toDegrees(camera.heading);
        const currentPitch = Cesium.Math.toDegrees(camera.pitch);
        const currentRoll = Cesium.Math.toDegrees(camera.roll);
        
        // Get fly distance and speed from UI
        const flyDistance = parseFloat(document.getElementById('droneFlyDistance').value) || 100;
        const speedKmh = parseFloat(document.getElementById('droneFlySpeed').value) || 100;
        
        // Validate speed range
        const speed = Math.max(25, Math.min(250, speedKmh));
        if (speed !== speedKmh) {
            document.getElementById('droneFlySpeed').value = speed;
        }
        
        // Convert speed from km/h to m/s
        // 1 km/h = 1000 m / 3600 s = 0.2778 m/s
        const speedMs = speed * 0.277777778;
        
        // Calculate flight duration based on distance and speed
        // duration = distance / speed
        const duration = Math.max(0.5, Math.min(30, flyDistance / speedMs)); // Clamp between 0.5s and 30s
        
        // Calculate destination point using geodetic calculations
        // Convert heading to bearing (Cesium heading: 0 = North, clockwise)
        // Geodetic bearing: 0 = North, clockwise
        const bearing = currentHeading; // Already in degrees, 0 = North
        
        // Calculate destination using haversine formula with altitude consideration
        const destination = this.calculateDestinationPoint(
            currentLat,
            currentLon,
            currentAlt,
            bearing,
            flyDistance
        );
        
        // Convert to Cesium coordinates
        const destinationCartesian = Cesium.Cartesian3.fromRadians(
            Cesium.Math.toRadians(destination.longitude),
            Cesium.Math.toRadians(destination.latitude),
            destination.altitude
        );
        
        // Fly to destination while maintaining orientation
        this.viewer.camera.flyTo({
            destination: destinationCartesian,
            duration: duration, // Calculated based on distance and speed
            orientation: {
                heading: Cesium.Math.toRadians(bearing), // Maintain heading
                pitch: Cesium.Math.toRadians(currentPitch), // Maintain pitch
                roll: Cesium.Math.toRadians(currentRoll) // Maintain roll
            },
            complete: () => {
                // Show notification when flight completes
                this.showNotification(
                    `Flew ${flyDistance}m forward at ${speed} km/h (heading: ${bearing.toFixed(1)}°)`,
                    'success'
                );
            }
        });
        
        // Show immediate feedback
        this.showNotification(
            `Flying ${flyDistance}m forward at ${speed} km/h along heading ${bearing.toFixed(1)}°...`,
            'info'
        );
    }
    
    /**
     * Calculate destination point given start point, bearing, and distance
     * Uses Cesium's ellipsoid calculations for accuracy
     * 
     * @param {number} lat - Starting latitude in degrees
     * @param {number} lon - Starting longitude in degrees
     * @param {number} alt - Starting altitude in meters
     * @param {number} bearing - Bearing in degrees (0 = North, clockwise)
     * @param {number} distance - Distance in meters
     * @returns {Object} Destination point {latitude, longitude, altitude}
     */
    calculateDestinationPoint(lat, lon, alt, bearing, distance) {
        const ellipsoid = Cesium.Ellipsoid.WGS84;
        
        // Convert to radians
        const latRad = Cesium.Math.toRadians(lat);
        const lonRad = Cesium.Math.toRadians(lon);
        const bearingRad = Cesium.Math.toRadians(bearing);
        
        // Get ellipsoid parameters
        const a = ellipsoid.maximumRadius; // Semi-major axis (meters)
        const b = ellipsoid.minimumRadius; // Semi-minor axis (meters)
        const f = (a - b) / a; // Flattening
        const e2 = f * (2 - f); // First eccentricity squared
        
        // Calculate radius of curvature at current latitude
        const sinLat = Math.sin(latRad);
        const cosLat = Math.cos(latRad);
        const N = a / Math.sqrt(1 - e2 * sinLat * sinLat); // Prime vertical radius
        
        // Total radius (ellipsoid + altitude)
        const R = N + alt;
        
        // Angular distance in radians
        const angularDistance = distance / R;
        
        // Calculate destination using spherical trigonometry
        // (Accurate for distances < 100km, which covers all drone flights)
        const cosAngularDist = Math.cos(angularDistance);
        const sinAngularDist = Math.sin(angularDistance);
        
        const destLat = Math.asin(
            sinLat * cosAngularDist +
            cosLat * sinAngularDist * Math.cos(bearingRad)
        );
        
        const destLon = lonRad + Math.atan2(
            Math.sin(bearingRad) * sinAngularDist * cosLat,
            cosAngularDist - sinLat * Math.sin(destLat)
        );
        
        return {
            latitude: Cesium.Math.toDegrees(destLat),
            longitude: Cesium.Math.toDegrees(destLon),
            altitude: alt // Maintain altitude
        };
    }
    
    updateSurveyCounter() {
        document.getElementById('currentPointNum').textContent = this.currentSampleIndex + 1;
        document.getElementById('totalPoints').textContent = this.currentSamples.length;
    }
    
    toggleAutoSurvey() {
        if (this.isAutoSurveyActive) {
            this.stopAutoSurvey();
        } else {
            this.startAutoSurvey();
        }
    }
    
    startAutoSurvey() {
        if (this.currentSamples.length === 0) {
            this.showNotification('No samples to survey', 'warning');
            return;
        }
        
        this.isAutoSurveyActive = true;
        const speed = parseInt(document.getElementById('surveySpeed').value) * 1000;
        
        // Update button
        const btn = document.getElementById('surveyAutoToggle');
        btn.innerHTML = '<i class="fas fa-pause"></i> Stop Auto-Survey';
        btn.className = 'btn btn-warning w-100';
        
        // Start auto-cycling
        this.autoSurveyInterval = setInterval(() => {
            this.navigateToNextSample();
        }, speed);
        
        // Fly to first sample immediately
        this.flyToSample(this.currentSampleIndex);
        
        this.showNotification('Auto-survey started', 'success');
    }
    
    stopAutoSurvey() {
        this.isAutoSurveyActive = false;
        
        if (this.autoSurveyInterval) {
            clearInterval(this.autoSurveyInterval);
            this.autoSurveyInterval = null;
        }
        
        // Update button
        const btn = document.getElementById('surveyAutoToggle');
        btn.innerHTML = '<i class="fas fa-play"></i> Start Auto-Survey';
        btn.className = 'btn btn-info w-100';
        
        this.showNotification('Auto-survey stopped', 'info');
    }
    
    showNotification(message, type = 'info') {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `sampler-notification notification-${type}`;
        notification.innerHTML = `
            <i class="fas fa-${this.getNotificationIcon(type)}"></i>
            <span>${message}</span>
        `;
        
        // Add styles if not exists
        if (!document.getElementById('samplerNotificationStyles')) {
            const style = document.createElement('style');
            style.id = 'samplerNotificationStyles';
            style.textContent = `
                .sampler-notification {
                    position: fixed;
                    top: 20px;
                    right: 360px;
                    padding: 12px 20px;
                    border-radius: 6px;
                    color: white;
                    font-size: 14px;
                    z-index: 10000;
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    animation: slideIn 0.3s ease-out;
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
                }
                
                .notification-success { background: #10b981; }
                .notification-error { background: #ef4444; }
                .notification-warning { background: #f59e0b; }
                .notification-info { background: #3b82f6; }
                
                @keyframes slideIn {
                    from {
                        transform: translateX(400px);
                        opacity: 0;
                    }
                    to {
                        transform: translateX(0);
                        opacity: 1;
                    }
                }
            `;
            document.head.appendChild(style);
        }
        
        document.body.appendChild(notification);
        
        // Remove after 3 seconds
        setTimeout(() => {
            notification.style.animation = 'slideIn 0.3s ease-out reverse';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }
    
    getNotificationIcon(type) {
        const icons = {
            success: 'check-circle',
            error: 'exclamation-circle',
            warning: 'exclamation-triangle',
            info: 'info-circle'
        };
        return icons[type] || 'info-circle';
    }
}


/**
 * Sampler API Client
 * Handles communication with the backend API
 */
class SamplerAPIClient {
    constructor() {
        this.baseURL = '/webclient/sampler';
    }
    
    async initialize(config) {
        return await this.post('/initialize', config);
    }
    
    async sample(n, method = 'weighted') {
        return await this.post('/sample', {n, method});
    }
    
    async update(config) {
        return await this.post('/update', config);
    }
    
    async query(lat, lon, alt, radius) {
        return await this.post('/query', {lat, lon, alt, radius});
    }
    
    async getStatistics() {
        return await this.get('/statistics');
    }
    
    async reset(keepHistory = false) {
        return await this.post('/reset', {keep_history: keepHistory});
    }
    
    async getHistory(limit = 100) {
        return await this.get(`/history?limit=${limit}`);
    }
    
    async post(endpoint, data) {
        const response = await fetch(this.baseURL + endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            throw new Error(`API Error: ${response.statusText}`);
        }
        
        return await response.json();
    }
    
    async get(endpoint) {
        const response = await fetch(this.baseURL + endpoint);
        
        if (!response.ok) {
            throw new Error(`API Error: ${response.statusText}`);
        }
        
        return await response.json();
    }
}


// Auto-initialize when viewer is ready
(function() {
    let initAttempts = 0;
    const maxAttempts = 30; // Try for 30 seconds
    
    function initWorldSampler() {
        initAttempts++;
        
        console.log(`[World Sampler] Initialization attempt ${initAttempts}/${maxAttempts}`);
        
        // Try multiple ways to find the viewer
        let viewer = null;
        
        if (window.viewer) {
            viewer = window.viewer;
            console.log('[World Sampler] Found viewer at window.viewer');
        } else if (window.DeepGISTopology && window.DeepGISTopology.viewer) {
            viewer = window.DeepGISTopology.viewer;
            console.log('[World Sampler] Found viewer at window.DeepGISTopology.viewer');
        } else if (window.cesiumViewer) {
            viewer = window.cesiumViewer;
            console.log('[World Sampler] Found viewer at window.cesiumViewer');
        }
        
        if (viewer && Cesium) {
            console.log('[World Sampler] ✅ Initializing World Sampler UI...');
            try {
                window.worldSamplerUI = new WorldSamplerUI(viewer);
                console.log('[World Sampler] ✅ World Sampler UI initialized successfully!');
                return; // Success, stop trying
            } catch (error) {
                console.error('[World Sampler] ❌ Failed to initialize:', error);
            }
        } else {
            console.log('[World Sampler] ⏳ Viewer not ready yet, retrying...');
            console.log('[World Sampler] Debug info:', {
                'window.viewer': !!window.viewer,
                'window.DeepGISTopology': !!window.DeepGISTopology,
                'window.Cesium': !!window.Cesium,
                'cesiumContainer': !!document.getElementById('cesiumContainer')
            });
        }
        
        // Keep trying if not yet successful
        if (initAttempts < maxAttempts) {
            setTimeout(initWorldSampler, 1000);
        } else {
            console.error('[World Sampler] ❌ Failed to initialize after', maxAttempts, 'attempts');
            console.error('[World Sampler] Final state:', {
                'window.viewer': !!window.viewer,
                'window.DeepGISTopology': !!window.DeepGISTopology,
                'window.Cesium': !!window.Cesium
            });
        }
    }
    
    // Start initialization
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            console.log('[World Sampler] DOM ready, starting initialization...');
            setTimeout(initWorldSampler, 2000); // Wait 2 seconds after DOM ready
        });
    } else {
        console.log('[World Sampler] DOM already ready, starting initialization...');
        setTimeout(initWorldSampler, 2000); // Wait 2 seconds
    }
})();


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
        this.samDataSource = null; // For SAM segmentation results
        
        // Orbit mode state
        this.orbitActive = false;
        this.orbitCancelled = false;
        this.orbitEscHandler = null;
        
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
        
        // Find container: HUD panel first, then sidebar
        const hudContainer = document.getElementById('hudSamplerContainer');
        const layerControls = hudContainer || 
                             document.querySelector('.layer-controls') || 
                             document.querySelector('#sidebar-wrapper .sidebar-content') ||
                             document.querySelector('.sidebar-content');
        
        if (!layerControls) {
            console.warn('[World Sampler] Could not find container, creating floating widget as fallback');
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
                <div class="accordion-content expanded" id="worldSamplerContent">
            
                <!-- Initialization Section -->
                <div class="sampler-section">
                    <h4 class="accordion-header" data-target="initContent">
                        <span><i class="fas fa-cog"></i> Initialize</span>
                        <i class="fas fa-chevron-down accordion-icon"></i>
                    </h4>
                    <div class="sampler-section-content expanded" id="initContent">
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
                    <div class="sampler-section-content expanded" id="sampleContent">
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
                
                <!-- GPS Telemetry has been moved to Mission Planner panel -->
                
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
            // GPS Telemetry has been moved to Mission Planner
        }, 0);
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
        // Safe event listener helper - won't throw if element doesn't exist
        const safeAddListener = (id, event, handler) => {
            const el = document.getElementById(id);
            if (el) el.addEventListener(event, handler);
        };
        
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
        safeAddListener('samplerInitBtn', 'click', () => this.initializeSampler());
        
        // Sample button
        safeAddListener('samplerSampleBtn', 'click', () => this.sampleLocations());
        
        // Feedback button
        safeAddListener('samplerFeedbackBtn', 'click', () => this.submitFeedback());
        
        // Explore button
        safeAddListener('samplerExplore', 'click', () => this.updateExploration());
        
        // Concentrate button
        safeAddListener('samplerConcentrate', 'click', () => this.updateConcentration());
        
        // Clear button
        safeAddListener('samplerClear', 'click', () => this.clearSamples());
        
        // Reset button
        safeAddListener('samplerReset', 'click', () => this.resetSampler());
        
        // Refresh stats button
        safeAddListener('samplerRefreshStats', 'click', () => this.updateStatistics());
        
        // Survey navigation buttons
        safeAddListener('surveyPrev', 'click', () => this.navigateToPreviousSample());
        safeAddListener('surveyNext', 'click', () => this.navigateToNextSample());
        
        // Auto-survey toggle
        safeAddListener('surveyAutoToggle', 'click', () => this.toggleAutoSurvey());
        
        // Survey speed slider
        safeAddListener('surveySpeed', 'input', (e) => {
            const speedValue = document.getElementById('surveySpeedValue');
            if (speedValue) speedValue.textContent = e.target.value + 's';
            
            // If auto-survey is running, restart with new speed
            if (this.isAutoSurveyActive) {
                this.stopAutoSurvey();
                this.startAutoSurvey();
            }
        });
        
        // Drone fly mode button
        safeAddListener('droneFlyBtn', 'click', () => this.flyDroneMode());
        
        // Update drone fly button text when distance or speed changes
        const updateDroneFlyButton = () => {
            const distEl = document.getElementById('droneFlyDistance');
            const speedEl = document.getElementById('droneFlySpeed');
            const btnEl = document.getElementById('droneFlyBtn');
            if (distEl && speedEl && btnEl) {
                const distance = distEl.value || 100;
                const speed = speedEl.value || 100;
                btnEl.innerHTML = `<i class="fas fa-paper-plane"></i> Fly Forward ${distance}m @ ${speed} km/h`;
            }
        };
        
        safeAddListener('droneFlyDistance', 'input', updateDroneFlyButton);
        safeAddListener('droneFlySpeed', 'input', updateDroneFlyButton);
        
        // Drone orbit mode button
        safeAddListener('droneOrbitBtn', 'click', () => this.orbitDroneMode());
        
        // Update drone orbit button text when radius or speed changes
        const updateDroneOrbitButton = () => {
            const radiusEl = document.getElementById('droneOrbitRadius');
            const speedEl = document.getElementById('droneOrbitSpeed');
            const btnEl = document.getElementById('droneOrbitBtn');
            if (radiusEl && speedEl && btnEl) {
                const radius = radiusEl.value || 1000;
                const speed = speedEl.value || 50;
                btnEl.innerHTML = `<i class="fas fa-circle-notch"></i> Orbit ${radius}m radius @ ${speed} km/h`;
            }
        };
        
        safeAddListener('droneOrbitRadius', 'input', updateDroneOrbitButton);
        safeAddListener('droneOrbitSpeed', 'input', updateDroneOrbitButton);
        safeAddListener('droneOrbitAltitude', 'input', updateDroneOrbitButton);
        safeAddListener('droneOrbitRevolutions', 'input', updateDroneOrbitButton);
        
        // Update orbit pitch display
        safeAddListener('droneOrbitPitch', 'input', (e) => {
            const pitchVal = document.getElementById('orbitPitchValue');
            if (pitchVal) pitchVal.textContent = `${e.target.value}°`;
        });
        
        // Stop orbit button
        safeAddListener('stopOrbitBtn', 'click', () => this.stopOrbitMode());
        
        // AI Viewport Analysis button (handled globally, see initialization at bottom of file)
        
        // Reward slider
        safeAddListener('samplerReward', 'input', (e) => {
            const value = parseFloat(e.target.value);
            const rewardVal = document.getElementById('samplerRewardValue');
            const rewardLabel = document.getElementById('samplerRewardLabel');
            if (rewardVal) rewardVal.textContent = value.toFixed(1);
            
            // Update label
            let label = 'Neutral';
            if (value > 0.7) label = 'Very Interesting';
            else if (value > 0.3) label = 'Interesting';
            else if (value > -0.3) label = 'Neutral';
            else if (value > -0.7) label = 'Not Interesting';
            else label = 'Avoid';
            
            if (rewardLabel) rewardLabel.textContent = label;
        });
        
        // Learning rate slider
        safeAddListener('samplerLearningRate', 'input', (e) => {
            const lrVal = document.getElementById('samplerLearningRateValue');
            if (lrVal) lrVal.textContent = e.target.value;
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
        const initTypeEl = document.getElementById('samplerInitType');
        const numPointsEl = document.getElementById('samplerNumPoints');
        
        // Handle missing elements gracefully
        if (!initTypeEl || !numPointsEl) {
            console.warn('[World Sampler] UI elements not found, using defaults');
        }
        
        const initType = initTypeEl ? initTypeEl.value : 'gaussian_mixture';
        const numPoints = numPointsEl ? parseInt(numPointsEl.value) : 1000;
        
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
        const numSamplesEl = document.getElementById('samplerNumSamples');
        const methodEl = document.getElementById('samplerMethod');
        const n = numSamplesEl ? parseInt(numSamplesEl.value) : 10;
        const method = methodEl ? methodEl.value : 'weighted';
        
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
            
            // Zoom to show all samples at lowest zoom level (highest altitude)
            if (entities.length > 0) {
                // Calculate center point of all samples
                let sumLon = 0, sumLat = 0;
                entities.forEach(entity => {
                    const position = entity.position.getValue(Cesium.JulianDate.now());
                const cartographic = Cesium.Cartographic.fromCartesian(position);
                    sumLon += cartographic.longitude;
                    sumLat += cartographic.latitude;
                });
                const centerLon = sumLon / entities.length;
                const centerLat = sumLat / entities.length;
                
                // Set to very high altitude (lowest zoom level) - 20,000 km for global view
                // This ensures all samples are visible at once
                const targetHeight = 20000000; // 20,000 km altitude
                
                this.viewer.camera.flyTo({
                    destination: Cesium.Cartesian3.fromRadians(
                        centerLon,
                        centerLat,
                        targetHeight
                    ),
                    duration: 2.0,
                    orientation: {
                        heading: Cesium.Math.toRadians(0),
                        pitch: Cesium.Math.toRadians(-90),  // Top-down view for best overview
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
        
        // Fly to selected sample with zoom level 14
        const position = entity.position.getValue(Cesium.JulianDate.now());
        const cartographic = Cesium.Cartographic.fromCartesian(position);
        
        // Calculate altitude for zoom level 14: altitude = 40075000 / (2^zoom)
        const zoomLevel = 14;
        const altitudeForZoom14 = 40075000 / Math.pow(2, zoomLevel);
        
        this.viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromRadians(
                cartographic.longitude,
                cartographic.latitude,
                altitudeForZoom14  // Zoom level 14
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
        
        // Calculate altitude for zoom level 14: altitude = 40075000 / (2^zoom)
        // Zoom level 14 ≈ 2445m altitude
        const zoomLevel = 14;
        const altitudeForZoom14 = 40075000 / Math.pow(2, zoomLevel);
        
        this.viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromRadians(
                cartographic.longitude,
                cartographic.latitude,
                altitudeForZoom14  // Zoom level 14
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
     * Drone Orbit Mode: Orbit around a center point at specified radius and altitude
     * Similar to PX4/QGC orbit mode - camera always faces the center point
     */
    async orbitDroneMode() {
        // Check if orbit is already active
        if (this.orbitActive) {
            this.showNotification('Orbit already in progress. Press ESC or Stop button to cancel.', 'warning');
            return;
        }
        
        const camera = this.viewer.camera;
        const scene = this.viewer.scene;
        const ellipsoid = scene.globe.ellipsoid;
        
        // Get orbit parameters from UI
        const orbitRadius = parseFloat(document.getElementById('droneOrbitRadius').value) || 5000;
        const altitudeAGL = parseFloat(document.getElementById('droneOrbitAltitude').value) || 2000;
        const speedKmh = parseFloat(document.getElementById('droneOrbitSpeed').value) || 50;
        const revolutions = parseFloat(document.getElementById('droneOrbitRevolutions').value) || 10;
        const pitchAngle = parseFloat(document.getElementById('droneOrbitPitch').value) || -10;
        
        // Validate parameters
        const radius = Math.max(20, Math.min(10000, orbitRadius));
        const altitude = Math.max(20, Math.min(10000, altitudeAGL));
        const speed = Math.max(10, Math.min(100, speedKmh));
        const revs = Math.max(0.25, Math.min(20, revolutions));
        const pitch = Math.max(-90, Math.min(0, pitchAngle));
        
        // Get current camera position
        const currentPosition = camera.positionCartographic;
        const currentLon = Cesium.Math.toDegrees(currentPosition.longitude);
        const currentLat = Cesium.Math.toDegrees(currentPosition.latitude);
        
        // Get terrain height at current location
        const centerCartographic = Cesium.Cartographic.fromDegrees(currentLon, currentLat);
        const terrainProvider = scene.terrainProvider;
        
        let terrainHeight = 0;
        try {
            const positions = await Cesium.sampleTerrainMostDetailed(terrainProvider, [centerCartographic]);
            terrainHeight = positions[0].height || 0;
        } catch (e) {
            console.warn('Could not sample terrain, using ellipsoid height:', e);
        }
        
        // Calculate orbit center point (the point we're orbiting around)
        // This is typically the point the camera is looking at, or current position
        const centerLon = currentLon;
        const centerLat = currentLat;
        const centerAltitude = terrainHeight + altitude;
        
        // Calculate total distance to travel (circumference * revolutions)
        const circumference = 2 * Math.PI * radius;
        const totalDistance = circumference * revs;
        
        // Calculate duration based on speed
        const speedMs = speed * 0.277777778; // km/h to m/s
        const duration = totalDistance / speedMs;
        
        // Get current heading to determine starting angle
        const currentHeading = Cesium.Math.toDegrees(camera.heading);
        
        // Calculate starting position (offset from center by radius)
        // Start from current heading direction
        const startAngle = currentHeading;
        
        // Create orbit path with keyframes
        const numKeyframes = Math.ceil(revs * 36); // 36 points per revolution (10° intervals)
        const angleStep = (360 * revs) / numKeyframes;
        
        // Build the orbit path
        const orbitPath = [];
        for (let i = 0; i <= numKeyframes; i++) {
            const angle = startAngle + (i * angleStep);
            const bearing = angle % 360;
            
            // Calculate position at this angle
            const pos = this.calculateDestinationPoint(
                centerLat,
                centerLon,
                centerAltitude,
                bearing,
                radius
            );
            
            // Calculate heading to face center (inward)
            // Heading is opposite to the bearing from center
            const headingToCenter = (bearing + 180) % 360;
            
            orbitPath.push({
                position: Cesium.Cartesian3.fromDegrees(
                    pos.longitude,
                    pos.latitude,
                    pos.altitude
                ),
                orientation: {
                    heading: Cesium.Math.toRadians(headingToCenter),
                    pitch: Cesium.Math.toRadians(pitch), // Use pitch from slider
                    roll: 0
                },
                time: (i / numKeyframes) * duration
            });
        }
        
        // Set orbit as active
        this.orbitActive = true;
        this.orbitCancelled = false;
        
        // Show stop button, hide start button
        document.getElementById('stopOrbitContainer').style.display = 'block';
        document.getElementById('droneOrbitBtn').disabled = true;
        
        // Add ESC key handler
        const escHandler = (e) => {
            if (e.key === 'Escape' && this.orbitActive) {
                this.stopOrbitMode();
            }
        };
        document.addEventListener('keydown', escHandler);
        this.orbitEscHandler = escHandler;
        
        // Show notification
        this.showNotification(
            `Starting ${revs} revolution orbit: ${radius}m radius @ ${speed} km/h (${duration.toFixed(1)}s) - Press ESC to cancel`,
            'info'
        );
        
        // Execute the orbit using camera path animation
        let currentKeyframe = 0;
        const startTime = Date.now();
        
        const animateOrbit = () => {
            // Check if orbit was cancelled
            if (this.orbitCancelled || !this.orbitActive) {
                this.cleanupOrbit();
                this.showNotification('Orbit cancelled', 'info');
                return;
            }
            
            const elapsed = (Date.now() - startTime) / 1000; // seconds
            
            // Find current keyframe based on elapsed time
            while (currentKeyframe < orbitPath.length - 1 && 
                   orbitPath[currentKeyframe + 1].time <= elapsed) {
                currentKeyframe++;
            }
            
            if (currentKeyframe >= orbitPath.length - 1) {
                // Orbit complete
                this.cleanupOrbit();
                this.showNotification(
                    `Orbit complete: ${revs} revolutions around ${radius}m radius`,
                    'success'
                );
                return;
            }
            
            // Interpolate between current and next keyframe
            const current = orbitPath[currentKeyframe];
            const next = orbitPath[currentKeyframe + 1];
            const t = (elapsed - current.time) / (next.time - current.time);
            
            // Linear interpolation of position
            const position = new Cesium.Cartesian3();
            Cesium.Cartesian3.lerp(current.position, next.position, t, position);
            
            // Spherical interpolation of orientation
            const heading = Cesium.Math.lerp(current.orientation.heading, next.orientation.heading, t);
            const pitchInterp = Cesium.Math.lerp(current.orientation.pitch, next.orientation.pitch, t);
            const roll = Cesium.Math.lerp(current.orientation.roll, next.orientation.roll, t);
            
            // Update camera
            camera.setView({
                destination: position,
                orientation: {
                    heading: heading,
                    pitch: pitchInterp,
                    roll: roll
                }
            });
            
            // Continue animation
            requestAnimationFrame(animateOrbit);
        };
        
        // Start the orbit animation
        requestAnimationFrame(animateOrbit);
    }
    
    /**
     * Stop the active orbit mode
     */
    stopOrbitMode() {
        if (this.orbitActive) {
            this.orbitCancelled = true;
            this.orbitActive = false;
        }
    }
    
    /**
     * Cleanup orbit mode state
     */
    cleanupOrbit() {
        this.orbitActive = false;
        this.orbitCancelled = false;
        
        // Hide stop button, enable start button
        document.getElementById('stopOrbitContainer').style.display = 'none';
        document.getElementById('droneOrbitBtn').disabled = false;
        
        // Remove ESC handler
        if (this.orbitEscHandler) {
            document.removeEventListener('keydown', this.orbitEscHandler);
            this.orbitEscHandler = null;
        }
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
    
    /**
     * Capture current viewport as image using Cesium's proper method
     * @returns {Object} {image: base64 string, location: camera pose}
     */
    async captureViewportImage() {
        const scene = this.viewer.scene;
        const canvas = scene.canvas;
        const camera = this.viewer.camera;
        const context = scene.context;
        const gl = context._gl;
        const width = canvas.width;
        const height = canvas.height;
        
        // Force scene to render completely before capture
        scene.requestRender();
        scene.render();
        
        // Wait for rendering to complete - use multiple frames
        await new Promise(resolve => {
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    requestAnimationFrame(resolve);
                });
            });
        });
        
        let imageData;
        let lastError;
        
        // Method 1: Render to texture approach (works without preserveDrawingBuffer)
        try {
            console.log('Attempting Method 1: Render to texture...');
            
            // Create a texture to render to
            const texture = gl.createTexture();
            gl.bindTexture(gl.TEXTURE_2D, texture);
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
            
            // Create framebuffer
            const framebuffer = gl.createFramebuffer();
            gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
            gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
            
            // Check framebuffer status
            if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) {
                throw new Error('Framebuffer not complete');
            }
            
            // Copy current framebuffer to our texture using copyTexImage2D
            gl.bindFramebuffer(gl.READ_FRAMEBUFFER, null); // Read from default framebuffer
            gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, framebuffer); // Draw to our framebuffer
            gl.blitFramebuffer(0, 0, width, height, 0, 0, width, height, gl.COLOR_BUFFER_BIT, gl.LINEAR);
            
            // Read from our framebuffer
            gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
            const pixels = new Uint8Array(width * height * 4);
            gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
            
            // Restore default framebuffer
            gl.bindFramebuffer(gl.FRAMEBUFFER, null);
            
            // Clean up
            gl.deleteFramebuffer(framebuffer);
            gl.deleteTexture(texture);
            
            // Check for data
            let hasData = false;
            for (let i = 0; i < Math.min(pixels.length, 10000); i += 4) {
                if (pixels[i] > 10 || pixels[i + 1] > 10 || pixels[i + 2] > 10) {
                    hasData = true;
                    break;
                }
            }
            
            if (hasData) {
                // Flip vertically
                const flippedPixels = new Uint8Array(width * height * 4);
                for (let y = 0; y < height; y++) {
                    const srcRow = (height - 1 - y) * width * 4;
                    const dstRow = y * width * 4;
                    flippedPixels.set(pixels.subarray(srcRow, srcRow + width * 4), dstRow);
                }
                
                // Create canvas and convert
                const tempCanvas = document.createElement('canvas');
                tempCanvas.width = width;
                tempCanvas.height = height;
                const ctx = tempCanvas.getContext('2d');
                const imageDataObj = ctx.createImageData(width, height);
                imageDataObj.data.set(flippedPixels);
                ctx.putImageData(imageDataObj, 0, 0);
                
                imageData = tempCanvas.toDataURL('image/png');
                console.log(`✓ Method 1 (Render to texture) succeeded (${width}x${height})`);
            } else {
                throw new Error('Render to texture returned blank image');
            }
        } catch (method1Error) {
            console.warn('Method 1 (Render to texture) failed:', method1Error.message);
            lastError = method1Error;
            
            // Method 2: Use postRender event to capture
            try {
                console.log('Attempting Method 2: postRender event capture...');
                
                imageData = await new Promise((resolve, reject) => {
                    const timeout = setTimeout(() => {
                        scene.postRender.removeEventListener(captureHandler);
                        reject(new Error('postRender capture timeout'));
                    }, 3000);
                    
                    const captureHandler = () => {
                        clearTimeout(timeout);
                        scene.postRender.removeEventListener(captureHandler);
                        
                        try {
                            // Try toDataURL
                            const data = canvas.toDataURL('image/png');
                            if (data && data.length > 100 && data !== 'data:,') {
                                resolve(data);
                            } else {
                                // Try readPixels
                                const pixels = new Uint8Array(width * height * 4);
                                gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
                                
                                let hasData = false;
                                for (let i = 0; i < Math.min(pixels.length, 10000); i += 4) {
                                    if (pixels[i] > 10 || pixels[i + 1] > 10 || pixels[i + 2] > 10) {
                                        hasData = true;
                                        break;
                                    }
                                }
                                
                                if (hasData) {
                                    // Flip and convert
                                    const flippedPixels = new Uint8Array(width * height * 4);
                                    for (let y = 0; y < height; y++) {
                                        const srcRow = (height - 1 - y) * width * 4;
                                        const dstRow = y * width * 4;
                                        flippedPixels.set(pixels.subarray(srcRow, srcRow + width * 4), dstRow);
                                    }
                                    
                                    const tempCanvas = document.createElement('canvas');
                                    tempCanvas.width = width;
                                    tempCanvas.height = height;
                                    const ctx = tempCanvas.getContext('2d');
                                    const imageDataObj = ctx.createImageData(width, height);
                                    imageDataObj.data.set(flippedPixels);
                                    ctx.putImageData(imageDataObj, 0, 0);
                                    resolve(tempCanvas.toDataURL('image/png'));
                                } else {
                                    reject(new Error('postRender capture returned blank'));
                                }
                            }
                        } catch (e) {
                            reject(e);
                        }
                    };
                    
                    scene.postRender.addEventListener(captureHandler);
                    scene.requestRender();
                });
                
                console.log(`✓ Method 2 (postRender) succeeded (${width}x${height})`);
            } catch (method2Error) {
                console.warn('Method 2 (postRender) failed:', method2Error.message);
                lastError = method2Error;
                
                // Method 3: Copy framebuffer using copyTexImage2D
                try {
                    console.log('Attempting Method 3: copyTexImage2D...');
                    
                    // Create texture
                    const texture = gl.createTexture();
                    gl.bindTexture(gl.TEXTURE_2D, texture);
                    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
                    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
                    
                    // Copy current framebuffer to texture
                    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
                    gl.copyTexImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 0, 0, width, height, 0);
                    
                    // Read from texture
                    const pixels = new Uint8Array(width * height * 4);
                    gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
                    
                    // Check for data
                    let hasData = false;
                    for (let i = 0; i < Math.min(pixels.length, 10000); i += 4) {
                        if (pixels[i] > 10 || pixels[i + 1] > 10 || pixels[i + 2] > 10) {
                            hasData = true;
                            break;
                        }
                    }
                    
                    if (hasData) {
                        // Flip and convert
                        const flippedPixels = new Uint8Array(width * height * 4);
                        for (let y = 0; y < height; y++) {
                            const srcRow = (height - 1 - y) * width * 4;
                            const dstRow = y * width * 4;
                            flippedPixels.set(pixels.subarray(srcRow, srcRow + width * 4), dstRow);
                        }
                        
                        const tempCanvas = document.createElement('canvas');
                        tempCanvas.width = width;
                        tempCanvas.height = height;
                        const ctx = tempCanvas.getContext('2d');
                        const imageDataObj = ctx.createImageData(width, height);
                        imageDataObj.data.set(flippedPixels);
                        ctx.putImageData(imageDataObj, 0, 0);
                        
                        imageData = tempCanvas.toDataURL('image/png');
                        console.log(`✓ Method 3 (copyTexImage2D) succeeded (${width}x${height})`);
                    } else {
                        throw new Error('copyTexImage2D returned blank');
                    }
                    
                    gl.deleteTexture(texture);
                } catch (method3Error) {
                    console.warn('Method 3 (copyTexImage2D) failed:', method3Error.message);
                    lastError = method3Error;
                    
                    // Method 4: Simple toDataURL (if preserveDrawingBuffer is enabled)
                    try {
                        console.log('Attempting Method 4: toDataURL...');
                        imageData = canvas.toDataURL('image/png');
                        
                        if (!imageData || imageData.length < 100 || imageData === 'data:,') {
                            throw new Error('toDataURL returned invalid image');
                        }
                        
                        console.log(`✓ Method 4 (toDataURL) succeeded (${width}x${height})`);
                    } catch (method4Error) {
                        console.error('All capture methods failed');
                        throw new Error(`All viewport capture methods failed. Last error: ${lastError?.message || method4Error.message}. Please refresh the page to enable preserveDrawingBuffer.`);
                    }
                }
            }
        }
        
        // Validate the captured image
        if (imageData) {
            const testImg = new Image();
            testImg.src = imageData;
            
            await new Promise((resolve, reject) => {
                const timeout = setTimeout(() => {
                    reject(new Error('Image validation timeout'));
                }, 2000);
                
                testImg.onload = () => {
                    clearTimeout(timeout);
                    const testCanvas = document.createElement('canvas');
                    testCanvas.width = Math.min(200, testImg.width);
                    testCanvas.height = Math.min(200, testImg.height);
                    const ctx = testCanvas.getContext('2d');
                    ctx.drawImage(testImg, 0, 0, testCanvas.width, testCanvas.height);
                    const sample = ctx.getImageData(0, 0, testCanvas.width, testCanvas.height);
                    
                    let nonBlack = 0;
                    const totalPixels = sample.data.length / 4;
                    for (let i = 0; i < sample.data.length; i += 4) {
                        const r = sample.data[i];
                        const g = sample.data[i + 1];
                        const b = sample.data[i + 2];
                        if (r > 10 || g > 10 || b > 10) {
                            nonBlack++;
                        }
                    }
                    
                    const nonBlackRatio = nonBlack / totalPixels;
                    console.log(`Image validation: ${(nonBlackRatio * 100).toFixed(2)}% non-black pixels`);
                    
                    if (nonBlackRatio < 0.01) {
                        reject(new Error(`Captured image is blank/black (${(nonBlackRatio * 100).toFixed(2)}% non-black)`));
                    } else {
                        resolve();
                    }
                };
                
                testImg.onerror = () => {
                    clearTimeout(timeout);
                    reject(new Error('Failed to decode captured image'));
                };
            });
        }
        
        // Get camera pose
        const position = camera.positionCartographic;
        const location = {
            lon: Cesium.Math.toDegrees(position.longitude),
            lat: Cesium.Math.toDegrees(position.latitude),
            alt: position.height,
            heading: Cesium.Math.toDegrees(camera.heading),
            pitch: Cesium.Math.toDegrees(camera.pitch),
            roll: Cesium.Math.toDegrees(camera.roll)
        };
        
        return {
            image: imageData,
            location: location
        };
    }
    
    /**
     * Wait until the camera stops moving so capture/projection matches the rendered frame
     */
    async waitForCameraStability(maxWaitMs = 800) {
        const camera = this.viewer.camera;
        const start = performance.now();
        
        let lastPosition = Cesium.Cartesian3.clone(camera.position);
        let lastHeading = camera.heading;
        let lastPitch = camera.pitch;
        let lastRoll = camera.roll;
        let stableFrames = 0;
        
        return new Promise((resolve) => {
            const check = () => {
                const pos = Cesium.Cartesian3.clone(camera.position);
                const posDelta = Cesium.Cartesian3.distance(pos, lastPosition);
                const headingDelta = Math.abs(camera.heading - lastHeading);
                const pitchDelta = Math.abs(camera.pitch - lastPitch);
                const rollDelta = Math.abs(camera.roll - lastRoll);
                
                // Treat camera as stable after two consecutive frames under tiny deltas
                if (posDelta < 0.05 && 
                    headingDelta < Cesium.Math.toRadians(0.05) &&
                    pitchDelta < Cesium.Math.toRadians(0.05) &&
                    rollDelta < Cesium.Math.toRadians(0.05)) {
                    stableFrames++;
                } else {
                    stableFrames = 0;
                }
                
                lastPosition = pos;
                lastHeading = camera.heading;
                lastPitch = camera.pitch;
                lastRoll = camera.roll;
                
                if (stableFrames >= 2 || (performance.now() - start) > maxWaitMs) {
                    resolve();
                } else {
                    requestAnimationFrame(check);
                }
            };
            
            check();
        });
    }
    
    /**
     * Prepare the viewport for AI capture by pausing orbiting, waiting for morphs, and stabilizing the camera.
     */
    async prepareViewportForAnalysis(statusTextEl) {
        const scene = this.viewer.scene;
        let orbitWasActive = false;
        
        // If the view is morphing between 2D/3D, wait until it finishes to avoid mis-projection
        if (scene.morphing) {
            if (statusTextEl) statusTextEl.textContent = 'Waiting for view change to finish...';
            await new Promise((resolve) => {
                const onComplete = () => {
                    scene.morphComplete.removeEventListener(onComplete);
                    resolve();
                };
                scene.morphComplete.addEventListener(onComplete);
            });
        }
        
        // Pause orbit animations to capture a stable frame
        if (this.orbitActive) {
            orbitWasActive = true;
            if (statusTextEl) statusTextEl.textContent = 'Stopping orbit for clean capture...';
            this.stopOrbitMode();
            this.cleanupOrbit();
            await new Promise((resolve) => requestAnimationFrame(resolve));
        }
        
        if (statusTextEl) statusTextEl.textContent = 'Stabilizing camera...';
        await this.waitForCameraStability();
        
        // Give Cesium two frames to render the settled view
        await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        
        return { orbitWasActive };
    }
    
    /**
     * Analyze viewport using AI models (SAM or Zero-Shot Detection)
     */
    async analyzeViewportWithSAM() {
        const statusDiv = document.getElementById('samAnalysisStatus');
        const statusText = document.getElementById('samStatusText');
        const analyzeBtn = document.getElementById('analyzeViewportBtn');
        const analysisTypeSelect = document.getElementById('analysisTypeSelect');
        let orbitPausedForAnalysis = false;
        
        // Get analysis type
        const analysisType = analysisTypeSelect ? analysisTypeSelect.value : 'sam';
        
        // Show status
        statusDiv.style.display = 'block';
        statusText.textContent = 'Preparing viewport...';
        analyzeBtn.disabled = true;
        
        try {
            // Ensure camera isn't moving (orbit / morph) before capture to keep projections aligned
            const prepState = await this.prepareViewportForAnalysis(statusText);
            orbitPausedForAnalysis = prepState.orbitWasActive;
            statusText.textContent = 'Capturing viewport...';
            
            // Ensure scene is fully rendered before capturing
            // Force a render and wait for it to complete
            this.viewer.scene.requestRender();
            this.viewer.scene.render();
            
            // Wait multiple frames to ensure WebGL context is ready
            await new Promise(resolve => {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        requestAnimationFrame(resolve); // Triple frame for safety
                    });
                });
            });
            
            // Temporarily hide SAM result overlays to capture clean viewport
            let samDataSourceWasVisible = false;
            if (this.samDataSource && this.viewer.dataSources.contains(this.samDataSource)) {
                this.viewer.dataSources.remove(this.samDataSource);
                samDataSourceWasVisible = true;
                console.log('[SAM] Temporarily hiding SAM overlays for clean viewport capture');
            }
            
            try {
                // Force another render before capture (without SAM overlays)
                this.viewer.scene.requestRender();
                this.viewer.scene.render();
                
                // Small delay to ensure framebuffer is ready
                await new Promise(resolve => setTimeout(resolve, 100));
                
                // Capture viewport (without SAM overlays)
                const viewportData = await this.captureViewportImage();
                
                // Restore SAM overlays if they were visible
                if (samDataSourceWasVisible && this.samDataSource) {
                    this.viewer.dataSources.add(this.samDataSource);
                    console.log('[SAM] Restored SAM overlays after capture');
                }
                
                // Continue with analysis using clean viewport
            const capturePose = viewportData.location;
            this.lastCapturePose = capturePose;
                
                // Get parameters based on analysis type
                let requestBody = {
                    image: viewportData.image,
                location: capturePose,
                    model_type: analysisType
                };
                
                if (analysisType === 'sam') {
                    const samModel = document.getElementById('samModelType').value;
                    const minArea = parseInt(document.getElementById('samMinArea').value) || 100;
                    requestBody.sam_model = samModel;
                    requestBody.min_area = minArea;
                    statusText.textContent = 'Sending to SAM for analysis...';
                } else if (analysisType === 'zero_shot') {
                    const confidenceSlider = document.getElementById('zeroShotConfidence');
                    const confidence = confidenceSlider ? parseFloat(confidenceSlider.value) / 100 : 0.5;
                    requestBody.confidence_threshold = confidence;
                    statusText.textContent = 'Sending to Zero-Shot Detection...';
                } else if (analysisType === 'mask2former') {
                    const confidenceSlider = document.getElementById('mask2formerConfidence');
                    const confidence = confidenceSlider ? parseFloat(confidenceSlider.value) / 100 : 0.5;
                    requestBody.confidence_threshold = confidence;
                    statusText.textContent = 'Sending to Mask2Former for analysis...';
                } else if (analysisType === 'yolov8') {
                    const yolov8Model = document.getElementById('yolov8ModelType');
                    const yolov8Confidence = document.getElementById('yolov8Confidence');
                    const yolov8Classes = document.getElementById('yolov8Classes');
                    requestBody.yolo_model = yolov8Model ? yolov8Model.value : 'yolov8n';
                    requestBody.confidence_threshold = yolov8Confidence ? parseFloat(yolov8Confidence.value) / 100 : 0.25;
                    requestBody.class_filter = yolov8Classes ? yolov8Classes.value.trim() : '';
                    statusText.textContent = 'Running YOLOv8 detection...';
                } else if (analysisType === 'grounding_dino') {
                    const textPrompt = document.getElementById('groundingDinoPrompt');
                    const boxThreshold = document.getElementById('gdBoxThreshold');
                    const textThreshold = document.getElementById('gdTextThreshold');
                    requestBody.text_prompt = textPrompt ? textPrompt.value.trim() : 'object';
                    requestBody.box_threshold = boxThreshold ? parseFloat(boxThreshold.value) / 100 : 0.3;
                    requestBody.text_threshold = textThreshold ? parseFloat(textThreshold.value) / 100 : 0.25;
                    statusText.textContent = 'Running Grounding DINO detection...';
                } else if (analysisType === 'prithvi') {
                    statusText.textContent = 'Extracting Earth Observation features with Prithvi...';
                }
                
                // Send to API
                const response = await fetch('/webclient/sampler/analyze-viewport', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(requestBody)
                });
                
                if (!response.ok) {
                    // Handle error response - check if body is JSON
                    let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
                    try {
                        const contentType = response.headers.get('content-type');
                        if (contentType && contentType.includes('application/json')) {
                            const errorData = await response.json();
                            errorMessage = errorData.message || errorMessage;
                        } else {
                            // Try to get text response for non-JSON errors
                            const errorText = await response.text();
                            if (errorText) {
                                errorMessage = errorText.substring(0, 200); // Limit error text length
                            }
                        }
                    } catch (parseError) {
                        // If parsing fails, use default error message
                        console.warn('Could not parse error response:', parseError);
                    }
                    throw new Error(errorMessage);
                }
                
                // Parse successful response
                let result;
                try {
                    result = await response.json();
                } catch (jsonError) {
                    throw new Error(`Failed to parse response: ${jsonError.message}`);
                }
                
                if (!result || result.status !== 'success') {
                    throw new Error(result?.message || 'Analysis failed');
                }
                
                // Show device info
                const deviceInfo = result.device_info || {};
                const deviceText = deviceInfo.cuda_available 
                    ? `GPU: ${deviceInfo.gpu_name || 'CUDA'}` 
                    : 'CPU';
                
                // Handle results based on analysis type
                if (analysisType === 'zero_shot' || analysisType === 'mask2former' || analysisType === 'yolov8' || analysisType === 'grounding_dino') {
                    const numDetections = result.num_detections || 0;
                    statusText.textContent = `✓ Found ${numDetections} objects (${deviceText})`;
                    statusText.style.color = '#10b981';
                    
                    // Display results (all detection models use same display method)
                    result.capture_pose = capturePose;
                    this.displayZeroShotResults(result);
                    
                    // Show notification
                    const deviceNote = deviceInfo.mode === 'remote_api' ? ' (Remote GPU)' : (deviceInfo.cuda_available ? ' (GPU)' : ' (CPU)');
                    let modelName = 'Zero-Shot Detection';
                    if (analysisType === 'mask2former') modelName = 'Mask2Former';
                    if (analysisType === 'yolov8') {
                        const yoloModel = result.yolo_model || 'yolov8n';
                        modelName = `YOLOv8 (${yoloModel})`;
                    }
                    if (analysisType === 'grounding_dino') {
                        modelName = 'Grounding DINO';
                    }
                    this.showNotification(
                        `${modelName}: Found ${numDetections} objects in viewport${deviceNote}`,
                        'success'
                    );
                } else {
                    // SAM results
                    const numSegments = result.num_segments || 0;
                    statusText.textContent = `✓ Found ${numSegments} segments (${deviceText})`;
                    statusText.style.color = '#10b981';
                    
                    // Display SAM results
                    result.capture_pose = capturePose;
                    this.displaySAMResults(result);
                    
                    // Show notification
                    const deviceNote = deviceInfo.cuda_available ? ' (GPU)' : ' (CPU)';
                    this.showNotification(
                        `SAM Analysis: Found ${numSegments} segments in viewport${deviceNote}`,
                        'success'
                    );
                }
                
                // Log device info to console
                if (deviceInfo.cuda_available) {
                    console.log(`SAM running on GPU: ${deviceInfo.gpu_name || 'CUDA device'}`);
                } else {
                    console.warn('SAM running on CPU. For faster processing, enable GPU in Docker.');
                }
                
                // Log saved files location
                if (result.saved_to) {
                    console.log('AI analysis results saved to:', result.saved_to.session_dir);
                    console.log('Files saved:', {
                        query_image: result.saved_to.query_image,
                        visualization: result.saved_to.visualization,
                        geojson: result.saved_to.geojson,
                        metadata: result.saved_to.metadata
                    });
                }
                
                // Show link to detailed report page
                if (result.report_url) {
                    const reportLink = document.createElement('a');
                    reportLink.href = result.report_url;
                    reportLink.target = '_blank';
                    reportLink.className = 'btn btn-sm btn-info mt-2';
                    reportLink.style.cssText = 'display: block; text-align: center; margin-top: 8px;';
                    reportLink.innerHTML = '<i class="fas fa-file-alt me-2"></i>View Detailed Report';
                    statusDiv.appendChild(reportLink);
                }
            } catch (captureError) {
                // Restore SAM overlays even if capture fails
                if (samDataSourceWasVisible && this.samDataSource) {
                    this.viewer.dataSources.add(this.samDataSource);
                }
                throw captureError;
            }
            
        } catch (error) {
            console.error('SAM analysis error:', error);
            statusText.textContent = `Error: ${error.message}`;
            statusText.style.color = '#ef4444';
            this.showNotification(`SAM Analysis failed: ${error.message}`, 'error');
        } finally {
            analyzeBtn.disabled = false;
            if (orbitPausedForAnalysis) {
                this.showNotification('Orbit was stopped to run AI analysis. Click Orbit to resume.', 'info');
            }
        }
    }
    
    /**
     * Run projection-sensitive work using the original capture pose to avoid drift.
     * Temporarily moves camera to capture position, does work, then restores.
     * Uses instant transitions (duration: 0) to prevent visual jumps.
     */
    withCapturePose(capturePose, workFn) {
        const camera = this.viewer.camera;
        const scene = this.viewer.scene;
        
        if (!capturePose) {
            console.warn('No capture pose available, using current camera position');
            return workFn();
        }
        
        // Store current camera state
        const originalPose = {
            position: Cesium.Cartesian3.clone(camera.position),
            heading: camera.heading,
            pitch: camera.pitch,
            roll: camera.roll
        };
        
        // Flag to track if we need to restore
        let needsRestore = false;
        
        try {
            // Move to capture pose INSTANTLY (no animation)
            camera.setView({
                destination: Cesium.Cartesian3.fromDegrees(
                    capturePose.lon,
                    capturePose.lat,
                    capturePose.alt
                ),
                orientation: {
                    heading: Cesium.Math.toRadians(capturePose.heading || 0),
                    pitch: Cesium.Math.toRadians(capturePose.pitch || 0),
                    roll: Cesium.Math.toRadians(capturePose.roll || 0)
                },
                duration: 0, // INSTANT - no animation to prevent flashing
                endTransform: Cesium.Matrix4.IDENTITY
            });
            needsRestore = true;
            
            // Force immediate render at capture pose
            scene.requestRender();
            
            // Do the projection work
            const result = workFn();
            
            return result;
            
        } catch (error) {
            console.error('Error in withCapturePose:', error);
            throw error;
        } finally {
            // ALWAYS restore camera position (even if workFn throws)
            if (needsRestore) {
                try {
                    camera.setView({
                        destination: originalPose.position,
                        orientation: {
                            heading: originalPose.heading,
                            pitch: originalPose.pitch,
                            roll: originalPose.roll
                        },
                        duration: 0, // INSTANT - no animation
                        endTransform: Cesium.Matrix4.IDENTITY
                    });
                    scene.requestRender();
                } catch (restoreError) {
                    console.error('Failed to restore camera after capture pose:', restoreError);
                    // Last resort: try direct position/orientation setting
                    try {
                        camera.position = originalPose.position;
                        camera.setView({
                            orientation: {
                                heading: originalPose.heading,
                                pitch: originalPose.pitch,
                                roll: originalPose.roll
                            },
                            duration: 0
                        });
                    } catch (fallbackError) {
                        console.error('Camera restore fallback also failed:', fallbackError);
                    }
                }
            }
        }
    }
    
    /**
     * Display SAM segmentation results on Cesium map
     * @param {Object} result - SAM analysis result
     */
    displaySAMResults(result) {
        if (!result.geojson || !result.geojson.features) {
            console.warn('No GeoJSON features in SAM results');
            return;
        }
        
        // Remove previous SAM results if any
        if (this.samDataSource) {
            this.viewer.dataSources.remove(this.samDataSource);
        }
        
        const capturePose = result.capture_pose || this.lastCapturePose || null;
        
        this.withCapturePose(capturePose, () => {
            const camera = this.viewer.camera;
            const scene = this.viewer.scene;
            const canvas = scene.canvas;
            const viewportWidth = canvas.width;
            const viewportHeight = canvas.height;
            const sceneMode = scene.mode;
            const pickPositionSupported = scene.pickPositionSupported && sceneMode === Cesium.SceneMode.SCENE3D;
            
            // Get the four corners of the viewport in world coordinates
            const corners = [
                new Cesium.Cartesian2(0, 0),                    // Top-left
                new Cesium.Cartesian2(viewportWidth, 0),       // Top-right
                new Cesium.Cartesian2(viewportWidth, viewportHeight), // Bottom-right
                new Cesium.Cartesian2(0, viewportHeight)       // Bottom-left
            ];
            
            const worldCorners = corners.map(screenPos => {
                let cartesian = null;
                
                // First try to pick from the terrain/globe if supported (3D only)
                if (pickPositionSupported) {
                    cartesian = scene.pickPosition(screenPos);
                }
                
                // Fallback to ellipsoid pick if pickPosition fails
                if (!Cesium.defined(cartesian) && scene.globe) {
                    cartesian = scene.camera.pickEllipsoid(screenPos, scene.globe.ellipsoid);
                }
                
                if (cartesian) {
                    const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
                    return {
                        lon: Cesium.Math.toDegrees(cartographic.longitude),
                        lat: Cesium.Math.toDegrees(cartographic.latitude),
                        height: cartographic.height
                    };
                }
                return null;
            }).filter(c => c !== null);
            
            if (worldCorners.length < 2) {
                console.warn('Could not determine viewport bounds, using approximate conversion');
                this.displaySAMResultsApproximate(result);
                return;
            }
            
            const lons = worldCorners.map(c => c.lon);
            const lats = worldCorners.map(c => c.lat);
            const minLon = Math.min(...lons);
            const maxLon = Math.max(...lons);
            const minLat = Math.min(...lats);
            const maxLat = Math.max(...lats);
            
            const lonRange = maxLon - minLon;
            const latRange = maxLat - minLat;
            
            this.samDataSource = new Cesium.GeoJsonDataSource('SAM Segments');
            
            const pixelToGeographic = (x_norm, y_norm) => {
                const screenX = x_norm * viewportWidth;
                const screenY = y_norm * viewportHeight;
                const screenPos = new Cesium.Cartesian2(screenX, screenY);
                
                let cartesian = null;
                if (pickPositionSupported) {
                    cartesian = scene.pickPosition(screenPos);
                }
                
                if (!Cesium.defined(cartesian) && scene.globe) {
                    cartesian = scene.camera.pickEllipsoid(screenPos, scene.globe.ellipsoid);
                }
                
                if (!Cesium.defined(cartesian)) {
                    const lon = minLon + (x_norm * lonRange);
                    const lat = maxLat - (y_norm * latRange); // Invert Y axis
                    return [lon, lat];
                }
                
                const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
                return [
                    Cesium.Math.toDegrees(cartographic.longitude),
                    Cesium.Math.toDegrees(cartographic.latitude)
                ];
            };
            
            const features = result.geojson.features.map((feature, index) => {
                const props = feature.properties;
                const coords = feature.geometry.coordinates[0];
                const geographicCoords = coords.map(([x_norm, y_norm]) => 
                    pixelToGeographic(x_norm, y_norm)
                );
                
                return {
                    type: 'Feature',
                    geometry: {
                        type: 'Polygon',
                        coordinates: [geographicCoords]
                    },
                    properties: {
                        segment_id: props.segment_id || index + 1,
                        area: props.area || 0,
                        predicted_iou: props.iou || props.predicted_iou || 0,
                        stability_score: props.stability || props.stability_score || 0
                    }
                };
            });
            
            const convertedGeoJSON = {
                type: 'FeatureCollection',
                features: features
            };
            
            this.samDataSource.load(convertedGeoJSON).then(() => {
                const entities = this.samDataSource.entities.values;
                
                entities.forEach((entity, index) => {
                    const props = entity.properties;
                    const segmentId = props.segment_id?.getValue() || index + 1;
                    const area = props.area?.getValue() || 0;
                    const iou = props.predicted_iou?.getValue() || 0;
                    
                    const hue = (segmentId * 137.508) % 360;
                    const color = Cesium.Color.fromHsl(hue / 360, 0.7, 0.5, 0.4);
                    
                    if (entity.polygon) {
                        entity.polygon.material = color;
                        entity.polygon.outline = true;
                        entity.polygon.outlineColor = Cesium.Color.WHITE.withAlpha(0.8);
                        entity.polygon.outlineWidth = 2;
                        entity.polygon.extrudedHeight = 0;
                        entity.polygon.heightReference = Cesium.HeightReference.CLAMP_TO_GROUND;
                    }
                    
                    entity.description = `
                        <table class="table table-sm" style="color: white;">
                            <tr><td><strong>Segment ID:</strong></td><td>${segmentId}</td></tr>
                            <tr><td><strong>Area:</strong></td><td>${area} pixels</td></tr>
                            <tr><td><strong>Quality (IoU):</strong></td><td>${iou.toFixed(3)}</td></tr>
                            <tr><td><strong>Stability:</strong></td><td>${(props.stability_score?.getValue() || 0).toFixed(3)}</td></tr>
                        </table>
                    `;
                });
                
                this.viewer.dataSources.add(this.samDataSource);
                
                const avgIoU = features.reduce((sum, f) => sum + (f.properties.predicted_iou || 0), 0) / features.length;
                this.showNotification(
                    `SAM: ${result.num_segments} segments displayed (avg quality: ${avgIoU.toFixed(2)})`,
                    'success'
                );
            }).catch(error => {
                console.error('Error loading SAM GeoJSON:', error);
                this.showNotification('Error displaying SAM results on map', 'error');
            });
        });
    }
    
    /**
     * Fallback method using approximate coordinate conversion
     */
    displaySAMResultsApproximate(result) {
        const camera = this.viewer.camera;
        const position = camera.positionCartographic;
        const centerLon = Cesium.Math.toDegrees(position.longitude);
        const centerLat = Cesium.Math.toDegrees(position.latitude);
        
        const canvas = this.viewer.scene.canvas;
        const viewportWidth = canvas.width;
        const viewportHeight = canvas.height;
        const height = position.height;
        const metersPerPixel = height / Math.max(viewportHeight, viewportWidth);
        const degreesPerMeter = 1.0 / 111320.0;
        const degreesPerPixel = metersPerPixel * degreesPerMeter;
        
        this.samDataSource = new Cesium.GeoJsonDataSource('SAM Segments');
        
        const features = result.geojson.features.map((feature, index) => {
            const props = feature.properties;
            const coords = feature.geometry.coordinates[0];
            const geographicCoords = coords.map(([x_norm, y_norm]) => {
                const pixelX = (x_norm - 0.5) * viewportWidth;
                const pixelY = (y_norm - 0.5) * viewportHeight;
                const lonOffset = pixelX * degreesPerPixel;
                const latOffset = -pixelY * degreesPerPixel;
                return [centerLon + lonOffset, centerLat + latOffset];
            });
            
            return {
                type: 'Feature',
                geometry: { type: 'Polygon', coordinates: [geographicCoords] },
                properties: {
                    segment_id: props.segment_id || index + 1,
                    area: props.area || 0,
                    predicted_iou: props.iou || props.predicted_iou || 0,
                    stability_score: props.stability || props.stability_score || 0
                }
            };
        });
        
        const convertedGeoJSON = { type: 'FeatureCollection', features: features };
        
        this.samDataSource.load(convertedGeoJSON).then(() => {
            const entities = this.samDataSource.entities.values;
            entities.forEach((entity, index) => {
                const props = entity.properties;
                const segmentId = props.segment_id?.getValue() || index + 1;
                const hue = (segmentId * 137.508) % 360;
                const color = Cesium.Color.fromHsl(hue / 360, 0.7, 0.5, 0.4);
                
                if (entity.polygon) {
                    entity.polygon.material = color;
                    entity.polygon.outline = true;
                    entity.polygon.outlineColor = Cesium.Color.WHITE.withAlpha(0.8);
                    entity.polygon.outlineWidth = 2;
                    entity.polygon.heightReference = Cesium.HeightReference.CLAMP_TO_GROUND;
                }
            });
            
            this.viewer.dataSources.add(this.samDataSource);
            console.log(`Displayed ${entities.length} SAM segments (approximate method)`);
        }).catch(error => {
            console.error('Error loading SAM GeoJSON (approximate):', error);
        });
    }
    
    /**
     * Display Zero-Shot Detection results on Cesium map
     * @param {Object} result - Zero-shot detection result
     */
    displayZeroShotResults(result) {
        if (!result.geojson || !result.geojson.features) {
            console.warn('No GeoJSON features in Zero-Shot results');
            return;
        }
        
        // Check if camera has moved since capture
        const capturePose = result.capture_pose || this.lastCapturePose;
        if (capturePose) {
            const currentPos = this.viewer.camera.positionCartographic;
            const currentLon = Cesium.Math.toDegrees(currentPos.longitude);
            const currentLat = Cesium.Math.toDegrees(currentPos.latitude);
            const currentAlt = currentPos.height;
            
            const lonDiff = Math.abs(currentLon - capturePose.lon);
            const latDiff = Math.abs(currentLat - capturePose.lat);
            const altDiff = Math.abs(currentAlt - capturePose.alt);
            
            // Warn if camera has moved significantly (>1% of altitude or >0.001 degrees)
            const altThreshold = capturePose.alt * 0.01; // 1% of altitude
            if (lonDiff > 0.001 || latDiff > 0.001 || altDiff > altThreshold) {
                console.warn('⚠️ Camera has moved since capture - detections may be misaligned!');
                console.log('  Capture:', capturePose);
                console.log('  Current:', { lon: currentLon, lat: currentLat, alt: currentAlt });
                console.log('  Diff:', { lon: lonDiff, lat: latDiff, alt: altDiff });
                
                // Show warning to user
                if (typeof this.showNotification === 'function') {
                    this.showNotification(
                        'Camera moved since capture - detections may be slightly misaligned',
                        'warning'
                    );
                }
            } else {
                console.log('✓ Camera position stable - detections should align correctly');
            }
        }
        
        // Remove previous SAM/Zero-Shot results if any
        if (this.samDataSource) {
            this.viewer.dataSources.remove(this.samDataSource);
        }
        
        const camera = this.viewer.camera;
        const scene = this.viewer.scene;
        const canvas = scene.canvas;
        const viewportWidth = canvas.width;
        const viewportHeight = canvas.height;
        
        // Get camera position
        const position = camera.positionCartographic;
        const centerLon = Cesium.Math.toDegrees(position.longitude);
        const centerLat = Cesium.Math.toDegrees(position.latitude);
        const height = position.height;
        
        // Get viewport bounds
        const corners = [
            new Cesium.Cartesian2(0, 0),
            new Cesium.Cartesian2(viewportWidth, 0),
            new Cesium.Cartesian2(viewportWidth, viewportHeight),
            new Cesium.Cartesian2(0, viewportHeight)
        ];
        
        const worldCorners = corners.map(screenPos => {
            // Try to pick from terrain first
            let cartesian = scene.pickPosition(screenPos);
            
            // Fallback to ellipsoid if pickPosition fails
            if (!Cesium.defined(cartesian)) {
                cartesian = scene.camera.pickEllipsoid(screenPos, scene.globe.ellipsoid);
            }
            
            if (cartesian) {
                const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
                return {
                    lon: Cesium.Math.toDegrees(cartographic.longitude),
                    lat: Cesium.Math.toDegrees(cartographic.latitude),
                    height: cartographic.height
                };
            }
            return null;
        }).filter(c => c !== null);
        
        // Use the same capturePose already defined earlier in function (line 2645)
        // const capturePose already declared above - no need to redeclare
        
        this.withCapturePose(capturePose, () => {
            const camera = this.viewer.camera;
            const scene = this.viewer.scene;
            const canvas = scene.canvas;
            const viewportWidth = canvas.width;
            const viewportHeight = canvas.height;
            const pickPositionSupported = scene.pickPositionSupported && scene.mode === Cesium.SceneMode.SCENE3D;
            
            const corners = [
                new Cesium.Cartesian2(0, 0),
                new Cesium.Cartesian2(viewportWidth, 0),
                new Cesium.Cartesian2(viewportWidth, viewportHeight),
                new Cesium.Cartesian2(0, viewportHeight)
            ];
            
            const worldCorners = corners.map(screenPos => {
                let cartesian = null;
                if (pickPositionSupported) {
                    cartesian = scene.pickPosition(screenPos);
                }
                if (!Cesium.defined(cartesian) && scene.globe) {
                    cartesian = scene.camera.pickEllipsoid(screenPos, scene.globe.ellipsoid);
                }
                if (cartesian) {
                    const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
                    return {
                        lon: Cesium.Math.toDegrees(cartographic.longitude),
                        lat: Cesium.Math.toDegrees(cartographic.latitude),
                        height: cartographic.height
                    };
                }
                return null;
            }).filter(c => c !== null);
            
            if (worldCorners.length < 2) {
                console.warn('Could not determine viewport bounds for Zero-Shot, using approximate');
                this.displayZeroShotResultsApproximate(result);
                return;
            }
            
            const lons = worldCorners.map(c => c.lon);
            const lats = worldCorners.map(c => c.lat);
            const minLon = Math.min(...lons);
            const maxLon = Math.max(...lons);
            const minLat = Math.min(...lats);
            const maxLat = Math.max(...lats);
            
            const lonRange = maxLon - minLon;
            const latRange = maxLat - minLat;
            
            this.samDataSource = new Cesium.GeoJsonDataSource('Zero-Shot Detections');
            
            const pixelToGeographic = (x_norm, y_norm) => {
                const screenX = x_norm * viewportWidth;
                const screenY = y_norm * viewportHeight;
                const screenPos = new Cesium.Cartesian2(screenX, screenY);
                
                let cartesian = null;
                if (pickPositionSupported) {
                    cartesian = scene.pickPosition(screenPos);
                }
                
                if (!Cesium.defined(cartesian)) {
                    const lon = minLon + (x_norm * lonRange);
                    const lat = minLat + ((1 - y_norm) * latRange); // Flip Y (image origin is top-left)
                    return [lon, lat];
                }
                
                const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
                return [
                    Cesium.Math.toDegrees(cartographic.longitude),
                    Cesium.Math.toDegrees(cartographic.latitude)
                ];
            };
            
            const features = result.geojson.features.map((feature, index) => {
                const props = feature.properties;
                const coords = feature.geometry.coordinates[0];
                
                const geographicCoords = coords.map(([x_norm, y_norm]) => 
                    pixelToGeographic(x_norm, y_norm)
                );
                
                return {
                    type: 'Feature',
                    geometry: {
                        type: 'Polygon',
                        coordinates: [geographicCoords]
                    },
                    properties: {
                        ...props,
                        detection_id: props.class_id || index + 1,
                        class_name: props.category || 'unknown',
                        confidence: props.confidence || 0.0
                    }
                };
            });
            
            const convertedGeoJSON = {
                type: 'FeatureCollection',
                features: features
            };
            
            this.samDataSource.load(convertedGeoJSON).then(() => {
                const entities = this.samDataSource.entities.values;
                
                const classColors = {
                    'person': Cesium.Color.RED,
                    'car': Cesium.Color.BLUE,
                    'bicycle': Cesium.Color.GREEN,
                    'truck': Cesium.Color.ORANGE,
                    'bus': Cesium.Color.YELLOW,
                    'motorcycle': Cesium.Color.CYAN,
                    'bird': Cesium.Color.MAGENTA,
                    'cat': Cesium.Color.PINK,
                    'dog': Cesium.Color.LIME
                };
                
                entities.forEach((entity, index) => {
                    try {
                        const props = entity.properties;
                        const detectionId = props.detection_id?.getValue() || (index + 1);
                        const className = props.class_name?.getValue() || 'unknown';
                        const confidence = props.confidence?.getValue() || 0.0;
                        
                        // Get color for this class
                        const baseColor = classColors[className.toLowerCase()] || Cesium.Color.fromHsl(
                            (index * 137.508) % 360 / 360, 0.7, 0.5
                        );
                        
                        // Make opacity based on confidence (higher confidence = more opaque)
                        const opacity = 0.3 + (confidence * 0.4);
                        const color = baseColor.withAlpha(opacity);
                        
                        // Style the polygon bounding box
                        if (entity.polygon) {
                            entity.polygon.material = color;
                            entity.polygon.outline = true;
                            entity.polygon.outlineColor = baseColor.withAlpha(1.0); // Full opacity for outline
                            entity.polygon.outlineWidth = 3; // Increased from 2 to 3
                            entity.polygon.heightReference = Cesium.HeightReference.CLAMP_TO_GROUND;
                        }
                        
                        // Enhanced label with ID number, class name, and confidence
                        entity.label = {
                            text: `#${detectionId}: ${className} (${(confidence * 100).toFixed(0)}%)`,
                            font: 'bold 14px sans-serif', // Increased from 12px to 14px, made bold
                            fillColor: Cesium.Color.WHITE,
                            outlineColor: Cesium.Color.BLACK,
                            outlineWidth: 3, // Increased from 2 to 3 for better readability
                            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                            pixelOffset: new Cesium.Cartesian2(0, -15), // Increased offset for visibility
                            scale: 1.0,
                            showBackground: true, // Add background for better contrast
                            backgroundColor: Cesium.Color.BLACK.withAlpha(0.6),
                            backgroundPadding: new Cesium.Cartesian2(8, 4),
                            disableDepthTestDistance: Number.POSITIVE_INFINITY // Always show labels on top
                        };
                        
                        // Enhanced description popup
                        entity.description = `
                            <div style="padding: 8px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 8px;">
                                <h4 style="margin: 0 0 10px 0; color: white; font-size: 16px;">
                                    🎯 Detection #${detectionId}
                                </h4>
                                <table style="width: 100%; color: white; font-size: 13px;">
                                    <tr style="background: rgba(255,255,255,0.1);">
                                        <td style="padding: 6px; font-weight: bold;">Class:</td>
                                        <td style="padding: 6px;">${className}</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 6px; font-weight: bold;">Confidence:</td>
                                        <td style="padding: 6px;">
                                            <span style="background: rgba(16, 185, 129, 0.3); padding: 2px 8px; border-radius: 4px;">
                                                ${(confidence * 100).toFixed(1)}%
                                            </span>
                                        </td>
                                    </tr>
                                    <tr style="background: rgba(255,255,255,0.1);">
                                        <td style="padding: 6px; font-weight: bold;">ID:</td>
                                        <td style="padding: 6px;">#${detectionId}</td>
                                    </tr>
                                </table>
                            </div>
                        `;
                        
                        // Log successful processing
                        if (index === 0 || index === entities.length - 1) {
                            console.log(`Styled detection #${detectionId}: ${className} (${(confidence * 100).toFixed(1)}%)`);
                        }
                        
                    } catch (error) {
                        console.error(`Error styling entity ${index}:`, error);
                        // Continue processing other entities even if one fails
                    }
                });
                
                this.viewer.dataSources.add(this.samDataSource);
                
                console.log(`Displayed ${entities.length} Zero-Shot detections on map`);
                console.log('Viewport bounds:', { minLon, maxLon, minLat, maxLat });
            }).catch(error => {
                console.error('Error loading Zero-Shot GeoJSON:', error);
            });
        });
    }
    
    /**
     * Display Zero-Shot results using approximate conversion (fallback)
     */
    displayZeroShotResultsApproximate(result) {
        const camera = this.viewer.camera;
        const scene = this.viewer.scene;
        const canvas = scene.canvas;
        const viewportWidth = canvas.width;
        const viewportHeight = canvas.height;
        
        const position = camera.positionCartographic;
        const height = position.height;
        const metersPerPixel = height / Math.max(viewportHeight, viewportWidth);
        const degreesPerMeter = 1.0 / 111320.0;
        const degreesPerPixel = metersPerPixel * degreesPerMeter;
        
        this.samDataSource = new Cesium.GeoJsonDataSource('Zero-Shot Detections');
        
        const features = result.geojson.features.map((feature, index) => {
            const props = feature.properties;
            const coords = feature.geometry.coordinates[0];
            const geographicCoords = coords.map(([x_norm, y_norm]) => {
                const lon = Cesium.Math.toDegrees(position.longitude) + (x_norm - 0.5) * viewportWidth * degreesPerPixel;
                const lat = Cesium.Math.toDegrees(position.latitude) + (0.5 - y_norm) * viewportHeight * degreesPerPixel;
                return [lon, lat];
            });
            
            return {
                type: 'Feature',
                geometry: {
                    type: 'Polygon',
                    coordinates: [geographicCoords]
                },
                properties: {
                    ...props,
                    detection_id: props.class_id || index + 1,
                    class_name: props.category || 'unknown',
                    confidence: props.confidence || 0.0
                }
            };
        });
        
        const convertedGeoJSON = { type: 'FeatureCollection', features: features };
        
        this.samDataSource.load(convertedGeoJSON).then(() => {
            const entities = this.samDataSource.entities.values;
            entities.forEach((entity, index) => {
                try {
                    const props = entity.properties;
                    const detectionId = props.detection_id?.getValue() || (index + 1);
                    const className = props.class_name?.getValue() || 'unknown';
                    const confidence = props.confidence?.getValue() || 0.0;
                    
                    const hue = (index * 137.508) % 360;
                    const baseColor = Cesium.Color.fromHsl(hue / 360, 0.7, 0.5);
                    const opacity = 0.3 + (confidence * 0.4);
                    const color = baseColor.withAlpha(opacity);
                    
                    if (entity.polygon) {
                        entity.polygon.material = color;
                        entity.polygon.outline = true;
                        entity.polygon.outlineColor = baseColor.withAlpha(1.0); // Full opacity outline
                        entity.polygon.outlineWidth = 3; // Increased from 2 to 3
                        entity.polygon.heightReference = Cesium.HeightReference.CLAMP_TO_GROUND;
                    }
                    
                    // Enhanced label with ID number
                    entity.label = {
                        text: `#${detectionId}: ${className} (${(confidence * 100).toFixed(0)}%)`,
                        font: 'bold 14px sans-serif', // Increased and made bold
                        fillColor: Cesium.Color.WHITE,
                        outlineColor: Cesium.Color.BLACK,
                        outlineWidth: 3, // Increased from 2 to 3
                        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                        pixelOffset: new Cesium.Cartesian2(0, -15),
                        scale: 1.0,
                        showBackground: true,
                        backgroundColor: Cesium.Color.BLACK.withAlpha(0.6),
                        backgroundPadding: new Cesium.Cartesian2(8, 4),
                        disableDepthTestDistance: Number.POSITIVE_INFINITY // Always show labels on top
                    };
                    
                    // Enhanced description popup
                    entity.description = `
                        <div style="padding: 8px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 8px;">
                            <h4 style="margin: 0 0 10px 0; color: white; font-size: 16px;">
                                🎯 Detection #${detectionId}
                            </h4>
                            <table style="width: 100%; color: white; font-size: 13px;">
                                <tr style="background: rgba(255,255,255,0.1);">
                                    <td style="padding: 6px; font-weight: bold;">Class:</td>
                                    <td style="padding: 6px;">${className}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 6px; font-weight: bold;">Confidence:</td>
                                    <td style="padding: 6px;">
                                        <span style="background: rgba(16, 185, 129, 0.3); padding: 2px 8px; border-radius: 4px;">
                                            ${(confidence * 100).toFixed(1)}%
                                        </span>
                                    </td>
                                </tr>
                                <tr style="background: rgba(255,255,255,0.1);">
                                    <td style="padding: 6px; font-weight: bold;">ID:</td>
                                    <td style="padding: 6px;">#${detectionId}</td>
                                </tr>
                            </table>
                            <p style="margin: 8px 0 0 0; padding: 6px; background: rgba(255,152,0,0.2); border-radius: 4px; font-size: 11px;">
                                ⚠️ Approximate positioning (fallback method)
                            </p>
                        </div>
                    `;
                } catch (error) {
                    console.error(`Error styling entity ${index} (approximate):`, error);
                }
            });
            
            this.viewer.dataSources.add(this.samDataSource);
            console.log(`Displayed ${entities.length} Zero-Shot detections (approximate method)`);
        }).catch(error => {
            console.error('Error loading Zero-Shot GeoJSON (approximate):', error);
        });
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

/**
 * Initialize SAM button handler globally (works independently of World Sampler)
 * This allows viewport analysis from anywhere in the application
 */
function initializeSAMButtonHandler(viewer, worldSamplerUI) {
    const analyzeBtn = document.getElementById('analyzeViewportBtn');
    if (!analyzeBtn) {
        console.warn('[AI Analysis] Analyze button not found, AI functionality may not work');
        return;
    }
    
    // Remove any existing listeners by cloning
    const newBtn = analyzeBtn.cloneNode(true);
    analyzeBtn.parentNode.replaceChild(newBtn, analyzeBtn);
    
    // Setup model selector toggle
    const analysisTypeSelect = document.getElementById('analysisTypeSelect');
    const samOptions = document.getElementById('samOptions');
    const zeroShotOptions = document.getElementById('zeroShotOptions');
    const mask2formerOptions = document.getElementById('mask2formerOptions');
    const yolov8Options = document.getElementById('yolov8Options');
    const groundingDinoOptions = document.getElementById('groundingDinoOptions');
    const analysisDescription = document.getElementById('analysisDescription');
    const zeroShotConfidenceSlider = document.getElementById('zeroShotConfidence');
    const zeroShotConfidenceValue = document.getElementById('zeroShotConfidenceValue');
    const mask2formerConfidenceSlider = document.getElementById('mask2formerConfidence');
    const mask2formerConfidenceValue = document.getElementById('mask2formerConfidenceValue');
    const yolov8ConfidenceSlider = document.getElementById('yolov8Confidence');
    const yolov8ConfidenceValueEl = document.getElementById('yolov8ConfidenceValue');
    const gdBoxThresholdSlider = document.getElementById('gdBoxThreshold');
    const gdBoxThresholdValue = document.getElementById('gdBoxThresholdValue');
    const gdTextThresholdSlider = document.getElementById('gdTextThreshold');
    const gdTextThresholdValue = document.getElementById('gdTextThresholdValue');
    
    if (analysisTypeSelect) {
        analysisTypeSelect.addEventListener('change', (e) => {
            const analysisType = e.target.value;
            // Hide all options first
            if (samOptions) samOptions.style.display = 'none';
            if (zeroShotOptions) zeroShotOptions.style.display = 'none';
            if (mask2formerOptions) mask2formerOptions.style.display = 'none';
            if (yolov8Options) yolov8Options.style.display = 'none';
            if (groundingDinoOptions) groundingDinoOptions.style.display = 'none';
            
            if (analysisType === 'zero_shot') {
                if (zeroShotOptions) zeroShotOptions.style.display = 'block';
                if (analysisDescription) {
                    analysisDescription.textContent = 'Detects common objects (person, car, bicycle, etc.) using pre-trained COCO Mask R-CNN model';
                }
            } else if (analysisType === 'mask2former') {
                if (mask2formerOptions) mask2formerOptions.style.display = 'block';
                if (analysisDescription) {
                    analysisDescription.textContent = 'State-of-the-art object detection with 80 COCO categories using Mask2Former (more accurate than Zero-Shot)';
                }
            } else if (analysisType === 'yolov8') {
                if (yolov8Options) yolov8Options.style.display = 'block';
                if (analysisDescription) {
                    analysisDescription.textContent = 'Ultra-fast real-time detection with 80 COCO classes - best for vehicles, people, common objects';
                }
            } else if (analysisType === 'grounding_dino') {
                if (groundingDinoOptions) groundingDinoOptions.style.display = 'block';
                if (analysisDescription) {
                    analysisDescription.textContent = 'Open-vocabulary detection - describe ANY object to find (rocks, craters, vehicles, custom objects)';
                }
            } else {
                // SAM (default)
                if (samOptions) samOptions.style.display = 'block';
                if (analysisDescription) {
                    analysisDescription.textContent = 'Segments all visible regions in current viewport using Segment Anything Model';
                }
            }
        });
    }
    
    // Setup Grounding DINO threshold sliders
    if (gdBoxThresholdSlider && gdBoxThresholdValue) {
        gdBoxThresholdSlider.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value) / 100;
            gdBoxThresholdValue.textContent = value.toFixed(2);
        });
    }
    
    if (gdTextThresholdSlider && gdTextThresholdValue) {
        gdTextThresholdSlider.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value) / 100;
            gdTextThresholdValue.textContent = value.toFixed(2);
        });
    }
    
    // Setup YOLOv8 confidence slider
    if (yolov8ConfidenceSlider && yolov8ConfidenceValueEl) {
        yolov8ConfidenceSlider.addEventListener('input', (e) => {
            yolov8ConfidenceValueEl.textContent = `${e.target.value}%`;
        });
    }
    
    // Setup confidence sliders
    if (zeroShotConfidenceSlider && zeroShotConfidenceValue) {
        zeroShotConfidenceSlider.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value) / 100;
            zeroShotConfidenceValue.textContent = value.toFixed(2);
        });
    }
    
    if (mask2formerConfidenceSlider && mask2formerConfidenceValue) {
        mask2formerConfidenceSlider.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value) / 100;
            mask2formerConfidenceValue.textContent = value.toFixed(2);
        });
    }
    
    // Add click handler
    newBtn.addEventListener('click', async () => {
        // Use worldSamplerUI if available
        if (worldSamplerUI) {
            worldSamplerUI.analyzeViewportWithSAM();
        } else {
            // Fallback: show error
            console.warn('[AI Analysis] WorldSamplerUI not available');
            const statusDiv = document.getElementById('samAnalysisStatus');
            const statusText = document.getElementById('samStatusText');
            const btn = document.getElementById('analyzeViewportBtn');
            
            if (statusDiv) statusDiv.style.display = 'block';
            if (statusText) {
                statusText.textContent = 'Error: World Sampler not initialized';
                statusText.style.color = '#ef4444';
            }
            if (btn) btn.disabled = false;
        }
    });
    
    console.log('[SAM] ✅ SAM button handler initialized');
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
                
                // Initialize SAM button handler globally (works independently of World Sampler)
                initializeSAMButtonHandler(viewer, window.worldSamplerUI);
                
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


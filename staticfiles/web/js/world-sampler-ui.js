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
        this.sceneGraphDataSource = null;
        this.worldDataSource = null;
        this.worldEntities = new Map();
        this.selectedWorldEntity = null;
        this.currentSceneGraph = null;
        this.currentSceneGraphCorners = null;
        this.vegetationTargetDataSource = null;
        this.vegetationGame = {
            sessionId: `vegetation-game-${Date.now()}`,
            targets: [],
            selectedTarget: null,
            osmContext: null,
            lastCapture: null,
            lastResult: null
        };
        
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
        this.viewer.scene.morphComplete.addEventListener(() => this.restyleResultsForSceneMode());
        this.viewer.scene.renderError.addEventListener((_scene, error) => this.recoverFromRenderError(error));
        
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
                
                <!-- Vegetation Annotation Game -->
                <div class="sampler-section">
                    <h4 class="accordion-header" data-target="vegetationGameContent">
                        <span><i class="fas fa-tree"></i> Vegetation Game</span>
                        <i class="fas fa-chevron-down accordion-icon"></i>
                    </h4>
                    <div class="sampler-section-content compact-vegetation-game" id="vegetationGameContent">
                        <div class="form-group veg-form-group">
                            <label>Prompt</label>
                            <input type="text" id="vegetationPrompt" class="form-control"
                                   value="tree. shrub. bush. canopy.">
                        </div>
                        <div class="form-group veg-form-group">
                            <label>Box Threshold <span id="vegetationBoxThresholdValue">0.30</span></label>
                            <input type="range" id="vegetationBoxThreshold" class="form-range"
                                   min="10" max="80" value="30">
                        </div>
                        <div class="veg-button-grid">
                            <button class="btn btn-outline-info btn-sm" id="vegetationFindTargetsBtn">
                                <i class="fas fa-parking"></i> Find OSM
                            </button>
                            <button class="btn btn-outline-primary btn-sm" id="vegetationFlyTargetBtn">
                                <i class="fas fa-location-arrow"></i> Fly
                            </button>
                        </div>
                        <select id="vegetationTargetSelect" class="form-control mb-2">
                            <option value="">Current viewport / no OSM target</option>
                        </select>
                        <button class="btn btn-success btn-sm w-100 mb-1" id="vegetationRunBtn">
                            <i class="fas fa-search"></i> Run Tree/Shrub
                        </button>
                        <div id="vegetationGameStatus" class="feedback-info veg-status">
                            <small>Find OSM targets, run proposals, then review.</small>
                        </div>
                        <div id="vegetationProposalList" class="vegetation-proposal-list"></div>
                        <button class="btn btn-warning btn-sm w-100 mt-1" id="vegetationSaveRoundBtn" disabled>
                            <i class="fas fa-save"></i> Save + Reward
                        </button>
                        <div class="btn-group w-100 mt-1 veg-export-group" role="group">
                            <button class="btn btn-outline-secondary btn-sm" id="vegetationExportCocoBtn">
                                COCO
                            </button>
                            <button class="btn btn-outline-secondary btn-sm" id="vegetationExportGraphBtn">
                                Graph
                            </button>
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
            
            #vegetationGameContent.compact-vegetation-game.expanded {
                padding: 8px;
                max-height: 900px;
            }
            
            .compact-vegetation-game .veg-form-group {
                margin-bottom: 6px;
            }
            
            .compact-vegetation-game label {
                font-size: 10px;
                margin-bottom: 2px;
                line-height: 1.1;
            }
            
            .compact-vegetation-game .form-control {
                padding: 4px 6px;
                font-size: 11px;
                min-height: 28px;
            }
            
            .compact-vegetation-game .form-range {
                height: 16px;
                margin: 0;
            }
            
            .compact-vegetation-game .btn {
                padding: 4px 6px;
                font-size: 11px;
                line-height: 1.2;
            }
            
            .veg-button-grid {
                display: grid;
                grid-template-columns: 1fr 0.55fr;
                gap: 5px;
                margin-bottom: 5px;
            }
            
            .veg-status {
                margin: 4px 0;
                line-height: 1.2;
            }
            
            .veg-status small {
                font-size: 10px;
            }
            
            .vegetation-proposal-list {
                max-height: 150px;
                overflow-y: auto;
                border: 1px solid rgba(148, 163, 184, 0.25);
                border-radius: 4px;
                padding: 3px 5px;
                background: rgba(15, 23, 42, 0.35);
                font-size: 10px;
            }
            
            .vegetation-proposal-row {
                display: grid;
                grid-template-columns: 16px minmax(0, 1fr) 56px;
                gap: 4px;
                align-items: center;
                padding: 3px 0;
                border-bottom: 1px solid rgba(148, 163, 184, 0.15);
                font-size: 10px;
                line-height: 1.15;
            }
            
            .vegetation-proposal-row span {
                overflow: hidden;
                white-space: nowrap;
                text-overflow: ellipsis;
            }
            
            .vegetation-proposal-row input[type="checkbox"] {
                width: 12px;
                height: 12px;
                margin: 0;
            }
            
            .vegetation-proposal-row .form-control {
                padding: 2px 3px;
                font-size: 10px;
                min-height: 22px;
            }
            
            .vegetation-proposal-row:last-child {
                border-bottom: none;
            }
            
            .veg-export-group .btn {
                padding: 3px 4px;
                font-size: 10px;
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
        safeAddListener('vegetationFindTargetsBtn', 'click', () => this.fetchVegetationTargets());
        safeAddListener('vegetationFlyTargetBtn', 'click', () => this.flyToSelectedVegetationTarget());
        safeAddListener('vegetationRunBtn', 'click', () => this.runVegetationBootstrap());
        safeAddListener('vegetationSaveRoundBtn', 'click', () => this.saveVegetationRound());
        safeAddListener('vegetationExportCocoBtn', 'click', () => this.exportVegetationGame('coco'));
        safeAddListener('vegetationExportGraphBtn', 'click', () => this.exportVegetationGame('graph'));
        safeAddListener('vegetationTargetSelect', 'change', () => this.updateSelectedVegetationTarget());
        safeAddListener('vegetationBoxThreshold', 'input', (e) => {
            const value = document.getElementById('vegetationBoxThresholdValue');
            if (value) value.textContent = (parseFloat(e.target.value) / 100).toFixed(2);
        });
        
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
    
    getViewportBbox() {
        const scene = this.viewer.scene;
        const canvas = scene.canvas;
        const ellipsoid = scene.globe.ellipsoid;
        const corners = [
            new Cesium.Cartesian2(0, 0),
            new Cesium.Cartesian2(canvas.clientWidth, 0),
            new Cesium.Cartesian2(canvas.clientWidth, canvas.clientHeight),
            new Cesium.Cartesian2(0, canvas.clientHeight),
            new Cesium.Cartesian2(canvas.clientWidth / 2, canvas.clientHeight / 2)
        ];
        const points = [];
        corners.forEach((screenPos) => {
            let cartesian;
            if (scene.pickPositionSupported) {
                try {
                    cartesian = scene.pickPosition(screenPos);
                } catch (e) {
                    cartesian = null;
                }
            }
            if (!cartesian) {
                cartesian = scene.camera.pickEllipsoid(screenPos, ellipsoid);
            }
            if (cartesian) {
                const c = Cesium.Cartographic.fromCartesian(cartesian);
                points.push({
                    lon: Cesium.Math.toDegrees(c.longitude),
                    lat: Cesium.Math.toDegrees(c.latitude)
                });
            }
        });
        if (points.length < 2) {
            const c = this.viewer.camera.positionCartographic;
            const lon = Cesium.Math.toDegrees(c.longitude);
            const lat = Cesium.Math.toDegrees(c.latitude);
            return { south: lat - 0.005, west: lon - 0.005, north: lat + 0.005, east: lon + 0.005 };
        }
        return {
            south: Math.min(...points.map(p => p.lat)),
            west: Math.min(...points.map(p => p.lon)),
            north: Math.max(...points.map(p => p.lat)),
            east: Math.max(...points.map(p => p.lon))
        };
    }
    
    setVegetationStatus(message, tone = 'info') {
        const el = document.getElementById('vegetationGameStatus');
        if (!el) return;
        const color = tone === 'error' ? '#ef4444' : tone === 'success' ? '#10b981' : '#94a3b8';
        el.innerHTML = `<small style="color: ${color};">${message}</small>`;
    }
    
    async fetchVegetationTargets() {
        const promptEl = document.getElementById('vegetationPrompt');
        const prompt = promptEl ? promptEl.value.trim() : 'tree. shrub. bush. canopy.';
        const bbox = this.getViewportBbox();
        this.setVegetationStatus('Fetching OSM parking lots and nearby buildings...');
        try {
            const response = await fetch('/webclient/sampler/vegetation-targets', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({bbox, prompt, limit: 30})
            });
            const result = await response.json();
            if (!response.ok || result.status !== 'success') {
                throw new Error(result.message || `HTTP ${response.status}`);
            }
            this.vegetationGame.targets = result.targets || [];
            this.vegetationGame.osmContext = result.osm_context || {};
            this.populateVegetationTargets();
            this.visualizeVegetationTargets(result.osm_context || {});
            this.setVegetationStatus(`Loaded ${this.vegetationGame.targets.length} OSM parking targets and ${(result.osm_context?.buildings || []).length} buildings.`, 'success');
        } catch (error) {
            console.error('Failed to fetch vegetation targets:', error);
            this.setVegetationStatus(`OSM target fetch failed: ${error.message}`, 'error');
        }
    }
    
    populateVegetationTargets() {
        const select = document.getElementById('vegetationTargetSelect');
        if (!select) return;
        select.innerHTML = '<option value="">Current viewport / no OSM target</option>';
        this.vegetationGame.targets.forEach((target, index) => {
            const option = document.createElement('option');
            option.value = String(index);
            option.textContent = `${target.target_id} (${target.nearby_building_count || 0} buildings)`;
            select.appendChild(option);
        });
        this.updateSelectedVegetationTarget();
    }
    
    updateSelectedVegetationTarget() {
        const select = document.getElementById('vegetationTargetSelect');
        const idx = select && select.value !== '' ? parseInt(select.value, 10) : null;
        this.vegetationGame.selectedTarget = Number.isInteger(idx) ? this.vegetationGame.targets[idx] : null;
    }
    
    visualizeVegetationTargets(osmContext) {
        if (this.vegetationTargetDataSource) {
            this.viewer.dataSources.remove(this.vegetationTargetDataSource);
            this.vegetationTargetDataSource = null;
        }
        const features = [];
        (osmContext.parking || []).forEach((feature) => {
            features.push({
                type: 'Feature',
                geometry: feature.geometry,
                properties: {kind: 'parking_lot', osm_id: feature.osm_id}
            });
        });
        (osmContext.buildings || []).forEach((feature) => {
            features.push({
                type: 'Feature',
                geometry: feature.geometry,
                properties: {kind: 'building', osm_id: feature.osm_id}
            });
        });
        if (!features.length) return;
        const cameraSnapshot = this.snapshotCamera();
        Cesium.GeoJsonDataSource.load({type: 'FeatureCollection', features}, {
            stroke: Cesium.Color.CYAN,
            fill: Cesium.Color.CYAN.withAlpha(0.12),
            strokeWidth: 2
        }).then((dataSource) => {
            this.vegetationTargetDataSource = dataSource;
            dataSource.entities.values.forEach((entity) => {
                const kind = entity.properties?.kind?.getValue?.() || '';
                if (kind === 'building' && entity.polygon) {
                    entity.polygon.material = Cesium.Color.ORANGE.withAlpha(0.18);
                    entity.polygon.outlineColor = Cesium.Color.ORANGE;
                }
            });
            this.addDataSourcePreservingCamera(dataSource, cameraSnapshot);
        });
    }
    
    flyToSelectedVegetationTarget() {
        this.updateSelectedVegetationTarget();
        const target = this.vegetationGame.selectedTarget;
        if (!target || !target.center) {
            this.showNotification('Select an OSM target first', 'warning');
            return;
        }
        this.viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(target.center.lon, target.center.lat, 750),
            duration: 1.5,
            orientation: {
                heading: Cesium.Math.toRadians(0),
                pitch: Cesium.Math.toRadians(-90),
                roll: 0
            }
        });
    }
    
    snapshotCamera() {
        return {
            position: Cesium.Cartesian3.clone(this.viewer.camera.position),
            heading: this.viewer.camera.heading,
            pitch: this.viewer.camera.pitch,
            roll: this.viewer.camera.roll
        };
    }

    // The "camera-preserving" helpers below are intentional no-ops on the camera.
    //
    // History: this UI used to (a) save a camera snapshot, (b) call
    // viewer.dataSources.add(...), (c) schedule one or more setView() calls to
    // restore the snapshot on the next microtask / [0, 50, 250, 750] ms timers.
    // The premise was "GeoJsonDataSource.load auto-zooms to its features", which
    // is false in modern Cesium — only viewer.zoomTo / flyTo / selectedEntity /
    // trackedEntity move the camera implicitly, and none of those run here.
    //
    // The "protective" setView calls were the actual cause of the visible
    // post-Analyze "zoom-out": if the user nudged the wheel during the network
    // round-trip, the snapshot we restored to was their PRE-analyze pose taken
    // before they nudged, snapping the camera back to where it was several
    // seconds ago. Worse, displayZeroShotResults's withCapturePose finally clause
    // restored to the pose at the start of *display*, which combined with stray
    // user input could leave the camera continents away from the capture site.
    //
    // We now keep the function names so call sites stay readable, but they only
    // add the data source. Projection is decoupled from the live camera via
    // computeViewportCornersGeo() + bilinearProjectFromCorners(), so we never
    // need to move the camera to render results.
    preserveCameraAfterAsyncRender(_snapshot) { /* no-op, kept for callers */ }

    addDataSourcePreservingCamera(dataSource, _snapshot = null) {
        this.viewer.dataSources.add(dataSource);
        return dataSource;
    }

    /**
     * Snapshot the four viewport corners as geographic coordinates using the
     * current camera. Call this immediately after a clean render when the user
     * is at the pose they want results aligned to (i.e. right after capture).
     *
     * Returns { tl, tr, br, bl, bbox } where each corner is { lon, lat } in
     * degrees and bbox is { minLon, maxLon, minLat, maxLat }. Returns null if
     * fewer than two corners can be picked (degenerate viewport, e.g. fully
     * off-globe).
     *
     * Picks use CSS pixels. canvas.width/height is the drawing buffer, and
     * this viewer sets useBrowserRecommendedResolution false, so that buffer
     * is client size times devicePixelRatio. Cesium's pickPosition and
     * pickEllipsoid reject a window position past clientWidth/clientHeight,
     * which used to null the snapshot and send every overlay through the
     * heading-blind fallback. The last pixel is client size minus one.
     */
    computeViewportCornersGeo() {
        const scene = this.viewer.scene;
        const canvas = scene.canvas;
        const w = Math.max((canvas.clientWidth || 0) - 1, 0);
        const h = Math.max((canvas.clientHeight || 0) - 1, 0);
        const pickPositionSupported = scene.pickPositionSupported &&
            scene.mode === Cesium.SceneMode.SCENE3D;

        const pickAt = (x, y) => {
            const sp = new Cesium.Cartesian2(x, y);
            let cart = null;
            if (pickPositionSupported) {
                try { cart = scene.pickPosition(sp); } catch (e) { cart = null; }
            }
            // pickPosition can miss at the canvas edge. The bare ellipsoid sits
            // at height 0, hundreds of metres under high terrain, which skews
            // that corner, so try the terrain surface first.
            if (!Cesium.defined(cart) && scene.globe && scene.mode === Cesium.SceneMode.SCENE3D) {
                const ray = scene.camera.getPickRay(sp);
                cart = ray ? scene.globe.pick(ray, scene) : undefined;
            }
            if (!Cesium.defined(cart) && scene.globe) {
                cart = scene.camera.pickEllipsoid(sp, scene.globe.ellipsoid);
            }
            if (!Cesium.defined(cart)) return null;
            const c = Cesium.Cartographic.fromCartesian(cart);
            return {
                lon: Cesium.Math.toDegrees(c.longitude),
                lat: Cesium.Math.toDegrees(c.latitude)
            };
        };

        const tl = pickAt(0, 0);
        const tr = pickAt(w, 0);
        const br = pickAt(w, h);
        const bl = pickAt(0, h);
        const got = [tl, tr, br, bl].filter(Boolean);
        if (got.length < 2) return null;

        const lons = got.map(p => p.lon);
        const lats = got.map(p => p.lat);
        return {
            tl, tr, br, bl,
            bbox: {
                minLon: Math.min(...lons),
                maxLon: Math.max(...lons),
                minLat: Math.min(...lats),
                maxLat: Math.max(...lats)
            }
        };
    }

    /**
     * Project a normalized image-space point (x_norm in [0,1] left→right,
     * y_norm in [0,1] top→bottom) onto a geographic [lon, lat] using bilinear
     * interpolation across the four pre-captured viewport corners. Handles
     * arbitrary camera headings without touching the live camera state.
     *
     * Falls back to the bbox-based linear interp if any corner is missing,
     * then to the centre point if the corners object is null.
     */
    bilinearProjectFromCorners(corners, x_norm, y_norm) {
        if (!corners) return null;
        const { tl, tr, br, bl, bbox } = corners;
        if (tl && tr && br && bl) {
            const u = x_norm;
            const v = y_norm;
            const wTL = (1 - u) * (1 - v);
            const wTR = u * (1 - v);
            const wBR = u * v;
            const wBL = (1 - u) * v;
            return [
                tl.lon * wTL + tr.lon * wTR + br.lon * wBR + bl.lon * wBL,
                tl.lat * wTL + tr.lat * wTR + br.lat * wBR + bl.lat * wBL
            ];
        }
        if (bbox) {
            const lonRange = bbox.maxLon - bbox.minLon;
            const latRange = bbox.maxLat - bbox.minLat;
            return [
                bbox.minLon + x_norm * lonRange,
                bbox.minLat + (1 - y_norm) * latRange
            ];
        }
        return null;
    }

    /**
     * Clean a projected [lon, lat] ring before Cesium tessellates it. A ring
     * that folds back on itself, has zero area, or repeats a vertex throws
     * inside Cesium's geometry worker ("Invalid array length", "EllipsoidRhumbLine
     * must have distinct start and end set") and stops rendering for the page.
     * Drops non-finite and repeated points, spikes and collinear vertices, and
     * returns a closed ring, or null when no real area is left.
     */
    cleanGeoRing(rawRing) {
        if (!rawRing || rawRing.length < 3) return null;
        const eps = 1e-7; // degrees, about 1 cm
        const same = (a, b) => Math.abs(a[0] - b[0]) < eps && Math.abs(a[1] - b[1]) < eps;
        let pts = [];
        for (const p of rawRing) {
            if (!p || p.length < 2) continue;
            const q = [Number(p[0]), Number(p[1])];
            if (!Number.isFinite(q[0]) || !Number.isFinite(q[1])) continue;
            if (pts.length && same(pts[pts.length - 1], q)) continue;
            pts.push(q);
        }
        while (pts.length > 1 && same(pts[0], pts[pts.length - 1])) pts.pop();

        const o = pts[0];
        const k = o ? Math.cos(Cesium.Math.toRadians(o[1])) : 1;
        const local = (p) => [(p[0] - o[0]) * k, p[1] - o[1]];
        let changed = true;
        while (changed && pts.length >= 3) {
            changed = false;
            for (let i = 0; i < pts.length && pts.length >= 3; i++) {
                const a = local(pts[(i - 1 + pts.length) % pts.length]);
                const b = local(pts[i]);
                const c = local(pts[(i + 1) % pts.length]);
                const ux = b[0] - a[0], uy = b[1] - a[1];
                const vx = c[0] - b[0], vy = c[1] - b[1];
                const cross = ux * vy - uy * vx;
                const scale = Math.hypot(ux, uy) * Math.hypot(vx, vy);
                if (same(a, c) || Math.abs(cross) <= 1e-9 * scale) {
                    pts.splice(i, 1);
                    changed = true;
                    i--;
                }
            }
        }
        if (pts.length < 3) return null;

        let area2 = 0;
        for (let i = 0; i < pts.length; i++) {
            const a = local(pts[i]);
            const b = local(pts[(i + 1) % pts.length]);
            area2 += a[0] * b[1] - b[0] * a[1];
        }
        if (Math.abs(area2) < eps * eps) return null;

        pts.push([pts[0][0], pts[0][1]]);
        return pts;
    }

    /** Clean every ring of a projected polygon; null if the outer ring is gone. */
    cleanGeoPolygon(rings) {
        const outer = this.cleanGeoRing(rings && rings[0]);
        if (!outer) return null;
        const holes = (rings || []).slice(1).map((r) => this.cleanGeoRing(r)).filter(Boolean);
        return [outer, ...holes];
    }

    /**
     * Ground-clamped polygons draw in 3D but not in 2D or Columbus view, and
     * Cesium drops outlines on clamped polygons. Clamp in 3D; draw flat with
     * an outline in the other modes. Labels sit on the ring's centroid.
     */
    styleResultEntity(entity) {
        const flat = this.viewer.scene.mode !== Cesium.SceneMode.SCENE3D;
        const polygon = entity.polygon;
        if (polygon) {
            polygon.heightReference = flat
                ? Cesium.HeightReference.NONE
                : Cesium.HeightReference.CLAMP_TO_GROUND;
            polygon.height = flat ? 0 : undefined;
            polygon.extrudedHeight = undefined;
            polygon.outline = flat;
            if (entity.label && !entity.position) {
                const ring = polygon.hierarchy.getValue(Cesium.JulianDate.now()).positions;
                if (ring && ring.length) {
                    const sum = ring.reduce((acc, p) => Cesium.Cartesian3.add(acc, p, acc), new Cesium.Cartesian3());
                    const centre = Cesium.Cartesian3.divideByScalar(sum, ring.length, sum);
                    entity.position = Cesium.Ellipsoid.WGS84.scaleToGeodeticSurface(centre, centre) || centre;
                }
            }
        }
        if (entity.label) {
            entity.label.heightReference = flat
                ? Cesium.HeightReference.NONE
                : Cesium.HeightReference.CLAMP_TO_GROUND;
        }
    }

    resultDataSources() {
        return [this.samDataSource, this.sceneGraphDataSource, this.worldDataSource]
            .filter((ds) => ds && this.viewer.dataSources.contains(ds));
    }

    // The models must see the bare globe, not our own polygons on it.
    async captureViewportWithoutOverlays() {
        const hidden = this.resultDataSources().filter((ds) => ds.show);
        hidden.forEach((ds) => { ds.show = false; });
        try {
            if (hidden.length) {
                this.viewer.scene.requestRender();
                this.viewer.scene.render();
                await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
            }
            return await this.captureViewportImage();
        } finally {
            hidden.forEach((ds) => { ds.show = true; });
            this.viewer.scene.requestRender();
        }
    }

    restyleResultsForSceneMode() {
        for (const ds of this.resultDataSources()) {
            ds.entities.values.forEach((entity) => this.styleResultEntity(entity));
        }
    }

    /**
     * Cesium stops its render loop after any exception in a frame. If AI
     * results are on the map, they are the likely cause: remove them and
     * restart rendering instead of leaving a frozen page.
     */
    recoverFromRenderError(error) {
        const now = Date.now();
        if (this._lastRenderRecovery && now - this._lastRenderRecovery < 10000) return;
        const sources = this.resultDataSources();
        if (!sources.length) return;
        this._lastRenderRecovery = now;
        console.error('Render error with AI results on the map; removing them:', error);
        sources.forEach((ds) => this.viewer.dataSources.remove(ds));
        this.samDataSource = null;
        this.sceneGraphDataSource = null;
        this.worldDataSource = null;
        const wmShow = document.getElementById('wmShow');
        if (wmShow) wmShow.checked = false;
        const sgShow = document.getElementById('sgShow');
        if (sgShow) sgShow.checked = false;
        document.querySelectorAll('.cesium-widget-errorPanel').forEach((el) => el.remove());
        this.viewer.useDefaultRenderLoop = true;
        this.viewer.scene.requestRender();
        this.showNotification('AI overlay could not be drawn and was cleared. Rendering resumed.', 'warning');
    }
    
    async runVegetationBootstrap() {
        const promptEl = document.getElementById('vegetationPrompt');
        const thresholdEl = document.getElementById('vegetationBoxThreshold');
        const prompt = promptEl ? promptEl.value.trim() : 'tree. shrub. bush. canopy.';
        const boxThreshold = thresholdEl ? parseFloat(thresholdEl.value) / 100 : 0.3;
        const saveBtn = document.getElementById('vegetationSaveRoundBtn');
        if (saveBtn) saveBtn.disabled = true;
        this.setVegetationStatus('Capturing viewport for vegetation bootstrap...');
        try {
            await this.prepareViewportForAnalysis();
            const viewportData = await this.captureViewportImage();
            const capturePose = viewportData.location;
            this.lastCapturePose = capturePose;
            const annotationContext = {
                game: 'vegetation_bootstrap',
                selected_target: this.vegetationGame.selectedTarget,
                osm_context: this.vegetationGame.osmContext
            };
            this.setVegetationStatus(`Running Grounding DINO prompt: ${prompt}`);
            const response = await fetch('/webclient/sampler/analyze-viewport', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    image: viewportData.image,
                    location: capturePose,
                    model_type: 'grounding_dino',
                    text_prompt: prompt,
                    box_threshold: boxThreshold,
                    text_threshold: 0.25,
                    annotation_context: annotationContext
                })
            });
            const result = await response.json();
            if (!response.ok || result.status !== 'success') {
                throw new Error(result.message || `HTTP ${response.status}`);
            }
            result.capture_pose = capturePose;
            result.world_corners = viewportData.world_corners;
            this.vegetationGame.lastCapture = viewportData;
            this.vegetationGame.lastResult = result;
            this.displayZeroShotResults(result);
            this.renderVegetationProposalList(result);
            if (saveBtn) saveBtn.disabled = false;
            this.setVegetationStatus(`${result.num_detections || 0} proposals. Review, then save.`, 'success');
        } catch (error) {
            console.error('Vegetation bootstrap failed:', error);
            this.setVegetationStatus(`Vegetation bootstrap failed: ${error.message}`, 'error');
        }
    }
    
    renderVegetationProposalList(result) {
        const container = document.getElementById('vegetationProposalList');
        if (!container) return;
        const detections = result.detections || [];
        const features = result.geojson?.features || [];
        if (!detections.length) {
            container.innerHTML = '<small>No proposals found.</small>';
            return;
        }
        container.innerHTML = detections.map((det, index) => {
            const label = (det.class_name || 'tree').toLowerCase().includes('shrub') ? 'shrub' : 'tree';
            const confidence = Number(det.confidence || 0).toFixed(2);
            const feature = features[index] || {};
            const geom = encodeURIComponent(JSON.stringify(feature.geometry || null));
            const proposal = encodeURIComponent(JSON.stringify(det));
            return `
                <div class="vegetation-proposal-row" data-geometry="${geom}" data-proposal="${proposal}">
                    <input type="checkbox" class="veg-accept" checked>
                    <span>${index + 1}. ${det.class_name || 'tree'} ${confidence}</span>
                    <select class="veg-class form-control form-control-sm">
                        <option value="tree" ${label === 'tree' ? 'selected' : ''}>tree</option>
                        <option value="shrub" ${label === 'shrub' ? 'selected' : ''}>shrub</option>
                    </select>
                </div>
            `;
        }).join('');
    }
    
    collectVegetationCorrections() {
        const rows = Array.from(document.querySelectorAll('#vegetationProposalList .vegetation-proposal-row'));
        return rows.map((row) => {
            const accepted = row.querySelector('.veg-accept')?.checked;
            const className = row.querySelector('.veg-class')?.value || 'tree';
            const geometry = JSON.parse(decodeURIComponent(row.dataset.geometry || 'null'));
            const proposal = JSON.parse(decodeURIComponent(row.dataset.proposal || '{}'));
            return {
                status: accepted ? 'accepted' : 'rejected',
                class_name: className,
                geometry,
                proposal
            };
        });
    }
    
    async saveVegetationRound() {
        const capture = this.vegetationGame.lastCapture;
        const result = this.vegetationGame.lastResult;
        if (!capture || !result) {
            this.showNotification('Run vegetation bootstrap before saving', 'warning');
            return;
        }
        const corrections = this.collectVegetationCorrections();
        const prompt = document.getElementById('vegetationPrompt')?.value.trim() || 'tree. shrub. bush. canopy.';
        const taskId = `veg_${Date.now()}`;
        try {
            const response = await fetch('/webclient/sampler/annotation-game/save', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    session_id: this.vegetationGame.sessionId,
                    task_id: taskId,
                    image: capture.image,
                    capture_pose: capture.location,
                    image_size: result.image_size,
                    prompt,
                    osm_context: this.vegetationGame.osmContext || {},
                    proposals: result.detections || [],
                    corrections,
                    metadata: {
                        selected_target: this.vegetationGame.selectedTarget,
                        result_session: result.saved_to?.session_dir,
                        report_url: result.report_url
                    },
                    zoom: this.getCameraZoomLevel()
                })
            });
            const saved = await response.json();
            if (!response.ok || saved.status !== 'success') {
                throw new Error(saved.message || saved.error || `HTTP ${response.status}`);
            }
            if (saved.feedback_point) {
                await this.samplerClient.update({
                    rule: 'reward',
                    feedback_points: [saved.feedback_point],
                    params: {learning_rate: 0.2, radius: 2500},
                    session_id: this.vegetationGame.sessionId
                });
            }
            this.setVegetationStatus(`Saved round ${saved.task_id}; reward ${Number(saved.reward).toFixed(2)} applied to sampler.`, 'success');
            this.showNotification('Vegetation round saved and sampler rewarded', 'success');
            await this.updateStatistics();
        } catch (error) {
            console.error('Failed to save vegetation round:', error);
            this.setVegetationStatus(`Save failed: ${error.message}`, 'error');
        }
    }
    
    async exportVegetationGame(kind) {
        const url = kind === 'graph'
            ? '/webclient/sampler/annotation-game/export-graph'
            : '/webclient/sampler/annotation-game/export-coco';
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({session_id: this.vegetationGame.sessionId})
            });
            const result = await response.json();
            if (!response.ok || result.status !== 'success') {
                throw new Error(result.message || result.error || `HTTP ${response.status}`);
            }
            this.setVegetationStatus(`${kind.toUpperCase()} export written to ${result.export_path}`, 'success');
        } catch (error) {
            console.error(`Failed to export ${kind}:`, error);
            this.setVegetationStatus(`${kind.toUpperCase()} export failed: ${error.message}`, 'error');
        }
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

        // Snapshot the four viewport corners as lon/lat using the camera at the
        // exact moment of capture. We reuse this for projecting AI results back
        // onto the globe later, so the display path never has to move the
        // camera (which is what used to cause the post-Analyze "zoom-out").
        const worldCorners = this.computeViewportCornersGeo();
        this.lastCaptureCorners = worldCorners;

        return {
            image: imageData,
            location: location,
            world_corners: worldCorners
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
        
        // SAM 3 is served by the Ultralytics (yolov8) analyzer.
        const selectedType = analysisTypeSelect ? analysisTypeSelect.value : 'sam';
        const analysisType = selectedType === 'sam3' ? 'yolov8' : selectedType;
        
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
            
            // Drop any prior overlay so the captured image is the raw globe.
            // We don't bother re-adding the old overlay on success: a successful
            // analysis replaces it with new results anyway, and on failure the
            // user can re-run. This saves us the round-trip of removing then
            // re-adding the same data source for nothing.
            if (this.samDataSource && this.viewer.dataSources.contains(this.samDataSource)) {
                this.viewer.dataSources.remove(this.samDataSource);
                console.log('[SAM] Dropped previous overlay for clean viewport capture');
            }

            try {
                this.viewer.scene.requestRender();
                this.viewer.scene.render();

                await new Promise(resolve => setTimeout(resolve, 100));

                const viewportData = await this.captureViewportWithoutOverlays();
                
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
                } else if (selectedType === 'sam3') {
                    const confidence = document.getElementById('sam3Confidence');
                    requestBody.yolo_model = 'sam3';
                    requestBody.confidence_threshold = confidence ? parseFloat(confidence.value) / 100 : 0.3;
                    requestBody.class_filter = document.getElementById('sam3Prompts')?.value.trim() || '';
                    statusText.textContent = 'Running SAM 3 (about 30 s)...';
                } else if (analysisType === 'yolov8') {
                    const yolov8Model = document.getElementById('yolov8ModelType');
                    const yolov8Confidence = document.getElementById('yolov8Confidence');
                    const yolov8Classes = document.getElementById('yolov8Classes');
                    requestBody.yolo_model = yolov8Model ? yolov8Model.value : 'yolo26x-seg';
                    requestBody.confidence_threshold = yolov8Confidence ? parseFloat(yolov8Confidence.value) / 100 : 0.25;
                    requestBody.class_filter = yolov8Classes ? yolov8Classes.value.trim() : '';
                    statusText.textContent = 'Running YOLO detection...';
                } else if (analysisType === 'grounding_dino') {
                    const textPrompt = document.getElementById('groundingDinoPrompt');
                    const boxThreshold = document.getElementById('gdBoxThreshold');
                    const textThreshold = document.getElementById('gdTextThreshold');
                    requestBody.text_prompt = textPrompt ? textPrompt.value.trim() : 'object';
                    requestBody.box_threshold = boxThreshold ? parseFloat(boxThreshold.value) / 100 : 0.3;
                    requestBody.text_threshold = textThreshold ? parseFloat(textThreshold.value) / 100 : 0.25;
                    statusText.textContent = 'Running Grounding DINO detection...';
                } else if (analysisType === 'maskrcnn_rocks') {
                    const modelIdEl = document.getElementById('maskrcnnRocksModelId');
                    const scoreEl = document.getElementById('maskrcnnRocksScore');
                    const maxDetEl = document.getElementById('maskrcnnRocksMaxDet');
                    const modelId = modelIdEl ? modelIdEl.value.trim() : '';
                    if (modelId) requestBody.model_id = modelId;
                    requestBody.score_threshold = scoreEl ? parseFloat(scoreEl.value) / 100 : 0.5;
                    requestBody.max_detections = maxDetEl ? parseInt(maxDetEl.value, 10) || 200 : 200;
                    statusText.textContent = `Running MaskRCNN Rocks${modelId ? ' (' + modelId + ')' : ''}...`;
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

                // A dead remote model is HTTP 200 with status success and an
                // empty collection. message includes the service URL, so the
                // panel shows the reason code instead.
                if (result.degraded) {
                    const reasonText = {
                        not_configured: 'is not configured',
                        connection_error: 'is unreachable',
                        timeout: 'timed out',
                        weights_missing: 'needs its weights file',
                    }[result.unavailable_reason] || 'is unavailable';
                    const unavailable = `${selectedType} ${reasonText}`;
                    statusText.textContent = result.suggestion
                        ? `${unavailable}. ${result.suggestion}`
                        : unavailable;
                    statusText.style.color = '#f59e0b';
                    this.showNotification(unavailable, 'warning');
                    return;
                }
                
                // Show device info
                const deviceInfo = result.device_info || {};
                const deviceText = deviceInfo.cuda_available 
                    ? `GPU: ${deviceInfo.gpu_name || 'CUDA'}` 
                    : (deviceInfo.mode === 'remote_api' ? 'GPU service' : 'CPU');
                
                // Handle results based on analysis type
                if (analysisType !== 'sam') {
                    const numDetections = result.num_detections || 0;
                    statusText.textContent = `✓ Found ${numDetections} objects (${deviceText})`;
                    statusText.style.color = '#10b981';
                    
                    // Display results (all detection models use same display method)
                    result.capture_pose = capturePose;
                    result.world_corners = viewportData.world_corners;
                    this.displayZeroShotResults(result);
                    
                    // Show notification
                    const deviceNote = deviceInfo.mode === 'remote_api' ? ' (Remote GPU)' : (deviceInfo.cuda_available ? ' (GPU)' : ' (CPU)');
                    let modelName = 'Detection';
                    if (selectedType === 'sam3') {
                        modelName = 'SAM 3';
                    } else if (analysisType === 'yolov8') {
                        modelName = `YOLO (${result.yolo_model || 'yolo26x-seg'})`;
                    } else if (analysisType === 'grounding_dino') {
                        modelName = 'Grounding DINO';
                    } else if (analysisType === 'maskrcnn_rocks') {
                        modelName = `MaskRCNN Rocks (${result.model_id || 'default'})`;
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
                    result.world_corners = viewportData.world_corners;
                    this.displaySAMResults(result);
                    
                    // Show notification
                    const deviceNote = deviceInfo.mode === 'remote_api' ? ' (Remote GPU)' : (deviceInfo.cuda_available ? ' (GPU)' : ' (CPU)');
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
     * Display SAM segmentation results on Cesium map
     * @param {Object} result - SAM analysis result
     */
    displaySAMResults(result) {
        if (!result.geojson || !result.geojson.features) {
            console.warn('No GeoJSON features in SAM results');
            return;
        }

        if (this.samDataSource) {
            this.viewer.dataSources.remove(this.samDataSource);
        }

        // Project results using the corner snapshot taken at capture time, so
        // we never have to move the camera during display.
        const corners = result.world_corners || this.lastCaptureCorners || null;
        if (!corners) {
            console.warn('No viewport corner snapshot available; falling back to approximate projection');
            this.displaySAMResultsApproximate(result);
            return;
        }

        const pixelToGeographic = (x_norm, y_norm) =>
            this.bilinearProjectFromCorners(corners, x_norm, y_norm);

        this.samDataSource = new Cesium.GeoJsonDataSource('SAM Segments');

        const features = result.geojson.features.map((feature, index) => {
            const props = feature.properties;
            const coords = feature.geometry.coordinates[0];
            const geographicCoords = this.cleanGeoRing(coords.map(([x_norm, y_norm]) =>
                pixelToGeographic(x_norm, y_norm)
            ).filter(Boolean));
            if (!geographicCoords) return null;

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
        }).filter(Boolean);

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
                    entity.polygon.outlineColor = Cesium.Color.WHITE.withAlpha(0.8);
                    entity.polygon.outlineWidth = 2;
                    this.styleResultEntity(entity);
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

            const avgIoU = features.length
                ? features.reduce((sum, f) => sum + (f.properties.predicted_iou || 0), 0) / features.length
                : 0;
            this.showNotification(
                `SAM: ${result.num_segments} segments displayed (avg quality: ${avgIoU.toFixed(2)})`,
                'success'
            );
        }).catch(error => {
            console.error('Error loading SAM GeoJSON:', error);
            this.showNotification('Error displaying SAM results on map', 'error');
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
            const geographicCoords = this.cleanGeoRing(coords.map(([x_norm, y_norm]) => {
                const pixelX = (x_norm - 0.5) * viewportWidth;
                const pixelY = (y_norm - 0.5) * viewportHeight;
                const lonOffset = pixelX * degreesPerPixel;
                const latOffset = -pixelY * degreesPerPixel;
                return [centerLon + lonOffset, centerLat + latOffset];
            }));
            if (!geographicCoords) return null;
            
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
        }).filter(Boolean);
        
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
                    entity.polygon.outlineColor = Cesium.Color.WHITE.withAlpha(0.8);
                    entity.polygon.outlineWidth = 2;
                    this.styleResultEntity(entity);
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

        if (this.samDataSource) {
            this.viewer.dataSources.remove(this.samDataSource);
        }

        // Project results using the corner snapshot taken at capture time, so
        // we never have to move the camera during display.
        const corners = result.world_corners || this.lastCaptureCorners || null;
        if (!corners) {
            console.warn('No viewport corner snapshot available; falling back to approximate projection');
            this.displayZeroShotResultsApproximate(result);
            return;
        }

        const pixelToGeographic = (x_norm, y_norm) =>
            this.bilinearProjectFromCorners(corners, x_norm, y_norm);

        this.samDataSource = new Cesium.GeoJsonDataSource('Zero-Shot Detections');

        {
            const features = result.geojson.features.map((feature, index) => {
                const props = feature.properties;
                const geom = feature.geometry;

                // Transform ALL rings in the polygon (exterior + holes)
                // coordinates structure: [ [exterior_ring], [hole1], [hole2], ... ]
                const transformedCoords = this.cleanGeoPolygon(geom.coordinates.map(ring =>
                    ring.map(([x_norm, y_norm]) => pixelToGeographic(x_norm, y_norm))
                        .filter(Boolean)
                ));
                if (!transformedCoords) return null;

                if (index === 0 && transformedCoords[0] && transformedCoords[0][0]) {
                    console.log('🔍 First entity coordinates:', {
                        firstPoint: transformedCoords[0][0],
                        numRings: transformedCoords.length,
                        ringLength: transformedCoords[0].length
                    });
                }

                return {
                    type: 'Feature',
                    geometry: {
                        type: 'Polygon',
                        coordinates: transformedCoords
                    },
                    properties: { ...props }
                };
            }).filter(Boolean);

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
                        const hasMask = props.has_mask?.getValue() || false;  // Check if using segmentation mask
                        
                        // Get color for this class
                        const baseColor = classColors[className.toLowerCase()] || Cesium.Color.fromHsl(
                            (index * 137.508) % 360 / 360, 0.7, 0.5
                        );
                        
                        // Make opacity based on confidence (higher confidence = more opaque)
                        // Segmentation masks get slightly higher opacity for better visibility
                        const baseOpacity = hasMask ? 0.4 : 0.3;
                        const opacity = baseOpacity + (confidence * 0.4);
                        const color = baseColor.withAlpha(opacity);
                        
                        // Style the polygon (segmentation mask or bounding box)
                        if (entity.polygon) {
                            entity.polygon.material = color;
                            // Segmentation masks get thicker, brighter outlines
                            entity.polygon.outlineColor = hasMask 
                                ? baseColor.withAlpha(1.0)  // Full opacity for mask outlines
                                : baseColor.withAlpha(0.8); // Slightly dimmer for bbox outlines
                            entity.polygon.outlineWidth = hasMask ? 4 : 3;  // Thicker outline for masks
                        }
                        
                        // Enhanced label with ID number, class name, and confidence
                        // Add indicator for segmentation masks
                        const labelPrefix = hasMask ? '🎯' : '▫️';
                        entity.label = {
                            text: `${labelPrefix} #${detectionId}: ${className} (${(confidence * 100).toFixed(0)}%)`,
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
                        this.styleResultEntity(entity);
                        
                        // Enhanced description popup with segmentation indicator
                        const segmentationType = hasMask 
                            ? '<span style="background: rgba(16, 185, 129, 0.3); padding: 2px 8px; border-radius: 4px;">🎯 Pixel-precise Segmentation</span>'
                            : '<span style="background: rgba(255, 152, 0, 0.3); padding: 2px 8px; border-radius: 4px;">▫️ Bounding Box</span>';
                        
                        entity.description = `
                            <div style="padding: 8px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 8px;">
                                <h4 style="margin: 0 0 10px 0; color: white; font-size: 16px;">
                                    Detection #${detectionId}
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
                                    <tr>
                                        <td style="padding: 6px; font-weight: bold;">Type:</td>
                                        <td style="padding: 6px;">${segmentationType}</td>
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
                    }
                });

                this.viewer.dataSources.add(this.samDataSource);
                console.log(`✅ Displayed ${entities.length} Zero-Shot detections on map`);
            }).catch(error => {
                console.error('Error loading Zero-Shot GeoJSON:', error);
            });
        }
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
            const geom = feature.geometry;
            
            // Transform ALL rings in the polygon (exterior + holes)
            const transformedCoords = this.cleanGeoPolygon(geom.coordinates.map(ring => 
                ring.map(([x_norm, y_norm]) => {
                    const lon = Cesium.Math.toDegrees(position.longitude) + (x_norm - 0.5) * viewportWidth * degreesPerPixel;
                    const lat = Cesium.Math.toDegrees(position.latitude) + (0.5 - y_norm) * viewportHeight * degreesPerPixel;
                    return [lon, lat];
                })
            ));
            if (!transformedCoords) return null;
            
            return {
                type: 'Feature',
                geometry: {
                    type: 'Polygon',
                    coordinates: transformedCoords  // Preserve all rings
                },
                properties: {
                    ...props  // Use backend properties as-is
                }
            };
        }).filter(Boolean);
        
        const convertedGeoJSON = { type: 'FeatureCollection', features: features };
        
        this.samDataSource.load(convertedGeoJSON).then(() => {
            const entities = this.samDataSource.entities.values;
            entities.forEach((entity, index) => {
                try {
                    const props = entity.properties;
                    const detectionId = props.detection_id?.getValue() || (index + 1);
                    const className = props.class_name?.getValue() || 'unknown';
                    const confidence = props.confidence?.getValue() || 0.0;
                    const hasMask = props.has_mask?.getValue() || false;
                    
                    const hue = (index * 137.508) % 360;
                    const baseColor = Cesium.Color.fromHsl(hue / 360, 0.7, 0.5);
                    const baseOpacity = hasMask ? 0.4 : 0.3;
                    const opacity = baseOpacity + (confidence * 0.4);
                    const color = baseColor.withAlpha(opacity);
                    
                    if (entity.polygon) {
                        entity.polygon.material = color;
                        entity.polygon.outlineColor = hasMask 
                            ? baseColor.withAlpha(1.0)
                            : baseColor.withAlpha(0.8);
                        entity.polygon.outlineWidth = hasMask ? 4 : 3;
                    }
                    
                    // Enhanced label with ID number and mask indicator
                    const labelPrefix = hasMask ? '🎯' : '▫️';
                    entity.label = {
                        text: `${labelPrefix} #${detectionId}: ${className} (${(confidence * 100).toFixed(0)}%)`,
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
                    this.styleResultEntity(entity);
                    
                    // Enhanced description popup with mask indicator
                    const segmentationType = hasMask 
                        ? '<span style="background: rgba(16, 185, 129, 0.3); padding: 2px 8px; border-radius: 4px;">🎯 Pixel-precise Segmentation</span>'
                        : '<span style="background: rgba(255, 152, 0, 0.3); padding: 2px 8px; border-radius: 4px;">▫️ Bounding Box</span>';
                    
                    entity.description = `
                        <div style="padding: 8px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 8px;">
                            <h4 style="margin: 0 0 10px 0; color: white; font-size: 16px;">
                                Detection #${detectionId}
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
                                <tr>
                                    <td style="padding: 6px; font-weight: bold;">Type:</td>
                                    <td style="padding: 6px;">${segmentationType}</td>
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

    /**
     * Distinction-Game SceneGraph orchestrator client.
     *
     * Captures the current viewport once, then for each kernel checked in
     * the SceneGraph panel runs the existing /webclient/sampler/analyze-viewport
     * endpoint with the same image. The per-kernel results plus the
     * checked OSM ground-truth sources are POSTed to
     * /webclient/sampler/scenegraph/build, which calls
     * kernelcal.distinction_game.build_scene_graph under urban_v1, returns
     * the fused SceneGraph and ingests it into the world model. The nodes
     * are rendered as polygons coloured by argmax category (with posterior
     * score driving opacity), and the strongest edges as lines between them.
     */
    async buildSceneGraph() {
        const statusDiv = document.getElementById('sceneGraphStatus');
        const statusText = document.getElementById('sceneGraphStatusText');
        const btn = document.getElementById('buildSceneGraphBtn');
        if (!btn) return;

        const setStatus = (msg, color) => {
            if (statusDiv) statusDiv.style.display = 'block';
            if (statusText) {
                statusText.textContent = msg;
                statusText.style.color = color || '#cbd5e1';
            }
        };

        const kernelChecks = [
            { id: 'sgKernelSam3',          kind: 'sam3',           analysis: 'yolov8',         label: 'SAM 3' },
            { id: 'sgKernelYolo',          kind: 'yolov8',         analysis: 'yolov8',         label: 'YOLOE' },
            { id: 'sgKernelGroundingDino', kind: 'grounding_dino', analysis: 'grounding_dino', label: 'Grounding DINO' },
            { id: 'sgKernelSam',           kind: 'sam',            analysis: 'sam',            label: 'SAM' },
            { id: 'sgKernelMrRocks',       kind: 'maskrcnn_rocks', analysis: 'maskrcnn_rocks', label: 'Rocks' },
        ];
        const selectedKernels = kernelChecks.filter((k) => {
            const el = document.getElementById(k.id);
            return el && el.checked;
        });
        const prompts = (document.getElementById('sgPrompts')?.value || '')
            .split(',').map((s) => s.trim()).filter(Boolean);
        if (!prompts.length) {
            prompts.push('building', 'house', 'tree', 'grass', 'car', 'swimming pool', 'road', 'parking lot', 'solar panel');
        }

        const gtSources = [];
        if (document.getElementById('sgGtOsmBuildings')?.checked) gtSources.push('osm_buildings');
        if (document.getElementById('sgGtOsmRoads')?.checked)     gtSources.push('osm_roads');

        if (selectedKernels.length === 0 && gtSources.length === 0) {
            setStatus('Tick at least one model.', '#f59e0b');
            return;
        }

        btn.disabled = true;
        try {
            setStatus('Preparing viewport...');
            await this.prepareViewportForAnalysis(statusText);
            this.viewer.scene.requestRender();
            this.viewer.scene.render();
            await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

            setStatus('Capturing viewport...');
            const viewportData = await this.captureViewportWithoutOverlays();
            const corners = viewportData.world_corners;
            if (!corners) {
                throw new Error('Could not snapshot viewport corners (camera off-globe?).');
            }
            // Mirror computeViewportCornersGeo() output into the
            // [NW, NE, SE, SW] array the orchestrator expects.
            const cornersArr = [
                [corners.tl.lon, corners.tl.lat],
                [corners.tr.lon, corners.tr.lat],
                [corners.br.lon, corners.br.lat],
                [corners.bl.lon, corners.bl.lat],
            ];
            const canvas = this.viewer.scene.canvas;
            const imageSize = [canvas.width, canvas.height];

            const kernelResults = {};
            const degradedKernels = [];
            for (let i = 0; i < selectedKernels.length; i++) {
                const k = selectedKernels[i];
                setStatus(`(${i + 1}/${selectedKernels.length}) Running ${k.label}...`);
                try {
                    const reqBody = {
                        image: viewportData.image,
                        location: viewportData.location,
                        model_type: k.analysis,
                    };
                    if (k.analysis === 'sam') {
                        const minAreaEl = document.getElementById('samMinArea');
                        reqBody.sam_model = document.getElementById('samModelType')?.value || 'vit_b';
                        reqBody.min_area = minAreaEl ? parseInt(minAreaEl.value, 10) || 100 : 100;
                    } else if (k.analysis === 'grounding_dino') {
                        reqBody.text_prompt = prompts.join(' . ');
                        reqBody.box_threshold = parseFloat(document.getElementById('gdBoxThreshold')?.value || 30) / 100;
                        reqBody.text_threshold = parseFloat(document.getElementById('gdTextThreshold')?.value || 25) / 100;
                    } else if (k.analysis === 'maskrcnn_rocks') {
                        const modelId = document.getElementById('maskrcnnRocksModelId')?.value?.trim();
                        if (modelId) reqBody.model_id = modelId;
                        reqBody.score_threshold = parseFloat(document.getElementById('maskrcnnRocksScore')?.value || 50) / 100;
                        reqBody.max_detections = parseInt(document.getElementById('maskrcnnRocksMaxDet')?.value || 200, 10);
                    } else if (k.kind === 'sam3') {
                        reqBody.yolo_model = 'sam3';
                        reqBody.confidence_threshold = 0.3;
                        reqBody.class_filter = prompts.join(', ');
                    } else if (k.kind === 'yolov8') {
                        reqBody.yolo_model = 'yoloe-26l-seg';
                        reqBody.confidence_threshold = 0.25;
                        reqBody.class_filter = prompts.join(', ');
                    }
                    const r = await fetch('/webclient/sampler/analyze-viewport', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(reqBody),
                    });
                    if (!r.ok) {
                        console.warn(`[SceneGraph] ${k.kind} HTTP ${r.status}`);
                        degradedKernels.push(k.label);
                        kernelResults[k.kind] = {};
                        continue;
                    }
                    const result = await r.json();
                    if (result && result.degraded) {
                        console.warn(`[SceneGraph] ${k.kind} unavailable:`, result.unavailable_reason);
                        degradedKernels.push(k.label);
                        kernelResults[k.kind] = {};
                    } else if (result && result.status === 'success') {
                        kernelResults[k.kind] = result;
                    } else {
                        console.warn(`[SceneGraph] ${k.kind} non-success:`, result?.message);
                        degradedKernels.push(k.label);
                        kernelResults[k.kind] = {};
                    }
                } catch (err) {
                    console.warn(`[SceneGraph] ${k.kind} threw:`, err);
                    degradedKernels.push(k.label);
                    kernelResults[k.kind] = {};
                }
            }

            // OSM road-graph regions: the orchestrator builds a kernelcal
            // CityGraph for this bbox and splices its street-aware adjacency
            // into the scene graph.
            const useCityGraph = !!document.getElementById('sgUseCityGraph')?.checked;
            const graphMode = 'road_knn';

            // Every source has Q_s under urban_v1 (older kernels are lifted),
            // so the panel always builds there and the world model stays in
            // one taxonomy.
            const taxonomyName = 'urban_v1';
            setStatus('Merging model outputs...');
            const buildBody = {
                viewport: {
                    image_size: imageSize,
                    world_corners: cornersArr,
                    camera: viewportData.location,
                },
                kernel_results: kernelResults,
                ground_truth_sources: gtSources,
                taxonomy: taxonomyName,
                min_score: 0.2,
                iou_threshold: 0.4,
                edge_proximity: 0.06,
                use_city_graph_regions: useCityGraph,
                graph_mode: graphMode,
            };
            const buildResp = await fetch('/webclient/sampler/scenegraph/build', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(buildBody),
            });
            if (!buildResp.ok) {
                const errBody = await buildResp.text();
                throw new Error(`SceneGraph build failed (${buildResp.status}): ${errBody.substring(0, 200)}`);
            }
            const built = await buildResp.json();
            if (!built || built.status !== 'success') {
                throw new Error(built?.message || 'SceneGraph build returned non-success');
            }

            this.currentSceneGraph = built.scene_graph;
            this.currentSceneGraphCorners = corners;
            const sgShow = document.getElementById('sgShow');
            if (sgShow) sgShow.checked = true;
            this.displaySceneGraph(built.scene_graph, corners);

            const nNodes = built.scene_graph?.nodes?.length || 0;
            const hist = built.scene_graph?.category_histogram || {};
            const histStr = Object.entries(hist)
                .filter(([, v]) => v > 0)
                .sort((a, b) => b[1] - a[1])
                .map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`)
                .join(', ') || 'nothing recognised';
            const fmeta = built.scene_graph?.fusion_metadata || {};
            let cgTail = '';
            if (fmeta.use_city_graph_regions) {
                cgTail = fmeta.city_graph_warning
                    ? ` OSM: ${fmeta.city_graph_warning}.`
                    : ` OSM added ${fmeta.n_road_edges_added || 0} road links.`;
            }
            const wu = built.world_update || {};
            let worldTail = '';
            if (wu.status === 'error') {
                worldTail = ' World model not updated.';
            } else if (wu.n_matched !== undefined) {
                worldTail = ` World model: ${wu.n_matched} matched, ${wu.n_new_entities || 0} new`
                    + `${wu.n_missed ? `, ${wu.n_missed} not seen again` : ''}.`;
            }
            const degTail = degradedKernels.length
                ? ` Unavailable: ${degradedKernels.join(', ')}.`
                : '';
            setStatus(
                `✓ ${nNodes} objects: ${histStr}.${worldTail}${cgTail}${degTail}`,
                degradedKernels.length || wu.status === 'error' ? '#f59e0b' : '#10b981'
            );
            this.showNotification(
                degradedKernels.length
                    ? `Scene graph built: ${nNodes} objects. Unavailable: ${degradedKernels.join(', ')}`
                    : `Scene graph built: ${nNodes} objects`,
                degradedKernels.length ? 'warning' : 'success'
            );
            if (this.worldDataSource) this.refreshWorldModel();
        } catch (err) {
            console.error('[SceneGraph] build failed:', err);
            setStatus(`✗ ${err.message || err}`, '#ef4444');
            this.showNotification(`SceneGraph build failed: ${err.message || err}`, 'error');
        } finally {
            btn.disabled = false;
        }
    }

    /**
     * Render a fused SceneGraph onto the globe. Each node becomes a
     * filled polygon coloured by argmax category, with posterior score
     * driving opacity. Geographic geometry is preferred (region.geo_polygon)
     * but the normalised polygon is projected via the captured corners as
     * a fallback so this works even for non-georeferenced kernels.
     */
    displaySceneGraph(sceneGraph, capturedCorners) {
        return this.displaySceneGraphDataSource(
            sceneGraph,
            capturedCorners,
            'SceneGraph',
            'sceneGraphDataSource',
        );
    }

    categoryColor(category) {
        const colorByCategory = {
            unknown:           Cesium.Color.GRAY,
            building:          Cesium.Color.fromCssColorString('#3b82f6'), // blue
            house:             Cesium.Color.fromCssColorString('#a855f7'), // purple
            solar_panel:       Cesium.Color.fromCssColorString('#1e3a8a'), // navy
            road:              Cesium.Color.fromCssColorString('#facc15'), // yellow
            parking_lot:       Cesium.Color.fromCssColorString('#e5e7eb'), // light gray
            pool:              Cesium.Color.fromCssColorString('#38bdf8'), // sky blue
            vehicle:           Cesium.Color.fromCssColorString('#ef4444'), // red
            tree:              Cesium.Color.fromCssColorString('#16a34a'), // green
            vegetation_other:  Cesium.Color.fromCssColorString('#84cc16'), // lime
            pavement:          Cesium.Color.fromCssColorString('#a3a3a3'), // gray
            bare_ground:       Cesium.Color.fromCssColorString('#a16207'), // brown
            water:             Cesium.Color.fromCssColorString('#06b6d4'), // cyan
            debris:            Cesium.Color.fromCssColorString('#f97316'), // orange
        };
        return colorByCategory[category] || Cesium.Color.WHITE;
    }

    displaySceneGraphDataSource(sceneGraph, capturedCorners, dataSourceName, dataSourceProp) {
        if (!sceneGraph || !sceneGraph.nodes) return Promise.resolve(null);
        this.hideSceneGraph();
        const ds = new Cesium.GeoJsonDataSource(dataSourceName || 'SceneGraph');
        const cleanRing = (rawRing) => this.cleanGeoRing(rawRing);

        const features = [];
        const centroids = new Map();
        for (const node of sceneGraph.nodes) {
            const region = node.region || {};
            let ring = null;
            if (region.geo_polygon && region.geo_polygon.length >= 3) {
                ring = region.geo_polygon.map((p) => [p[0], p[1]]);
            } else if (region.polygon && region.polygon.length >= 3 && capturedCorners) {
                ring = region.polygon
                    .map((p) => this.bilinearProjectFromCorners(capturedCorners, p[0], p[1]))
                    .filter(Boolean);
            }
            ring = cleanRing(ring);
            if (!ring) continue;
            const verts = ring.slice(0, -1);
            centroids.set(node.id, [
                verts.reduce((s, p) => s + p[0], 0) / verts.length,
                verts.reduce((s, p) => s + p[1], 0) / verts.length,
            ]);
            features.push({
                type: 'Feature',
                geometry: { type: 'Polygon', coordinates: [ring] },
                properties: {
                    node_id: node.id,
                    category: node.category,
                    score: node.score,
                    sources: node.sources || [],
                    n_claims: (node.attributes || {}).n_claims || 0,
                    n_distinct_sources: (node.attributes || {}).n_distinct_sources || 0,
                },
            });
        }

        if (features.length === 0) {
            console.warn('[SceneGraph] no renderable nodes');
            return Promise.resolve(null);
        }
        const fc = { type: 'FeatureCollection', features };
        return ds.load(fc).then(() => {
            const entities = ds.entities.values;
            entities.forEach((entity) => {
                const props = entity.properties;
                const category = props.category?.getValue() || 'unknown';
                const score = props.score?.getValue() || 0.5;
                const nSources = props.n_distinct_sources?.getValue() || 1;
                const sourcesArr = props.sources?.getValue() || [];
                const baseColor = this.categoryColor(category);
                const opacity = 0.25 + Math.min(0.6, score * 0.6);
                if (entity.polygon) {
                    entity.polygon.material = baseColor.withAlpha(opacity);
                    entity.polygon.outlineColor = baseColor.withAlpha(0.95);
                    entity.polygon.outlineWidth = 1 + nSources;
                }
                entity.label = {
                    text: `${category} ${(score * 100).toFixed(0)}% [${sourcesArr.join(',')}]`,
                    font: 'bold 12px sans-serif',
                    fillColor: Cesium.Color.WHITE,
                    outlineColor: Cesium.Color.BLACK,
                    outlineWidth: 2,
                    style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                    verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                    pixelOffset: new Cesium.Cartesian2(0, -10),
                    showBackground: true,
                    backgroundColor: Cesium.Color.BLACK.withAlpha(0.55),
                    backgroundPadding: new Cesium.Cartesian2(6, 3),
                    disableDepthTestDistance: Number.POSITIVE_INFINITY,
                };
                this.styleResultEntity(entity);
            });
            if (document.getElementById('sgShowLinks')?.checked !== false) {
                this.addSceneGraphLinks(ds, sceneGraph.edges || [], centroids);
            }
            this[dataSourceProp || 'sceneGraphDataSource'] = ds;
            this.viewer.dataSources.add(ds);
            console.log(`[${dataSourceName || 'SceneGraph'}] rendered ${entities.length} nodes`);
            return ds;
        }).catch((err) => {
            console.error('[SceneGraph] failed to load GeoJSON:', err);
            return null;
        });
    }

    // Graphs carry thousands of adjacency edges; drawing them all hides the
    // objects, so keep each node's strongest few.
    addSceneGraphLinks(ds, edges, centroids, { perNode = 3, minWeight = 0.2, maxLinks = 400 } = {}) {
        const candidates = edges
            .filter((e) => centroids.has(e.source) && centroids.has(e.target)
                && e.source !== e.target && (e.weight ?? 1) >= minWeight)
            .sort((a, b) => (b.weight ?? 1) - (a.weight ?? 1));
        const degree = new Map();
        const seen = new Set();
        let n = 0;
        for (const e of candidates) {
            if (n >= maxLinks) break;
            const key = e.source < e.target ? `${e.source}|${e.target}` : `${e.target}|${e.source}`;
            if (seen.has(key)) continue;
            if ((degree.get(e.source) || 0) >= perNode || (degree.get(e.target) || 0) >= perNode) continue;
            seen.add(key);
            degree.set(e.source, (degree.get(e.source) || 0) + 1);
            degree.set(e.target, (degree.get(e.target) || 0) + 1);
            const w = Math.min(1, e.weight ?? 1);
            const color = e.relation === 'adjacent' ? Cesium.Color.WHITE : Cesium.Color.fromCssColorString('#facc15');
            const [a, b] = [centroids.get(e.source), centroids.get(e.target)];
            ds.entities.add({
                polyline: {
                    positions: Cesium.Cartesian3.fromDegreesArray([a[0], a[1], b[0], b[1]]),
                    width: 2 + 2 * w,
                    material: color.withAlpha(0.45 + 0.5 * w),
                    clampToGround: true,
                },
                properties: { relation: e.relation, weight: e.weight },
            });
            n++;
        }
        return n;
    }

    hideSceneGraph() {
        if (this.sceneGraphDataSource && this.viewer.dataSources.contains(this.sceneGraphDataSource)) {
            this.viewer.dataSources.remove(this.sceneGraphDataSource);
        }
        this.sceneGraphDataSource = null;
        if (this.viewer?.scene) {
            this.viewer.scene.requestRender();
        }
    }

    setSceneGraphViewportVisible(visible) {
        if (visible) {
            if (this.currentSceneGraph) {
                this.displaySceneGraph(this.currentSceneGraph, this.currentSceneGraphCorners);
            } else {
                const sgShow = document.getElementById('sgShow');
                if (sgShow) sgShow.checked = false;
                this.showNotification('No scene graph yet. Build one first.', 'info');
            }
        } else {
            this.hideSceneGraph();
        }
    }

    // ---- World model (/webclient/sampler/world/*, apps/scene_store) ----

    worldCategories(taxonomy) {
        if (taxonomy === 'phx_urban_v0') {
            return ['unknown', 'building', 'road', 'vehicle', 'tree', 'vegetation_other',
                'pavement', 'bare_ground', 'water', 'debris'];
        }
        return ['unknown', 'building', 'house', 'solar_panel', 'road', 'vehicle', 'pavement',
            'parking_lot', 'tree', 'vegetation_other', 'bare_ground', 'water', 'pool', 'debris'];
    }

    setWorldStatus(message, color) {
        const el = document.getElementById('wmStatus');
        if (!el) return;
        el.textContent = message;
        el.style.color = color || '#94a3b8';
    }

    worldViewBbox() {
        const rect = this.viewer.camera.computeViewRectangle(this.viewer.scene.globe.ellipsoid);
        if (!rect) return null;
        const deg = Cesium.Math.toDegrees;
        return [deg(rect.west), deg(rect.south), deg(rect.east), deg(rect.north)];
    }

    worldAtParam() {
        const hours = document.getElementById('wmAt')?.value;
        if (hours === undefined || hours === '') return null;
        return new Date(Date.now() + parseFloat(hours) * 3600 * 1000).toISOString();
    }

    async setWorldModelVisible(visible) {
        if (!this._worldCameraListener) {
            let timer = null;
            this._worldCameraListener = this.viewer.camera.moveEnd.addEventListener(() => {
                if (!this.worldDataSource) return;
                clearTimeout(timer);
                timer = setTimeout(() => this.refreshWorldModel(), 400);
            });
            this.installWorldPickHandler();
        }
        if (visible) {
            await this.refreshWorldModel();
        } else {
            this.hideWorldModel();
            this.setWorldStatus('');
        }
    }

    hideWorldModel() {
        if (this.worldDataSource && this.viewer.dataSources.contains(this.worldDataSource)) {
            this.viewer.dataSources.remove(this.worldDataSource);
        }
        this.worldDataSource = null;
        this.worldEntities.clear();
        this.selectWorldEntity(null);
        this.viewer.scene.requestRender();
    }

    async refreshWorldModel() {
        const bbox = this.worldViewBbox();
        if (!bbox) {
            this.setWorldStatus('Point the camera at the ground to see the world model.', '#f59e0b');
            return;
        }
        if ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) > 0.05 * 0.05) {
            await this.renderWorldEntities([]);
            this.setWorldStatus('Zoom in to see the world model (view is larger than about 5 km).', '#f59e0b');
            return;
        }
        const params = new URLSearchParams({ bbox: bbox.map((v) => v.toFixed(6)).join(','), min_p_exists: '0.05' });
        const at = this.worldAtParam();
        if (at) params.set('at', at);
        const seq = (this._worldSeq = (this._worldSeq || 0) + 1);
        this.setWorldStatus('Loading...');
        try {
            const resp = await fetch(`/webclient/sampler/world/entities?${params}`);
            const payload = await resp.json().catch(() => ({}));
            if (seq !== this._worldSeq) return;
            if (!resp.ok || payload.status !== 'success') {
                throw new Error(payload.message || `HTTP ${resp.status}`);
            }
            const viewArea = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]);
            const shown = await this.renderWorldEntities(payload.entities || [], viewArea);
            const hidden = (payload.entities || []).length - shown.length;
            if (!shown.length && !hidden) {
                this.setWorldStatus('Nothing remembered here yet. Build a scene graph to add objects.');
                return;
            }
            const counts = {};
            shown.forEach((e) => { counts[e.category] = (counts[e.category] || 0) + 1; });
            const kinds = Object.entries(counts).sort((a, b) => b[1] - a[1]);
            const top = kinds.slice(0, 4).map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`).join(', ');
            this.setWorldStatus(`${shown.length} objects in view: ${top}${kinds.length > 4 ? ' and more' : ''}.`
                + `${hidden ? ` ${hidden} view-sized regions hidden.` : ''}`);
        } catch (err) {
            if (seq !== this._worldSeq) return;
            console.error('[WorldModel] load failed:', err);
            this.setWorldStatus(`World model unavailable: ${err.message || err}`, '#ef4444');
        }
    }

    // Regions bigger than a quarter of the view are whole-frame claims from
    // oblique captures; drawing them would cover everything else.
    async renderWorldEntities(entities, viewArea) {
        const ringArea = (r) => {
            let a = 0;
            for (let i = 0; i < r.length - 1; i++) a += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1];
            return Math.abs(a / 2);
        };
        const features = [];
        const byId = new Map();
        for (const e of entities) {
            const ring = this.cleanGeoRing(e.geo_polygon);
            if (!ring || (viewArea && ringArea(ring) > 0.25 * viewArea)) continue;
            byId.set(e.id, e);
            features.push({
                type: 'Feature',
                geometry: { type: 'Polygon', coordinates: [ring] },
                properties: { world_entity_id: e.id },
            });
        }
        const ds = new Cesium.GeoJsonDataSource('World model');
        await ds.load({ type: 'FeatureCollection', features });
        ds.entities.values.forEach((entity) => {
            const e = byId.get(entity.properties.world_entity_id.getValue());
            if (!entity.polygon || !e) return;
            const color = this.categoryColor(e.category);
            entity.polygon.material = color.withAlpha(0.1 + 0.55 * e.p_exists);
            entity.polygon.outlineColor = color.withAlpha(0.35 + 0.6 * e.p_exists);
            this.styleResultEntity(entity);
        });
        if (this.worldDataSource && this.viewer.dataSources.contains(this.worldDataSource)) {
            this.viewer.dataSources.remove(this.worldDataSource);
        }
        this.worldDataSource = ds;
        this.worldEntities = byId;
        this.viewer.dataSources.add(ds);
        if (this.selectedWorldEntity) {
            this.selectWorldEntity(byId.get(this.selectedWorldEntity.id) || null);
        }
        this.viewer.scene.requestRender();
        return [...byId.values()];
    }

    installWorldPickHandler() {
        const handler = new Cesium.ScreenSpaceEventHandler(this.viewer.scene.canvas);
        handler.setInputAction((click) => {
            if (!this.worldDataSource) return;
            const picked = this.viewer.scene.pick(click.position);
            const entity = picked && picked.id;
            if (!entity || !this.worldDataSource.entities.contains(entity)) return;
            const id = entity.properties?.world_entity_id?.getValue();
            this.selectWorldEntity(this.worldEntities.get(id) || null);
        }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
        this._worldPickHandler = handler;
    }

    selectWorldEntity(e) {
        this.selectedWorldEntity = e;
        const box = document.getElementById('wmSelected');
        const text = document.getElementById('wmSelectedText');
        if (!box || !text) return;
        box.hidden = !e;
        if (!e) return;
        const name = (c) => c.replace(/_/g, ' ');
        const day = (iso) => new Date(iso).toLocaleDateString();
        const sources = (e.sources || []).join(', ') || 'none';
        text.innerHTML = '';
        const title = document.createElement('strong');
        title.textContent = `${name(e.category)} (${Math.round(e.score * 100)}% sure)`;
        text.appendChild(title);
        const detail = document.createElement('div');
        detail.style.color = '#94a3b8';
        detail.textContent = `${Math.round(e.p_exists * 100)}% likely still there. Seen ${e.n_hits}×`
            + `${e.n_misses ? `, missed ${e.n_misses}×` : ''}, ${day(e.first_seen)} to ${day(e.last_seen)}. Models: ${sources}.`;
        text.appendChild(detail);
        const select = document.getElementById('wmRelabelSelect');
        if (select) {
            select.innerHTML = '';
            this.worldCategories(e.taxonomy)
                .filter((c) => c !== 'unknown' && c !== e.category)
                .forEach((c) => select.add(new Option(name(c), c)));
        }
    }

    async sendWorldFeedback(kind) {
        const e = this.selectedWorldEntity;
        if (!e) return;
        const body = { entity_id: e.id, kind };
        if (kind === 'relabel') body.category = document.getElementById('wmRelabelSelect')?.value || '';
        try {
            const resp = await fetch('/webclient/sampler/world/feedback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const payload = await resp.json().catch(() => ({}));
            if (!resp.ok || payload.status !== 'success') {
                throw new Error(payload.message || `HTTP ${resp.status}`);
            }
            this.showNotification(
                kind === 'reject' ? 'Marked as not there' : `Saved: ${payload.entity.category.replace(/_/g, ' ')}`,
                'success',
            );
            await this.refreshWorldModel();
            this.selectWorldEntity(this.worldEntities.get(e.id) || payload.entity);
        } catch (err) {
            console.error('[WorldModel] feedback failed:', err);
            this.showNotification(`Feedback failed: ${err.message || err}`, 'error');
        }
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
    
    // Model options, sliders and preferences live in hud/ai-panel.js.

    // World model layer and feedback.
    if (worldSamplerUI) {
        const wmShow = document.getElementById('wmShow');
        wmShow?.addEventListener('change', (e) => worldSamplerUI.setWorldModelVisible(!!e.target.checked));
        document.getElementById('wmAt')?.addEventListener('change', () => {
            if (worldSamplerUI.worldDataSource) worldSamplerUI.refreshWorldModel();
        });
        document.getElementById('wmRefreshBtn')?.addEventListener('click', () => {
            if (wmShow && !wmShow.checked) wmShow.checked = true;
            worldSamplerUI.setWorldModelVisible(true);
        });
        document.getElementById('wmConfirmBtn')?.addEventListener('click', () => worldSamplerUI.sendWorldFeedback('confirm'));
        document.getElementById('wmRelabelBtn')?.addEventListener('click', () => worldSamplerUI.sendWorldFeedback('relabel'));
        document.getElementById('wmRejectBtn')?.addEventListener('click', () => worldSamplerUI.sendWorldFeedback('reject'));

        document.getElementById('sgShow')?.addEventListener('change', (e) => worldSamplerUI.setSceneGraphViewportVisible(!!e.target.checked));
        document.getElementById('sgShowLinks')?.addEventListener('change', () => {
            if (worldSamplerUI.sceneGraphDataSource) worldSamplerUI.setSceneGraphViewportVisible(true);
        });
    }

    // Distinction-Game SceneGraph orchestrator button.
    const sgBtn = document.getElementById('buildSceneGraphBtn');
    if (sgBtn) {
        const newSgBtn = sgBtn.cloneNode(true);
        sgBtn.parentNode.replaceChild(newSgBtn, sgBtn);
        newSgBtn.addEventListener('click', async () => {
            if (!worldSamplerUI) {
                console.warn('[SceneGraph] WorldSamplerUI not available');
                return;
            }
            try {
                await worldSamplerUI.buildSceneGraph();
            } catch (err) {
                console.error('[SceneGraph] orchestrator threw:', err);
            }
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


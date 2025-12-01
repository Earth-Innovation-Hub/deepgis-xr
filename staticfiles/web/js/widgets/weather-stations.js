/**
 * Weather Stations Widget
 * UI controls for NWS weather station layer
 */
import { NWSWeatherStationLayer } from '../utils/nws-weather-stations.js';
import { updateStatusIndicator, showSnackBar } from '../core/ui-helpers.js';

export class WeatherStationsWidget {
  constructor(viewer) {
    this.viewer = viewer;
    this.weatherLayer = null;
    this.isEnabled = false;
    // Individual state station lists
    this.californiaStations = [
      'KSFO', // San Francisco
      'KOAK', // Oakland
      'KSJC', // San Jose
      'KLAX', // Los Angeles
      'KSAN', // San Diego
      'KSAC'  // Sacramento
    ];
    
    this.arizonaStations = [
      'KPHX', // Phoenix Sky Harbor
      'KTUS', // Tucson International
      'KFLG', // Flagstaff Pulliam
      'KPRC', // Prescott
      'KNYL'  // Yuma Marine Corps Air Station
    ];
    
    this.coloradoStations = [
      'KDEN', // Denver International
      'KCOS', // Colorado Springs
      'KGJT', // Grand Junction
      'KPUB', // Pueblo
      'KFNL'  // Fort Collins-Loveland
    ];
    
    this.nevadaStations = [
      'KLAS', // Las Vegas McCarran
      'KRNO', // Reno/Tahoe
      'KEKO', // Elko
      'KELY', // Ely
      'KTPH'  // Tonopah
    ];
    
    // Default stations: combine all four states
    this.defaultStations = [
      ...this.californiaStations,
      ...this.arizonaStations,
      ...this.coloradoStations,
      ...this.nevadaStations
    ];
    
    this.init();
  }

  async init() {
    // Initialize weather layer
    this.weatherLayer = new NWSWeatherStationLayer(this.viewer);
    
    // Create UI
    this.createUI();
    
    // Setup event handlers
    this.setupEventHandlers();
    
    console.log('Weather Stations Widget initialized');
  }

  createUI() {
    // Check if UI already exists
    if (document.getElementById('weatherStationsSection')) {
      return;
    }

    // First priority: HUD panel container (for label_search.html)
    const hudWeatherContainer = document.getElementById('weatherStationsHudContainer');
    if (hudWeatherContainer) {
      return this.createHudPanelUI(hudWeatherContainer);
    }

    // Second priority: Try to find left sidebar area (where camera pose and drone controls are)
    // Look for existing left-side widgets to attach near them
    const leftSideWidgets = document.querySelector('.drone-fly-widget') || 
                           document.querySelector('.drone-orbit-widget') ||
                           document.querySelector('.camera-pose-widget');
    
    // If left sidebar widgets exist, create a similar floating widget
    if (leftSideWidgets) {
      return this.createLeftSideWidget();
    }

    // Fallback: try HUD container or sidebar
    const hudContainer = document.getElementById('hudSamplerContainer');
    const sidebar = document.querySelector('.layer-controls') || 
                   document.querySelector('#sidebar-wrapper .sidebar-content') ||
                   document.querySelector('.sidebar-content');

    const container = hudContainer || sidebar;
    
    if (!container) {
      console.warn('[Weather Stations] Could not find container, creating floating widget');
      return this.createFloatingUI();
    }

    // Create weather stations section
    const section = document.createElement('div');
    section.id = 'weatherStationsSection';
    section.className = 'layer-group accordion-panel';
    section.style.border = '2px solid #10b981';
    section.style.background = 'rgba(16, 185, 129, 0.05)';
    section.innerHTML = `
      <div class="layer-group-title accordion-header" data-target="weatherStationsContent">
        <span><i class="fas fa-cloud-sun"></i> Weather Stations</span>
        <i class="fas fa-chevron-down accordion-icon"></i>
      </div>
      <div class="accordion-content expanded" id="weatherStationsContent">
        <div class="form-group" style="margin-bottom: 12px;">
          <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
            <input type="checkbox" id="weatherStationsToggle" style="cursor: pointer;">
            <span>Show Weather Stations</span>
          </label>
        </div>
        
        <div id="weatherStationsControls" style="display: none;">
          <div class="form-group" style="margin-bottom: 12px;">
            <label>Stations:</label>
            <div id="weatherStationsList" style="max-height: 200px; overflow-y: auto; margin-top: 8px;">
              <div style="font-size: 0.85rem; color: #94a3b8;">
                Click "Load Stations" to add weather stations
              </div>
            </div>
          </div>
          
          <div class="form-group" style="margin-bottom: 12px;">
            <label>Add Station:</label>
            <div style="display: flex; gap: 4px;">
              <input type="text" id="weatherStationId" 
                     placeholder="e.g., KSFO" 
                     class="form-control" 
                     style="flex: 1; font-size: 0.9rem;">
              <button class="btn btn-sm btn-primary" id="addWeatherStationBtn">
                <i class="fas fa-plus"></i>
              </button>
            </div>
          </div>
          
          <div class="form-group" style="margin-bottom: 12px;">
            <button class="btn btn-sm btn-secondary w-100" id="loadDefaultStationsBtn">
              <i class="fas fa-download"></i> Load Default Stations
            </button>
          </div>
          
          <div class="form-group" style="margin-bottom: 12px;">
            <label style="display: flex; align-items: center; gap: 8px;">
              <input type="checkbox" id="weatherStationsAutoUpdate" checked style="cursor: pointer;">
              <span>Auto-update (15 min)</span>
            </label>
          </div>
          
          <div class="form-group">
            <button class="btn btn-sm btn-danger w-100" id="clearWeatherStationsBtn">
              <i class="fas fa-trash"></i> Clear All Stations
            </button>
          </div>
          
          <div id="weatherStationsStatus" style="margin-top: 8px; font-size: 0.85rem; color: #94a3b8;">
            <span id="weatherStationsCount">0</span> stations loaded
          </div>
        </div>
      </div>
    `;

    // Insert into container
    if (container.id === 'hudSamplerContainer') {
      container.appendChild(section);
    } else {
      // Insert at the beginning of sidebar
      container.insertBefore(section, container.firstChild);
    }

    // Setup accordion behavior
    this.setupAccordion();
  }

  createHudPanelUI(container) {
    // Create weather stations UI inside HUD panel
    const section = document.createElement('div');
    section.id = 'weatherStationsSection';
    section.innerHTML = `
      <div class="form-group mb-3">
        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; color: #cbd5e1; font-size: 0.85rem;">
          <input type="checkbox" id="weatherStationsToggle" style="cursor: pointer;">
          <span>Show Weather Stations</span>
        </label>
      </div>
      
      <div id="weatherStationsControls" style="display: none;">
        <div class="form-group mb-3">
          <label class="form-label" style="color: #cbd5e1; font-size: 0.85rem;">Stations:</label>
          <div id="weatherStationsList" style="max-height: 200px; overflow-y: auto; margin-top: 8px; padding: 8px; background: rgba(0,0,0,0.3); border-radius: 4px; font-size: 0.8rem; color: #94a3b8;">
            Click "Load Default Stations" to add weather stations
          </div>
        </div>
        
        <div class="form-group mb-3">
          <label class="form-label" style="color: #cbd5e1; font-size: 0.85rem;">Add Station:</label>
          <div style="display: flex; gap: 4px;">
            <input type="text" id="weatherStationId" 
                   placeholder="e.g., KSFO" 
                   class="form-control form-control-sm" 
                   style="flex: 1; background: #374151; border: 1px solid #64748b; color: #f1f5f9; font-size: 0.8rem;">
            <button class="btn btn-sm btn-primary" id="addWeatherStationBtn" style="background: #10b981; border: none;">
              <i class="fas fa-plus"></i>
            </button>
          </div>
        </div>
        
        <div class="form-group mb-3">
          <label class="form-label" style="color: #cbd5e1; font-size: 0.85rem; margin-bottom: 6px;">Quick Load:</label>
          <div class="btn-group w-100 mb-2" role="group">
            <button class="btn btn-sm btn-secondary" id="loadDefaultStationsBtn" style="background: #475569; border: none; color: white; flex: 1;">
              <i class="fas fa-download me-1"></i>All States
            </button>
          </div>
          <div class="btn-group w-100" role="group">
            <button class="btn btn-sm btn-secondary" id="loadCaliforniaStationsBtn" style="background: #475569; border: none; color: white; flex: 1;">
              CA
            </button>
            <button class="btn btn-sm btn-secondary" id="loadArizonaStationsBtn" style="background: #475569; border: none; color: white; flex: 1;">
              AZ
            </button>
            <button class="btn btn-sm btn-secondary" id="loadColoradoStationsBtn" style="background: #475569; border: none; color: white; flex: 1;">
              CO
            </button>
            <button class="btn btn-sm btn-secondary" id="loadNevadaStationsBtn" style="background: #475569; border: none; color: white; flex: 1;">
              NV
            </button>
          </div>
        </div>
        
        <div class="form-check mb-3">
          <input class="form-check-input" type="checkbox" id="weatherStationsAutoUpdate" checked style="cursor: pointer;">
          <label class="form-check-label" for="weatherStationsAutoUpdate" style="color: #cbd5e1; font-size: 0.85rem; cursor: pointer;">
            Auto-update (15 min)
          </label>
        </div>
        
        <div class="form-group mb-2">
          <button class="btn btn-sm btn-danger w-100" id="clearWeatherStationsBtn" style="background: #ef4444; border: none;">
            <i class="fas fa-trash me-2"></i>Clear All Stations
          </button>
        </div>
        
        <div id="weatherStationsStatus" style="margin-top: 8px; font-size: 0.8rem; color: #94a3b8; text-align: center;">
          <span id="weatherStationsCount">0</span> stations loaded
        </div>
      </div>
    `;
    
    container.appendChild(section);
  }

  createLeftSideWidget() {
    // Create a floating widget on the left side, similar to drone controls
    const widget = document.createElement('div');
    widget.id = 'weatherStationsSection';
    widget.className = 'weather-stations-widget';
    widget.style.cssText = `
      position: fixed;
      top: 800px;
      left: 20px;
      width: 220px;
      max-height: 50vh;
      overflow-y: auto;
      z-index: 1400;
      background: rgba(15, 23, 42, 0.8);
      border-radius: 12px;
      padding: 12px;
      border: 1px solid rgba(16, 185, 129, 0.3);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
      backdrop-filter: blur(8px);
    `;
    widget.innerHTML = `
      <div class="widget-title" style="color: #10b981; font-size: 11px; font-weight: bold; text-align: center; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; display: flex; align-items: center; justify-content: center; gap: 6px;">
        <i class="fas fa-cloud-sun"></i> Weather Stations
      </div>
      <div class="widget-item" style="margin-bottom: 8px;">
        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 11px; color: #cbd5e1;">
          <input type="checkbox" id="weatherStationsToggle" style="cursor: pointer;">
          <span>Show Stations</span>
        </label>
      </div>
      <div id="weatherStationsControls" style="display: none;">
        <div class="widget-item" style="margin-bottom: 8px;">
          <label style="font-size: 11px; color: #cbd5e1; margin-bottom: 4px; display: block;">Stations:</label>
          <div id="weatherStationsList" style="max-height: 150px; overflow-y: auto; margin-top: 4px; font-size: 10px;">
            <div style="color: #94a3b8;">Click "Load Default" to add stations</div>
          </div>
        </div>
        <div class="widget-item" style="margin-bottom: 8px;">
          <label style="font-size: 11px; color: #cbd5e1; margin-bottom: 4px; display: block;">Add Station:</label>
          <div style="display: flex; gap: 4px;">
            <input type="text" id="weatherStationId" placeholder="e.g., KSFO" 
                   style="flex: 1; padding: 6px; background: rgba(255, 255, 255, 0.1); border: 1px solid #475569; border-radius: 4px; color: #f1f5f9; font-size: 11px;">
            <button class="btn btn-sm btn-primary" id="addWeatherStationBtn" style="padding: 6px 10px; font-size: 11px; background: #10b981; border: none; border-radius: 4px; color: white; cursor: pointer;">
              <i class="fas fa-plus"></i>
            </button>
          </div>
        </div>
        <div class="widget-item" style="margin-bottom: 8px;">
          <label style="font-size: 10px; color: #94a3b8; margin-bottom: 4px; display: block;">Quick Load:</label>
          <button class="btn btn-sm btn-secondary w-100" id="loadDefaultStationsBtn" style="width: 100%; padding: 8px; font-size: 11px; background: #475569; border: none; border-radius: 4px; color: white; cursor: pointer; margin-bottom: 4px;">
            <i class="fas fa-download"></i> All States
          </button>
          <div style="display: flex; gap: 4px;">
            <button class="btn btn-sm btn-secondary" id="loadCaliforniaStationsBtn" style="flex: 1; padding: 6px; font-size: 10px; background: #475569; border: none; border-radius: 4px; color: white; cursor: pointer;">
              CA
            </button>
            <button class="btn btn-sm btn-secondary" id="loadArizonaStationsBtn" style="flex: 1; padding: 6px; font-size: 10px; background: #475569; border: none; border-radius: 4px; color: white; cursor: pointer;">
              AZ
            </button>
            <button class="btn btn-sm btn-secondary" id="loadColoradoStationsBtn" style="flex: 1; padding: 6px; font-size: 10px; background: #475569; border: none; border-radius: 4px; color: white; cursor: pointer;">
              CO
            </button>
            <button class="btn btn-sm btn-secondary" id="loadNevadaStationsBtn" style="flex: 1; padding: 6px; font-size: 10px; background: #475569; border: none; border-radius: 4px; color: white; cursor: pointer;">
              NV
            </button>
          </div>
        </div>
        <div class="widget-item" style="margin-bottom: 8px;">
          <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 11px; color: #cbd5e1;">
            <input type="checkbox" id="weatherStationsAutoUpdate" checked style="cursor: pointer;">
            <span>Auto-update (15 min)</span>
          </label>
        </div>
        <div class="widget-item">
          <button class="btn btn-sm btn-danger w-100" id="clearWeatherStationsBtn" style="width: 100%; padding: 8px; font-size: 11px; background: #ef4444; border: none; border-radius: 4px; color: white; cursor: pointer;">
            <i class="fas fa-trash"></i> Clear All
          </button>
        </div>
        <div id="weatherStationsStatus" style="margin-top: 8px; font-size: 10px; color: #94a3b8; text-align: center;">
          <span id="weatherStationsCount">0</span> stations
        </div>
      </div>
    `;
    document.body.appendChild(widget);
    
    // Setup scrollbar styling
    const style = document.createElement('style');
    style.textContent = `
      .weather-stations-widget::-webkit-scrollbar {
        width: 6px;
      }
      .weather-stations-widget::-webkit-scrollbar-track {
        background: rgba(0, 0, 0, 0.2);
        border-radius: 3px;
      }
      .weather-stations-widget::-webkit-scrollbar-thumb {
        background: rgba(16, 185, 129, 0.4);
        border-radius: 3px;
      }
    `;
    document.head.appendChild(style);
  }

  createFloatingUI() {
    // Fallback: create floating widget
    const widget = document.createElement('div');
    widget.id = 'weatherStationsSection';
    widget.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      width: 300px;
      background: rgba(15, 23, 42, 0.95);
      border: 1px solid rgba(16, 185, 129, 0.3);
      border-radius: 8px;
      padding: 16px;
      z-index: 1000;
    `;
    widget.innerHTML = `
      <h4 style="margin-top: 0; color: #10b981;">
        <i class="fas fa-cloud-sun"></i> Weather Stations
      </h4>
      <label>
        <input type="checkbox" id="weatherStationsToggle"> Show Stations
      </label>
    `;
    document.body.appendChild(widget);
  }

  setupAccordion() {
    const header = document.querySelector('#weatherStationsSection .accordion-header');
    const content = document.getElementById('weatherStationsContent');
    
    if (header && content) {
      header.addEventListener('click', () => {
        content.classList.toggle('expanded');
        const icon = header.querySelector('.accordion-icon');
        if (icon) {
          icon.style.transform = content.classList.contains('expanded') ? 'rotate(180deg)' : 'rotate(0deg)';
        }
      });
    }
  }

  setupEventHandlers() {
    // Toggle weather stations
    const toggle = document.getElementById('weatherStationsToggle');
    if (toggle) {
      toggle.addEventListener('change', async (e) => {
        await this.toggleWeatherStations(e.target.checked);
      });
    }

    // Add station button
    const addBtn = document.getElementById('addWeatherStationBtn');
    const stationInput = document.getElementById('weatherStationId');
    
    if (addBtn) {
      addBtn.addEventListener('click', async () => {
        const stationId = stationInput?.value.trim().toUpperCase();
        if (stationId) {
          await this.addStation(stationId);
          if (stationInput) stationInput.value = '';
        }
      });
    }

    // Enter key on station input
    if (stationInput) {
      stationInput.addEventListener('keypress', async (e) => {
        if (e.key === 'Enter') {
          const stationId = stationInput.value.trim().toUpperCase();
          if (stationId) {
            await this.addStation(stationId);
            stationInput.value = '';
          }
        }
      });
    }

    // Load default stations
    const loadDefaultBtn = document.getElementById('loadDefaultStationsBtn');
    if (loadDefaultBtn) {
      loadDefaultBtn.addEventListener('click', async () => {
        await this.loadDefaultStations();
      });
    }

    // Load California stations
    const loadCaliforniaBtn = document.getElementById('loadCaliforniaStationsBtn');
    if (loadCaliforniaBtn) {
      loadCaliforniaBtn.addEventListener('click', async () => {
        await this.loadCaliforniaStations();
      });
    }

    // Load Arizona stations
    const loadArizonaBtn = document.getElementById('loadArizonaStationsBtn');
    if (loadArizonaBtn) {
      loadArizonaBtn.addEventListener('click', async () => {
        await this.loadArizonaStations();
      });
    }

    // Load Colorado stations
    const loadColoradoBtn = document.getElementById('loadColoradoStationsBtn');
    if (loadColoradoBtn) {
      loadColoradoBtn.addEventListener('click', async () => {
        await this.loadColoradoStations();
      });
    }

    // Load Nevada stations
    const loadNevadaBtn = document.getElementById('loadNevadaStationsBtn');
    if (loadNevadaBtn) {
      loadNevadaBtn.addEventListener('click', async () => {
        await this.loadNevadaStations();
      });
    }

    // Auto-update toggle
    const autoUpdate = document.getElementById('weatherStationsAutoUpdate');
    if (autoUpdate) {
      autoUpdate.addEventListener('change', (e) => {
        if (e.target.checked && this.isEnabled) {
          this.weatherLayer.startAutoUpdate(15);
        } else {
          this.weatherLayer.stopAutoUpdate();
        }
      });
    }

    // Clear all stations
    const clearBtn = document.getElementById('clearWeatherStationsBtn');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        this.clearAllStations();
      });
    }
  }

  async toggleWeatherStations(enabled) {
    this.isEnabled = enabled;
    const controls = document.getElementById('weatherStationsControls');
    
    if (enabled) {
      if (controls) controls.style.display = 'block';
      
      // Show existing stations or load defaults
      if (this.weatherLayer.getStationCount() === 0) {
        updateStatusIndicator('Loading default weather stations...');
        await this.loadDefaultStations();
      } else {
        this.weatherLayer.showAll();
      }
      
      // Start auto-update if enabled
      const autoUpdate = document.getElementById('weatherStationsAutoUpdate');
      if (autoUpdate && autoUpdate.checked) {
        this.weatherLayer.startAutoUpdate(15);
      }
      
      updateStatusIndicator('Weather stations enabled');
      showSnackBar('Weather stations loaded', 'success');
    } else {
      this.weatherLayer.hideAll();
      this.weatherLayer.stopAutoUpdate();
      if (controls) controls.style.display = 'none';
      updateStatusIndicator('Weather stations hidden');
    }
    
    this.updateStatus();
  }

  async loadDefaultStations() {
    updateStatusIndicator('Loading default weather stations...');
    showSnackBar('Loading weather stations...', 'info');
    
    try {
      await this.weatherLayer.addStations(this.defaultStations);
      this.updateStatus();
      updateStatusIndicator(`Loaded ${this.defaultStations.length} weather stations`);
      showSnackBar(`Loaded ${this.defaultStations.length} weather stations`, 'success');
    } catch (error) {
      console.error('Error loading default stations:', error);
      updateStatusIndicator('Error loading weather stations');
      showSnackBar('Error loading weather stations', 'error');
    }
  }

  async loadCaliforniaStations() {
    updateStatusIndicator('Loading California weather stations...');
    showSnackBar('Loading California weather stations...', 'info');
    
    try {
      await this.weatherLayer.addStations(this.californiaStations);
      this.updateStatus();
      updateStatusIndicator(`Loaded ${this.californiaStations.length} California weather stations`);
      showSnackBar(`Loaded ${this.californiaStations.length} California weather stations`, 'success');
    } catch (error) {
      console.error('Error loading California stations:', error);
      updateStatusIndicator('Error loading California weather stations');
      showSnackBar('Error loading California weather stations', 'error');
    }
  }

  async loadArizonaStations() {
    updateStatusIndicator('Loading Arizona weather stations...');
    showSnackBar('Loading Arizona weather stations...', 'info');
    
    try {
      await this.weatherLayer.addStations(this.arizonaStations);
      this.updateStatus();
      updateStatusIndicator(`Loaded ${this.arizonaStations.length} Arizona weather stations`);
      showSnackBar(`Loaded ${this.arizonaStations.length} Arizona weather stations`, 'success');
    } catch (error) {
      console.error('Error loading Arizona stations:', error);
      updateStatusIndicator('Error loading Arizona weather stations');
      showSnackBar('Error loading Arizona weather stations', 'error');
    }
  }

  async loadColoradoStations() {
    updateStatusIndicator('Loading Colorado weather stations...');
    showSnackBar('Loading Colorado weather stations...', 'info');
    
    try {
      await this.weatherLayer.addStations(this.coloradoStations);
      this.updateStatus();
      updateStatusIndicator(`Loaded ${this.coloradoStations.length} Colorado weather stations`);
      showSnackBar(`Loaded ${this.coloradoStations.length} Colorado weather stations`, 'success');
    } catch (error) {
      console.error('Error loading Colorado stations:', error);
      updateStatusIndicator('Error loading Colorado weather stations');
      showSnackBar('Error loading Colorado weather stations', 'error');
    }
  }

  async loadNevadaStations() {
    updateStatusIndicator('Loading Nevada weather stations...');
    showSnackBar('Loading Nevada weather stations...', 'info');
    
    try {
      await this.weatherLayer.addStations(this.nevadaStations);
      this.updateStatus();
      updateStatusIndicator(`Loaded ${this.nevadaStations.length} Nevada weather stations`);
      showSnackBar(`Loaded ${this.nevadaStations.length} Nevada weather stations`, 'success');
    } catch (error) {
      console.error('Error loading Nevada stations:', error);
      updateStatusIndicator('Error loading Nevada weather stations');
      showSnackBar('Error loading Nevada weather stations', 'error');
    }
  }

  async addStation(stationId) {
    if (!stationId || stationId.length < 3) {
      showSnackBar('Invalid station ID', 'error');
      return;
    }

    updateStatusIndicator(`Adding weather station: ${stationId}...`);
    
    try {
      const entity = await this.weatherLayer.addStation(stationId);
      if (entity) {
        this.updateStatus();
        updateStatusIndicator(`Added station: ${stationId}`);
        showSnackBar(`Added weather station: ${stationId}`, 'success');
      } else {
        showSnackBar(`Failed to add station: ${stationId}`, 'error');
      }
    } catch (error) {
      console.error(`Error adding station ${stationId}:`, error);
      updateStatusIndicator(`Error adding station: ${stationId}`);
      showSnackBar(`Error adding station: ${stationId}`, 'error');
    }
  }

  clearAllStations() {
    if (confirm('Remove all weather stations?')) {
      this.weatherLayer.removeAllStations();
      this.updateStatus();
      updateStatusIndicator('All weather stations removed');
      showSnackBar('All weather stations removed', 'info');
    }
  }

  updateStatus() {
    const count = this.weatherLayer.getStationCount();
    const countEl = document.getElementById('weatherStationsCount');
    if (countEl) {
      countEl.textContent = count;
    }

    // Update stations list
    const listEl = document.getElementById('weatherStationsList');
    if (listEl) {
      const stationIds = this.weatherLayer.getStationIds();
      if (stationIds.length === 0) {
        listEl.innerHTML = '<div style="font-size: 0.85rem; color: #94a3b8;">No stations loaded</div>';
      } else {
        listEl.innerHTML = stationIds.map(id => `
          <div style="display: flex; justify-content: space-between; align-items: center; 
                      padding: 4px 8px; margin: 2px 0; 
                      background: rgba(16, 185, 129, 0.1); 
                      border-radius: 4px; font-size: 0.85rem;">
            <span>${id}</span>
            <button class="btn btn-sm" style="padding: 2px 6px; font-size: 0.75rem;" 
                    onclick="window.weatherStationsWidget.removeStation('${id}')">
              <i class="fas fa-times"></i>
            </button>
          </div>
        `).join('');
      }
    }
  }

  removeStation(stationId) {
    this.weatherLayer.removeStation(stationId);
    this.updateStatus();
    showSnackBar(`Removed station: ${stationId}`, 'info');
  }
}

// Export default
export default WeatherStationsWidget;


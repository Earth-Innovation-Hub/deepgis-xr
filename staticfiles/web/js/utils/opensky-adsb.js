/**
 * OpenSky ADS-B Aircraft Layer
 * Displays real-time aircraft positions from OpenSky Network API as Cesium entities
 * 
 * API: https://opensky-network.org/apidoc/rest.html
 * Free tier: Anonymous requests limited to 10 requests/minute
 */
import { ErrorHandler } from './errors.js';

export class OpenSkyADSBLayer {
  constructor(viewer) {
    this.viewer = viewer;
    this.aircraft = new Map(); // icao24 -> {entity, data, lastSeen}
    this.updateInterval = null;
    this.updateIntervalSeconds = 5;
    this.isEnabled = false;
    this.lastBounds = null;
    this.staleThresholdMs = 60000; // Remove aircraft not seen in 60 seconds
    
    // API endpoint
    this.apiBaseUrl = 'https://opensky-network.org/api/states/all';
    
    // Aircraft icon colors by altitude (in meters)
    this.altitudeColors = {
      ground: '#888888',      // On ground
      low: '#22c55e',         // < 1000m (green)
      medium: '#3b82f6',      // 1000-5000m (blue)
      high: '#8b5cf6',        // 5000-10000m (purple)
      veryHigh: '#ef4444'     // > 10000m (red)
    };
  }

  /**
   * Get current view bounds from Cesium viewer
   * Returns {lamin, lomin, lamax, lomax} or null if can't determine
   */
  getViewBounds() {
    try {
      const camera = this.viewer.camera;
      const canvas = this.viewer.scene.canvas;
      
      // Get the four corners of the view
      const corners = [
        new Cesium.Cartesian2(0, 0),
        new Cesium.Cartesian2(canvas.width, 0),
        new Cesium.Cartesian2(0, canvas.height),
        new Cesium.Cartesian2(canvas.width, canvas.height)
      ];
      
      let minLat = 90, maxLat = -90, minLon = 180, maxLon = -180;
      let validCorners = 0;
      
      for (const corner of corners) {
        const ray = camera.getPickRay(corner);
        if (ray) {
          const position = this.viewer.scene.globe.pick(ray, this.viewer.scene);
          if (position) {
            const cartographic = Cesium.Cartographic.fromCartesian(position);
            const lat = Cesium.Math.toDegrees(cartographic.latitude);
            const lon = Cesium.Math.toDegrees(cartographic.longitude);
            
            minLat = Math.min(minLat, lat);
            maxLat = Math.max(maxLat, lat);
            minLon = Math.min(minLon, lon);
            maxLon = Math.max(maxLon, lon);
            validCorners++;
          }
        }
      }
      
      // If we couldn't get valid corners, use camera position with a reasonable buffer
      if (validCorners < 2) {
        const cameraPosition = camera.positionCartographic;
        const centerLat = Cesium.Math.toDegrees(cameraPosition.latitude);
        const centerLon = Cesium.Math.toDegrees(cameraPosition.longitude);
        const altitude = cameraPosition.height;
        
        // Buffer size based on altitude (rough approximation)
        const buffer = Math.min(5, Math.max(0.5, altitude / 50000));
        
        return {
          lamin: centerLat - buffer,
          lamax: centerLat + buffer,
          lomin: centerLon - buffer,
          lomax: centerLon + buffer
        };
      }
      
      // Add small buffer to bounds
      const latBuffer = (maxLat - minLat) * 0.1;
      const lonBuffer = (maxLon - minLon) * 0.1;
      
      return {
        lamin: Math.max(-90, minLat - latBuffer),
        lamax: Math.min(90, maxLat + latBuffer),
        lomin: Math.max(-180, minLon - lonBuffer),
        lomax: Math.min(180, maxLon + lonBuffer)
      };
    } catch (error) {
      console.error('[OpenSky ADS-B] Error getting view bounds:', error);
      return null;
    }
  }

  /**
   * Fetch aircraft states from OpenSky Network API
   */
  async fetchAircraftStates(bounds) {
    if (!bounds) {
      bounds = this.getViewBounds();
    }
    
    if (!bounds) {
      console.warn('[OpenSky ADS-B] Could not determine view bounds');
      return null;
    }

    const url = new URL(this.apiBaseUrl);
    url.searchParams.append('lamin', bounds.lamin.toFixed(4));
    url.searchParams.append('lamax', bounds.lamax.toFixed(4));
    url.searchParams.append('lomin', bounds.lomin.toFixed(4));
    url.searchParams.append('lomax', bounds.lomax.toFixed(4));

    try {
      const response = await fetch(url.toString(), {
        headers: {
          'Accept': 'application/json'
        }
      });

      if (response.status === 429) {
        console.warn('[OpenSky ADS-B] Rate limited by API, will retry next interval');
        return null;
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      this.lastBounds = bounds;
      return data;
    } catch (error) {
      console.error('[OpenSky ADS-B] Error fetching aircraft states:', error);
      return null;
    }
  }

  /**
   * Parse OpenSky state vector
   * State vector indices: https://opensky-network.org/apidoc/rest.html#response
   */
  parseStateVector(state) {
    return {
      icao24: state[0],           // ICAO24 transponder address
      callsign: state[1]?.trim() || null,  // Callsign
      originCountry: state[2],    // Country of origin
      timePosition: state[3],     // Unix timestamp of position
      lastContact: state[4],      // Unix timestamp of last contact
      longitude: state[5],        // Longitude in degrees
      latitude: state[6],         // Latitude in degrees
      baroAltitude: state[7],     // Barometric altitude in meters
      onGround: state[8],         // Is on ground
      velocity: state[9],         // Ground speed in m/s
      trueTrack: state[10],       // True track (heading) in degrees
      verticalRate: state[11],    // Vertical rate in m/s
      sensors: state[12],         // IDs of sensors
      geoAltitude: state[13],     // Geometric altitude in meters
      squawk: state[14],          // Transponder squawk code
      spi: state[15],             // Special purpose indicator
      positionSource: state[16]   // Position source (0=ADS-B, 1=ASTERIX, 2=MLAT)
    };
  }

  /**
   * Update all aircraft from API response
   */
  async updateAircraft() {
    if (!this.isEnabled) return;

    const data = await this.fetchAircraftStates();
    if (!data || !data.states) {
      return;
    }

    const now = Date.now();
    const seenIcao24s = new Set();

    // Update or add aircraft
    for (const state of data.states) {
      const aircraft = this.parseStateVector(state);
      
      // Skip if no valid position
      if (aircraft.latitude === null || aircraft.longitude === null) {
        continue;
      }

      seenIcao24s.add(aircraft.icao24);
      
      if (this.aircraft.has(aircraft.icao24)) {
        // Update existing aircraft
        this.updateAircraftEntity(aircraft);
      } else {
        // Add new aircraft
        this.addAircraftEntity(aircraft);
      }
    }

    // Remove stale aircraft
    for (const [icao24, aircraftData] of this.aircraft.entries()) {
      if (!seenIcao24s.has(icao24) && (now - aircraftData.lastSeen) > this.staleThresholdMs) {
        this.removeAircraftEntity(icao24);
      }
    }

    console.log(`[OpenSky ADS-B] Updated: ${seenIcao24s.size} aircraft visible`);
  }

  /**
   * Add new aircraft entity to viewer
   */
  addAircraftEntity(aircraft) {
    const altitude = aircraft.geoAltitude || aircraft.baroAltitude || 0;
    const heading = aircraft.trueTrack || 0;
    
    // Position with altitude
    const position = Cesium.Cartesian3.fromDegrees(
      aircraft.longitude,
      aircraft.latitude,
      altitude
    );

    // Create orientation from heading
    const hpr = new Cesium.HeadingPitchRoll(
      Cesium.Math.toRadians(heading),
      0,
      0
    );
    const orientation = Cesium.Transforms.headingPitchRollQuaternion(position, hpr);

    // Get color based on altitude
    const color = this.getAltitudeColor(altitude, aircraft.onGround);
    
    // Create entity
    const entity = this.viewer.entities.add({
      id: `aircraft_${aircraft.icao24}`,
      position: position,
      orientation: orientation,
      point: {
        pixelSize: aircraft.onGround ? 6 : 10,
        color: Cesium.Color.fromCssColorString(color),
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 1,
        heightReference: aircraft.onGround ? 
          Cesium.HeightReference.CLAMP_TO_GROUND : 
          Cesium.HeightReference.NONE,
        disableDepthTestDistance: Number.POSITIVE_INFINITY
      },
      label: {
        text: aircraft.callsign || aircraft.icao24.toUpperCase(),
        font: '11px monospace',
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        pixelOffset: new Cesium.Cartesian2(0, -15),
        heightReference: aircraft.onGround ? 
          Cesium.HeightReference.CLAMP_TO_GROUND : 
          Cesium.HeightReference.NONE,
        scaleByDistance: new Cesium.NearFarScalar(1e3, 1.0, 5e5, 0.3),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        show: !aircraft.onGround // Hide labels for ground aircraft
      },
      description: this.createDescription(aircraft)
    });

    this.aircraft.set(aircraft.icao24, {
      entity: entity,
      data: aircraft,
      lastSeen: Date.now()
    });
  }

  /**
   * Update existing aircraft entity
   */
  updateAircraftEntity(aircraft) {
    const existing = this.aircraft.get(aircraft.icao24);
    if (!existing) return;

    const entity = existing.entity;
    const altitude = aircraft.geoAltitude || aircraft.baroAltitude || 0;
    const heading = aircraft.trueTrack || 0;

    // Update position
    const position = Cesium.Cartesian3.fromDegrees(
      aircraft.longitude,
      aircraft.latitude,
      altitude
    );
    entity.position = position;

    // Update orientation
    const hpr = new Cesium.HeadingPitchRoll(
      Cesium.Math.toRadians(heading),
      0,
      0
    );
    entity.orientation = Cesium.Transforms.headingPitchRollQuaternion(position, hpr);

    // Update color
    const color = this.getAltitudeColor(altitude, aircraft.onGround);
    entity.point.color = Cesium.Color.fromCssColorString(color);
    entity.point.pixelSize = aircraft.onGround ? 6 : 10;

    // Update label
    entity.label.text = aircraft.callsign || aircraft.icao24.toUpperCase();
    entity.label.show = !aircraft.onGround;

    // Update description
    entity.description = this.createDescription(aircraft);

    // Update tracking data
    existing.data = aircraft;
    existing.lastSeen = Date.now();
  }

  /**
   * Remove aircraft entity
   */
  removeAircraftEntity(icao24) {
    const existing = this.aircraft.get(icao24);
    if (existing) {
      this.viewer.entities.remove(existing.entity);
      this.aircraft.delete(icao24);
    }
  }

  /**
   * Get color based on altitude
   */
  getAltitudeColor(altitude, onGround) {
    if (onGround) return this.altitudeColors.ground;
    if (altitude < 1000) return this.altitudeColors.low;
    if (altitude < 5000) return this.altitudeColors.medium;
    if (altitude < 10000) return this.altitudeColors.high;
    return this.altitudeColors.veryHigh;
  }

  /**
   * Create HTML description for aircraft popup
   */
  createDescription(aircraft) {
    const altitude = aircraft.geoAltitude || aircraft.baroAltitude;
    const altitudeFt = altitude ? Math.round(altitude * 3.28084) : null;
    const speedKnots = aircraft.velocity ? Math.round(aircraft.velocity * 1.94384) : null;
    const verticalFpm = aircraft.verticalRate ? Math.round(aircraft.verticalRate * 196.85) : null;

    return `
      <div style="font-family: 'Courier New', monospace; padding: 12px; max-width: 320px; background: #1e293b; color: #e2e8f0;">
        <h3 style="margin: 0 0 12px 0; color: #3b82f6; border-bottom: 1px solid #3b82f6; padding-bottom: 8px;">
          ✈️ ${aircraft.callsign || 'N/A'}
        </h3>
        <table style="width: 100%; border-collapse: collapse; font-size: 12px;">
          <tr>
            <td style="padding: 4px 8px; color: #94a3b8;">ICAO24:</td>
            <td style="padding: 4px 8px; font-weight: bold;">${aircraft.icao24.toUpperCase()}</td>
          </tr>
          <tr>
            <td style="padding: 4px 8px; color: #94a3b8;">Origin:</td>
            <td style="padding: 4px 8px;">${aircraft.originCountry || 'Unknown'}</td>
          </tr>
          <tr>
            <td style="padding: 4px 8px; color: #94a3b8;">Altitude:</td>
            <td style="padding: 4px 8px;">${altitudeFt !== null ? altitudeFt.toLocaleString() + ' ft' : 'N/A'}</td>
          </tr>
          <tr>
            <td style="padding: 4px 8px; color: #94a3b8;">Speed:</td>
            <td style="padding: 4px 8px;">${speedKnots !== null ? speedKnots + ' kts' : 'N/A'}</td>
          </tr>
          <tr>
            <td style="padding: 4px 8px; color: #94a3b8;">Heading:</td>
            <td style="padding: 4px 8px;">${aircraft.trueTrack !== null ? Math.round(aircraft.trueTrack) + '°' : 'N/A'}</td>
          </tr>
          <tr>
            <td style="padding: 4px 8px; color: #94a3b8;">Vertical:</td>
            <td style="padding: 4px 8px; ${verticalFpm > 0 ? 'color: #22c55e;' : verticalFpm < 0 ? 'color: #ef4444;' : ''}">
              ${verticalFpm !== null ? (verticalFpm > 0 ? '↑' : verticalFpm < 0 ? '↓' : '→') + ' ' + Math.abs(verticalFpm) + ' fpm' : 'N/A'}
            </td>
          </tr>
          <tr>
            <td style="padding: 4px 8px; color: #94a3b8;">Squawk:</td>
            <td style="padding: 4px 8px;">${aircraft.squawk || 'N/A'}</td>
          </tr>
          <tr>
            <td style="padding: 4px 8px; color: #94a3b8;">Position:</td>
            <td style="padding: 4px 8px; font-size: 10px;">
              ${aircraft.latitude?.toFixed(4)}°, ${aircraft.longitude?.toFixed(4)}°
            </td>
          </tr>
          <tr>
            <td style="padding: 4px 8px; color: #94a3b8;">Status:</td>
            <td style="padding: 4px 8px;">
              <span style="color: ${aircraft.onGround ? '#f59e0b' : '#22c55e'};">
                ${aircraft.onGround ? '🛬 On Ground' : '✈️ In Flight'}
              </span>
            </td>
          </tr>
        </table>
        <div style="margin-top: 10px; font-size: 10px; color: #64748b; text-align: right;">
          Source: OpenSky Network
        </div>
      </div>
    `;
  }

  /**
   * Start tracking aircraft
   */
  start(intervalSeconds = 5) {
    if (this.isEnabled) {
      console.log('[OpenSky ADS-B] Already running');
      return;
    }

    this.isEnabled = true;
    this.updateIntervalSeconds = intervalSeconds;

    // Initial update
    this.updateAircraft();

    // Set up interval
    this.updateInterval = setInterval(() => {
      this.updateAircraft();
    }, intervalSeconds * 1000);

    console.log(`[OpenSky ADS-B] Started tracking (update every ${intervalSeconds}s)`);
  }

  /**
   * Stop tracking aircraft
   */
  stop() {
    this.isEnabled = false;

    if (this.updateInterval) {
      clearInterval(this.updateInterval);
      this.updateInterval = null;
    }

    console.log('[OpenSky ADS-B] Stopped tracking');
  }

  /**
   * Clear all aircraft from viewer
   */
  clearAll() {
    for (const [icao24] of this.aircraft) {
      this.removeAircraftEntity(icao24);
    }
    this.aircraft.clear();
    console.log('[OpenSky ADS-B] Cleared all aircraft');
  }

  /**
   * Show all aircraft entities
   */
  showAll() {
    for (const [, aircraftData] of this.aircraft) {
      aircraftData.entity.show = true;
    }
  }

  /**
   * Hide all aircraft entities
   */
  hideAll() {
    for (const [, aircraftData] of this.aircraft) {
      aircraftData.entity.show = false;
    }
  }

  /**
   * Get count of tracked aircraft
   */
  getAircraftCount() {
    return this.aircraft.size;
  }

  /**
   * Get all tracked aircraft data
   */
  getAllAircraft() {
    return Array.from(this.aircraft.values()).map(a => a.data);
  }

  /**
   * Fly to specific aircraft
   */
  flyToAircraft(icao24) {
    const aircraftData = this.aircraft.get(icao24);
    if (aircraftData) {
      this.viewer.flyTo(aircraftData.entity, {
        duration: 1.5,
        offset: new Cesium.HeadingPitchRange(0, -45, 5000)
      });
    }
  }

  /**
   * Check if tracking is enabled
   */
  isTracking() {
    return this.isEnabled;
  }
}

// Export default
export default OpenSkyADSBLayer;


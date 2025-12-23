/**
 * OpenSky ADS-B Aircraft Layer with Smooth Animation
 * Animates aircraft based on heading and speed for smooth, realistic movement
 * 
 * API: https://opensky-network.org/apidoc/rest.html
 * Free tier: Anonymous requests limited to 10 requests/minute
 */
import { ErrorHandler } from './errors.js';

export class OpenSkyADSBLayer {
  constructor(viewer) {
    this.viewer = viewer;
    this.aircraft = new Map(); // icao24 -> {entity, data, lastSeen, lastPosition, lastUpdate}
    this.updateInterval = null;
    this.updateIntervalSeconds = 5;
    this.isEnabled = false;
    this.lastBounds = null;
    this.staleThresholdMs = 60000; // Remove aircraft not seen in 60 seconds
    this.animationEnabled = true; // Enable smooth animation
    
    // API endpoint
    this.apiBaseUrl = 'https://opensky-network.org/api/states/all';
    
    // Optimization: Request management
    this.updateInProgress = false; // Prevent overlapping requests
    this.lastRequestTime = 0; // Track last API call
    this.minRequestInterval = 5000; // Minimum 5 seconds between requests
    this.lastSuccessfulData = null; // Cache last successful response
    this.lastSuccessfulBounds = null; // Cache bounds for last successful request
    this.boundsChangeThreshold = 0.5; // Only refetch if bounds changed by >0.5 degrees
    this.consecutiveFailures = 0; // Track failures for backoff
    this.maxConsecutiveFailures = 3; // Back off after 3 failures
    this.adaptiveInterval = 5; // Start with 5 seconds, adapt based on rate limits
    
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
        
        // Buffer size based on altitude (larger buffer to reduce API calls)
        // Increased buffer by 50% to reduce frequency of requests
        const buffer = Math.min(7.5, Math.max(0.75, altitude / 33333));
        
        return {
          lamin: centerLat - buffer,
          lamax: centerLat + buffer,
          lomin: centerLon - buffer,
          lomax: centerLon + buffer
        };
      }
      
      // Add larger buffer to bounds (reduces frequency of API calls)
      // 20% buffer instead of 10% to reduce bounds change frequency
      const latBuffer = (maxLat - minLat) * 0.2;
      const lonBuffer = (maxLon - minLon) * 0.2;
      
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
   * Check if bounds have changed significantly
   */
  boundsChangedSignificantly(newBounds, oldBounds) {
    if (!oldBounds) return true;
    
    const latChange = Math.abs(newBounds.lamax - oldBounds.lamax) + 
                      Math.abs(newBounds.lamin - oldBounds.lamin);
    const lonChange = Math.abs(newBounds.lomax - oldBounds.lomax) + 
                      Math.abs(newBounds.lomin - oldBounds.lomin);
    
    return latChange > this.boundsChangeThreshold || lonChange > this.boundsChangeThreshold;
  }

  /**
   * Fetch aircraft states from OpenSky Network API (optimized)
   */
  async fetchAircraftStates(bounds) {
    // Prevent overlapping requests
    if (this.updateInProgress) {
      console.log('[OpenSky ADS-B] Request already in progress, skipping');
      return this.lastSuccessfulData; // Return cached data
    }
    
    // Rate limiting: Don't make requests too frequently
    const timeSinceLastRequest = Date.now() - this.lastRequestTime;
    if (timeSinceLastRequest < this.minRequestInterval) {
      console.log(`[OpenSky ADS-B] Rate limiting: ${timeSinceLastRequest}ms since last request, using cache`);
      return this.lastSuccessfulData;
    }
    
    if (!bounds) {
      bounds = this.getViewBounds();
    }
    
    if (!bounds) {
      console.warn('[OpenSky ADS-B] Could not determine view bounds');
      return this.lastSuccessfulData; // Return cached data
    }

    // Optimization: Check if bounds changed significantly
    if (!this.boundsChangedSignificantly(bounds, this.lastSuccessfulBounds)) {
      console.log('[OpenSky ADS-B] Bounds unchanged, using cached data');
      return this.lastSuccessfulData; // Reuse cached data
    }

    // Mark request as in progress
    this.updateInProgress = true;
    this.lastRequestTime = Date.now();

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
        console.warn('[OpenSky ADS-B] Rate limited by API, backing off');
        this.consecutiveFailures++;
        this.adaptiveInterval = Math.min(this.adaptiveInterval * 2, 60); // Double interval, max 60s
        this.updateInProgress = false;
        return this.lastSuccessfulData; // Return cached data
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      
      // Success: cache data and reset failure counter
      this.lastSuccessfulData = data;
      this.lastSuccessfulBounds = { ...bounds }; // Deep copy
      this.lastBounds = bounds;
      this.consecutiveFailures = 0;
      
      // Adaptive interval: reduce if successful (but not below 5s)
      if (this.adaptiveInterval > 5) {
        this.adaptiveInterval = Math.max(5, this.adaptiveInterval * 0.8);
      }
      
      this.updateInProgress = false;
      return data;
    } catch (error) {
      console.error('[OpenSky ADS-B] Error fetching aircraft states:', error);
      this.consecutiveFailures++;
      
      // Back off on consecutive failures
      if (this.consecutiveFailures >= this.maxConsecutiveFailures) {
        this.adaptiveInterval = Math.min(this.adaptiveInterval * 2, 60);
        console.warn(`[OpenSky ADS-B] ${this.consecutiveFailures} consecutive failures, backing off to ${this.adaptiveInterval}s`);
      }
      
      this.updateInProgress = false;
      return this.lastSuccessfulData; // Return cached data on error
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
   * Calculate position at future time based on current heading and speed
   */
  calculateFuturePosition(lat, lon, alt, heading, speed, verticalRate, timeSeconds) {
    // Convert heading to radians (0° = North, clockwise)
    const headingRad = Cesium.Math.toRadians(heading);
    
    // Calculate horizontal distance traveled
    const horizontalDistance = speed * timeSeconds; // meters
    
    // Calculate altitude change
    const altitudeChange = (verticalRate || 0) * timeSeconds;
    const newAltitude = alt + altitudeChange;
    
    // Use geodesic calculations for accurate position
    const ellipsoid = Cesium.Ellipsoid.WGS84;
    const startCart = Cesium.Cartographic.fromDegrees(lon, lat, alt);
    
    // Calculate new position using bearing and distance
    // Using ENU local tangent plane for simplicity
    const earthRadius = ellipsoid.maximumRadius;
    
    // North and East components
    const north = horizontalDistance * Math.cos(headingRad);
    const east = horizontalDistance * Math.sin(headingRad);
    
    // Convert to lat/lon deltas
    const deltaLat = north / earthRadius;
    const deltaLon = east / (earthRadius * Math.cos(Cesium.Math.toRadians(lat)));
    
    const newLat = lat + Cesium.Math.toDegrees(deltaLat);
    const newLon = lon + Cesium.Math.toDegrees(deltaLon);
    
    return {
      latitude: newLat,
      longitude: newLon,
      altitude: newAltitude
    };
  }

  /**
   * Create smooth position property with animation between updates
   */
  createAnimatedPosition(aircraft, startTime, endTime) {
    const positionProperty = new Cesium.SampledPositionProperty();
    
    // Ensure clock is running for time-based properties
    if (this.viewer.clock) {
      // Set clock to current time if not already set
      const now = Cesium.JulianDate.now();
      if (!this.viewer.clock.currentTime || 
          Cesium.JulianDate.secondsDifference(now, this.viewer.clock.currentTime) > 1) {
        this.viewer.clock.currentTime = now;
      }
      // Ensure clock is running
      this.viewer.clock.shouldAnimate = true;
    }
    
    const startPos = Cesium.Cartesian3.fromDegrees(
      aircraft.longitude,
      aircraft.latitude,
      aircraft.geoAltitude || aircraft.baroAltitude || 0
    );
    
    // Set start position using current clock time
    const currentTime = this.viewer.clock ? this.viewer.clock.currentTime : Cesium.JulianDate.fromDate(startTime);
    positionProperty.addSample(currentTime, startPos);
    
    // Calculate intermediate positions based on heading and speed
    if (aircraft.velocity && aircraft.trueTrack !== null && !aircraft.onGround) {
      const intervalDuration = (endTime - startTime) / 1000; // seconds
      const numSamples = Math.min(10, Math.max(2, Math.ceil(intervalDuration)));
      
      for (let i = 1; i <= numSamples; i++) {
        const fraction = i / numSamples;
        const sampleTime = new Date(startTime.getTime() + (endTime - startTime) * fraction);
        const elapsed = (sampleTime - startTime) / 1000;
        
        const futurePos = this.calculateFuturePosition(
          aircraft.latitude,
          aircraft.longitude,
          aircraft.geoAltitude || aircraft.baroAltitude || 0,
          aircraft.trueTrack,
          aircraft.velocity,
          aircraft.verticalRate || 0,
          elapsed
        );
        
        const cartesian = Cesium.Cartesian3.fromDegrees(
          futurePos.longitude,
          futurePos.latitude,
          futurePos.altitude
        );
        
        // Use clock time if available, otherwise use sample time
        const julianTime = this.viewer.clock ? 
          Cesium.JulianDate.addSeconds(currentTime, elapsed, new Cesium.JulianDate()) :
          Cesium.JulianDate.fromDate(sampleTime);
        positionProperty.addSample(julianTime, cartesian);
      }
    } else {
      // For stationary or ground aircraft, just hold position
      const endJulianTime = this.viewer.clock ?
        Cesium.JulianDate.addSeconds(currentTime, (endTime - startTime) / 1000, new Cesium.JulianDate()) :
        Cesium.JulianDate.fromDate(endTime);
      positionProperty.addSample(endJulianTime, startPos);
    }
    
    // Set interpolation
    positionProperty.setInterpolationOptions({
      interpolationDegree: 1,
      interpolationAlgorithm: Cesium.LinearApproximation
    });
    
    return positionProperty;
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
    const updateTime = new Date(now);
    const nextUpdateTime = new Date(now + this.updateIntervalSeconds * 1000);

    // Update or add aircraft
    for (const state of data.states) {
      const aircraft = this.parseStateVector(state);
      
      // Skip if no valid position
      if (aircraft.latitude === null || aircraft.longitude === null) {
        continue;
      }

      seenIcao24s.add(aircraft.icao24);
      
      if (this.aircraft.has(aircraft.icao24)) {
        // Update existing aircraft with animation
        this.updateAircraftEntity(aircraft, updateTime, nextUpdateTime);
      } else {
        // Add new aircraft
        this.addAircraftEntity(aircraft, updateTime, nextUpdateTime);
      }
    }

    // Remove stale aircraft
    for (const [icao24, aircraftData] of this.aircraft.entries()) {
      if (!seenIcao24s.has(icao24) && (now - aircraftData.lastSeen) > this.staleThresholdMs) {
        this.removeAircraftEntity(icao24);
      }
    }

    console.log(`[OpenSky ADS-B] Updated: ${seenIcao24s.size} aircraft visible (animated: ${this.animationEnabled}, interval: ${this.adaptiveInterval.toFixed(1)}s)`);
  }

  /**
   * Add new aircraft entity to viewer with animation
   */
  addAircraftEntity(aircraft, updateTime, nextUpdateTime) {
    const altitude = aircraft.geoAltitude || aircraft.baroAltitude || 0;
    const heading = aircraft.trueTrack || 0;
    
    // Create animated position property (with fallback to static if clock unavailable)
    let positionProperty;
    try {
      if (this.animationEnabled && this.viewer.clock) {
        positionProperty = this.createAnimatedPosition(aircraft, updateTime, nextUpdateTime);
      } else {
        // Fallback to static position if animation disabled or clock unavailable
        positionProperty = Cesium.Cartesian3.fromDegrees(aircraft.longitude, aircraft.latitude, altitude);
        if (this.animationEnabled && !this.viewer.clock) {
          console.warn('[OpenSky ADS-B] Clock not available, using static positions');
        }
      }
    } catch (error) {
      console.error('[OpenSky ADS-B] Error creating animated position, using static:', error);
      positionProperty = Cesium.Cartesian3.fromDegrees(aircraft.longitude, aircraft.latitude, altitude);
    }

    // Get color based on altitude
    const color = this.getAltitudeColor(altitude, aircraft.onGround);
    
    // Determine orientation based on position property type
    let orientation;
    if (this.animationEnabled && !aircraft.onGround && positionProperty instanceof Cesium.SampledPositionProperty) {
      // Use VelocityOrientationProperty for animated entities
      try {
        orientation = new Cesium.VelocityOrientationProperty(positionProperty);
      } catch (error) {
        console.warn('[OpenSky ADS-B] Failed to create VelocityOrientationProperty, using static:', error);
        orientation = this.createOrientation(aircraft.longitude, aircraft.latitude, altitude, heading);
      }
    } else {
      // Use static orientation for non-animated or ground aircraft
      orientation = this.createOrientation(aircraft.longitude, aircraft.latitude, altitude, heading);
    }
    
    // Create entity with animated position
    const entity = this.viewer.entities.add({
      id: `aircraft_${aircraft.icao24}`,
      position: positionProperty,
      orientation: orientation,
      // Use point as primary (more reliable than billboard)
      point: {
        pixelSize: aircraft.onGround ? 6 : 10,
        color: Cesium.Color.fromCssColorString(color),
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 1,
        heightReference: aircraft.onGround ? 
          Cesium.HeightReference.CLAMP_TO_GROUND : 
          Cesium.HeightReference.NONE,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        show: true // Primary visualization
      },
      // Optional billboard (may not render in all cases)
      billboard: {
        image: this.createAircraftIcon(color, aircraft.onGround),
        scale: aircraft.onGround ? 0.6 : 1.0,
        heightReference: aircraft.onGround ? 
          Cesium.HeightReference.CLAMP_TO_GROUND : 
          Cesium.HeightReference.NONE,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        rotation: Cesium.Math.toRadians(-90), // Adjust for icon orientation
        alignedAxis: Cesium.Cartesian3.UNIT_Z,
        show: false // Disabled by default - enable if billboard rendering works
      },
      label: {
        text: aircraft.callsign || aircraft.icao24.toUpperCase(),
        font: '11px monospace',
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        pixelOffset: new Cesium.Cartesian2(0, -20),
        heightReference: aircraft.onGround ? 
          Cesium.HeightReference.CLAMP_TO_GROUND : 
          Cesium.HeightReference.NONE,
        scaleByDistance: new Cesium.NearFarScalar(1e3, 1.0, 5e5, 0.3),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        show: !aircraft.onGround // Hide labels for ground aircraft
      },
      // Add path/trail for moving aircraft
      path: !aircraft.onGround && this.animationEnabled ? {
        resolution: 1,
        material: new Cesium.PolylineGlowMaterialProperty({
          glowPower: 0.2,
          color: Cesium.Color.fromCssColorString(color).withAlpha(0.7)
        }),
        width: 2,
        leadTime: 0,
        trailTime: 60 // 60 second trail
      } : undefined,
      description: this.createDescription(aircraft)
    });

    this.aircraft.set(aircraft.icao24, {
      entity: entity,
      data: aircraft,
      lastSeen: Date.now(),
      lastUpdate: updateTime,
      lastPosition: {
        lat: aircraft.latitude,
        lon: aircraft.longitude,
        alt: altitude
      }
    });
    
    // Debug: verify entity was added
    console.log(`[OpenSky ADS-B] Added aircraft ${aircraft.icao24} at ${aircraft.latitude.toFixed(4)}, ${aircraft.longitude.toFixed(4)}, alt: ${altitude.toFixed(0)}m`);
  }

  /**
   * Create orientation quaternion from heading
   */
  createOrientation(lon, lat, alt, heading) {
    const position = Cesium.Cartesian3.fromDegrees(lon, lat, alt);
    const hpr = new Cesium.HeadingPitchRoll(
      Cesium.Math.toRadians(heading),
      0,
      0
    );
    return Cesium.Transforms.headingPitchRollQuaternion(position, hpr);
  }

  /**
   * Create SVG aircraft icon
   */
  createAircraftIcon(color, onGround) {
    try {
      const size = onGround ? 16 : 24;
      const svg = `
        <svg width="${size}" height="${size}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
          <path fill="${color}" stroke="white" stroke-width="1" 
            d="M12 2 L14 10 L22 12 L14 14 L12 22 L10 14 L2 12 L10 10 Z"/>
          ${onGround ? '<circle cx="12" cy="12" r="3" fill="white" opacity="0.5"/>' : ''}
        </svg>
      `;
      // Use encodeURIComponent for better compatibility
      const encoded = encodeURIComponent(svg);
      return 'data:image/svg+xml;charset=utf-8,' + encoded;
    } catch (error) {
      console.warn('[OpenSky ADS-B] Failed to create SVG icon, using fallback:', error);
      // Fallback: use a simple colored circle
      return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(
        `<svg width="24" height="24" xmlns="http://www.w3.org/2000/svg">
          <circle cx="12" cy="12" r="8" fill="${color}" stroke="white" stroke-width="2"/>
        </svg>`
      )}`;
    }
  }

  /**
   * Update existing aircraft entity with smooth animation
   */
  updateAircraftEntity(aircraft, updateTime, nextUpdateTime) {
    const existing = this.aircraft.get(aircraft.icao24);
    if (!existing) return;

    const entity = existing.entity;
    const altitude = aircraft.geoAltitude || aircraft.baroAltitude || 0;

    // Update position with animation
    if (this.animationEnabled) {
      entity.position = this.createAnimatedPosition(aircraft, updateTime, nextUpdateTime);
      
      // Update orientation to follow velocity
      if (!aircraft.onGround) {
        entity.orientation = new Cesium.VelocityOrientationProperty(entity.position);
      } else {
        entity.orientation = this.createOrientation(
          aircraft.longitude, aircraft.latitude, altitude, aircraft.trueTrack || 0
        );
      }
    } else {
      // Direct position update (no animation)
      const position = Cesium.Cartesian3.fromDegrees(aircraft.longitude, aircraft.latitude, altitude);
      entity.position = position;
      entity.orientation = this.createOrientation(
        aircraft.longitude, aircraft.latitude, altitude, aircraft.trueTrack || 0
      );
    }

    // Update color
    const color = this.getAltitudeColor(altitude, aircraft.onGround);
    if (entity.billboard) {
      entity.billboard.image = this.createAircraftIcon(color, aircraft.onGround);
      entity.billboard.scale = aircraft.onGround ? 0.6 : 1.0;
    }
    if (entity.point) {
      entity.point.color = Cesium.Color.fromCssColorString(color);
      entity.point.pixelSize = aircraft.onGround ? 6 : 10;
    }

    // Update trail color
    if (entity.path && entity.path.material) {
      entity.path.material.color = Cesium.Color.fromCssColorString(color).withAlpha(0.7);
    }

    // Update label
    entity.label.text = aircraft.callsign || aircraft.icao24.toUpperCase();
    entity.label.show = !aircraft.onGround;

    // Update description
    entity.description = this.createDescription(aircraft);

    // Update tracking data
    existing.data = aircraft;
    existing.lastSeen = Date.now();
    existing.lastUpdate = updateTime;
    existing.lastPosition = {
      lat: aircraft.latitude,
      lon: aircraft.longitude,
      alt: altitude
    };
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
          Source: OpenSky Network ${this.animationEnabled ? '• Animated' : ''}
        </div>
      </div>
    `;
  }

  /**
   * Toggle animation on/off
   */
  setAnimationEnabled(enabled) {
    this.animationEnabled = enabled;
    console.log(`[OpenSky ADS-B] Animation ${enabled ? 'enabled' : 'disabled'}`);
  }

  /**
   * Start tracking aircraft (optimized)
   */
  start(intervalSeconds = 5) {
    if (this.isEnabled) {
      console.log('[OpenSky ADS-B] Already running');
      return;
    }

    this.isEnabled = true;
    this.updateIntervalSeconds = intervalSeconds;
    this.adaptiveInterval = intervalSeconds; // Start with requested interval

    // Initial update
    this.updateAircraft();

    // Set up adaptive interval (will adjust based on rate limits)
    this.scheduleNextUpdate();

    console.log(`[OpenSky ADS-B] Started tracking with smooth animation (adaptive interval, starting at ${intervalSeconds}s)`);
  }
  
  /**
   * Schedule next update with adaptive interval
   */
  scheduleNextUpdate() {
    if (!this.isEnabled) return;
    
    // Clear existing interval
    if (this.updateInterval) {
      clearTimeout(this.updateInterval);
    }
    
    // Use adaptive interval (adjusts based on rate limits)
    const nextInterval = Math.max(this.minRequestInterval, this.adaptiveInterval * 1000);
    
    this.updateInterval = setTimeout(() => {
      this.updateAircraft();
      this.scheduleNextUpdate(); // Schedule next update
    }, nextInterval);
  }

  /**
   * Stop tracking aircraft
   */
  stop() {
    this.isEnabled = false;

    if (this.updateInterval) {
      clearTimeout(this.updateInterval);
      this.updateInterval = null;
    }
    
    // Reset optimization state
    this.updateInProgress = false;
    this.consecutiveFailures = 0;
    this.adaptiveInterval = 5;

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


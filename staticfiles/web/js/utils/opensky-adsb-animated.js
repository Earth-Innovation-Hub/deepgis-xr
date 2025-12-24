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
    this.minIntervalSeconds = 10; // Minimum interval to respect OpenSky anon quota (10 req/min)
    this.minRequestInterval = this.minIntervalSeconds * 1000; // Enforce floor when scheduling
    this.lastSuccessfulData = null; // Cache last successful response
    this.lastSuccessfulBounds = null; // Cache bounds for last successful request
    this.dataStale = false; // Flag to clear entities when cache is invalid for new view
    this.boundsChangeThreshold = 0.5; // Only refetch if bounds changed by >0.5 degrees
    this.consecutiveFailures = 0; // Track failures for backoff
    this.maxConsecutiveFailures = 3; // Back off after 3 failures
    this.adaptiveInterval = 5; // Start with 5 seconds, adapt based on rate limits
    
    // 100km radius limit for queries
    this.maxQueryRadiusKm = 100; // Maximum 100km radius from camera
    this.maxQueryRadiusM = 100000; // 100km in meters
    
    // Additional optimizations
    this.lastCameraPosition = null; // Track camera movement
    this.cameraMovementThreshold = 5000; // Only refetch if camera moved >5km
    this.maxAircraftCount = 200; // Limit number of aircraft to display
    this.minAltitude = -1000; // Filter out aircraft below -1000m (invalid data)
    this.maxAltitude = 20000; // Filter out aircraft above 20km (rare, saves processing)
    
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
   * Optimized: Uses fixed 100km radius from camera position
   */
  getViewBounds() {
    try {
      const camera = this.viewer.camera;
      const cameraPosition = camera.positionCartographic;
      
      if (!cameraPosition) {
        console.warn('[OpenSky ADS-B] Camera position not available');
        return null;
      }
      
      const centerLat = Cesium.Math.toDegrees(cameraPosition.latitude);
      const centerLon = Cesium.Math.toDegrees(cameraPosition.longitude);
      
      // Calculate 100km radius bounds using geodesic math
      // Convert 100km to angular distance (degrees)
      const ellipsoid = Cesium.Ellipsoid.WGS84;
      const earthRadius = ellipsoid.maximumRadius; // meters
      const radiusMeters = this.maxQueryRadiusM; // 100km
      
      // Angular distance in radians
      const angularDistance = radiusMeters / earthRadius;
      
      // Convert to degrees
      const angularDistanceDeg = Cesium.Math.toDegrees(angularDistance);
      
      // Calculate latitude bounds (simple: ±angular distance)
      const latBuffer = angularDistanceDeg;
      
      // Calculate longitude bounds (account for latitude-dependent convergence)
      // At equator: lonBuffer = angularDistanceDeg
      // At higher latitudes: lonBuffer = angularDistanceDeg / cos(lat)
      const latRad = Cesium.Math.toRadians(centerLat);
      const cosLat = Math.cos(latRad);
      
      // Prevent division by zero at poles
      const lonBuffer = angularDistanceDeg / Math.max(0.087, Math.abs(cosLat)); // Clamp to prevent extreme values
      
      // Calculate bounds
      const bounds = {
        lamin: Math.max(-90, centerLat - latBuffer),
        lamax: Math.min(90, centerLat + latBuffer),
        lomin: Math.max(-180, centerLon - lonBuffer),
        lomax: Math.min(180, centerLon + lonBuffer)
      };
      
      // Verify bounds are reasonable
      if (bounds.lamax - bounds.lamin > 10 || bounds.lomax - bounds.lomin > 10) {
        console.warn('[OpenSky ADS-B] Calculated bounds seem too large, clamping');
        // Fallback to smaller bounds if calculation seems wrong
        bounds.lamin = Math.max(-90, centerLat - 1);
        bounds.lamax = Math.min(90, centerLat + 1);
        bounds.lomin = Math.max(-180, centerLon - 1);
        bounds.lomax = Math.min(180, centerLon + 1);
      }
      
      return bounds;
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

    // Always fetch on schedule so aircraft keep updating even when camera is stationary.
    // We still use bounds to scope the query, but we do not skip polling based on bounds.

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
        // If camera moved to a new area, invalidate cache so we don't show stale aircraft
        if (this.boundsChangedSignificantly(bounds, this.lastSuccessfulBounds)) {
          this.dataStale = true;
          this.lastSuccessfulData = null;
          this.lastSuccessfulBounds = null;
          this.updateInProgress = false;
          return null;
        }
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
      this.dataStale = false;
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
      
      // If camera moved since last good fetch, mark cache stale to avoid showing wrong region
      if (bounds && this.boundsChangedSignificantly(bounds, this.lastSuccessfulBounds)) {
        this.dataStale = true;
        this.lastSuccessfulData = null;
        this.lastSuccessfulBounds = null;
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
    // Input validation
    if (!isFinite(lat) || !isFinite(lon) || !isFinite(alt) || 
        !isFinite(heading) || !isFinite(speed) || !isFinite(timeSeconds) ||
        speed < 0 || heading < 0 || heading > 360 || timeSeconds < 0) {
      console.warn('[OpenSky ADS-B] Invalid input for position calculation:', {lat, lon, alt, heading, speed, timeSeconds});
      return { latitude: lat, longitude: lon, altitude: alt };
    }
    
    // Convert heading to radians (0° = North, clockwise)
    const headingRad = Cesium.Math.toRadians(heading);
    
    // Calculate horizontal distance traveled
    const horizontalDistance = speed * timeSeconds; // meters
    
    // Calculate altitude change
    const altitudeChange = (verticalRate || 0) * timeSeconds;
    const newAltitude = alt + altitudeChange;
    
    // Use geodesic calculations for accurate position
    const ellipsoid = Cesium.Ellipsoid.WGS84;
    const earthRadius = ellipsoid.maximumRadius;
    
    // North and East components (aviation standard: 0°=North, 90°=East)
    const north = horizontalDistance * Math.cos(headingRad);
    const east = horizontalDistance * Math.sin(headingRad);
    
    // Convert to lat/lon deltas
    const deltaLat = north / earthRadius;
    
    // Handle poles: avoid division by zero when cos(lat) ≈ 0
    const latRad = Cesium.Math.toRadians(lat);
    const cosLat = Math.cos(latRad);
    
    // If near poles (±85° or more), use simplified calculation
    if (Math.abs(lat) > 85) {
      // Near poles: longitude changes are minimal, use simplified approach
      const deltaLon = east / (earthRadius * Math.max(0.087, Math.abs(cosLat))); // Clamp to prevent division by zero
      const newLat = lat + Cesium.Math.toDegrees(deltaLat);
      const newLon = lon + Cesium.Math.toDegrees(deltaLon);
      
      // Normalize longitude to -180 to 180
      let normalizedLon = newLon;
      while (normalizedLon > 180) normalizedLon -= 360;
      while (normalizedLon < -180) normalizedLon += 360;
      
      return {
        latitude: Math.max(-90, Math.min(90, newLat)), // Clamp latitude
        longitude: normalizedLon,
        altitude: newAltitude
      };
    }
    
    // Standard calculation for non-polar regions
    const deltaLon = east / (earthRadius * cosLat);
    const newLat = lat + Cesium.Math.toDegrees(deltaLat);
    const newLon = lon + Cesium.Math.toDegrees(deltaLon);
    
    // Normalize longitude to -180 to 180
    let normalizedLon = newLon;
    while (normalizedLon > 180) normalizedLon -= 360;
    while (normalizedLon < -180) normalizedLon += 360;
    
    return {
      latitude: Math.max(-90, Math.min(90, newLat)), // Clamp latitude to valid range
      longitude: normalizedLon,
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
   * Calculate distance from camera to aircraft position
   */
  getDistanceFromCamera(aircraftLat, aircraftLon) {
    try {
      const camera = this.viewer.camera;
      const cameraPos = camera.positionCartographic;
      
      if (!cameraPos) return Infinity;
      
      const cameraLat = Cesium.Math.toDegrees(cameraPos.latitude);
      const cameraLon = Cesium.Math.toDegrees(cameraPos.longitude);
      
      // Calculate distance using geodesic
      const startCart = Cesium.Cartographic.fromDegrees(cameraLon, cameraLat);
      const endCart = Cesium.Cartographic.fromDegrees(aircraftLon, aircraftLat);
      
      const geodesic = new Cesium.EllipsoidGeodesic(startCart, endCart);
      const distance = geodesic.surfaceDistance; // meters
      
      return distance;
    } catch (error) {
      return Infinity;
    }
  }

  /**
   * Check if camera has moved significantly
   */
  hasCameraMovedSignificantly() {
    try {
      const camera = this.viewer.camera;
      const currentPos = camera.positionCartographic;
      
      if (!currentPos || !this.lastCameraPosition) {
        this.lastCameraPosition = {
          lat: Cesium.Math.toDegrees(currentPos.latitude),
          lon: Cesium.Math.toDegrees(currentPos.longitude)
        };
        return true; // First time, consider it moved
      }
      
      const currentLat = Cesium.Math.toDegrees(currentPos.latitude);
      const currentLon = Cesium.Math.toDegrees(currentPos.longitude);
      
      // Calculate distance moved
      const startCart = Cesium.Cartographic.fromDegrees(this.lastCameraPosition.lon, this.lastCameraPosition.lat);
      const endCart = Cesium.Cartographic.fromDegrees(currentLon, currentLat);
      const geodesic = new Cesium.EllipsoidGeodesic(startCart, endCart);
      const distanceMoved = geodesic.surfaceDistance;
      
      if (distanceMoved > this.cameraMovementThreshold) {
        this.lastCameraPosition = { lat: currentLat, lon: currentLon };
        return true;
      }
      
      return false;
    } catch (error) {
      return true; // On error, assume moved
    }
  }

  /**
   * Update all aircraft from API response (optimized)
   */
  async updateAircraft() {
    if (!this.isEnabled) return;

    // Note: Always fetch updates to keep aircraft animation smooth
    // Camera movement check removed - we want animated aircraft even when camera is stationary
    
    const data = await this.fetchAircraftStates();
    
    // If cache is marked stale (e.g., camera moved and fetch failed), clear and wait for fresh data
    if (this.dataStale) {
      this.clearAll();
      this.dataStale = false;
      return;
    }
    
    if (!data || !data.states) {
      return;
    }

    const now = Date.now();
    const seenIcao24s = new Set();
    const updateTime = new Date(now);
    const nextUpdateTime = new Date(now + this.updateIntervalSeconds * 1000);
    
    // Get camera position for distance filtering
    const camera = this.viewer.camera;
    const cameraPos = camera.positionCartographic;
    const cameraLat = cameraPos ? Cesium.Math.toDegrees(cameraPos.latitude) : 0;
    const cameraLon = cameraPos ? Cesium.Math.toDegrees(cameraPos.longitude) : 0;

    // Filter and sort aircraft by distance (closest first)
    const aircraftWithDistance = [];
    
    for (const state of data.states) {
      const aircraft = this.parseStateVector(state);
      
      // Skip if no valid position
      if (aircraft.latitude === null || aircraft.longitude === null ||
          !isFinite(aircraft.latitude) || !isFinite(aircraft.longitude)) {
        continue;
      }
      
      // Validate data ranges
      if (aircraft.latitude < -90 || aircraft.latitude > 90 ||
          aircraft.longitude < -180 || aircraft.longitude > 180) {
        continue;
      }
      
      // Filter by altitude (remove invalid/extreme altitudes)
      const altitude = aircraft.geoAltitude || aircraft.baroAltitude || 0;
      if (altitude < this.minAltitude || altitude > this.maxAltitude) {
        continue;
      }
      
      // Calculate distance from camera
      const distance = this.getDistanceFromCamera(aircraft.latitude, aircraft.longitude);
      
      // Filter by 100km radius
      if (distance > this.maxQueryRadiusM) {
        continue; // Skip aircraft outside 100km radius
      }
      
      // Validate speed and heading if present
      if (aircraft.velocity !== null && (aircraft.velocity < 0 || aircraft.velocity > 1000)) {
        aircraft.velocity = null; // Disable animation for invalid speed
      }
      
      if (aircraft.trueTrack !== null && (aircraft.trueTrack < 0 || aircraft.trueTrack > 360)) {
        aircraft.trueTrack = null; // Disable animation for invalid heading
      }
      
      aircraftWithDistance.push({ aircraft, distance });
    }
    
    // Sort by distance (closest first) and limit count
    aircraftWithDistance.sort((a, b) => a.distance - b.distance);
    const limitedAircraft = aircraftWithDistance.slice(0, this.maxAircraftCount);

    // Update or add aircraft (only closest N aircraft)
    for (const { aircraft } of limitedAircraft) {

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

    const totalFiltered = data.states ? data.states.length - limitedAircraft.length : 0;
    console.log(`[OpenSky ADS-B] Updated: ${seenIcao24s.size} aircraft visible (${totalFiltered} filtered by distance/altitude, radius: ${this.maxQueryRadiusKm}km, max: ${this.maxAircraftCount}, animated: ${this.animationEnabled}, interval: ${this.adaptiveInterval.toFixed(1)}s)`);
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
    if (altitude && isFinite(altitude) && altitude > -1000 && altitude < 100000) {
      console.log(`[OpenSky ADS-B] Added aircraft ${aircraft.icao24} at ${aircraft.latitude.toFixed(4)}, ${aircraft.longitude.toFixed(4)}, alt: ${altitude.toFixed(0)}m, speed: ${aircraft.velocity?.toFixed(0) || 0}m/s, heading: ${aircraft.trueTrack?.toFixed(0) || 0}°`);
    } else {
      console.warn(`[OpenSky ADS-B] Added aircraft ${aircraft.icao24} with invalid altitude: ${altitude}`);
    }
    
    // Verify entity is visible
    if (entity && this.viewer) {
      // Check if entity is in view
      try {
        const boundingSphere = entity.boundingSphere;
        if (boundingSphere) {
          const inView = this.viewer.camera.viewRectangle.intersect(boundingSphere);
          if (!inView) {
            console.log(`[OpenSky ADS-B] Aircraft ${aircraft.icao24} added but may be outside view`);
          }
        }
      } catch (e) {
        // Bounding sphere may not be available yet, ignore
      }
    }
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
  start(intervalSeconds = 10) {
    if (this.isEnabled) {
      console.log('[OpenSky ADS-B] Already running');
      return;
    }

    this.isEnabled = true;
    const clampedInterval = Math.max(intervalSeconds, this.minIntervalSeconds);
    this.updateIntervalSeconds = clampedInterval;
    this.adaptiveInterval = clampedInterval; // Start with requested interval respecting floor

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


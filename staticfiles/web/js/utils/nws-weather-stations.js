/**
 * NWS Weather Station Layer
 * Displays weather stations from National Weather Service API as Cesium entities
 */
import { ErrorHandler } from './errors.js';

export class NWSWeatherStationLayer {
  constructor(viewer) {
    this.viewer = viewer;
    this.stations = new Map();
    this.updateInterval = null;
    this.updateIntervalMinutes = 15;
    this.isEnabled = false;
  }

  /**
   * Add a weather station by station ID
   */
  async addStation(stationId) {
    try {
      // Check if station already exists
      if (this.stations.has(stationId)) {
        console.log(`Station ${stationId} already exists, skipping`);
        return this.stations.get(stationId).entity;
      }

      // Check if entity already exists in viewer (in case it was added outside this layer)
      const existingEntity = this.viewer.entities.getById(`weather_${stationId}`);
      if (existingEntity) {
        console.log(`Entity for station ${stationId} already exists in viewer, using existing`);
        // Try to get position from existing entity
        let lat = null, lon = null;
        try {
          if (existingEntity.position) {
            const cartographic = Cesium.Cartographic.fromCartesian(existingEntity.position.getValue());
            lat = Cesium.Math.toDegrees(cartographic.latitude);
            lon = Cesium.Math.toDegrees(cartographic.longitude);
          }
        } catch (e) {
          console.warn(`Could not extract position from existing entity for ${stationId}`);
        }
        this.stations.set(stationId, {
          entity: existingEntity,
          stationId: stationId,
          lat: lat,
          lon: lon,
          lastUpdate: new Date()
        });
        return existingEntity;
      }

      // Get station info
      const stationInfo = await this.getStationInfo(stationId);
      if (!stationInfo || !stationInfo.properties) {
        console.warn(`Station info not found for ${stationId}`);
        return null;
      }

      // Get latest observation
      const observation = await this.getLatestObservation(stationId);
      if (!observation || !observation.properties) {
        console.warn(`Observation not found for ${stationId}`);
        return null;
      }

      const props = observation.properties;
      
      // NWS API returns GeoJSON format - coordinates are in geometry.coordinates as [lon, lat]
      let lat, lon;
      if (stationInfo.geometry && stationInfo.geometry.coordinates && Array.isArray(stationInfo.geometry.coordinates)) {
        // GeoJSON format: [longitude, latitude]
        lon = stationInfo.geometry.coordinates[0];
        lat = stationInfo.geometry.coordinates[1];
      } else if (stationInfo.properties && stationInfo.properties.latitude !== undefined && stationInfo.properties.longitude !== undefined) {
        // Fallback: check if coordinates are in properties (some APIs use this)
        lat = stationInfo.properties.latitude;
        lon = stationInfo.properties.longitude;
      }

      if (lat === undefined || lon === undefined || isNaN(lat) || isNaN(lon)) {
        console.warn(`Invalid coordinates for station ${stationId}`, {
          hasGeometry: !!stationInfo.geometry,
          hasCoordinates: !!(stationInfo.geometry && stationInfo.geometry.coordinates),
          properties: stationInfo.properties
        });
        return null;
      }

      // Create Cesium entity with billboard icon
      const entity = this.viewer.entities.add({
        id: `weather_${stationId}`,
        position: Cesium.Cartesian3.fromDegrees(lon, lat),
        billboard: {
          image: this.getWeatherIcon(props.temperature?.value, props.relativeHumidity?.value),
          width: 32,
          height: 32,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          scale: 1.0,
          disableDepthTestDistance: Number.POSITIVE_INFINITY // Always on top
        },
        point: {
          pixelSize: 8,
          color: this.getTemperatureColor(props.temperature?.value),
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: 1,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          scaleByDistance: new Cesium.NearFarScalar(1.5e2, 1.0, 8.0e6, 0.5) // Scale with distance
        },
        label: {
          text: `${this.formatTemp(props.temperature?.value)}°F`,
          font: '12pt sans-serif',
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          pixelOffset: new Cesium.Cartesian2(0, -40),
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          scaleByDistance: new Cesium.NearFarScalar(1.5e2, 1.0, 8.0e6, 0.5) // Scale with distance
        },
        description: this.createDescription(stationInfo, observation)
      });

      // Create wind vector visualization
      const windSpeed = props.windSpeed?.value;
      const windDirection = props.windDirection?.value;
      console.log(`[Wind Vector] Station ${stationId}: windSpeed=${windSpeed}, windDirection=${windDirection}`);
      
      const windVectorEntity = this.createWindVector(stationId, lon, lat, windSpeed, windDirection);
      if (windVectorEntity) {
        console.log(`[Wind Vector] Created wind vector for ${stationId}`);
      } else {
        console.log(`[Wind Vector] No wind vector created for ${stationId} (missing or invalid wind data)`);
      }

      this.stations.set(stationId, {
        entity: entity,
        windVector: windVectorEntity,
        stationId: stationId,
        lat: lat,
        lon: lon,
        lastUpdate: new Date()
      });

      console.log(`Added weather station: ${stationId} at ${lat}, ${lon}`);
      return entity;
    } catch (error) {
      console.error(`Error adding station ${stationId}:`, error);
      ErrorHandler.handleLayerError(error, null, null, null, 'addStation');
      return null;
    }
  }

  /**
   * Add multiple stations
   */
  async addStations(stationIds) {
    const results = await Promise.allSettled(
      stationIds.map(id => this.addStation(id))
    );
    
    const successful = results.filter(r => r.status === 'fulfilled' && r.value !== null).length;
    console.log(`Added ${successful} of ${stationIds.length} weather stations`);
    return results;
  }

  /**
   * Get station info from NWS API
   */
  async getStationInfo(stationId) {
    const url = `https://api.weather.gov/stations/${stationId}`;
    try {
      const response = await fetch(url, {
        headers: {
          'Accept': 'application/json',
          'User-Agent': 'DeepGIS-XR/1.0'
        }
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error(`Error fetching station info for ${stationId}:`, error);
      throw error;
    }
  }

  /**
   * Get latest observation from NWS API
   */
  async getLatestObservation(stationId) {
    const url = `https://api.weather.gov/stations/${stationId}/observations/latest`;
    try {
      const response = await fetch(url, {
        headers: {
          'Accept': 'application/json',
          'User-Agent': 'DeepGIS-XR/1.0'
        }
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error(`Error fetching observation for ${stationId}:`, error);
      throw error;
    }
  }

  /**
   * Update station observation
   */
  async updateStation(stationId) {
    const station = this.stations.get(stationId);
    if (!station) {
      console.warn(`Station ${stationId} not found for update`);
      return false;
    }

    try {
      const observation = await this.getLatestObservation(stationId);
      if (!observation || !observation.properties) {
        console.warn(`No observation data for ${stationId}`);
        return false;
      }

      this.updateStationEntity(station, observation);
      station.lastUpdate = new Date();
      return true;
    } catch (error) {
      console.error(`Error updating station ${stationId}:`, error);
      return false;
    }
  }

  /**
   * Update station entity with new observation
   */
  updateStationEntity(station, observation) {
    const props = observation.properties;
    const entity = station.entity;

    // Update temperature label and icon
    if (props.temperature?.value !== undefined) {
      const tempF = this.formatTemp(props.temperature.value);
      entity.label.text = `${tempF}°F`;
      entity.point.color = this.getTemperatureColor(props.temperature.value);
      // Update billboard icon if it exists
      if (entity.billboard) {
        entity.billboard.image = this.getWeatherIcon(
          props.temperature.value, 
          props.relativeHumidity?.value
        );
      }
    }

    // Update wind vector
    const windSpeed = props.windSpeed?.value;
    const windDirection = props.windDirection?.value;
    console.log(`[Wind Vector Update] Station ${station.stationId}: windSpeed=${windSpeed}, windDirection=${windDirection}`);
    this.updateWindVector(station, windSpeed, windDirection);

    // Update description
    entity.description = this.createDescription(
      { properties: { name: station.stationId } },
      observation
    );
  }

  /**
   * Update all stations
   */
  async updateAllStations() {
    if (this.stations.size === 0) return;

    console.log(`Updating ${this.stations.size} weather stations...`);
    const promises = Array.from(this.stations.keys()).map(stationId => 
      this.updateStation(stationId).catch(error => {
        console.error(`Failed to update station ${stationId}:`, error);
        return false;
      })
    );
    
    const results = await Promise.allSettled(promises);
    const successful = results.filter(r => r.status === 'fulfilled' && r.value === true).length;
    console.log(`Updated ${successful} of ${this.stations.size} stations`);
  }

  /**
   * Get time series data for a station
   */
  async getTimeSeries(stationId, startTime, endTime) {
    const url = `https://api.weather.gov/stations/${stationId}/observations`;
    const params = new URLSearchParams({
      start: startTime.toISOString(),
      end: endTime.toISOString()
    });
    
    try {
      const response = await fetch(`${url}?${params}`, {
        headers: {
          'Accept': 'application/json',
          'User-Agent': 'DeepGIS-XR/1.0'
        }
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error(`Error fetching time series for ${stationId}:`, error);
      throw error;
    }
  }

  /**
   * Create HTML description for popup
   */
  createDescription(stationInfo, observation) {
    const props = observation.properties;
    const temp = props.temperature?.value;
    const humidity = props.relativeHumidity?.value;
    const windSpeed = props.windSpeed?.value;
    const windDir = props.windDirection?.value;
    const pressure = props.barometricPressure?.value;
    const visibility = props.visibility?.value;
    const stationName = stationInfo.properties?.name || stationInfo.properties?.stationIdentifier || 'Weather Station';

    return `
      <div style="font-family: sans-serif; padding: 10px; max-width: 300px;">
        <h3 style="margin-top: 0;">${stationName}</h3>
        <table style="width: 100%; border-collapse: collapse;">
          <tr>
            <td style="padding: 4px; font-weight: bold;">Temperature:</td>
            <td style="padding: 4px;">${temp !== undefined ? this.formatTemp(temp) + '°F' : 'N/A'}</td>
          </tr>
          <tr>
            <td style="padding: 4px; font-weight: bold;">Humidity:</td>
            <td style="padding: 4px;">${humidity !== undefined && humidity !== null ? humidity.toFixed(1) + '%' : 'N/A'}</td>
          </tr>
          <tr>
            <td style="padding: 4px; font-weight: bold;">Wind Speed:</td>
            <td style="padding: 4px;">${windSpeed !== undefined && windSpeed !== null ? (windSpeed * 2.237).toFixed(1) + ' mph' : 'N/A'}</td>
          </tr>
          <tr>
            <td style="padding: 4px; font-weight: bold;">Wind Direction:</td>
            <td style="padding: 4px;">${windDir !== undefined && windDir !== null ? windDir.toFixed(0) + '°' : 'N/A'}</td>
          </tr>
          ${pressure !== undefined ? `
          <tr>
            <td style="padding: 4px; font-weight: bold;">Pressure:</td>
            <td style="padding: 4px;">${(pressure / 100).toFixed(2)} hPa</td>
          </tr>
          ` : ''}
          ${visibility !== undefined ? `
          <tr>
            <td style="padding: 4px; font-weight: bold;">Visibility:</td>
            <td style="padding: 4px;">${(visibility * 0.000621371).toFixed(1)} mi</td>
          </tr>
          ` : ''}
          <tr>
            <td style="padding: 4px; font-weight: bold;">Updated:</td>
            <td style="padding: 4px;">${new Date(props.timestamp).toLocaleString()}</td>
          </tr>
        </table>
      </div>
    `;
  }

  /**
   * Get weather icon based on temperature and conditions
   * Returns a data URI for a weather icon
   */
  getWeatherIcon(tempC, humidity) {
    // Create a simple weather icon using canvas
    const canvas = document.createElement('canvas');
    canvas.width = 32;
    canvas.height = 32;
    const ctx = canvas.getContext('2d');
    
    // Determine icon type based on temperature and humidity
    let iconType = 'sunny'; // default
    if (tempC !== undefined && tempC !== null) {
      const tempF = (tempC * 9/5) + 32;
      if (tempF < 32) {
        iconType = 'snow';
      } else if (tempF < 50) {
        iconType = 'cloudy';
      } else if (humidity !== undefined && humidity > 70) {
        iconType = 'rainy';
      } else {
        iconType = 'sunny';
      }
    }
    
    // Draw icon based on type
    ctx.clearRect(0, 0, 32, 32);
    
    if (iconType === 'sunny') {
      // Sun icon
      ctx.fillStyle = '#FFD700';
      ctx.beginPath();
      ctx.arc(16, 16, 10, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#FFA500';
      ctx.lineWidth = 2;
      ctx.stroke();
    } else if (iconType === 'cloudy') {
      // Cloud icon
      ctx.fillStyle = '#CCCCCC';
      ctx.beginPath();
      ctx.arc(12, 16, 6, 0, Math.PI * 2);
      ctx.arc(20, 16, 8, 0, Math.PI * 2);
      ctx.fill();
    } else if (iconType === 'rainy') {
      // Rain cloud
      ctx.fillStyle = '#888888';
      ctx.beginPath();
      ctx.arc(12, 14, 6, 0, Math.PI * 2);
      ctx.arc(20, 14, 8, 0, Math.PI * 2);
      ctx.fill();
      // Rain drops
      ctx.fillStyle = '#4A90E2';
      ctx.fillRect(10, 20, 2, 4);
      ctx.fillRect(15, 22, 2, 4);
      ctx.fillRect(20, 20, 2, 4);
    } else if (iconType === 'snow') {
      // Snowflake
      ctx.strokeStyle = '#FFFFFF';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(16, 8);
      ctx.lineTo(16, 24);
      ctx.moveTo(8, 16);
      ctx.lineTo(24, 16);
      ctx.moveTo(11, 11);
      ctx.lineTo(21, 21);
      ctx.moveTo(21, 11);
      ctx.lineTo(11, 21);
      ctx.stroke();
    }
    
    return canvas.toDataURL();
  }

  /**
   * Get color based on temperature
   */
  getTemperatureColor(tempC) {
    if (tempC === undefined || tempC === null) return Cesium.Color.WHITE;
    const tempF = (tempC * 9/5) + 32;
    
    // Color scale: cyan (freezing) -> blue (cold) -> green (cool) -> yellow (warm) -> red (hot)
    if (tempF < 32) return Cesium.Color.CYAN;      // Freezing
    if (tempF < 50) return Cesium.Color.BLUE;     // Cold
    if (tempF < 70) return Cesium.Color.GREEN;     // Cool
    if (tempF < 85) return Cesium.Color.YELLOW;    // Warm
    return Cesium.Color.RED;                        // Hot
  }

  /**
   * Format temperature from Celsius to Fahrenheit
   */
  formatTemp(tempC) {
    if (tempC === undefined || tempC === null) return 'N/A';
    return Math.round((tempC * 9/5) + 32);
  }

  /**
   * Start auto-update
   */
  startAutoUpdate(intervalMinutes = 15) {
    if (this.updateInterval) {
      this.stopAutoUpdate();
    }

    this.updateIntervalMinutes = intervalMinutes;
    this.updateInterval = setInterval(() => {
      this.updateAllStations();
    }, intervalMinutes * 60 * 1000);

    console.log(`Started auto-update for weather stations (every ${intervalMinutes} minutes)`);
  }

  /**
   * Stop auto-update
   */
  stopAutoUpdate() {
    if (this.updateInterval) {
      clearInterval(this.updateInterval);
      this.updateInterval = null;
      console.log('Stopped auto-update for weather stations');
    }
  }

  /**
   * Helper function to calculate a point at a given distance and bearing from a start point
   */
  calculateDestinationPoint(startLatRad, startLonRad, distanceMeters, bearingRad, earthRadius = 6378137) {
    const latRad = Math.asin(
      Math.sin(startLatRad) * Math.cos(distanceMeters / earthRadius) +
      Math.cos(startLatRad) * Math.sin(distanceMeters / earthRadius) * Math.cos(bearingRad)
    );
    const lonRad = startLonRad + Math.atan2(
      Math.sin(bearingRad) * Math.sin(distanceMeters / earthRadius) * Math.cos(startLatRad),
      Math.cos(distanceMeters / earthRadius) - Math.sin(startLatRad) * Math.sin(latRad)
    );
    return {
      lat: Cesium.Math.toDegrees(latRad),
      lon: Cesium.Math.toDegrees(lonRad),
      latRad: latRad,
      lonRad: lonRad
    };
  }

  /**
   * Create wind vector visualization
   */
  createWindVector(stationId, lon, lat, windSpeed, windDirection) {
    // Check if wind data is available
    // Note: windSpeed can be 0, so we only check for null/undefined
    if (windSpeed === undefined || windSpeed === null ||
        windDirection === undefined || windDirection === null) {
      console.log(`[Wind Vector] Missing data for ${stationId}: speed=${windSpeed}, direction=${windDirection}`);
      return null;
    }
    
    // Allow wind speed of 0 but make minimum visible length
    const minWindSpeed = 0.1; // m/s - minimum to show a vector
    if (windSpeed < minWindSpeed) {
      console.log(`[Wind Vector] Wind speed too low for ${stationId}: ${windSpeed} m/s`);
      return null;
    }

    // Wind direction is where wind comes FROM, so we add 180° to get direction wind is blowing TO
    const windBearing = (windDirection + 180) % 360;
    const windBearingRad = Cesium.Math.toRadians(windBearing);

    // Scale wind speed to a reasonable visual length (meters)
    // Wind speed is in m/s, scale: 1 m/s = 1000 meters of arrow length
    // Cap at reasonable max length (e.g., 50 km for very high winds)
    const baseScale = 1000; // meters per m/s
    const maxLength = 50000; // maximum arrow length in meters
    const arrowLength = Math.min(windSpeed * baseScale, maxLength);

    // Calculate end point of wind vector
    const startPosition = Cesium.Cartesian3.fromDegrees(lon, lat);
    const heading = windBearingRad;
    
    // Use a simple approximation for small distances on the globe
    // For more accuracy, we could use geodesic calculations
    const earthRadius = 6378137; // meters
    const latRad = Cesium.Math.toRadians(lat);
    const lonRad = Cesium.Math.toRadians(lon);
    
    // Calculate end point using geodesic calculation
    const endPoint = this.calculateDestinationPoint(latRad, lonRad, arrowLength, heading);
    const endLatRad = endPoint.latRad;
    const endLonRad = endPoint.lonRad;
    const endLon = endPoint.lon;
    const endLat = endPoint.lat;
    const endPosition = Cesium.Cartesian3.fromDegrees(endLon, endLat);

    // Create polyline for wind vector shaft
    const windVectorEntity = this.viewer.entities.add({
      id: `weather_${stationId}_wind_vector`,
      polyline: {
        positions: [startPosition, endPosition],
        width: 4,
        material: Cesium.Color.CYAN.withAlpha(0.9),
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        clampToGround: true,
        scaleByDistance: new Cesium.NearFarScalar(1.5e2, 1.0, 8.0e6, 0.3),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 1.0e7),
        show: true
      }
    });

    // Create arrowhead at the end of the wind vector using proper geodesic calculations
    // Arrowhead should be a triangle pointing in the wind direction
    // Size: proportional to arrow length, but reasonable limits
    const arrowheadSizeMeters = Math.min(Math.max(arrowLength * 0.08, 300), 3000); // 8% of length, 300m-3km range
    const arrowheadBaseWidthMeters = arrowheadSizeMeters * 0.5; // Base width is 50% of arrowhead size
    
    // Calculate arrowhead points using geodesic calculations
    // Tip: extends slightly beyond end point in wind direction
    const tipExtensionMeters = arrowheadSizeMeters * 0.4;
    const tipDistance = arrowLength + tipExtensionMeters;
    const tipPoint = this.calculateDestinationPoint(latRad, lonRad, tipDistance, heading);
    const tipPosition = Cesium.Cartesian3.fromDegrees(tipPoint.lon, tipPoint.lat);
    
    // Base points: perpendicular to wind direction at the end point
    // Calculate perpendicular bearing (90 degrees from wind direction)
    const perpBearing1 = (windBearing + 90) % 360;
    const perpBearing2 = (windBearing - 90 + 360) % 360;
    const perpBearing1Rad = Cesium.Math.toRadians(perpBearing1);
    const perpBearing2Rad = Cesium.Math.toRadians(perpBearing2);
    
    // Calculate base point 1 (left side when looking in wind direction)
    const base1Distance = arrowheadBaseWidthMeters / 2;
    const base1Point = this.calculateDestinationPoint(endLatRad, endLonRad, base1Distance, perpBearing1Rad);
    const base1Position = Cesium.Cartesian3.fromDegrees(base1Point.lon, base1Point.lat);
    
    // Calculate base point 2 (right side when looking in wind direction)
    const base2Point = this.calculateDestinationPoint(endLatRad, endLonRad, base1Distance, perpBearing2Rad);
    const base2Position = Cesium.Cartesian3.fromDegrees(base2Point.lon, base2Point.lat);
    
    // Create arrowhead triangle: tip at the front, base points at the back
    // Order: base1 -> tip -> base2 (creates a triangle pointing forward)
    const arrowheadPositions = [
      base1Position,
      tipPosition,
      base2Position
    ];
    
    const arrowheadEntity = this.viewer.entities.add({
      id: `weather_${stationId}_wind_arrowhead`,
      polygon: {
        hierarchy: new Cesium.PolygonHierarchy(arrowheadPositions),
        material: Cesium.Color.CYAN.withAlpha(0.9),
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        outline: true,
        outlineColor: Cesium.Color.CYAN,
        outlineWidth: 2,
        scaleByDistance: new Cesium.NearFarScalar(1.5e2, 1.0, 8.0e6, 0.3),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 1.0e7),
        show: true
      }
    });

    // Add a label showing wind speed at the midpoint of the vector
    const midLon = (lon + endLon) / 2;
    const midLat = (lat + endLat) / 2;
    const midPosition = Cesium.Cartesian3.fromDegrees(midLon, midLat);
    
    const windLabelEntity = this.viewer.entities.add({
      id: `weather_${stationId}_wind_label`,
      position: midPosition,
      label: {
        text: `${(windSpeed * 2.237).toFixed(1)} mph`, // Convert m/s to mph
        font: '11pt sans-serif',
        fillColor: Cesium.Color.CYAN,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        pixelOffset: new Cesium.Cartesian2(0, -15),
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        scaleByDistance: new Cesium.NearFarScalar(1.5e2, 1.0, 8.0e6, 0.3),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 1.0e7),
        show: true
      }
    });

    // Store all entities
    return {
      vector: windVectorEntity,
      arrowhead: arrowheadEntity,
      label: windLabelEntity
    };
  }

  /**
   * Update wind vector visualization
   */
  updateWindVector(station, windSpeed, windDirection) {
    // Remove existing wind vector if it exists
    if (station.windVector) {
      if (station.windVector.vector) {
        this.viewer.entities.remove(station.windVector.vector);
      }
      if (station.windVector.arrowhead) {
        this.viewer.entities.remove(station.windVector.arrowhead);
      }
      if (station.windVector.label) {
        this.viewer.entities.remove(station.windVector.label);
      }
      station.windVector = null;
    }

    // Create new wind vector if wind data is available
    // Use same logic as createWindVector
    if (windSpeed !== undefined && windSpeed !== null &&
        windDirection !== undefined && windDirection !== null) {
      const minWindSpeed = 0.1; // m/s - minimum to show a vector
      if (windSpeed >= minWindSpeed) {
        station.windVector = this.createWindVector(
          station.stationId,
          station.lon,
          station.lat,
          windSpeed,
          windDirection
        );
        if (station.windVector) {
          console.log(`[Wind Vector Update] Created wind vector for ${station.stationId}`);
        }
      } else {
        console.log(`[Wind Vector Update] Wind speed too low for ${station.stationId}: ${windSpeed} m/s`);
      }
    } else {
      console.log(`[Wind Vector Update] Missing wind data for ${station.stationId}: speed=${windSpeed}, direction=${windDirection}`);
    }
  }

  /**
   * Remove station
   */
  removeStation(stationId) {
    const station = this.stations.get(stationId);
    if (station) {
      this.viewer.entities.remove(station.entity);
      // Remove wind vector entities if they exist
      if (station.windVector) {
        if (station.windVector.vector) {
          this.viewer.entities.remove(station.windVector.vector);
        }
        if (station.windVector.arrowhead) {
          this.viewer.entities.remove(station.windVector.arrowhead);
        }
        if (station.windVector.label) {
          this.viewer.entities.remove(station.windVector.label);
        }
      }
      this.stations.delete(stationId);
      console.log(`Removed weather station: ${stationId}`);
    }
  }

  /**
   * Remove all stations
   */
  removeAllStations() {
    this.stations.forEach((station) => {
      this.viewer.entities.remove(station.entity);
      // Remove wind vector entities if they exist
      if (station.windVector) {
        if (station.windVector.vector) {
          this.viewer.entities.remove(station.windVector.vector);
        }
        if (station.windVector.arrowhead) {
          this.viewer.entities.remove(station.windVector.arrowhead);
        }
        if (station.windVector.label) {
          this.viewer.entities.remove(station.windVector.label);
        }
      }
    });
    this.stations.clear();
    this.stopAutoUpdate();
    this.isEnabled = false;
    console.log('Removed all weather stations');
  }

  /**
   * Show all stations
   */
  showAll() {
    this.stations.forEach((station) => {
      station.entity.show = true;
      // Show wind vectors if they exist
      if (station.windVector) {
        if (station.windVector.vector) {
          station.windVector.vector.show = true;
        }
        if (station.windVector.arrowhead) {
          station.windVector.arrowhead.show = true;
        }
        if (station.windVector.label) {
          station.windVector.label.show = true;
        }
      }
    });
  }

  /**
   * Hide all stations
   */
  hideAll() {
    this.stations.forEach((station) => {
      station.entity.show = false;
      // Hide wind vectors if they exist
      if (station.windVector) {
        if (station.windVector.vector) {
          station.windVector.vector.show = false;
        }
        if (station.windVector.arrowhead) {
          station.windVector.arrowhead.show = false;
        }
        if (station.windVector.label) {
          station.windVector.label.show = false;
        }
      }
    });
  }

  /**
   * Get station count
   */
  getStationCount() {
    return this.stations.size;
  }

  /**
   * Get all station IDs
   */
  getStationIds() {
    return Array.from(this.stations.keys());
  }
}


/**
 * OpenTopography LiDAR Data Search
 * Searches for available LiDAR/point cloud datasets in the current viewport area
 */

export class OpenTopographyLidarSearch {
  constructor(viewer) {
    this.viewer = viewer;
    this.apiEndpoint = '/api/opentopography/lidar-search';
  }

  /**
   * Get viewport bounds from Cesium camera
   */
  getViewportBounds() {
    try {
      const rectangle = this.viewer.camera.computeViewRectangle();
      
      if (!rectangle) {
        // If computeViewRectangle returns null (e.g., looking straight down from space),
        // calculate bounds from camera position and altitude
        const position = this.viewer.camera.positionCartographic;
        const height = position.height;
        const lat = Cesium.Math.toDegrees(position.latitude);
        const lon = Cesium.Math.toDegrees(position.longitude);
        
        // Estimate viewport size based on altitude and FOV
        const fov = this.viewer.camera.frustum.fov || Cesium.Math.toRadians(60);
        const halfFov = fov / 2;
        const groundDistance = height * Math.tan(halfFov);
        
        // Convert to degrees (approximate)
        const metersPerDegLat = 111320;
        const metersPerDegLon = 111320 * Math.cos(Cesium.Math.toRadians(lat));
        
        const deltaLat = groundDistance / metersPerDegLat;
        const deltaLon = groundDistance / metersPerDegLon;
        
        return {
          west: lon - deltaLon,
          east: lon + deltaLon,
          south: lat - deltaLat,
          north: lat + deltaLat
        };
      }
      
      return {
        west: Cesium.Math.toDegrees(rectangle.west),
        east: Cesium.Math.toDegrees(rectangle.east),
        south: Cesium.Math.toDegrees(rectangle.south),
        north: Cesium.Math.toDegrees(rectangle.north)
      };
    } catch (error) {
      console.error('Error computing viewport bounds:', error);
      return null;
    }
  }

  /**
   * Search for LiDAR datasets in current viewport
   */
  async searchViewport() {
    const bounds = this.getViewportBounds();
    
    if (!bounds) {
      throw new Error('Could not determine viewport bounds');
    }

    try {
      const url = `${this.apiEndpoint}?` +
        `west=${bounds.west}&` +
        `east=${bounds.east}&` +
        `south=${bounds.south}&` +
        `north=${bounds.north}`;
      
      const response = await fetch(url);
      
      if (!response.ok) {
        throw new Error(`API error: ${response.status} ${response.statusText}`);
      }
      
      const data = await response.json();
      return data;
    } catch (error) {
      console.error('Error searching OpenTopography:', error);
      throw error;
    }
  }

  /**
   * Format bounds for display
   */
  formatBounds(bounds) {
    return {
      west: bounds.west.toFixed(6),
      east: bounds.east.toFixed(6),
      south: bounds.south.toFixed(6),
      north: bounds.north.toFixed(6)
    };
  }

  /**
   * Get viewport area in square kilometers
   */
  getViewportArea(bounds) {
    const lat1 = bounds.south;
    const lat2 = bounds.north;
    const lon1 = bounds.west;
    const lon2 = bounds.east;
    
    // Approximate area calculation using Haversine formula
    const R = 6371; // Earth radius in km
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
              Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
              Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    const distance = R * c;
    
    // Approximate area (simplified - assumes rectangular region)
    const avgLat = (lat1 + lat2) / 2;
    const latDistance = distance;
    const lonDistance = distance * Math.cos(avgLat * Math.PI / 180);
    const area = latDistance * lonDistance;
    
    return area;
  }
}

export default OpenTopographyLidarSearch;


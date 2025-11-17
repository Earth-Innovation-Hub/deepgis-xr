/**
 * Navigation Widgets Module
 * Heading dial and attitude indicator
 */
import { AppState } from '../state.js';

/**
 * Initialize navigation widgets
 */
export function initializeNavigation(viewer) {
  initializeHeadingDial();
  startNavigationUpdates(viewer);
}

/**
 * Initialize heading dial markings and labels
 */
function initializeHeadingDial() {
  const markingsContainer = document.getElementById('headingDialMarkings');
  const labelsContainer = document.getElementById('headingDialLabels');
  
  if (!markingsContainer || !labelsContainer) return;
  
  markingsContainer.innerHTML = '';
  labelsContainer.innerHTML = '';
  
  for (let angle = 0; angle < 360; angle += 10) {
    const mark = document.createElement('div');
    mark.className = angle % 30 === 0 ? 'heading-dial-mark major' : 'heading-dial-mark minor';
    
    const markRadius = angle % 30 === 0 ? 40 : 37;
    const markAngle = (angle - 90) * Math.PI / 180;
    const markX = markRadius * Math.cos(markAngle);
    const markY = markRadius * Math.sin(markAngle);
    
    mark.style.left = `calc(50% + ${markX}px)`;
    mark.style.top = `calc(50% + ${markY}px)`;
    mark.style.transform = `translate(-50%, -50%) rotate(${angle}deg)`;
    
    markingsContainer.appendChild(mark);
    
    if (angle % 30 === 0) {
      const label = document.createElement('div');
      label.className = 'heading-dial-label';
      
      if (angle === 0) {
        label.className += ' north';
        label.textContent = 'N';
      } else if (angle === 90) {
        label.textContent = 'E';
      } else if (angle === 180) {
        label.textContent = 'S';
      } else if (angle === 270) {
        label.textContent = 'W';
      } else {
        label.textContent = (angle / 10).toString().padStart(2, '0');
      }
      
      const labelRadius = 32;
      const labelAngle = (angle - 90) * Math.PI / 180;
      const labelX = labelRadius * Math.cos(labelAngle);
      const labelY = labelRadius * Math.sin(labelAngle);
      
      label.style.left = `calc(50% + ${labelX}px)`;
      label.style.top = `calc(50% + ${labelY}px)`;
      
      labelsContainer.appendChild(label);
    }
  }
}

/**
 * Start navigation widget updates
 */
function startNavigationUpdates(viewer) {
  function updateNavigation() {
    if (!viewer) return;
    
    const camera = viewer.camera;
    const position = camera.positionCartographic;
    
    const longitude = Cesium.Math.toDegrees(position.longitude);
    const latitude = Cesium.Math.toDegrees(position.latitude);
    const altitude = position.height;
    
    const heading = Cesium.Math.toDegrees(camera.heading);
    const pitch = Cesium.Math.toDegrees(camera.pitch);
    const roll = Cesium.Math.toDegrees(camera.roll);
    
    // Calculate approximate zoom level based on altitude
    // Formula: zoom ≈ log2(40075016.686 / (altitude * 0.0254 / 96 / 256))
    // Simplified: zoom ≈ log2(40075016.686 / altitude) - log2(0.0254 / 96 / 256)
    // Web Mercator zoom calculation
    const metersPerPixel = altitude * 0.0254 / 96; // Assuming 96 DPI
    const earthCircumference = 40075016.686; // meters
    const zoom = Math.log2(earthCircumference / (metersPerPixel * 256));
    const zoomLevel = Math.max(0, Math.min(24, zoom)); // Clamp between 0-24
    
    // Update camera info display
    const lonEl = document.getElementById('cameraLon');
    const latEl = document.getElementById('cameraLat');
    const altEl = document.getElementById('cameraAlt');
    const zoomEl = document.getElementById('cameraZoom');
    const headingEl = document.getElementById('cameraHeading');
    const pitchEl = document.getElementById('cameraPitch');
    const rollEl = document.getElementById('cameraRoll');
    
    if (lonEl) lonEl.textContent = longitude.toFixed(6) + '°';
    if (latEl) latEl.textContent = latitude.toFixed(6) + '°';
    if (altEl) altEl.textContent = altitude.toFixed(1) + ' m';
    if (zoomEl) zoomEl.textContent = zoomLevel.toFixed(2);
    if (headingEl) headingEl.textContent = heading.toFixed(1) + '°';
    if (pitchEl) pitchEl.textContent = pitch.toFixed(1) + '°';
    if (rollEl) rollEl.textContent = roll.toFixed(1) + '°';
    
    // Update heading dial
    updateHeadingDial(heading);
    
    // Update attitude indicator
    updateAttitudeIndicator(pitch, roll);
    
    requestAnimationFrame(updateNavigation);
  }
  
  requestAnimationFrame(updateNavigation);
}

function updateHeadingDial(headingDegrees) {
  let normalizedHeading = headingDegrees;
  while (normalizedHeading < 0) normalizedHeading += 360;
  while (normalizedHeading >= 360) normalizedHeading -= 360;
  
  const dialFace = document.getElementById('headingDialFace');
  if (dialFace) {
    dialFace.style.transform = `translate(-50%, -50%) rotate(${-normalizedHeading}deg)`;
  }
  
  const readout = document.getElementById('headingDialReadout');
  if (readout) {
    readout.textContent = `${normalizedHeading.toFixed(0).padStart(3, '0')}°T`;
  }
}

function updateAttitudeIndicator(pitchDegrees, rollDegrees) {
  let normalizedPitch = Math.max(-90, Math.min(90, pitchDegrees));
  let normalizedRoll = rollDegrees;
  while (normalizedRoll > 180) normalizedRoll -= 360;
  while (normalizedRoll < -180) normalizedRoll += 360;
  
  const horizon = document.getElementById('attitudeHorizon');
  if (horizon) {
    const pitchOffset = normalizedPitch * 1.5;
    horizon.style.transform = `translate(-50%, calc(-50% + ${-pitchOffset}px)) rotate(${-normalizedRoll}deg)`;
  }
  
  const readout = document.getElementById('attitudeReadout');
  if (readout) {
    readout.textContent = `${normalizedPitch.toFixed(0).padStart(3, '0')}°P ${normalizedRoll.toFixed(0).padStart(3, '0')}°R`;
  }
}

export default {
  initializeNavigation
};


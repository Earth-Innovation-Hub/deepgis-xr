/**
 * WebXR/VR Feature Module
 * Lazy loaded when VR functionality is needed
 */
import { AppState } from '../js/state.js';

/**
 * Check WebXR support for all available modes
 */
export async function checkWebXRSupport() {
  const statusElement = document.getElementById('vrStatus');
  const enterButton = document.getElementById('enterVR');
  
  try {
    if (!navigator.xr) {
      statusElement.textContent = 'VR Status: WebXR not supported';
      statusElement.style.color = '#ef4444';
      return false;
    }
    
    // Check support for different session modes
    const vrSupported = await navigator.xr.isSessionSupported('immersive-vr');
    const arSupported = await navigator.xr.isSessionSupported('immersive-ar');
    
    // Store support status
    AppState.webxr.isSupported = vrSupported;
    AppState.webxr.vrSupported = vrSupported;
    AppState.webxr.arSupported = arSupported;
    
    // Build status message with available modes
    const supportedModes = [];
    if (vrSupported) supportedModes.push('VR');
    if (arSupported) supportedModes.push('AR/MR');
    
    if (vrSupported || arSupported) {
      const modeText = supportedModes.length > 0 
        ? `WebXR supported! Modes: ${supportedModes.join(', ')}`
        : 'WebXR supported!';
      statusElement.textContent = `VR Status: ${modeText}`;
      statusElement.style.color = '#10b981';
      enterButton.disabled = false;
      
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator(`WebXR support detected: ${supportedModes.join(', ')}`);
      }
      
      console.log('WebXR Support:', {
        'immersive-vr': vrSupported,
        'immersive-ar': arSupported
      });
    } else {
      statusElement.textContent = 'VR Status: WebXR available but no immersive modes supported';
      statusElement.style.color = '#f59e0b';
    }
    
    return vrSupported || arSupported;
    
  } catch (error) {
    console.error('Error checking WebXR support:', error);
    statusElement.textContent = 'VR Status: Error checking support';
    statusElement.style.color = '#ef4444';
    return false;
  }
}

/**
 * Wait for viewer to be fully ready
 */
async function waitForViewerReady(viewer, maxWaitTime = 10000) {
  const startTime = Date.now();
  
  while (Date.now() - startTime < maxWaitTime) {
    // Check if viewer is initialized
    if (!AppState.isInitialized) {
      await new Promise(resolve => setTimeout(resolve, 100));
      continue;
    }
    
    // Check if scene is ready
    if (!viewer || !viewer.scene || !viewer.scene.context) {
      await new Promise(resolve => setTimeout(resolve, 100));
      continue;
    }
    
    // Check if WebGL context is ready
    const gl = viewer.scene.context._gl;
    if (!gl || gl.isContextLost()) {
      await new Promise(resolve => setTimeout(resolve, 100));
      continue;
    }
    
    // Check if scene is in a valid state
    if (viewer.scene.mode === undefined) {
      await new Promise(resolve => setTimeout(resolve, 100));
      continue;
    }
    
    return true;
  }
  
  return false;
}

/**
 * Enter WebXR session
 */
export async function enterWebXR() {
  if (!AppState.webxr.isSupported) {
    if (typeof window.showSnackBar === 'function') {
      window.showSnackBar('WebXR VR not supported on this device');
    }
    return;
  }
  
  const viewer = AppState.viewer;
  if (!viewer) {
    if (typeof window.showSnackBar === 'function') {
      window.showSnackBar('Cesium viewer not initialized');
    }
    return;
  }
  
  try {
    if (typeof window.updateStatusIndicator === 'function') {
      window.updateStatusIndicator('Preparing VR mode...');
    }
    
    // Wait for viewer to be fully ready
    const statusElement = document.getElementById('vrStatus');
    if (statusElement) {
      statusElement.textContent = 'VR Status: Waiting for scene to be ready...';
      statusElement.style.color = '#f59e0b';
    }
    
    const isReady = await waitForViewerReady(viewer);
    if (!isReady) {
      throw new Error('Viewer did not become ready in time');
    }
    
    if (statusElement) {
      statusElement.textContent = 'VR Status: Requesting VR session...';
    }
    
    // Ensure we're in 3D mode for VR
    if (viewer.scene.mode !== Cesium.SceneMode.SCENE3D) {
      viewer.scene.morphTo3D(0);
      // Wait a bit for morph to complete
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    
    if (typeof window.updateStatusIndicator === 'function') {
      window.updateStatusIndicator('Entering VR mode...');
    }
    
    // Determine which session mode to use
    // Prefer AR if available (for passthrough), otherwise use VR
    let sessionMode = 'immersive-vr';
    if (AppState.webxr.arSupported) {
      sessionMode = 'immersive-ar';
      console.log('Using AR mode (passthrough enabled)');
    } else {
      console.log('Using VR mode (full immersive)');
    }
    
    const session = await navigator.xr.requestSession(sessionMode, {
      requiredFeatures: ['local-floor'],
      optionalFeatures: ['hand-tracking', 'layers']
    });
    
    AppState.webxr.sessionMode = sessionMode;
    
    AppState.webxr.session = session;
    AppState.webxr.isInSession = true;
    
    const gl = viewer.scene.context._gl;
    if (!gl || gl.isContextLost()) {
      throw new Error('WebGL context is not available or lost');
    }
    
    AppState.webxr.gl = gl;
    
    // Create base layer with proper configuration
    const baseLayer = new XRWebGLLayer(session, gl, {
      antialias: true,
      depth: true,
      stencil: false,
      alpha: true,
      ignoreDepthValues: false,
      framebufferScaleFactor: 1.0
    });
    AppState.webxr.baseLayer = baseLayer;
    
    await session.updateRenderState({ baseLayer: baseLayer });
    
    const referenceSpace = await session.requestReferenceSpace('local-floor');
    AppState.webxr.referenceSpace = referenceSpace;
    
    // Store initial camera position for VR
    const initialPosition = Cesium.Cartesian3.clone(viewer.camera.position);
    const initialOrientation = Cesium.Quaternion.clone(viewer.camera.quaternion);
    AppState.webxr.initialPosition = initialPosition;
    AppState.webxr.initialOrientation = initialOrientation;
    
    session.addEventListener('end', onXRSessionEnd);
    session.addEventListener('inputsourceschange', onInputSourcesChange);
    
    // Mark XR as ready to render
    AppState.webxr.isReady = true;
    
    // Start rendering loop
    session.requestAnimationFrame(onXRFrame);
    
    document.getElementById('enterVR').disabled = true;
    const exitButton = document.getElementById('exitVR');
    if (exitButton) exitButton.disabled = false;
    
    if (statusElement) {
      statusElement.textContent = 'VR Status: In VR session';
      statusElement.style.color = '#10b981';
    }
    
    if (typeof window.updateStatusIndicator === 'function') {
      window.updateStatusIndicator('VR mode active');
    }
    if (typeof window.showSnackBar === 'function') {
      window.showSnackBar('Entered VR mode successfully!');
    }
    
    console.log('WebXR session started successfully');
    
  } catch (error) {
    console.error('Error entering WebXR:', error);
    AppState.webxr.isInSession = false;
    AppState.webxr.isReady = false;
    
    const statusElement = document.getElementById('vrStatus');
    if (statusElement) {
      statusElement.textContent = 'VR Status: Failed to enter VR';
      statusElement.style.color = '#ef4444';
    }
    
    if (typeof window.updateStatusIndicator === 'function') {
      window.updateStatusIndicator('Failed to enter VR mode');
    }
    if (typeof window.showSnackBar === 'function') {
      window.showSnackBar('Failed to enter VR: ' + error.message);
    }
  }
}

/**
 * Exit WebXR session
 */
export async function exitWebXR() {
  const session = AppState.webxr.session;
  if (session) {
    await session.end();
  }
}

function onXRSessionEnd() {
  AppState.webxr.session = null;
  AppState.webxr.isInSession = false;
  AppState.webxr.isReady = false;
  AppState.webxr.sessionMode = null;
  AppState.webxr.referenceSpace = null;
  AppState.webxr.baseLayer = null;
  AppState.webxr.initialPosition = null;
  AppState.webxr.initialOrientation = null;
  
  const enterButton = document.getElementById('enterVR');
  const exitButton = document.getElementById('exitVR');
  const statusElement = document.getElementById('vrStatus');
  
  if (enterButton) enterButton.disabled = false;
  if (exitButton) exitButton.disabled = true;
  if (statusElement) {
    statusElement.textContent = 'VR Status: Session ended';
    statusElement.style.color = '#cbd5e1';
  }
  
  // Restore camera to original position if available
  const viewer = AppState.viewer;
  if (viewer && AppState.webxr.initialPosition) {
    try {
      viewer.camera.position = AppState.webxr.initialPosition;
      if (AppState.webxr.initialOrientation) {
        viewer.camera.quaternion = AppState.webxr.initialOrientation;
      }
      viewer.scene.requestRender();
    } catch (error) {
      console.warn('Could not restore camera position:', error);
    }
  }
  
  if (typeof window.updateStatusIndicator === 'function') {
    window.updateStatusIndicator('Exited VR mode');
  }
  if (typeof window.showSnackBar === 'function') {
    window.showSnackBar('Exited VR mode');
  }
  
  console.log('WebXR session ended');
}

function onInputSourcesChange(event) {
  console.log('XR input sources changed:', event);
}

function onXRFrame(time, frame) {
  const session = AppState.webxr.session;
  const viewer = AppState.viewer;
  
  if (!session || !viewer) {
    // Session ended, stop rendering
    return;
  }
  
  // Continue the render loop
  session.requestAnimationFrame(onXRFrame);
  
  const gl = AppState.webxr.gl;
  const baseLayer = AppState.webxr.baseLayer;
  const referenceSpace = AppState.webxr.referenceSpace;
  
  if (!gl || !baseLayer || !referenceSpace) {
    return;
  }
  
  // Check if WebGL context is still valid
  if (gl.isContextLost()) {
    console.error('WebGL context lost during XR session');
    return;
  }
  
  // Check if XR is ready to render
  if (!AppState.webxr.isReady) {
    return;
  }
  
  try {
    const pose = frame.getViewerPose(referenceSpace);
    if (!pose) {
      // No pose available yet, skip this frame
      return;
    }
    
    // Bind the XR framebuffer
    gl.bindFramebuffer(gl.FRAMEBUFFER, baseLayer.framebuffer);
    
    // Render each view (left and right eye)
    for (let i = 0; i < pose.views.length; i++) {
      const view = pose.views[i];
      const viewport = baseLayer.getViewport(view);
      
      if (!viewport) {
        console.warn('No viewport for view', i);
        continue;
      }
      
      gl.viewport(viewport.x, viewport.y, viewport.width, viewport.height);
      
      // Update camera for this view
      updateCameraForXRView(viewer, view, pose);
      
      // Ensure scene is ready before rendering
      if (viewer.scene && viewer.scene.context && !viewer.scene.context._gl.isContextLost()) {
        try {
          viewer.scene.render();
        } catch (renderError) {
          console.error('Error rendering scene in XR frame:', renderError);
          // Continue to next view even if this one fails
        }
      }
    }
    
  } catch (error) {
    console.error('Error in XR frame:', error);
    // Don't stop the render loop on error, just log it
  }
}

function updateCameraForXRView(viewer, view, pose) {
  try {
    const camera = viewer.scene.camera;
    if (!camera) return;
    
    const transform = pose.transform;
    if (!transform || !transform.position || !transform.orientation) {
      return;
    }
    
    // Get the XR head position in local space
    const xrPosition = new Cesium.Cartesian3(
      transform.position.x,
      transform.position.y, 
      transform.position.z
    );
    
    // Get the current camera position on the globe
    const currentCartographic = Cesium.Cartographic.fromCartesian(camera.position);
    if (!currentCartographic) {
      return;
    }
    
    // Create a local frame at the camera's current position
    const localFrame = Cesium.Transforms.eastNorthUpToFixedFrame(
      Cesium.Cartesian3.fromRadians(
        currentCartographic.longitude,
        currentCartographic.latitude,
        currentCartographic.height
      )
    );
    
    // Transform XR position to world coordinates
    const worldPosition = Cesium.Matrix4.multiplyByPoint(
      localFrame,
      xrPosition,
      new Cesium.Cartesian3()
    );
    
    // Update camera position
    camera.position = worldPosition;
    
    // Get the view orientation
    const viewTransform = view.transform;
    if (!viewTransform || !viewTransform.orientation) {
      return;
    }
    
    // Create quaternion from XR orientation
    const xrQuaternion = new Cesium.Quaternion(
      viewTransform.orientation.x,
      viewTransform.orientation.y,
      viewTransform.orientation.z,
      viewTransform.orientation.w
    );
    
    // Convert to heading/pitch/roll
    const hpr = Cesium.HeadingPitchRoll.fromQuaternion(xrQuaternion);
    
    // Update camera orientation
    camera.setView({
      orientation: {
        heading: hpr.heading,
        pitch: hpr.pitch,
        roll: hpr.roll
      }
    });
    
    // Update camera projection matrix for this view
    if (view.projectionMatrix) {
      // Note: Cesium doesn't directly support setting projection matrix,
      // but the view transform should handle the stereo projection
      // The view matrix is already applied via the camera position/orientation
    }
    
  } catch (error) {
    console.error('Error updating camera for XR view:', error);
    // Don't throw, just log - allow rendering to continue
  }
}

// Export default object for lazy loading
export default {
  checkWebXRSupport,
  enterWebXR,
  exitWebXR
};


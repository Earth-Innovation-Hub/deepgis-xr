/**
 * WebXR/VR Feature Module
 * Lazy loaded when VR functionality is needed
 */
import { AppState } from '../state.js';

/**
 * Check WebXR support
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
    
    const isSupported = await navigator.xr.isSessionSupported('immersive-vr');
    AppState.webxr.isSupported = isSupported;
    
    if (isSupported) {
      statusElement.textContent = 'VR Status: WebXR supported! Ready for VR.';
      statusElement.style.color = '#10b981';
      enterButton.disabled = false;
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator('WebXR VR support detected');
      }
    } else {
      statusElement.textContent = 'VR Status: WebXR available but VR not supported';
      statusElement.style.color = '#f59e0b';
    }
    
    return isSupported;
    
  } catch (error) {
    console.error('Error checking WebXR support:', error);
    statusElement.textContent = 'VR Status: Error checking support';
    statusElement.style.color = '#ef4444';
    return false;
  }
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
      window.updateStatusIndicator('Entering VR mode...');
    }
    
    const session = await navigator.xr.requestSession('immersive-vr', {
      requiredFeatures: ['local-floor'],
      optionalFeatures: ['hand-tracking', 'layers']
    });
    
    AppState.webxr.session = session;
    AppState.webxr.isInSession = true;
    
    const gl = viewer.scene.context._gl;
    AppState.webxr.gl = gl;
    
    const baseLayer = new XRWebGLLayer(session, gl);
    AppState.webxr.baseLayer = baseLayer;
    
    await session.updateRenderState({ baseLayer: baseLayer });
    
    const referenceSpace = await session.requestReferenceSpace('local-floor');
    AppState.webxr.referenceSpace = referenceSpace;
    
    session.addEventListener('end', onXRSessionEnd);
    session.addEventListener('inputsourceschange', onInputSourcesChange);
    
    session.requestAnimationFrame(onXRFrame);
    
    document.getElementById('enterVR').disabled = true;
    document.getElementById('exitVR').disabled = false;
    document.getElementById('vrStatus').textContent = 'VR Status: In VR session';
    document.getElementById('vrStatus').style.color = '#10b981';
    
    if (typeof window.updateStatusIndicator === 'function') {
      window.updateStatusIndicator('VR mode active');
    }
    if (typeof window.showSnackBar === 'function') {
      window.showSnackBar('Entered VR mode successfully!');
    }
    
  } catch (error) {
    console.error('Error entering WebXR:', error);
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
  AppState.webxr.referenceSpace = null;
  AppState.webxr.baseLayer = null;
  
  document.getElementById('enterVR').disabled = false;
  document.getElementById('exitVR').disabled = true;
  document.getElementById('vrStatus').textContent = 'VR Status: Session ended';
  document.getElementById('vrStatus').style.color = '#cbd5e1';
  
  if (typeof window.updateStatusIndicator === 'function') {
    window.updateStatusIndicator('Exited VR mode');
  }
  if (typeof window.showSnackBar === 'function') {
    window.showSnackBar('Exited VR mode');
  }
}

function onInputSourcesChange(event) {
  console.log('XR input sources changed:', event);
}

function onXRFrame(time, frame) {
  const session = AppState.webxr.session;
  const viewer = AppState.viewer;
  
  if (!session || !viewer) return;
  
  session.requestAnimationFrame(onXRFrame);
  
  const gl = AppState.webxr.gl;
  const baseLayer = AppState.webxr.baseLayer;
  const referenceSpace = AppState.webxr.referenceSpace;
  
  if (!gl || !baseLayer || !referenceSpace) return;
  
  try {
    const pose = frame.getViewerPose(referenceSpace);
    if (!pose) return;
    
    gl.bindFramebuffer(gl.FRAMEBUFFER, baseLayer.framebuffer);
    
    for (let i = 0; i < pose.views.length; i++) {
      const view = pose.views[i];
      const viewport = baseLayer.getViewport(view);
      
      gl.viewport(viewport.x, viewport.y, viewport.width, viewport.height);
      
      updateCameraForXRView(viewer, view, pose);
      viewer.scene.render();
    }
    
  } catch (error) {
    console.error('Error in XR frame:', error);
  }
}

function updateCameraForXRView(viewer, view, pose) {
  const camera = viewer.scene.camera;
  const transform = pose.transform;
  const position = new Cesium.Cartesian3(
    transform.position.x,
    transform.position.y, 
    transform.position.z
  );
  
  const worldPosition = Cesium.Matrix4.multiplyByPoint(
    viewer.scene.globe.ellipsoid.eastNorthUpToFixedFrame(camera.position),
    position,
    new Cesium.Cartesian3()
  );
  
  camera.position = worldPosition;
  
  const orientation = new Cesium.Quaternion(
    view.transform.orientation.x,
    view.transform.orientation.y,
    view.transform.orientation.z,
    view.transform.orientation.w
  );
  
  const hpr = Cesium.HeadingPitchRoll.fromQuaternion(orientation);
  camera.setView({
    orientation: {
      heading: hpr.heading,
      pitch: hpr.pitch,
      roll: hpr.roll
    }
  });
}

// Export default object for lazy loading
export default {
  checkWebXRSupport,
  enterWebXR,
  exitWebXR
};


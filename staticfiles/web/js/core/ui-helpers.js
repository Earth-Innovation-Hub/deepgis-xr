/**
 * UI Helper Functions
 * Global UI update functions used throughout the application
 */

/**
 * Update status indicator
 */
export function updateStatusIndicator(message) {
  const statusEl = document.getElementById('statusIndicator');
  if (statusEl) {
    statusEl.textContent = message;
  }
}

/**
 * Show snackbar notification with fade in/out animation
 */
export function showSnackBar(message, type = 'info') {
  const snackbar = document.createElement('div');
  
  const colors = {
    info: '#333',
    success: '#10b981',
    warning: '#f59e0b',
    error: '#ef4444'
  };
  
  snackbar.style.cssText = `
    position: fixed;
    bottom: 20px;
    left: 50%;
    transform: translateX(-50%) translateY(10px);
    background-color: ${colors[type] || colors.info};
    color: white;
    padding: 12px 24px;
    border-radius: 4px;
    z-index: 10000;
    min-width: 250px;
    text-align: center;
    box-shadow: 0 2px 5px rgba(0,0,0,0.2);
    font-weight: ${type === 'error' ? 'bold' : 'normal'};
    opacity: 0;
    transition: opacity 0.3s ease, transform 0.3s ease;
  `;
  snackbar.textContent = message;
  document.body.appendChild(snackbar);
  
  // Trigger entrance animation on next frame
  requestAnimationFrame(() => {
    snackbar.style.opacity = '1';
    snackbar.style.transform = 'translateX(-50%) translateY(0)';
  });
  
  const duration = type === 'error' ? 5000 : 3000;
  setTimeout(() => {
    // Fade out before removing
    snackbar.style.opacity = '0';
    snackbar.style.transform = 'translateX(-50%) translateY(10px)';
    setTimeout(() => snackbar.remove(), 300);
  }, duration);
}

/**
 * Log layer operation to debug console
 */
export function logLayerOperation(operation, layerId, layerInfo, details = {}) {
  const layerName = layerInfo?.name || layerId || 'unknown';
  if (typeof window.addDebugLogEntry === 'function') {
    window.addDebugLogEntry('layer', `${operation}: ${layerName}`, {
      layerId,
      layerName,
      operation,
      ...details
    });
  }
}

// Expose globally for backward compatibility
window.updateStatusIndicator = updateStatusIndicator;
window.showSnackBar = showSnackBar;
window.logLayerOperation = logLayerOperation;

export default {
  updateStatusIndicator,
  showSnackBar,
  logLayerOperation
};


/**
 * Debug Console Feature Module
 * Lazy loaded when debug functionality is needed
 */
import { AppState } from '../js/state.js';

let debugConsoleLogs = [];
let debugConsoleVisible = false;
const MAX_DEBUG_LOGS = 500;

export function toggleDebugConsole() {
  const content = document.getElementById('debugConsoleContent');
  const chevron = document.getElementById('debugConsoleChevron');
  debugConsoleVisible = !debugConsoleVisible;
  
  if (debugConsoleVisible) {
    content.style.display = 'block';
    chevron.classList.remove('fa-chevron-down');
    chevron.classList.add('fa-chevron-up');
  } else {
    content.style.display = 'none';
    chevron.classList.remove('fa-chevron-up');
    chevron.classList.add('fa-chevron-down');
  }
}

export function clearDebugConsole() {
  debugConsoleLogs = [];
  const logContainer = document.getElementById('debugConsoleLog');
  if (logContainer) {
    logContainer.innerHTML = '<div style="color: #64748b;">Debug console cleared.</div>';
  }
  updateDebugConsoleBadge();
}

export function exportDebugLog() {
  const logData = {
    timestamp: new Date().toISOString(),
    logs: debugConsoleLogs,
    applicationState: {
      availableLayers: Object.keys(AppState?.availableLayers || {}).length,
      currentBaseRaster: AppState?.currentLayers?.baseRaster ? 'loaded' : 'none',
      currentOverlays: Object.keys(AppState?.currentLayers?.overlays || {}).length,
      errorCount: AppState?.errorLog?.length || 0
    }
  };
  
  const blob = new Blob([JSON.stringify(logData, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `debug-log-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

function updateDebugConsoleBadge() {
  const badge = document.getElementById('debugConsoleBadge');
  if (badge) {
    badge.textContent = debugConsoleLogs.length;
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function formatDetails(details) {
  if (typeof details === 'string') {
    return escapeHtml(details);
  }
  try {
    return escapeHtml(JSON.stringify(details, null, 2));
  } catch (e) {
    return escapeHtml(String(details));
  }
}

export function addDebugLogEntry(type, message, details = null) {
  const timestamp = new Date().toLocaleTimeString();
  const entry = {
    timestamp,
    type,
    message,
    details,
    id: Date.now() + Math.random()
  };
  
  debugConsoleLogs.push(entry);
  
  if (debugConsoleLogs.length > MAX_DEBUG_LOGS) {
    debugConsoleLogs.shift();
  }
  
  updateDebugConsoleBadge();
  
  if (debugConsoleVisible) {
    const logContainer = document.getElementById('debugConsoleLog');
    if (logContainer) {
      const entryElement = document.createElement('div');
      entryElement.className = `debug-log-entry ${type}`;
      
      let html = `<span class="debug-log-timestamp">[${timestamp}]</span>`;
      html += `<span class="debug-log-type">[${type.toUpperCase()}]</span>`;
      html += `<span>${escapeHtml(message)}</span>`;
      
      if (details) {
        html += `<div class="debug-log-details">${formatDetails(details)}</div>`;
      }
      
      entryElement.innerHTML = html;
      logContainer.appendChild(entryElement);
      logContainer.scrollTop = logContainer.scrollHeight;
    }
  }
}

// Expose globally for backward compatibility
window.addDebugLogEntry = addDebugLogEntry;
window.toggleDebugConsole = toggleDebugConsole;
window.clearDebugConsole = clearDebugConsole;
window.exportDebugLog = exportDebugLog;

export default {
  toggleDebugConsole,
  clearDebugConsole,
  exportDebugLog,
  addDebugLogEntry
};


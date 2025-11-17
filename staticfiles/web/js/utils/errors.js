/**
 * Error Handling Utilities
 */
import { AppState } from '../state.js';

export const ErrorHandler = {
  /**
   * Create error context object
   */
  createErrorContext: (error, layerId, layerInfo, viewer) => {
    return {
      layerId: layerId || 'unknown',
      layerName: layerInfo?.name || AppState.availableLayers[layerId]?.name || layerId || 'unknown',
      errorType: error?.constructor?.name || 'Unknown',
      errorMessage: error?.message || String(error),
      errorStack: error?.stack,
      viewerReady: !!viewer,
      sceneReady: !!(viewer?.scene),
      availableLayers: Object.keys(AppState?.availableLayers || {}).length,
      timestamp: new Date().toISOString()
    };
  },
  
  /**
   * Get user-friendly error message
   */
  getUserMessage: (errorMessage, layerName) => {
    if (errorMessage.includes('out of memory') || errorMessage.includes('memory')) {
      return `Memory error loading ${layerName}. Try a layer with lower max zoom (< 20) or refresh the page.`;
    } else if (errorMessage.includes('network') || errorMessage.includes('fetch')) {
      return `Network error loading ${layerName}. Check your connection or try again.`;
    } else if (errorMessage.includes('not found') || errorMessage.includes('404')) {
      return `Layer ${layerName} not found. It may have been removed or renamed.`;
    }
    return `Error loading ${layerName}: ${errorMessage}`;
  },
  
  /**
   * Handle layer loading error with full context
   */
  handleLayerError: (error, layerId, layerInfo, viewer, errorType = 'loadLayer') => {
    const errorContext = ErrorHandler.createErrorContext(error, layerId, layerInfo, viewer);
    
    if (AppState.debugMode || errorType === 'error') {
      console.error(`[${errorType.toUpperCase()}]`, error, errorContext);
    }
    
    // Update status indicator if function exists
    if (typeof window.updateStatusIndicator === 'function') {
      const userMessage = ErrorHandler.getUserMessage(errorContext.errorMessage, errorContext.layerName);
      window.updateStatusIndicator(userMessage);
    }
    
    if (AppState?.errorLog) {
      AppState.errorLog.push({
        type: errorType,
        ...errorContext
      });
      
      // Keep only last 100 errors
      if (AppState.errorLog.length > 100) {
        AppState.errorLog.shift();
      }
    }
  }
};


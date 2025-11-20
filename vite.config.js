import { defineConfig } from 'vite';
import legacy from '@vitejs/plugin-legacy';

export default defineConfig({
  build: {
    outDir: 'deepgis_xr/apps/web/static/web',
    assetsDir: 'assets',
    sourcemap: false,
    rollupOptions: {
      input: {
        main: 'src/main.js'
      },
      // CSS will be automatically extracted by Vite
      output: {
        // Code splitting configuration
        manualChunks: {
          // Core modules
          cesiumCore: ['./src/core/cesium-init.js'],
          layerManagement: ['./src/core/layer-management.js'],
          baseMap: ['./src/core/base-map.js'],
          uiHelpers: ['./src/core/ui-helpers.js'],
          memoryManager: ['./src/core/memory-manager.js'],
          
          // Heavy features - lazy loaded
          webxr: ['./src/features/webxr.js'],
          models: ['./src/features/models.js'],
          measurements: ['./src/features/measurements.js'],
          
          // Navigation widgets
          navigation: ['./src/widgets/navigation.js'],
          
          // Utilities
          utils: [
            './src/utils/coordinates.js',
            './src/utils/layers.js',
            './src/utils/errors.js',
            './src/utils/camera.js'
          ],
          
          // Astronomical calculations (can be lazy loaded)
          astronomy: ['./src/utils/astronomy.js'],
          
          // Debug console (lazy loaded)
          debug: ['./src/features/debug-console.js'],
          
          // Statistics (lazy loaded)
          statistics: ['./src/features/statistics.js']
        },
        // Chunk file naming - using camelCase for chunk names, kebab-case for files
        chunkFileNames: 'chunks/[name]-[hash].js',
        entryFileNames: 'js/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]'
      }
    },
    // Chunk size warnings
    chunkSizeWarningLimit: 1000
  },
  plugins: [
    legacy({
      targets: ['defaults', 'not IE 11']
    })
  ],
  server: {
    port: 3000,
    open: false
  }
});


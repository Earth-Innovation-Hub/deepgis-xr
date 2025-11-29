/**
 * Statistics Feature Module
 * Lazy loaded when statistics functionality is needed
 */
import { AppState } from '../js/state.js';

let histogramChart = null;

export function initializeHistogram() {
  const ctx = document.getElementById('histogram')?.getContext('2d');
  if (!ctx) return;
  
  histogramChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: [],
      datasets: [{
        label: 'Feature Distribution',
        data: [],
        backgroundColor: 'rgba(59, 130, 246, 0.6)',
        borderColor: 'rgba(59, 130, 246, 1)',
        borderWidth: 1
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: 'white' }
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: { color: 'white' },
          grid: { color: 'rgba(255, 255, 255, 0.1)' }
        },
        x: {
          ticks: { color: 'white' },
          grid: { color: 'rgba(255, 255, 255, 0.1)' }
        }
      }
    }
  });
  
  AppState.histogram_chart = histogramChart;
}

export function updateHistogram(data) {
  if (histogramChart && data) {
    histogramChart.data.labels = data.labels || [];
    histogramChart.data.datasets[0].data = data.values || [];
    histogramChart.update();
  }
}

export default {
  initializeHistogram,
  updateHistogram
};


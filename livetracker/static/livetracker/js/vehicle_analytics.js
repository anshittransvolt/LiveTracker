/**
 * ========================================
 * VEHICLE ANALYTICS MODULE
 * ========================================
 * Handles analytics sidebar functionality for individual vehicle pages.
 * 
 * RESPONSIBILITIES:
 * - Fetch analytics data from API (/livetracker/api/analytics/{reg_no}/)
 * - Update sidebar UI elements (SOC, distance, efficiency, etc.)
 * - Calculate and populate ride summary (moving/stopped/charging times)
 * - Render SOC time series chart
 * 
 * DATA FLOW:
 * 1. API returns: current_status, soc_analytics, trip_analytics, 
 *    efficiency_analytics, event_summary, soc_time_series
 * 2. updateAnalyticsFromAPI() updates all sidebar metrics
 * 3. calculateRideSummary() formats event_summary times
 * 4. window.populateRideSummary() displays ride summary panel
 * 5. renderSocChart() creates Chart.js visualization
 * 
 * NOTE: This module only runs on vehicle-specific pages,
 * not on the global "All Vehicles" view.
 */

// ===================================================
// MODULE STATE
// ===================================================
let currentVehicle = null;
let currentSocTimeSeries = null; // Store for zoom modal

// ===================================================
// MAIN ANALYTICS LOADER
// ===================================================
/**
 * Load and display analytics for a specific vehicle.
 * 
 * @param {string} registrationNumber - Vehicle registration number
 * @param {string} [historicalDate] - Optional date for historical data (YYYY-MM-DD)
 * @returns {Promise<void>}
 */
export async function loadVehicleAnalytics(registrationNumber, historicalDate = null) {
  // console.log('📊 loadVehicleAnalytics called with:');
  // console.log('  - registrationNumber:', registrationNumber);
  // console.log('  - historicalDate:', historicalDate);
  // console.log('  - historicalDate type:', typeof historicalDate);
  // console.log('  - historicalDate is null:', historicalDate === null);
  // console.log('  - historicalDate is empty:', historicalDate === '');
  
  // Guard: Only run on vehicle-specific pages
  const isVehiclePage = window.location.pathname.includes('/livetracker/') && 
                       window.location.pathname !== '/livetracker/';
  
  // console.log('  - isVehiclePage:', isVehiclePage);
  // console.log('  - pathname:', window.location.pathname);
  
  if (!isVehiclePage) {
    console.log('⚠️ Not a vehicle page, returning early');
    return; // Silent return for non-vehicle pages
  }

  try {
    currentVehicle = registrationNumber;
    showAnalyticsLoading(true);
    
    // Build API URL with optional date parameter
    let apiUrl = `/livetracker/api/analytics/${encodeURIComponent(registrationNumber)}/`;
    if (historicalDate) {
      apiUrl += `?date=${encodeURIComponent(historicalDate)}`;
    }
    
    // console.log('🌐 Fetching analytics from URL:', apiUrl);
    
    // Fetch analytics from Django API
    const analyticsResponse = await fetch(apiUrl);
    
    // console.log('📥 Analytics response status:', analyticsResponse.status);
    // console.log('📥 Analytics response ok:', analyticsResponse.ok);
    
    if (!analyticsResponse.ok) {
      const errorData = await analyticsResponse.json().catch(() => null);
      let errorMessage = `API returned ${analyticsResponse.status}`;
      if (analyticsResponse.status === 404) {
        errorMessage = errorData?.error || 'No analytics data available for this vehicle today.';
        
        // Show modal for 404 errors
        showAnalyticsLoading(false);
        if (window.showNoDataModal) {
          window.showNoDataModal(errorMessage, registrationNumber);
        }
      }
      throw new Error(errorMessage);
    }
    
    const analyticsData = await analyticsResponse.json();
    
    // Check if data is empty
    if (!analyticsData || Object.keys(analyticsData).length === 0) {
      showAnalyticsLoading(false);
      if (window.showNoDataModal) {
        window.showNoDataModal(
          `No analytics data available for vehicle ${registrationNumber} today.`,
          registrationNumber
        );
      }
      throw new Error('Analytics data is empty');
    }
    
    // ========================================
    // UPDATE ALL UI COMPONENTS
    // ========================================
    
    // 1. Update sidebar metrics (SOC, distance, etc.)
    updateAnalyticsFromAPI(analyticsData);

    // 2. Calculate and display ride summary
    if (analyticsData.trip_analytics && analyticsData.event_summary) {
        const rideSummary = calculateRideSummary(
          analyticsData.event_summary, 
          analyticsData.trip_analytics.duration_minutes
        );
        
        if (window.populateRideSummary) {
            window.populateRideSummary(rideSummary);
        } else {
            console.warn('⚠️ populateRideSummary function not available');
        }
    } 

    // 3. Render SOC time series chart
    if (analyticsData.soc_time_series && Array.isArray(analyticsData.soc_time_series)) {
      currentSocTimeSeries = analyticsData.soc_time_series; // Store for zoom modal
      renderSocChart(analyticsData.soc_time_series);
    } else {
      currentSocTimeSeries = [];
      renderSocChart([]); // Render empty chart
    }

    showAnalyticsLoading(false);
    
  } catch (error) {
    console.error('❌ Error loading vehicle analytics:', error);
    showAnalyticsError(error.message);
    
    // Show toastr notification as well
    if (typeof toastr !== 'undefined' && error.message.includes('No data')) {
      toastr.warning(error.message, 'No Data Available', {
        timeOut: 5000,
        closeButton: true,
        progressBar: true
      });
    }
  }
}
// ===================================================
// RIDE SUMMARY CALCULATION
// ===================================================
/**
 * Calculate ride summary from event summary and total duration.
 * Formats time values from seconds to HH:MM:SS format.
 * 
 * @param {Object} eventSummary - Event summary from API { moving, stopped, charging } in seconds
 * @param {number} totalDurationMinutes - Total ride duration in minutes
 * @returns {Object} Formatted ride summary with HH:MM:SS strings
 */
function calculateRideSummary(eventSummary, totalDurationMinutes) {
  const moving = eventSummary.moving || 0;
  const stopped = eventSummary.stopped || 0;
  const charging = eventSummary.charging || 0;
  const total = Math.round((totalDurationMinutes || 0) * 60); // Convert minutes to seconds
  
  return {
    totalMovingTime: formatDuration(moving),
    totalStopTime: formatDuration(stopped),
    totalChargingTime: formatDuration(charging),
    totalRideTime: formatDuration(total)
  };
}

/**
 * Format duration in seconds to HH:MM:SS format.
 * 
 * @param {number} seconds - Duration in seconds
 * @returns {string} Formatted time string (HH:MM:SS)
 */
function formatDuration(seconds) {
  seconds = Math.round(seconds);
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

// ===================================================
// UPDATE ANALYTICS UI
// ===================================================
/**
 * Update all sidebar analytics elements with data from API.
 * Updates: current status, trip analytics, efficiency, battery stats
 * 
 * @param {Object} analyticsData - Complete analytics data from API
 */
function updateAnalyticsFromAPI(analyticsData) {
  const { current_status, trip_analytics, efficiency_analytics, soc_analytics } = analyticsData;
  
  // Helper to format values with fallback to '--'
  const fmt = (value, suffix = '') => {
    if (value === null || value === undefined || value === 'N/A' || value === '') {
      return '--';
    }
    return suffix ? `${value}${suffix}` : value;
  };
  
  // Update current status
  if (current_status) {
    updateElement('vehicleStatus', fmt(current_status.status));
    updateElement('vehicleBattery', fmt(current_status.soc, '%'));
    updateElement('lastUpdate', fmt(current_status.last_update));
    updateElement('driverName', fmt(current_status.driver_name));
  }
  
  // Update trip analytics
  if (trip_analytics) {
    updateElement('totalDistance', fmt(trip_analytics.total_distance, ' km'));
    
    // Always show duration in hours with two decimals
    let durationHr = '--';
    if (typeof trip_analytics.duration_minutes === 'number' && !isNaN(trip_analytics.duration_minutes)) {
      durationHr = (trip_analytics.duration_minutes / 60).toFixed(2);
    }
    updateElement('tripDuration', durationHr === '--' ? '--' : `${durationHr} hrs`);
    
    updateElement('dataPoints', fmt(trip_analytics.total_points));
    
    // Calculate average speed if we have distance and duration
    if (trip_analytics.total_distance && trip_analytics.duration_minutes) {
      const avgSpeed = (trip_analytics.total_distance / (trip_analytics.duration_minutes / 60)).toFixed(1);
      updateElement('avgSpeed', `${avgSpeed} km/h`);
    } else {
      updateElement('avgSpeed', '--');
    }
  }
  
  // Update energy efficiency analytics
  if (efficiency_analytics) {
    updateElement('energyConsumed', fmt(efficiency_analytics.energy_kwh));
    updateElement('energyEfficiency', fmt(efficiency_analytics.eff_kwh_per_km));
    
    // Extract SOC drop from soc_discharge string (e.g., "15.5%" -> "15.5%")
    const socDrop = efficiency_analytics.soc_discharge || null;
    updateElement('socDrop', fmt(socDrop));
  }
  
  // Update SOC analytics
  if (soc_analytics) {
    updateElement('socStart', fmt(soc_analytics.start_soc, '%'));
    updateElement('socEnd', fmt(soc_analytics.end_soc, '%'));
    updateElement('socMax', fmt(soc_analytics.max_soc, '%'));
    updateElement('socMin', fmt(soc_analytics.min_soc, '%'));
  }
}

// ===================================================
// UTILITY FUNCTIONS
// ===================================================
function updateElement(id, value) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = value;
  }
}

function showAnalyticsLoading(show) {
  // Show/hide loading spinner using global loading overlay
  if (show) {
    // Hide error message before showing loading
    const errorDiv = document.getElementById('analytics-error');
    if (errorDiv) {
        errorDiv.classList.add('hidden');
    }
    window.showLoading?.('Loading analytics...');
  } else {
    window.hideLoading?.();
  }
}

function showAnalyticsError(message) {
  console.error('Analytics error:', message);
  window.hideLoading?.();
  
  // Show error message in the UI
  const errorDiv = document.getElementById('analytics-error');
  const errorMessageElement = document.getElementById('analytics-error-message');
  if (errorDiv && errorMessageElement) {
    errorMessageElement.textContent = message;
    errorDiv.classList.remove('hidden');
  }
  
  // Set all fields to '--' on error
  const fields = [
    'vehicleStatus', 'vehicleBattery', 'lastUpdate', 'driverName',
    'totalDistance', 'tripDuration', 'dataPoints', 'avgSpeed',
    'energyConsumed', 'energyEfficiency', 'socDrop',
    'socStart', 'socEnd', 'socMax', 'socMin'
  ];
  
  fields.forEach(id => updateElement(id, '--'));
}

// ===================================================
// EXPORT FOR GLOBAL ACCESS
// ===================================================
window.loadVehicleAnalytics = loadVehicleAnalytics;
window.updateAnalyticsFromAPI = updateAnalyticsFromAPI; // Expose for patching in vehicle.html
window.renderSocChartZoom = renderSocChartZoom; // Expose for zoom modal

// ===================================================
// SOC CHART RENDERING
// ===================================================
/**
 * Render SOC (State of Charge) time series chart using Chart.js.
 * Colors data points based on vehicle status (charging/discharging/low battery).
 * 
 * @param {Array} socTimeSeries - Array of {soc, status, timestamp} objects
 */
function renderSocChart(socTimeSeries) {
  const canvas = document.getElementById('socGraph');
  if (!canvas) {
    console.warn('SOC Graph canvas not found');
    return;
  }
  const ctx = canvas.getContext('2d');

  // Destroy previous chart instance if exists
  if (window.socChartInstance) {
    window.socChartInstance.destroy();
  }

  // Reverse array so earliest is first
  const reversedSeries = Array.isArray(socTimeSeries) ? [...socTimeSeries].reverse() : [];

  // Prepare data
  // Show only time (HH:mm) for compact x-axis labels
  const labels = reversedSeries.map(point => {
    if (!point.timestamp) return '';
    try {
      // Extract time part (HH:mm) from ISO string
      const t = point.timestamp.split('T')[1];
      return t ? t.slice(0, 5) : '';
    } catch (e) {
      return '';
    }
  });
  const data = reversedSeries.map(point => point.soc ?? null);

  // Theme colors for segments
    const segmentColors = reversedSeries.map(point => {
    if (point.soc < 30) return 'rgba(255,117,24,0.8)'; // Red for SOC < 30%
    if (point.status && point.status.toLowerCase() === 'charging') return 'rgba(59, 130, 246, 0.7)'; // Green for charging
    if (point.status && point.status.toLowerCase() === 'moving') return 'rgba(80, 200, 120, 0.7)'; // Green for moving
    if (point.status && point.status.toLowerCase() === 'stop') return 'rgb(105,105,105)'; // Gray for stopped
    return 'rgba(80, 200, 120, 0.7)'; // Blue for discharging/other
  });

  // Show message if no data
  const chartContainer = canvas.parentElement;
  let noDataMsg = chartContainer.querySelector('.soc-no-data-msg');
  if (data.length === 0 || data.every(v => v === null)) {
    if (!noDataMsg) {
      noDataMsg = document.createElement('div');
      noDataMsg.className = 'soc-no-data-msg text-center text-sm text-slate-500 mt-2';
      noDataMsg.textContent = 'No SOC data available for this vehicle.';
      chartContainer.appendChild(noDataMsg);
    }
    canvas.style.display = 'none';
    return;
  } else {
    if (noDataMsg) {
      chartContainer.removeChild(noDataMsg);
    }
    canvas.style.display = 'block';
  }

  window.socChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        label: 'SOC (%)',
        data: data,
        borderColor: 'rgba(200, 200, 200, 0.5)',
        backgroundColor: 'rgba(59,130,246,0.1)',
        pointBackgroundColor: segmentColors,
        pointRadius: data.length > 50 ? 0 : 2,
        segment: {
          borderColor: ctx => {
            const idx = ctx.p0DataIndex;
            return (idx >= 0 && idx < segmentColors.length) ? segmentColors[idx] : 'rgba(59, 130, 246, 0.7)';
          }
        },
        fill: false,
        tension: 0.3,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      aspectRatio: 2.5,
      layout: {
        padding: {
          left: 8,
          right: 8,
          top: 4,
          bottom: 4
        }
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          enabled: true,
          callbacks: {
            label: function(context) {
              const pt = socTimeSeries[context.dataIndex];
              const status = pt?.status || 'Unknown';
              return `SOC: ${context.parsed.y}% (${status})`;
            }
          }
        }
      },
      scales: {
        x: {
          title: { display: true, text: 'Time', font: { size: 13 } },
          ticks: { maxTicksLimit: 16, font: { size: 12 }, autoSkip: true },
          grid: { display: true, color: 'rgba(200,200,200,0.15)' }
        },
        y: {
          title: { display: true, text: 'SOC (%)', font: { size: 13 } },
          min: 0,
          max: 100,
          ticks: { stepSize: 20, font: { size: 12 } },
          grid: { display: true, color: 'rgba(200,200,200,0.15)' }
        }
      }
    }
  });
}

// ===================================================
// ZOOM CHART RENDERING (MODAL VIEW)
// ===================================================
/**
 * Render a larger, more detailed version of the SOC chart in the zoom modal.
 * Enhanced visibility with larger points, more ticks, and better labeling.
 */
function renderSocChartZoom() {
  const canvas = document.getElementById('socGraphZoom');
  if (!canvas) {
    console.warn('SOC Graph Zoom canvas not found');
    return;
  }
  const ctx = canvas.getContext('2d');

  // Use stored time series data
  const socTimeSeries = currentSocTimeSeries || [];

  // Destroy previous zoom chart instance if exists
  if (window.socChartZoomInstance) {
    window.socChartZoomInstance.destroy();
  }

  // Reverse array so earliest is first
  const reversedSeries = Array.isArray(socTimeSeries) ? [...socTimeSeries].reverse() : [];

  // Prepare data with full timestamps for zoom view
  const labels = reversedSeries.map(point => {
    if (!point.timestamp) return '';
    try {
      // Show full timestamp (date + time) for detailed view
      const dt = new Date(point.timestamp);
      const date = dt.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
      const time = dt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
      return `${date} ${time}`;
    } catch (e) {
      return '';
    }
  });
  const data = reversedSeries.map(point => point.soc ?? null);

  // Enhanced colors for zoom view
    const segmentColors = reversedSeries.map(point => {
    if (point.soc < 30) return 'rgba(255,117,24,0.8)'; // Red for SOC < 30%
    if (point.status && point.status.toLowerCase() === 'charging') return 'rgba(59, 130, 246, 0.7)'; // Blue for charging
    if (point.status && point.status.toLowerCase() === 'moving') return 'rgba(80, 200, 120, 0.7)'; // Green for moving
    if (point.status && point.status.toLowerCase() === 'stop') return '	rgb(105,105,105)'; // gray for stopped
    return 'rgba(80, 200, 120, 0.7)'; // Blue for discharging/other
  });
  // Show message if no data
  const chartContainer = canvas.parentElement;
  if (data.length === 0 || data.every(v => v === null)) {
    const noDataMsg = document.createElement('div');
    noDataMsg.className = 'text-center text-lg text-slate-500';
    noDataMsg.textContent = 'No SOC data available for this vehicle.';
    chartContainer.innerHTML = '';
    chartContainer.appendChild(noDataMsg);
    return;
  }

  canvas.style.display = 'block';

  window.socChartZoomInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        label: 'SOC (%)',
        data: data,
        borderColor: 'rgba(100, 100, 100, 0.3)',
        backgroundColor: 'rgba(59,130,246,0.08)',
        pointBackgroundColor: segmentColors,
        pointBorderColor: segmentColors,
        pointRadius: 4, // Larger points for zoom view
        pointHoverRadius: 6,
        pointBorderWidth: 2,
        segment: {
          borderColor: ctx => {
            const idx = ctx.p0DataIndex;
            return (idx >= 0 && idx < segmentColors.length) ? segmentColors[idx] : 'rgba(59, 130, 246, 0.8)';
          },
          borderWidth: 3 // Thicker lines
        },
        fill: true,
        tension: 0.3,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      aspectRatio: 2.2,
      interaction: {
        mode: 'index',
        intersect: false,
      },
      plugins: {
        legend: { 
          display: false 
        },
        tooltip: {
          enabled: true,
          backgroundColor: 'rgba(0, 0, 0, 0.85)',
          titleFont: { size: 14, weight: 'bold' },
          bodyFont: { size: 13 },
          padding: 12,
          cornerRadius: 8,
          displayColors: true,
          callbacks: {
            title: function(context) {
              return labels[context[0].dataIndex] || '';
            },
            label: function(context) {
              const pt = reversedSeries[context.dataIndex];
              const status = pt?.status || 'Unknown';
              const statusEmoji = status.toLowerCase() === 'charging' ? '' : 
                                 pt?.soc < 30 ? '' : '';
              return `${statusEmoji} SOC: ${context.parsed.y}% (${status})`;
            }
          }
        },
        annotation: {
          annotations: {
            criticalLine: {
              type: 'line',
              yMin: 30,
              yMax: 30,
              borderColor: 'rgba(239, 68, 68, 0.5)',
              borderWidth: 2,
              borderDash: [5, 5],
              label: {
                content: 'Critical Level (30%)',
                enabled: true,
                position: 'end',
                backgroundColor: 'rgba(239, 68, 68, 0.8)',
                color: '#fff',
                font: {
                  size: 11,
                  weight: 'bold'
                },
                padding: 6
              }
            }
          }
        }
      },
      scales: {
        x: {
          title: { 
            display: true, 
            text: 'Timestamp', 
            font: { size: 15, weight: 'bold' },
            color: '#475569'
          },
          ticks: { 
            maxRotation: 45,
            minRotation: 45,
            font: { size: 11 },
            color: '#64748b',
            maxTicksLimit: 20
          },
          grid: { 
            display: true, 
            color: 'rgba(148, 163, 184, 0.15)',
            drawBorder: true,
            borderColor: '#cbd5e1',
            borderWidth: 2
          }
        },
        y: {
          title: { 
            display: true, 
            text: 'State of Charge (%)', 
            font: { size: 15, weight: 'bold' },
            color: '#475569'
          },
          min: 0,
          max: 100,
          ticks: { 
            stepSize: 10, // More granular steps
            font: { size: 12 },
            color: '#64748b',
            callback: function(value) {
              return value + '%';
            }
          },
          grid: { 
            display: true, 
            color: 'rgba(148, 163, 184, 0.15)',
            drawBorder: true,
            borderColor: '#cbd5e1',
            borderWidth: 2
          }
        }
      }
    }
  });
}

// ===================================================
// REPORT GENERATION
// ===================================================
/**
 * Generate CSV report for charging sessions.
 * Extracts charging events from SOC time series and downloads as CSV.
 */
function generateChargingReport() {
  if (!currentSocTimeSeries || currentSocTimeSeries.length === 0) {
    alert('No data available for charging report');
    return;
  }
  
  // Identify charging sessions (consecutive Charging status points)
  const chargingSessions = [];
  let currentSession = null;
  
  for (const point of currentSocTimeSeries) {
    if (point.status === 'Charging') {
      if (!currentSession) {
        currentSession = {
          startTime: point.timestamp,
          startSOC: point.soc,
          endTime: point.timestamp,
          endSOC: point.soc,
          points: 1
        };
      } else {
        currentSession.endTime = point.timestamp;
        currentSession.endSOC = point.soc;
        currentSession.points += 1;
      }
    } else {
      if (currentSession) {
        currentSession.duration = calculateSessionDuration(currentSession.startTime, currentSession.endTime);
        currentSession.socGain = currentSession.endSOC - currentSession.startSOC;
        chargingSessions.push(currentSession);
        currentSession = null;
      }
    }
  }
  
  if (currentSession) {
    currentSession.duration = calculateSessionDuration(currentSession.startTime, currentSession.endTime);
    currentSession.socGain = currentSession.endSOC - currentSession.startSOC;
    chargingSessions.push(currentSession);
  }
  
  // Generate CSV
  const csvHeader = 'Charging Session Report\nVehicle: ' + currentVehicle + '\nGenerated: ' + new Date().toISOString() + '\n\n';
  const csvCols = ['Session #', 'Start Time', 'End Time', 'Duration (min)', 'Start SOC (%)', 'End SOC (%)', 'SOC Gain (%)', 'Data Points'];
  const csvData = chargingSessions.map((session, idx) => [
    idx + 1,
    session.startTime,
    session.endTime,
    session.duration.toFixed(1),
    session.startSOC,
    session.endSOC,
    session.socGain.toFixed(1),
    session.points
  ]);
  
  downloadCSV(csvHeader + csvCols.join(',') + '\n' + csvData.map(row => row.join(',')).join('\n'), 'charging-report-' + currentVehicle);
}

/**
 * Generate CSV report for stoppage sessions.
 * Extracts stopped events from SOC time series and downloads as CSV.
 */
function generateStoppageReport() {
  if (!currentSocTimeSeries || currentSocTimeSeries.length === 0) {
    alert('No data available for stoppage report');
    return;
  }
  
  // Identify stoppage sessions (consecutive Stop status points)
  const stopSessions = [];
  let currentSession = null;
  
  for (const point of currentSocTimeSeries) {
    if (point.status === 'Stop') {
      if (!currentSession) {
        currentSession = {
          startTime: point.timestamp,
          startSOC: point.soc,
          endTime: point.timestamp,
          endSOC: point.soc,
          points: 1
        };
      } else {
        currentSession.endTime = point.timestamp;
        currentSession.endSOC = point.soc;
        currentSession.points += 1;
      }
    } else {
      if (currentSession) {
        currentSession.duration = calculateSessionDuration(currentSession.startTime, currentSession.endTime);
        currentSession.socDrop = currentSession.startSOC - currentSession.endSOC;
        stopSessions.push(currentSession);
        currentSession = null;
      }
    }
  }
  
  if (currentSession) {
    currentSession.duration = calculateSessionDuration(currentSession.startTime, currentSession.endTime);
    currentSession.socDrop = currentSession.startSOC - currentSession.endSOC;
    stopSessions.push(currentSession);
  }
  
  // Generate CSV
  const csvHeader = 'Stoppage Session Report\nVehicle: ' + currentVehicle + '\nGenerated: ' + new Date().toISOString() + '\n\n';
  const csvCols = ['Session #', 'Start Time', 'End Time', 'Duration (min)', 'Start SOC (%)', 'End SOC (%)', 'SOC Drop (%)', 'Data Points'];
  const csvData = stopSessions.map((session, idx) => [
    idx + 1,
    session.startTime,
    session.endTime,
    session.duration.toFixed(1),
    session.startSOC,
    session.endSOC,
    session.socDrop.toFixed(1),
    session.points
  ]);
  
  downloadCSV(csvHeader + csvCols.join(',') + '\n' + csvData.map(row => row.join(',')).join('\n'), 'stoppage-report-' + currentVehicle);
}

/**
 * Calculate session duration in minutes from two ISO timestamps.
 */
function calculateSessionDuration(startTime, endTime) {
  const start = new Date(startTime);
  const end = new Date(endTime);
  return (end - start) / (1000 * 60); // Convert ms to minutes
}

/**
 * Download CSV string as file.
 */
function downloadCSV(csvContent, filename) {
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  const url = URL.createObjectURL(blob);
  
  link.setAttribute('href', url);
  link.setAttribute('download', filename + '.csv');
  link.style.visibility = 'hidden';
  
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  
  // Show success notification
  if (typeof toastr !== 'undefined') {
    toastr.success('Report downloaded successfully', 'Download Complete', {
      timeOut: 3000,
      closeButton: true
    });
  }
}

// Export functions for global access
window.generateChargingReport = generateChargingReport;
window.generateStoppageReport = generateStoppageReport;

// ===================================================
// INITIALIZE EVENT LISTENERS
// ===================================================
/**
 * Initialize event listeners for report buttons.
 * Called when page loads.
 */
function initializeReportButtons() {
  const chargingBtn = document.getElementById('downloadChargingReport');
  const stoppageBtn = document.getElementById('downloadStoppageReport');
  
  if (chargingBtn) {
    chargingBtn.addEventListener('click', function() {
      console.log('Generating charging report...');
      generateChargingReport();
    });
  }
  
  if (stoppageBtn) {
    stoppageBtn.addEventListener('click', function() {
      console.log('Generating stoppage report...');
      generateStoppageReport();
    });
  }
}

// Auto-initialize when module loads
document.addEventListener('DOMContentLoaded', initializeReportButtons);

// Also try to initialize immediately (in case DOMContentLoaded already fired)
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeReportButtons);
} else {
  initializeReportButtons();
}

// Export for manual initialization if needed
window.initializeReportButtons = initializeReportButtons;

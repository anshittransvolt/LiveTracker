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
// Global chart font
if (typeof Chart !== 'undefined') {
  Chart.defaults.font.family = 'Inter, system-ui, sans-serif';
}

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
    
    // Build API URL with optional date and project parameters
    let apiUrl = `/livetracker/api/analytics/${encodeURIComponent(registrationNumber)}/`;
    // Read SPV from the ?spv= query param (canonical), then the project-switcher
    // dropdown (live map only), then window.CURRENT_PROJECT (set on every page).
    let spv = new URLSearchParams(window.location.search).get('spv')
      || document.getElementById('projectSwitcher')?.value
      || window.CURRENT_PROJECT
      || '';
    const params = new URLSearchParams();
    if (historicalDate) params.set('date', historicalDate);
    if (spv) params.set('spv', spv);
    if (params.toString()) apiUrl += `?${params.toString()}`;
    
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
        
        // Show modal for 404 errors (the catch block below hides loading
        // uniformly on every throw path — hiding here too would double-
        // decrement the shared loading counter)
        if (window.showNoDataModal) {
          window.showNoDataModal(errorMessage, registrationNumber);
        }
      }
      throw new Error(errorMessage);
    }
    
    const analyticsData = await analyticsResponse.json();
    
    // Check if data is empty
    if (!analyticsData || Object.keys(analyticsData).length === 0) {
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
  const total = Math.round((totalDurationMinutes || 0) * 60);

  // Only display a time if it's actually non-zero; avoid misleading 00:00:00
  const fmtOrDash = (secs) => secs > 0 ? formatDuration(secs) : '—';

  return {
    totalMovingTime: fmtOrDash(moving),
    totalStopTime: fmtOrDash(stopped),
    totalChargingTime: fmtOrDash(charging),
    totalRideTime: total > 0 ? formatDuration(total) : '—'
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

  const EMPTY = '—';

  const fmt = (value, suffix = '') => {
    if (value === null || value === undefined || value === 'N/A' || value === '') return EMPTY;
    const str = String(value).trim();
    if (!str || str === 'N/A') return EMPTY;
    return suffix ? `${str}${suffix}` : str;
  };

  // Hide a metric row when its value is empty
  const setRow = (rowId, elementId, value) => {
    updateElement(elementId, value);
    const row = document.getElementById(rowId);
    if (row) row.classList.toggle('lv-hidden', value === EMPTY || value === '--');
  };

  // Collapse an entire metric card if all its data rows are hidden
  const syncCard = (cardId, ...rowIds) => {
    const card = document.getElementById(cardId);
    if (!card) return;
    const allHidden = rowIds.every(id => {
      const row = document.getElementById(id);
      return row && row.classList.contains('lv-hidden');
    });
    card.classList.toggle('lv-empty', allHidden);
  };

  // ── Current Status ──────────────────────────────────────────────
  if (current_status) {
    setRow('mc-row-status',  'vehicleStatus',  fmt(current_status.status));
    setRow('mc-row-battery', 'vehicleBattery', fmt(current_status.soc, '%'));
    // Last Updated: always show when present, don't hide row
    updateElement('lastUpdate', fmt(current_status.last_update));
    updateElement('driverName', fmt(current_status.driver_name));
  }
  // Current Status card always visible (at minimum shows last update)

  // ── Trip Analytics ──────────────────────────────────────────────
  if (trip_analytics) {
    setRow('mc-row-distance', 'totalDistance', fmt(trip_analytics.total_distance, ' km'));

    let durationVal = EMPTY;
    if (typeof trip_analytics.duration_minutes === 'number' && !isNaN(trip_analytics.duration_minutes) && trip_analytics.duration_minutes > 0) {
      durationVal = `${(trip_analytics.duration_minutes / 60).toFixed(2)} hrs`;
    }
    setRow('mc-row-duration', 'tripDuration', durationVal);

    // Avg speed: suppress if overall average is too low relative to distance
    // (indicates high stop time that makes the number misleading).
    // Use event_summary stopped time to decide: if stops > 40% of trip, don't show.
    let avgSpeedVal = EMPTY;
    if (trip_analytics.total_distance && trip_analytics.duration_minutes && trip_analytics.duration_minutes > 0) {
      const overallAvg = trip_analytics.total_distance / (trip_analytics.duration_minutes / 60);
      const stopSecs  = analyticsData.event_summary?.stopped || 0;
      const totalSecs = trip_analytics.duration_minutes * 60;
      const stopRatio = totalSecs > 0 ? stopSecs / totalSecs : 0;
      // Only show if we can't detect high stop time OR stop ratio is acceptable
      if (stopRatio < 0.4 || stopSecs === 0) {
        avgSpeedVal = `${overallAvg.toFixed(1)} km/h`;
      }
    }
    setRow('mc-row-avgspeed', 'avgSpeed', avgSpeedVal);

    const pointsVal = trip_analytics.total_points > 0 ? fmt(trip_analytics.total_points) : EMPTY;
    setRow('mc-row-points', 'dataPoints', pointsVal);

    syncCard('mc-trip', 'mc-row-distance', 'mc-row-duration', 'mc-row-avgspeed', 'mc-row-points');
  }

  // ── Energy Efficiency ───────────────────────────────────────────
  if (efficiency_analytics) {
    setRow('mc-row-energy', 'energyConsumed', fmt(efficiency_analytics.energy_kwh));
    setRow('mc-row-eff',    'energyEfficiency', fmt(efficiency_analytics.eff_kwh_per_km));

    // Suppress SOC discharge if zero or "0.00%" — data artifact, not real discharge
    const rawDrop = efficiency_analytics.soc_discharge || null;
    const dropVal = (rawDrop && rawDrop !== '0.00%' && parseFloat(rawDrop) > 0) ? rawDrop : null;
    setRow('mc-row-socdrop', 'socDrop', fmt(dropVal));

    syncCard('mc-energy', 'mc-row-energy', 'mc-row-eff', 'mc-row-socdrop');
  }

  // ── Battery Analytics ───────────────────────────────────────────
  if (soc_analytics) {
    updateElement('socStart', fmt(soc_analytics.start_soc, '%'));
    updateElement('socEnd',   fmt(soc_analytics.end_soc, '%'));
    setRow('mc-row-socmax', 'socMax', fmt(soc_analytics.max_soc, '%'));
    setRow('mc-row-socmin', 'socMin', fmt(soc_analytics.min_soc, '%'));
    syncCard('mc-battery', 'mc-row-socmax', 'mc-row-socmin');
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
  
  // Reset all fields on error
  const fields = [
    'vehicleStatus', 'vehicleBattery', 'lastUpdate', 'driverName',
    'totalDistance', 'tripDuration', 'dataPoints', 'avgSpeed',
    'energyConsumed', 'energyEfficiency', 'socDrop',
    'socStart', 'socEnd', 'socMax', 'socMin'
  ];
  fields.forEach(id => updateElement(id, '—'));

  // Restore card/row visibility on error reset
  ['mc-row-status','mc-row-battery','mc-row-distance','mc-row-duration',
   'mc-row-avgspeed','mc-row-points','mc-row-energy','mc-row-eff',
   'mc-row-socdrop','mc-row-socmax','mc-row-socmin'].forEach(id => {
    document.getElementById(id)?.classList.remove('lv-hidden');
  });
  ['mc-trip','mc-energy','mc-battery'].forEach(id => {
    document.getElementById(id)?.classList.remove('lv-empty');
  });
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

  // Sort ascending by timestamp so oldest is left, newest is right
  const reversedSeries = Array.isArray(socTimeSeries)
    ? [...socTimeSeries].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
    : [];

  // Theme-aware palette
  const isDark = document.body.classList.contains('dark-theme');
  const gridCol   = isDark ? '#0f1829'              : '#e2e8f0';
  const tickCol   = isDark ? '#334155'              : '#334155';
  const tooltipBg = isDark ? '#0c1221'              : '#0f172a';
  const tooltipBorder = isDark ? '#1a2540'          : 'rgba(0,0,0,0)';
  const tooltipTitle  = isDark ? '#94a3b8'          : '#94a3b8';
  const tooltipBody   = isDark ? '#e2e8f0'          : '#f1f5f9';

  // Prepare data — time (HH:mm) labels for compact x-axis
  const labels = reversedSeries.map(point => {
    if (!point.timestamp) return '';
    try {
      const t = point.timestamp.split('T')[1];
      return t ? t.slice(0, 5) : '';
    } catch (e) {
      return '';
    }
  });
  const data = reversedSeries.map(point => point.soc ?? null);

  // Segment colors keyed by vehicle state
  const segmentColors = reversedSeries.map(point => {
    const st = (point.status || '').toLowerCase();
    if (point.soc < 30)        return 'rgba(255,117,24,0.9)';   // orange — low battery
    if (st === 'charging')     return 'rgba(90,162,255,0.85)';  // blue — charging
    if (st === 'moving')       return 'rgba(61,220,132,0.85)';  // green — moving
    if (st === 'stop' || st === 'stopped') return isDark ? 'rgba(140,150,168,0.7)' : 'rgba(100,110,130,0.65)'; // muted — stopped
    return 'rgba(61,220,132,0.75)'; // default green
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

  // Plugin: clear the canvas before each draw so CSS transparent background shows through
  const clearBgPlugin = {
    id: 'clearBg',
    beforeDraw(chart) {
      chart.ctx.clearRect(0, 0, chart.width, chart.height);
    }
  };

  window.socChartInstance = new Chart(ctx, {
    type: 'line',
    plugins: [clearBgPlugin],
    data: {
      labels: labels,
      datasets: [{
        label: 'SOC',
        data: data,
        borderColor: '#22c55e',
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: '#22c55e',
        tension: 0.35,
        fill: true,
        backgroundColor: (ctx) => {
          const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height || 200);
          g.addColorStop(0, 'rgba(34,197,94,0.25)');
          g.addColorStop(1, 'rgba(34,197,94,0.00)');
          return g;
        },
        segment: {
          borderColor: ctx => {
            const idx = ctx.p0DataIndex;
            return (idx >= 0 && idx < segmentColors.length) ? segmentColors[idx] : segmentColors[segmentColors.length - 1];
          }
        },
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { left: 8, right: 8, top: 4, bottom: 4 } },
      plugins: {
        legend: { labels: { color: '#475569', font: { size: 10 }, boxWidth: 8, boxHeight: 8, borderRadius: 4, padding: 12, usePointStyle: true, pointStyleWidth: 8 } },
        tooltip: {
          backgroundColor: tooltipBg, borderColor: tooltipBorder, borderWidth: 1,
          titleColor: tooltipTitle, bodyColor: tooltipBody,
          titleFont: { size: 10 }, bodyFont: { size: 11, weight: '600' },
          padding: 8, cornerRadius: 6,
          callbacks: {
            label: function(context) {
              const pt = reversedSeries[context.dataIndex];
              const status = pt?.status || 'Unknown';
              return `SOC: ${context.parsed.y}% · ${status}`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(0,0,0,0)', drawBorder: false },
          ticks: {
            color: tickCol,
            font: { size: 9 },
            maxTicksLimit: 6,
            maxRotation: 0,
            autoSkip: false,
            callback: function(val, idx) {
              const n = labels.length;
              if (n <= 6) return labels[idx] || '';
              const step = Math.max(1, Math.floor(n / 5));
              if (idx === 0 || idx === n - 1 || idx % step === 0) return labels[idx] || '';
              return '';
            }
          },
          border: { display: false }
        },
        y: {
          min: 0, max: 100,
          grid: { color: gridCol, lineWidth: 1, drawBorder: false },
          ticks: { color: tickCol, font: { size: 9 }, stepSize: 20, callback: v => v + '%' },
          border: { display: false }
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

  // Sort ascending by timestamp so oldest is left, newest is right
  const reversedSeries = Array.isArray(socTimeSeries)
    ? [...socTimeSeries].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
    : [];

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

  // Theme-aware colors for zoom view
  const isDarkZ = document.body.classList.contains('dark-theme');
  const gridColZ   = isDarkZ ? '#0f1829'     : '#e2e8f0';
  const tickColZ   = isDarkZ ? '#334155'     : '#334155';
  const tooltipBgZ = isDarkZ ? '#0c1221'     : '#0f172a';
  const tooltipBorderZ = isDarkZ ? '#1a2540' : 'rgba(0,0,0,0)';
  const tooltipTitleZ  = isDarkZ ? '#94a3b8' : '#94a3b8';
  const tooltipBodyZ   = isDarkZ ? '#e2e8f0' : '#f1f5f9';

  const segmentColors = reversedSeries.map(point => {
    const st = (point.status || '').toLowerCase();
    if (point.soc < 30)                         return 'rgba(255,117,24,0.9)';
    if (st === 'charging')                       return 'rgba(90,162,255,0.9)';
    if (st === 'moving')                         return 'rgba(61,220,132,0.9)';
    if (st === 'stop' || st === 'stopped')       return isDarkZ ? 'rgba(140,150,168,0.75)' : 'rgba(100,110,130,0.7)';
    return 'rgba(61,220,132,0.85)';
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

  const clearBgPluginZ = {
    id: 'clearBgZ',
    beforeDraw(chart) {
      chart.ctx.clearRect(0, 0, chart.width, chart.height);
    }
  };

  window.socChartZoomInstance = new Chart(ctx, {
    type: 'line',
    plugins: [clearBgPluginZ],
    data: {
      labels: labels,
      datasets: [{
        label: 'SOC',
        data: data,
        borderColor: '#22c55e',
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: '#22c55e',
        tension: 0.35,
        fill: true,
        backgroundColor: (ctx) => {
          const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height || 200);
          g.addColorStop(0, 'rgba(34,197,94,0.25)');
          g.addColorStop(1, 'rgba(34,197,94,0.00)');
          return g;
        },
        segment: {
          borderColor: ctx => {
            const idx = ctx.p0DataIndex;
            return (idx >= 0 && idx < segmentColors.length) ? segmentColors[idx] : segmentColors[segmentColors.length - 1];
          },
          borderWidth: 2.5,
        },
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
        legend: { labels: { color: '#475569', font: { size: 10 }, boxWidth: 8, boxHeight: 8, borderRadius: 4, padding: 12, usePointStyle: true, pointStyleWidth: 8 } },
        tooltip: {
          backgroundColor: tooltipBgZ, borderColor: tooltipBorderZ, borderWidth: 1,
          titleColor: tooltipTitleZ, bodyColor: tooltipBodyZ,
          titleFont: { size: 10 }, bodyFont: { size: 11, weight: '600' },
          padding: 8, cornerRadius: 6,
          callbacks: {
            title: function(context) {
              return labels[context[0].dataIndex] || '';
            },
            label: function(context) {
              const pt = reversedSeries[context.dataIndex];
              const status = pt?.status || 'Unknown';
              return `SOC: ${context.parsed.y}% · ${status}`;
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
          grid: { color: 'rgba(0,0,0,0)', drawBorder: false },
          ticks: {
            color: tickColZ,
            font: { size: 9 },
            maxTicksLimit: 6,
            maxRotation: 0,
            autoSkip: false,
            callback: function(val, idx) {
              const n = labels.length;
              if (n <= 8) return labels[idx] || '';
              const step = Math.max(1, Math.floor(n / 7));
              if (idx === 0 || idx === n - 1 || idx % step === 0) return labels[idx] || '';
              return '';
            }
          },
          border: { display: false }
        },
        y: {
          min: 0, max: 100,
          grid: { color: gridColZ, lineWidth: 1, drawBorder: false },
          ticks: { color: tickColZ, font: { size: 9 }, stepSize: 20, callback: v => v + '%' },
          border: { display: false }
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

// ===================================================
// playback.js
// Handles vehicle playback visualization.
// Triggered from map.js via window.enterPlaybackMode().
// 
// INDUSTRY COLOR CONVENTIONS:
// - GREEN = Moving (healthy operation)
// - RED = Stopped (urgent attention, exception)
// - BLUE = Charging (EV/UI blue for electricity)
// - ORANGE = Idling (caution, inefficiency)
// ===================================================

import { fetchVehicleOneDay } from './api_handler.js';
import { addGeofences } from "./geofence.js";

let playbackMap, playbackPolyline, playbackMarker;
let playbackData = [];
let currentIndex = 0;
let playbackInterval = null;
let playbackSpeed = 500; // ms per frame
let playbackContainer;

// Industry-standard colors
const INDUSTRY_COLORS = {
  MOVING: '#22c55e',    // Green
  STOPPED: '#ef4444',   // Red
  CHARGING: '#3b82f6',  // Blue
  IDLING: '#fb923c'     // Orange
};


// Helper: return a human-readable IST time string from a data point.
// Prefers last_connected (already normalised to ISO/IST by backend), then gps_time,
// then event_datetime. Handles both ISO strings and Unix int timestamps.
function formatPointTime(pt) {
  const raw = pt.last_connected || pt.gps_time || pt.event_datetime;
  if (!raw) return 'N/A';
  // Unix integer (seconds since epoch)
  if (typeof raw === 'number' || (typeof raw === 'string' && /^\d{9,11}$/.test(raw.trim()))) {
    const d = new Date(parseInt(raw) * 1000);
    return d.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false });
  }
  // ISO string — format as IST
  try {
    const d = new Date(raw);
    if (!isNaN(d)) return d.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false });
  } catch {}
  return String(raw);
}

// Bus icon
const busIcon = L.icon({
  iconUrl: '/static/livetracker/images/truck.png',
  iconSize: [40, 40],
  iconAnchor: [20, 40],
  popupAnchor: [0, -40],
});

// ===================================================
// 1️⃣ MAIN ENTRY POINT
// ===================================================
window.enterPlaybackMode = async function (registration_number) {
  try {
    // console.log(`🎬 Entering playback mode for ${registration_number}...`);
    showSpinner(true);

    // ✅ Corrected: Fetch playback data using the proper query param
    let data = await fetchVehicleOneDay(registration_number);

    if (!Array.isArray(data) || data.length === 0) {
      showSpinner(false);
      const errorMsg = `No playback data available for vehicle ${registration_number}.\n\nThis vehicle may not have:\n• Location tracking enabled\n• GPS data in the system\n• 24-hour historical data available\n\nPlease select a different vehicle or contact support.`;
      alert(errorMsg);
      exitPlaybackMode();
      return;
    }

    // ✅ IMPORTANT: Reverse the data for playback
    // fetchVehicleOneDay returns data sorted newest-first (for dashboard display)
    // But for playback visualization, we need chronological order (oldest-first)
    // so the marker progresses through time from past to future
    data = data.reverse();

    playbackData = data;
    setupPlaybackUI();
    drawPlaybackPath();
    showSpinner(false);

  } catch (err) {
    console.error('❌ Playback error:', err);
    alert('Playback failed: ' + err.message);
    showSpinner(false);
    exitPlaybackMode();
  }
};

// ===================================================
// 2️⃣ UI SETUP
// ===================================================
function setupPlaybackUI() {
  const oldContainer = document.getElementById('playbackContainer');
  if (oldContainer) oldContainer.remove();

  playbackContainer = document.createElement('div');
  playbackContainer.id = 'playbackContainer';
  playbackContainer.style.cssText = `
    position: fixed;
    top: 0; left: 0;
    width: 100vw; height: 100vh;
    background: #f8f9fa;
    z-index: 99999;
    display: flex;
    flex-direction: column;
  `;
  document.body.appendChild(playbackContainer);

  // Toolbar
  const toolbar = document.createElement('div');
  toolbar.style.cssText = `
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 12px;
    padding: 10px;
    background: #ffffff;
    border-bottom: 1px solid #ddd;
  `;
  playbackContainer.appendChild(toolbar);

  const makeBtn = (label, cb) => {
    const btn = document.createElement('button');
    btn.textContent = label;
    btn.style.cssText = `
      padding: 6px 12px;
      font-size: 14px;
      border-radius: 6px;
      cursor: pointer;
      border: 1px solid #ccc;
      background: #f5f5f5;
    `;
    btn.addEventListener('click', cb);
    toolbar.appendChild(btn);
  };

  makeBtn('⏯️ Play/Pause', togglePlayback);
  makeBtn('⏮️ Reset', resetPlayback);
  makeBtn('⏩ Speed+', increaseSpeed);
  makeBtn('⏬ Speed-', decreaseSpeed);
  makeBtn('↩️ Back', exitPlaybackMode);

  // Map area
  const mapDiv = document.createElement('div');
  mapDiv.id = 'playbackMap';
  mapDiv.style.cssText = `flex-grow: 1; width: 100%;`;
  playbackContainer.appendChild(mapDiv);

  // Timeline area (added BEFORE map initialization)
  const timelineDiv = document.createElement('div');
  timelineDiv.id = 'playbackTimeline';
  timelineDiv.style.cssText = `
    width: 100%;
    height: 80px;
    background: #f5f5f5;
    border-top: 1px solid #ddd;
    display: flex;
    flex-direction: column;
    order: 10;
  `;
  playbackContainer.appendChild(timelineDiv);

  // Initialize playback map
  playbackMap = L.map(mapDiv).setView([20.59, 78.96], 5);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    subdomains: 'abc'
  }).addTo(playbackMap);

  // ✅ Add geofences overlay
  addGeofences(playbackMap);
}





// ===================================================
// 3️⃣ DRAW PATH AND MARKER
// ===================================================
function drawPlaybackPath() {
  const latlngs = playbackData
    .filter(pt => pt.latitude && pt.longitude)
    .map(pt => [parseFloat(pt.latitude), parseFloat(pt.longitude)]);

  if (!latlngs.length) {
    alert('No valid coordinates found.');
    return;
  }

  if (playbackPolyline) playbackMap.removeLayer(playbackPolyline);
  playbackPolyline = L.polyline(latlngs, {
    color: '#15803d',  // Darker green than INDUSTRY_COLORS.MOVING — that lighter green
                        // is tuned for the status legend/scrubber, not a map line against OSM tiles
    weight: 4,
    opacity: 0.95,
  }).addTo(playbackMap);

  playbackMap.fitBounds(playbackPolyline.getBounds(), { padding: [30, 30] });

  if (playbackMarker) playbackMap.removeLayer(playbackMarker);
  playbackMarker = L.marker(latlngs[0], { icon: busIcon }).addTo(playbackMap);
  const startData = playbackData[0];
  const startTime = formatPointTime(startData);
  playbackMarker.bindPopup(`<strong>Journey Start:</strong> ${startTime}`).openPopup();

  currentIndex = 0;
  
  // ✅ Draw the visual timeline bar
  drawTimelineBar();
}

// ===================================================
// 3.5️⃣ DRAW VISUAL TIMELINE BAR - PROFESSIONAL & CLEAN
// ===================================================
function drawTimelineBar() {
  const timelineContainer = document.getElementById('playbackTimeline');
  if (!timelineContainer) return;

  timelineContainer.innerHTML = '';
  timelineContainer.style.cssText = `
    width: 100%;
    height: 80px;
    background: #f5f5f5;
    border-top: 1px solid #ddd;
    display: flex;
    flex-direction: column;
    overflow-x: auto;
  `;

  if (playbackData.length === 0) return;

  // 1. STATUS BAR (50px) - Colored segments for vehicle status
  const statusBar = document.createElement('div');
  statusBar.style.cssText = `
    display: flex;
    height: 50px;
    width: 100%;
    flex-shrink: 0;
  `;
  timelineContainer.appendChild(statusBar);

  // Group consecutive points with same status
  const segments = [];
  let currentSegment = {
    status: playbackData[0].vehicle_status || 'unknown',
    startIdx: 0,
    count: 1
  };

  for (let i = 1; i < playbackData.length; i++) {
    const status = playbackData[i].vehicle_status || 'unknown';
    if (status === currentSegment.status) {
      currentSegment.count++;
    } else {
      segments.push(currentSegment);
      currentSegment = { status, startIdx: i, count: 1 };
    }
  }
  segments.push(currentSegment);

  // Helper: Get color for status
  const getStatusColor = (status) => {
    const s = (status || '').toLowerCase();
    if (s.includes('moving')) return INDUSTRY_COLORS.MOVING;      // Green
    if (s.includes('stop')) return INDUSTRY_COLORS.STOPPED;        // Red
    if (s.includes('charging')) return INDUSTRY_COLORS.CHARGING;   // Blue
    if (s.includes('idle')) return INDUSTRY_COLORS.IDLING;         // Orange
    return '#999';
  };

  // Draw colored segments (no gaps)
  segments.forEach((seg) => {
    const segmentDiv = document.createElement('div');
    const percentage = (seg.count / playbackData.length) * 100;
    
    segmentDiv.style.cssText = `
      flex: ${percentage};
      background-color: ${getStatusColor(seg.status)};
      cursor: pointer;
      transition: opacity 0.2s;
      border-right: 1px solid rgba(255,255,255,0.3);
    `;
    
    segmentDiv.title = `${seg.status}: ${seg.count} points (${percentage.toFixed(1)}%)`;
    segmentDiv.addEventListener('click', () => {
      currentIndex = seg.startIdx;
      if (!playbackInterval) {
        const pt = playbackData[currentIndex];
        if (pt.latitude && pt.longitude) {
          playbackMarker.setLatLng([pt.latitude, pt.longitude]);
          playbackMap.panTo([pt.latitude, pt.longitude]);
        }
      }
    });
    
    segmentDiv.addEventListener('mouseenter', () => {
      segmentDiv.style.opacity = '0.7';
    });
    
    segmentDiv.addEventListener('mouseleave', () => {
      segmentDiv.style.opacity = '1';
    });
    
    statusBar.appendChild(segmentDiv);
  });

  // 2. TIME LABELS (30px) - No white gap
  const timeLabels = document.createElement('div');
  timeLabels.style.cssText = `
    display: flex;
    justify-content: space-between;
    height: 30px;
    padding: 0 10px;
    align-items: center;
    font-size: 11px;
    color: #666;
    background: #f5f5f5;
    border-top: 1px solid #ddd;
    flex-shrink: 0;
  `;

  const firstTime = formatPointTime(playbackData[0]) || 'Start';
  const lastTime = formatPointTime(playbackData[playbackData.length - 1]) || 'End';
  const midIdx = Math.floor(playbackData.length / 2);
  const midTime = formatPointTime(playbackData[midIdx]) || 'Mid';

  timeLabels.innerHTML = `
    <span><strong>${firstTime}</strong></span>
    <span>${midTime}</span>
    <span><strong>${lastTime}</strong></span>
  `;
  timelineContainer.appendChild(timeLabels);
}


// ===================================================
// 4️⃣ PLAYBACK CONTROLS
// ===================================================
function startPlayback() {
  if (playbackInterval) return;
  // console.log('▶️ Playback started at speed:', playbackSpeed, 'ms/frame');
  playbackInterval = setInterval(() => {
    if (currentIndex >= playbackData.length - 1) {
      stopPlayback();
      // console.log('⏹️ Playback finished.');
      return;
    }
    currentIndex++;
    const pt = playbackData[currentIndex];
    const lat = parseFloat(pt.latitude);
    const lng = parseFloat(pt.longitude);
    if (lat && lng) {
      playbackMarker.setLatLng([lat, lng]);
      // Format timestamps with fallback
      const displayTime = formatPointTime(pt);
      
      playbackMarker.bindPopup(`
        <div style="max-width: 300px; font-size: 13px;">
          <strong>GPS Time (IST):</strong> ${displayTime}<br/>
          <strong>Speed:</strong> ${pt.speed ?? 'N/A'} km/h<br/>
          <strong>SOC:</strong> ${pt.soc ?? 'N/A'}%<br/>
          <strong>Latitude:</strong> ${pt.latitude?.toFixed(6) ?? 'N/A'}<br/>
          <strong>Longitude:</strong> ${pt.longitude?.toFixed(6) ?? 'N/A'}<br/>
          <strong>Altitude:</strong> ${pt.altitude ?? 'N/A'} m<br/>
          <strong>Odometer:</strong> ${pt.odometer ?? 'N/A'} km<br/>
          <strong>Heading:</strong> ${pt.heading ?? pt.gps_heading ?? 'N/A'}°<br/>
          <strong>Vehicle Status:</strong> ${pt.vehicle_status ?? 'N/A'}<br/>
        </div>
      `, { maxWidth: 350 }).openPopup();
      playbackMap.panTo([lat, lng], { animate: true });
    }
  }, playbackSpeed);
}

function stopPlayback() {
  clearInterval(playbackInterval);
  playbackInterval = null;
  // console.log('⏸️ Playback paused.');
}

function togglePlayback() {
  playbackInterval ? stopPlayback() : startPlayback();
}

function resetPlayback() {
  stopPlayback();
  if (!playbackData.length) return;
  currentIndex = 0;
  const pt = playbackData[0];
  playbackMarker.setLatLng([pt.latitude, pt.longitude]);
  playbackMarker.bindPopup(`Start: ${pt.gps_time}`).openPopup();
  playbackMap.panTo([pt.latitude, pt.longitude]);
}

function increaseSpeed() {
  if (playbackSpeed > 100) playbackSpeed -= 100;
  restartPlayback();
}

function decreaseSpeed() {
  playbackSpeed += 100;
  restartPlayback();
}

function restartPlayback() {
  if (playbackInterval) {
    stopPlayback();
    startPlayback();
  }
  // console.log(`⚙️ Playback speed adjusted: ${playbackSpeed} ms/frame`);
}

// ===================================================
// 5️⃣ EXIT BACK TO LIVE MAP
// ===================================================
function exitPlaybackMode() {
  stopPlayback();
  if (playbackContainer) playbackContainer.remove();
  // console.log('↩️ Returning to live map mode.');
  if (window.LiveMap) window.LiveMap.map.invalidateSize();
}

// ===================================================
// 6️⃣ SPINNER HANDLER (Shared from map.js)
// ===================================================
function showSpinner(show) {
  let spinner = document.getElementById('globalSpinner');
  if (!spinner && show) {
    spinner = document.createElement('div');
    spinner.id = 'globalSpinner';
    spinner.className = 'fixed inset-0 flex items-center justify-center bg-white bg-opacity-75 z-[999999]';
    spinner.innerHTML = `<div class="animate-spin rounded-full h-16 w-16 border-t-4 border-blue-500"></div>`;
    document.body.appendChild(spinner);
  }
  if (spinner && !show) spinner.remove();
}

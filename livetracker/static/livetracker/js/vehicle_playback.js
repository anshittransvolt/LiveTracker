// ===================================================
// vehicle_playback.js
// Handles vehicle playback visualization for the vehicle page.
// ===================================================

import { fetchVehicleOneDay } from './api_handler.js';
import { addGeofences } from "./geofence.js";
import { getDisplayVehicleNumber } from './vehicle_mapping.js';

let playbackMap, playbackPolyline, playbackMarker;
let playbackData = [];
let detectedEvents = [];
let playbackPolylineSegments = [];
let currentIndex = 0;
let animationFrameId = null;
let playbackSpeed = 3.0; // Speed multiplier (1x = real-time)
let addressCache = {};
let currentVehicleNumber = null; // For fetching vehicle-specific alerts

let stoppageHeatmapLayer = null;
let heatmapVisible = true; // Default to ON

// ===================================================
// TILE LAYER SWITCHING (dark ↔ light theme)
// ===================================================
let _vehicleTileLayer = null;

function _getVehicleTileUrl() {
  return document.body.classList.contains('dark-theme')
    ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
    : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';
}

function switchVehicleTiles() {
  if (!playbackMap) return;
  if (_vehicleTileLayer) {
    try { playbackMap.removeLayer(_vehicleTileLayer); } catch (_) {}
  }
  _vehicleTileLayer = L.tileLayer(_getVehicleTileUrl(), {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
    subdomains: 'abcd'
  }).addTo(playbackMap);
}
window.switchVehicleTiles = switchVehicleTiles;

// =============================
// ROUTE CORRIDOR & DEVIATION
// =============================
let corridorSegments = null;
let corridorLayers = [];
let deviationMarkers = [];
let corridorVisible = false;

// Deviation alert throttling
let lastDeviationAlertAt = 0;
let lastDeviationAlertPt = null; // {lat, lon}
const MIN_ALERT_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes
const MIN_ALERT_DISTANCE_BETWEEN_POINTS_M = 100; // don't alert again if within 100m of last alert

function toXYMeters(lat, lon, lat0Rad) {
  const k = 111320.0;
  return [lon * k * Math.cos(lat0Rad), lat * k];
}

function pointToPolylineDistanceM(lat, lon, polyline) {
  if (!polyline || polyline.length < 2) return Infinity;
  // Equirectangular projection around average latitude for local meter-scale distances
  const lat0 = polyline.reduce((s, p) => s + p[0], 0) / polyline.length;
  const lat0Rad = (lat0 * Math.PI) / 180.0;
  const [px, py] = toXYMeters(lat, lon, lat0Rad);
  let minD = Infinity;
  for (let i = 1; i < polyline.length; i++) {
    const a = polyline[i - 1], b = polyline[i];
    const [ax, ay] = toXYMeters(a[0], a[1], lat0Rad);
    const [bx, by] = toXYMeters(b[0], b[1], lat0Rad);
    const vx = bx - ax, vy = by - ay;
    const wx = px - ax, wy = py - ay;
    const c1 = vx * wx + vy * wy;
    const c2 = vx * vx + vy * vy;
    let t = c2 > 0 ? c1 / c2 : 0;
    t = Math.max(0, Math.min(1, t));
    const projx = ax + t * vx;
    const projy = ay + t * vy;
    const dx = px - projx;
    const dy = py - projy;
    const d = Math.sqrt(dx * dx + dy * dy);
    if (d < minD) minD = d;
  }
  return minD;
}

async function loadCorridor() {
  try {
    const res = await fetch('/livetracker/api/corridor/');
    if (!res.ok) return {};
    const json = await res.json();
    return json.segments || {};
  } catch (e) {
    console.warn('Failed to load corridor:', e);
    return {};
  }
}

function clearCorridorLayers() {
  if (!playbackMap) return;
  corridorLayers.forEach(l => playbackMap.removeLayer(l));
  corridorLayers = [];
}

function drawCorridor(map) {
  if (!map || !corridorSegments) return;
  clearCorridorLayers();
  const colorMap = { M_J: '#1d4ed8', J_D: '#0f766e', D_M: '#7c3aed' };
  for (const key of ['M_J', 'J_D', 'D_M']) {
    const seg = corridorSegments[key];
    if (!seg || !Array.isArray(seg.polyline) || seg.polyline.length < 2) continue;
    const latlngs = seg.polyline.map(p => [p[0], p[1]]);
    const chunks = splitPolylineByGap(latlngs, 2000); // break if gap > 2.0 km
    chunks.forEach(chunk => {
      if (chunk.length >= 2) {
        const pl = L.polyline(chunk, { color: colorMap[key] || '#334155', weight: 4, opacity: 0.9, dashArray: '8 6' });
        pl.addTo(map);
        corridorLayers.push(pl);
      }
    });
  }
  corridorVisible = corridorLayers.length > 0;
  updateCorridorButtonState();
}

function updateCorridorButtonState() {
  const btn = document.getElementById('corridorToggleBtn');
  if (!btn) return;
  btn.innerHTML = `
    <div class="flex items-center gap-2">
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M2 12h20"/><path d="M12 2v20"/>
      </svg>
      <span>${corridorVisible ? 'Hide Corridor' : 'Show Corridor'}</span>
    </div>
  `;
  btn.style.background = corridorVisible ? '#e0ecff' : '#fff';
  btn.style.color = corridorVisible ? '#1d4ed8' : '#1e293b';
  btn.style.border = `2px solid ${corridorVisible ? '#1d4ed8' : '#cbd5e1'}`;
}

async function toggleCorridorOverlay() {
  if (!playbackMap) return;
  if (!corridorSegments) {
    corridorSegments = await loadCorridor();
  }
  if (corridorVisible) {
    clearCorridorLayers();
    corridorVisible = false;
    updateCorridorButtonState();
  } else {
    drawCorridor(playbackMap);
  }
}

function addCorridorToggleButton() {
  if (!playbackMap) return;
  if (document.getElementById('corridorToggleBtn')) return;
  const btn = document.createElement('button');
  btn.id = 'corridorToggleBtn';
  btn.style.position = 'absolute';
  btn.style.top = '300px';
  btn.style.left = '16px';
  btn.style.zIndex = 1200;
  btn.style.background = '#fff';
  btn.style.color = '#1e293b';
  btn.style.border = '2px solid #cbd5e1';
  btn.style.borderRadius = '8px';
  btn.style.padding = '8px 12px';
  btn.style.fontSize = '12px';
  btn.style.fontWeight = '600';
  btn.style.cursor = 'pointer';
  btn.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)';
  btn.onclick = toggleCorridorOverlay;
  playbackMap.getContainer().appendChild(btn);
  updateCorridorButtonState();
}


// =============================
// Corridor helpers: split large gaps
// =============================
function haversineM(a, b) {
  const R = 6371000; // meters
  const toRad = x => (x * Math.PI) / 180;
  const dLat = toRad(b[0] - a[0]);
  const dLon = toRad(b[1] - a[1]);
  const lat1 = toRad(a[0]);
  const lat2 = toRad(b[0]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function splitPolylineByGap(latlngs, maxGapM) {
  const chunks = [];
  let current = [];
  for (let i = 0; i < latlngs.length; i++) {
    const pt = latlngs[i];
    if (current.length === 0) {
      current.push(pt);
    } else {
      const prev = current[current.length - 1];
      const d = haversineM(prev, pt);
      if (d > maxGapM) {
        if (current.length >= 2) chunks.push(current);
        current = [pt];
      } else {
        current.push(pt);
      }
    }
  }
  if (current.length >= 2) chunks.push(current);
  return chunks;
}

// =============================
// Deviation detection helpers
// =============================
async function ensureCorridorLoaded() {
  if (!corridorSegments) {
    corridorSegments = await loadCorridor();
  }
  return corridorSegments && Object.keys(corridorSegments).length > 0;
}

function getNearestCorridorInfo(lat, lon) {
  if (!corridorSegments) return null;
  let nearest = { key: null, distance_m: Infinity, buffer_m: 0 };
  for (const key of ['M_J', 'J_D', 'D_M']) {
    const seg = corridorSegments[key];
    if (!seg || !Array.isArray(seg.polyline) || seg.polyline.length < 2) continue;
    const d = pointToPolylineDistanceM(lat, lon, seg.polyline);
    if (d < nearest.distance_m) {
      nearest = { key, distance_m: d, buffer_m: seg.buffer_m || 0 };
    }
  }
  return nearest.key ? nearest : null;
}

function addDeviationMarker(lat, lon, distance_m) {
  if (!playbackMap) return;
  const marker = L.circleMarker([lat, lon], {
    radius: 5,
    color: '#b91c1c',
    fillColor: '#ef4444',
    fillOpacity: 0.9,
    weight: 2
  }).addTo(playbackMap);
  marker.bindPopup(`Deviation: ${Math.round(distance_m)} m`).openPopup();
  deviationMarkers.push(marker);
  // Cap markers to avoid clutter
  if (deviationMarkers.length > 100) {
    const old = deviationMarkers.shift();
    try { playbackMap.removeLayer(old); } catch (_) {}
  }
}

function clearDeviationMarkers() {
  if (!playbackMap) return;
  deviationMarkers.forEach(m => {
    try { playbackMap.removeLayer(m); } catch (_) {}
  });
  deviationMarkers = [];
}

async function maybeReportDeviation(point) {
  // Corridor deviation only applies to Ultratech project
  const _pp = window.location.pathname.split('/').filter(Boolean);
  const _isUT = !(_pp.length >= 2 && _pp[1] === 'livetracker') || _pp[0].toLowerCase() === 'ultratech';
  if (!_isUT) return;

  const lat = parseFloat(point.latitude);
  const lon = parseFloat(point.longitude);
  if (isNaN(lat) || isNaN(lon)) return;

  const loaded = await ensureCorridorLoaded();
  if (!loaded) return;

  const info = getNearestCorridorInfo(lat, lon);
  if (!info) return;

  if (info.distance_m <= (info.buffer_m || 0)) return; // within corridor

  // Throttle alerts
  const now = Date.now();
  const tooSoon = now - lastDeviationAlertAt < MIN_ALERT_INTERVAL_MS;
  const tooClose = lastDeviationAlertPt
    ? haversineM([lastDeviationAlertPt.lat, lastDeviationAlertPt.lon], [lat, lon]) < MIN_ALERT_DISTANCE_BETWEEN_POINTS_M
    : false;
  if (tooSoon && tooClose) {
    // Still add a marker for visualization
    addDeviationMarker(lat, lon, info.distance_m);
    return;
  }

  addDeviationMarker(lat, lon, info.distance_m);

  // Post to backend
  try {
    await fetch('/livetracker/api/alerts/deviation/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        vehicle_no: point.registration_number || point.vehicle_no || 'Vehicle',
        lat: lat,
        lon: lon,
        distance_m: Math.round(info.distance_m),
        message: 'Outside defined corridor',
        soc: point.soc || null,
        vehicle_id: point.vehicle_id || null
      })
    });
    lastDeviationAlertAt = now;
    lastDeviationAlertPt = { lat, lon };
  } catch (e) {
    console.warn('Failed to post deviation alert:', e);
  }
}

// =============================
// HEATMAP OF STOPPAGE POINTS
// =============================
function getStoppagePointsWithMeta() {
  // Returns array of {lat, lng, duration, event, point}
  if (!detectedEvents || detectedEvents.length === 0) return [];
  let points = [];
  detectedEvents.forEach(event => {
    if ((event.type === 'stopped' || event.type === 'unplanned_stop') && event.points && event.points.length > 0) {
      // Duration in minutes
      const duration = event.duration ? Math.round(event.duration / 60) : null;
      // Use the first point as the marker location
      const pt = event.points[0];
      if (pt.latitude && pt.longitude) {
        points.push({
          lat: parseFloat(pt.latitude),
          lng: parseFloat(pt.longitude),
          duration,
          event,
          point: pt
        });
      }
    }
  });
  return points;
}

function showStoppageHeatmap() {
  if (!playbackMap) return;
  const pointsMeta = getStoppagePointsWithMeta();
  if (!pointsMeta.length) {
    alert('No stoppage points found.');
    return;
  }
  if (stoppageHeatmapLayer) {
    playbackMap.removeLayer(stoppageHeatmapLayer);
    stoppageHeatmapLayer = null;
  }
  // One red dot per stop transition (no heat blobs)
  pointsMeta.forEach(meta => {
    const isDark = document.body.classList.contains('dark-theme');
    const dotBorder = isDark ? '#06100b' : '#ffffff';
    const marker = L.marker([meta.lat, meta.lng], {
      icon: L.divIcon({
        html: `<div style="width:10px;height:10px;border-radius:50%;background:var(--va-st,#ff5d5d);border:2px solid ${dotBorder};box-shadow:0 0 0 3px rgba(255,93,93,.25)"></div>`,
        className: '',
        iconSize: [10, 10],
        iconAnchor: [5, 5]
      })
    }).addTo(playbackMap);
    const border   = isDark ? '#203328' : '#e2e8f0';
    const textMuted = isDark ? '#475569' : '#64748b';
    const textSub   = isDark ? '#94a3b8' : '#334155';
    const stoppageHTML = `<div style="min-width:140px;font-family:Inter,system-ui,sans-serif;">
      <div style="font-size:11px;font-weight:600;color:#ff5d5d;margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid ${border}">Stoppage</div>
      <div style="display:flex;flex-direction:column;gap:3px">
        ${meta.duration !== null ? `<div style="display:flex;justify-content:space-between">
          <span style="font-size:10px;color:${textMuted}">Duration</span>
          <span style="font-size:10px;font-weight:600;color:#ff5d5d">${meta.duration} min</span>
        </div>` : ''}
        ${meta.point?.gps_time ? `<div style="display:flex;justify-content:space-between">
          <span style="font-size:10px;color:${textMuted}">Time</span>
          <span style="font-size:10px;color:${textSub}">${new Date(meta.point.gps_time).toLocaleTimeString()}</span>
        </div>` : ''}
      </div>
    </div>`;
    marker.bindPopup(stoppageHTML, { className: 'tv-popup', maxWidth: 200, autoPan: false });
    marker.on('mouseover', function() { marker.openPopup(); });
    marker.on('mouseout', function() { marker.closePopup(); });
    if (!showStoppageHeatmap._markers) showStoppageHeatmap._markers = [];
    showStoppageHeatmap._markers.push(marker);
  });
  heatmapVisible = true;
}

function hideStoppageHeatmap() {
  if (stoppageHeatmapLayer && playbackMap) {
    playbackMap.removeLayer(stoppageHeatmapLayer);
    stoppageHeatmapLayer = null;
  }
  // Remove all stoppage markers
  if (showStoppageHeatmap._markers) {
    showStoppageHeatmap._markers.forEach(m => playbackMap.removeLayer(m));
    showStoppageHeatmap._markers = [];
  }
  heatmapVisible = false;
}

function toggleStoppageHeatmap() {
  if (heatmapVisible) {
    hideStoppageHeatmap();
  } else {
    showStoppageHeatmap();
  }
  updateHeatmapButtonState();
}

function addHeatmapToggleButton() {
  // Skip if the Trip Replay panel in vehicle.html provides its own toggle
  if (!playbackMap) return;
  if (document.getElementById('tripReplayPanel')) return;
  if (document.getElementById('heatmapToggleBtn')) return;
  const btn = document.createElement('button');
  btn.id = 'heatmapToggleBtn';
  btn.innerHTML = `
    <div class="flex items-center gap-2">
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M2 12h20"/><path d="M12 2v20"/>
      </svg>
      <span>${heatmapVisible ? 'Hide Heatmap' : 'Show Heatmap'}</span>
    </div>
  `;
  btn.style.position = 'absolute';
  btn.style.top = '210px';
  btn.style.left = '16px';
  btn.style.bottom = '';
  btn.style.right = '';
  btn.style.zIndex = 1200;
  btn.style.background = heatmapVisible ? '#fee2e2' : '#fff';
  btn.style.color = heatmapVisible ? '#b91c1c' : '#1e293b';
  btn.style.border = `2px solid ${heatmapVisible ? '#b91c1c' : '#cbd5e1'}`;
  btn.style.borderRadius = '8px';
  btn.style.padding = '8px 12px';
  btn.style.fontSize = '12px';
  btn.style.fontWeight = '600';
  btn.style.cursor = 'pointer';
  btn.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)';
  btn.style.transition = 'all 0.2s ease';
  btn.style.display = 'flex';
  btn.style.alignItems = 'center';
  btn.style.gap = '8px';
  btn.style.backdropFilter = 'blur(12px)';
  btn.onmouseover = () => {
    btn.style.transform = 'translateY(-2px)';
    btn.style.boxShadow = '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)';
  };
  btn.onmouseout = () => {
    btn.style.transform = '';
    btn.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)';
  };
  btn.onclick = toggleStoppageHeatmap;
  // Attach to map container
  const mapEl = playbackMap.getContainer();
  mapEl.appendChild(btn);
  updateHeatmapButtonState();
}

function updateHeatmapButtonState() {
  const btn = document.getElementById('heatmapToggleBtn');
  if (btn) {
    btn.innerHTML = `
      <div class="flex items-center gap-2">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M2 12h20"/><path d="M12 2v20"/>
        </svg>
        <span>${heatmapVisible ? 'Hide Heatmap' : 'Show Heatmap'}</span>
      </div>
    `;
    btn.style.background = heatmapVisible ? '#fee2e2' : '#fff';
    btn.style.color = heatmapVisible ? '#b91c1c' : '#1e293b';
    btn.style.borderColor = heatmapVisible ? '#b91c1c' : '#cbd5e1';
    btn.style.border = `2px solid ${heatmapVisible ? '#b91c1c' : '#cbd5e1'}`;
  }
}

function buildPlaybackPopupHTML(displayNumber, timeStr, speed, soc, location) {
  const isDark = document.body.classList.contains('dark-theme');
  const border   = isDark ? '#1a2540' : '#e2e8f0';
  const textMuted = isDark ? '#475569' : '#64748b';
  const textSub   = isDark ? '#94a3b8' : '#334155';
  const socCol    = soc > 60 ? '#22c55e' : soc > 30 ? '#f59e0b' : '#ef4444';
  const loc = location || '';
  return `<div style="min-width:170px;font-family:Inter,system-ui,sans-serif;">
  <div style="font-size:12px;font-weight:600;margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid ${border}">${displayNumber}</div>
  <div style="display:flex;flex-direction:column;gap:4px">
    <div style="display:flex;justify-content:space-between;gap:12px">
      <span style="font-size:10px;color:${textMuted};flex-shrink:0">Time</span>
      <span style="font-size:10px;color:${textSub};text-align:right">${timeStr}</span>
    </div>
    <div style="display:flex;justify-content:space-between">
      <span style="font-size:10px;color:${textMuted}">Speed</span>
      <span style="font-size:10px;color:${textSub}">${speed} km/h</span>
    </div>
    <div style="display:flex;justify-content:space-between">
      <span style="font-size:10px;color:${textMuted}">Battery</span>
      <span style="font-size:10px;font-weight:600;color:${socCol}">${soc}%</span>
    </div>
    ${loc ? `<div style="display:flex;justify-content:space-between;gap:8px">
      <span style="font-size:10px;color:${textMuted};flex-shrink:0">Location</span>
      <span style="font-size:10px;color:${textSub};text-align:right;line-height:1.3">${loc}</span>
    </div>` : ''}
  </div>
  <div style="margin-top:8px;height:3px;border-radius:2px;background:${isDark ? '#0f1829' : '#e2e8f0'};overflow:hidden">
    <div style="width:${Math.min(soc,100)}%;height:100%;border-radius:2px;background:${socCol}"></div>
  </div>
</div>`;
}

/**
 * Vehicle truck icon for playback (status-aware, heading-aware)
 */
function getVehicleIcon(status, heading = 0) {
  const s = (status || 'moving').toLowerCase();
  const isDark = document.body.classList.contains('dark-theme');
  const hl = isDark
    ? { beam1: 'rgba(255,250,140,.13)', beam2: 'rgba(255,250,140,.22)', halo: 'rgba(255,252,160,.28)', mid: 'rgba(255,254,200,.75)', core: '#fffde0' }
    : { beam1: 'rgba(200,130,0,.28)', beam2: 'rgba(210,145,0,.45)', halo: 'rgba(225,155,0,.40)', mid: 'rgba(240,170,0,.88)', core: '#a86800' };
  const colors = {
    moving:   { body: '#0d2240', front: '#112a52', stroke: '#2563eb', bolt: '#22c55e' },
    stopped:  { body: '#2a0d0d', front: '#3a1010', stroke: '#7f1d1d', bolt: '#ef4444' },
    charging: { body: '#0d1f3c', front: '#112347', stroke: '#1d4ed8', bolt: '#3b82f6' },
    idling:   { body: '#251800', front: '#2e1f00', stroke: '#92400e', bolt: '#f59e0b' },
  };
  const c = colors[s] || colors.moving;
  const style = localStorage.getItem('markerStyle') || 'truck';

  if (style === 'arrow') {
    const arrowSVG = `<svg width="22" height="30" viewBox="0 0 22 30" fill="none" overflow="visible">
      <g transform="rotate(${heading},11,15)">
        <path d="M11 2 L21 28 L11 21 L1 28 Z" fill="rgba(0,0,0,.3)" transform="translate(0.8,1)"/>
        <path d="M11 2 L21 28 L11 21 L1 28 Z" fill="${c.bolt}" stroke="rgba(255,255,255,.35)" stroke-width="1.2" stroke-linejoin="round"/>
        <line x1="11" y1="11" x2="11" y2="21" stroke="rgba(255,255,255,.35)" stroke-width="1"/>
      </g>
    </svg>`;
    return L.divIcon({
      html: `<div style="position:relative;width:44px;height:44px;display:flex;align-items:center;justify-content:center">${arrowSVG}</div>`,
      className: '',
      iconSize: [44, 44],
      iconAnchor: [22, 22],
      popupAnchor: [0, -24]
    });
  }

  // Slimmed truck with headlight beams
  const truckSVG = `<svg width="26" height="46" viewBox="0 0 26 46" fill="none" overflow="visible">
    <g transform="rotate(${heading},13,23)">
      <path d="M7.5 4 L-6 -22 L18 -22 Z" fill="${hl.beam1}"/>
      <path d="M7.5 4 L-1 -14 L15 -14 Z" fill="${hl.beam2}"/>
      <path d="M18.5 4 L8  -22 L32 -22 Z" fill="${hl.beam1}"/>
      <path d="M18.5 4 L11 -14 L27 -14 Z" fill="${hl.beam2}"/>
      <rect x="5" y="4" width="16" height="38" rx="3" fill="${c.body}" stroke="${c.stroke}" stroke-width="1.5"/>
      <rect x="6.5" y="4" width="13" height="8" rx="2.5" fill="${c.front}"/>
      <rect x="8" y="5.5" width="10" height="5" rx="1.5" fill="${c.stroke}" opacity=".45"/>
      <rect x="1"  y="10" width="4" height="8" rx="1.5" fill="#09140d" stroke="${c.stroke}" stroke-width=".7" opacity=".85"/>
      <rect x="21" y="10" width="4" height="8" rx="1.5" fill="#09140d" stroke="${c.stroke}" stroke-width=".7" opacity=".85"/>
      <rect x="1"  y="29" width="4" height="8" rx="1.5" fill="#09140d" stroke="${c.stroke}" stroke-width=".7" opacity=".85"/>
      <rect x="21" y="29" width="4" height="8" rx="1.5" fill="#09140d" stroke="${c.stroke}" stroke-width=".7" opacity=".85"/>
      <path d="M14.5 17l-5 9h5l-4 9 10-11h-6z" fill="${c.bolt}" opacity=".92"/>
      <circle cx="7.5"  cy="4" r="4"   fill="${hl.halo}"/>
      <circle cx="7.5"  cy="4" r="1.8" fill="${hl.mid}"/>
      <circle cx="7.5"  cy="4" r=".85" fill="${hl.core}"/>
      <circle cx="18.5" cy="4" r="4"   fill="${hl.halo}"/>
      <circle cx="18.5" cy="4" r="1.8" fill="${hl.mid}"/>
      <circle cx="18.5" cy="4" r=".85" fill="${hl.core}"/>
    </g>
  </svg>`;
  return L.divIcon({
    html: `<div style="position:relative;width:52px;height:52px;display:flex;align-items:center;justify-content:center">${truckSVG}</div>`,
    className: '',
    iconSize: [52, 52],
    iconAnchor: [26, 26],
    popupAnchor: [0, -30]
  });
}


/**
 * Get address from coordinates with caching.
 * @param {number} lat - Latitude
 * @param {number} lon - Longitude
 * @returns {Promise<string>} Address string or 'Loading address...'
 */
async function getAddressFromCoords(lat, lon) {
  // Round to 4 decimal places for cache key (~11 meters precision)
  const cacheKey = `${lat.toFixed(4)}_${lon.toFixed(4)}`;
  
  // Check cache first
  if (addressCache[cacheKey]) {
    return addressCache[cacheKey];
  }
  
  try {
    const response = await fetch(`/livetracker/api/geocode/?lat=${lat}&lon=${lon}`);
    const data = await response.json();
    
    if (data.success && data.address) {
      // Cache the result
      addressCache[cacheKey] = data.address;
      return data.address;
    } else {
      // Cache negative result to avoid repeated failed calls
      addressCache[cacheKey] = `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
      return addressCache[cacheKey];
    }
  } catch (error) {
    console.warn('Geocoding failed:', error);
    // Return coordinates as fallback
    const fallback = `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
    addressCache[cacheKey] = fallback;
    return fallback;
  }
}

// ===================================================
// MAIN ENTRY POINT FOR VEHICLE PAGE
// ===================================================
export async function initializeVehiclePlayback(registrationNumber, historicalDate = null) {
  try {
    
    // Get existing map container
    const mapContainer = document.getElementById('map');
    if (!mapContainer) {
      throw new Error('Map container not found');
    }

    // Initialize map if not already done
    if (!playbackMap) {
      setupVehicleMap();
    }

    // Show loading state
    showSpinner(true, historicalDate ? `Loading historical data for ${historicalDate}...` : 'Loading playback data...');

    const data = await fetchVehicleOneDay(registrationNumber, historicalDate);

    if (!Array.isArray(data) || data.length === 0) {
      showSpinner(false);
      console.error('❌ No playback data returned. Vehicle:', registrationNumber, 'Date:', historicalDate);
      if (window.showNoDataModal) {
        window.showNoDataModal(
          `No GPS tracking data available for vehicle ${registrationNumber}${historicalDate ? ` on ${historicalDate}` : ' today'}.`,
          registrationNumber
        );
      } else {
        alert(`No data available for vehicle ${registrationNumber}`);
      }
      throw new Error('No playback data found.');
    }

    // data is already sorted oldest→newest by fetchVehicleOneDay
    playbackData = data;
    currentVehicleNumber = registrationNumber;
    
    // Detect events from playback data
    
    try {
      detectedEvents = detectEventsFromData(playbackData);
    } catch (eventError) {
      console.error('❌ Error detecting events:', eventError);
      detectedEvents = [];
    }
    
    // Create floating header with vehicle info
    createVehicleInfoHeader(registrationNumber, playbackData[0]);
    
    setupPlaybackControls();
    
    // Add event visualization to timeline after DOM is ready
    setTimeout(() => {
      if (detectedEvents && detectedEvents.length > 0) {
        try {
          addEventBlocksToTimeline(detectedEvents);
        } catch (timelineError) {
          console.error('❌ Error adding events to timeline:', timelineError);
        }
      } else {
        console.warn('⚠️ No events to add to timeline');
      }
    }, 100);
    
    drawPlaybackPath();
    showSpinner(false);
    
    // Add heatmap after map is ready and show heatmap if enabled by default
    // Use longer timeout to ensure events and path are fully rendered
    setTimeout(() => {
      addHeatmapToggleButton();
      if (heatmapVisible) {
        showStoppageHeatmap();
      }
    }, 300);
    return data; // Return the data for analytics
  } catch (err) {
    console.error('❌ Playback error:', err);
    console.error('❌ Error stack:', err.stack);
    showSpinner(false);
    throw err; // Re-throw for proper error handling
  }
}

// ===================================================
// VEHICLE INFO HEADER
// ===================================================
async function createVehicleInfoHeader(registrationNumber, firstPoint) {
  // Check if header already exists
  let header = document.getElementById('vehicleInfoHeader');
  
  if (!header) {
    header = document.createElement('div');
    header.id = 'vehicleInfoHeader';
    document.body.appendChild(header);
  }
  
  const displayNumber = getDisplayVehicleNumber(registrationNumber);
  const vehicleModel = firstPoint?.model || '';

  // Style the header - compact and clean
  header.style.cssText = `
    position: fixed;
    top: 76px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 10000;
    background: rgba(255, 255, 255, 0.98);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    padding: 8px 16px;
    border-radius: 10px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1), 0 1px 4px rgba(0, 0, 0, 0.06);
    border: 1px solid rgba(226, 232, 240, 0.6);
    transition: all 0.2s ease;
  `;

  // Add subtle hover effect
  header.onmouseenter = () => {
    header.style.boxShadow = '0 6px 20px rgba(0, 0, 0, 0.12), 0 2px 6px rgba(0, 0, 0, 0.08)';
  };

  header.onmouseleave = () => {
    header.style.boxShadow = '0 4px 16px rgba(0, 0, 0, 0.1), 0 1px 4px rgba(0, 0, 0, 0.06)';
  };

  header.innerHTML = `
    <div class="flex items-center gap-2.5 text-base">
      <div class="flex items-center gap-2">
        <i data-lucide="truck" class="w-4.5 h-4.5 text-blue-600"></i>
        <span class="font-bold text-slate-900">${displayNumber}</span>
      </div>
    </div>
  `;

  // Initialize Lucide icons if available
  if (typeof lucide !== 'undefined') {
    setTimeout(() => lucide.createIcons(), 50);
  }
}

// ===================================================
// MAP SETUP
// ===================================================
function setupVehicleMap() {
  const mapEl = document.getElementById('map');
  
  // Check if map is already initialized
  if (playbackMap) {
    return;
  }
  
  // Check if the element already has a Leaflet map
  if (mapEl._leaflet_id) {
    mapEl._leaflet_id = null;
    mapEl.innerHTML = ''; // Clear the container
  }

  // Ensure map container has proper CSS for interaction
  mapEl.style.pointerEvents = 'auto';
  mapEl.style.touchAction = 'none';
  
  playbackMap = L.map(mapEl, {
    center: [21.1458, 75.0842], // Default center (adjust as needed)
    zoom: 10,
    zoomControl: false,
    attributionControl: false,
    dragging: true,
    touchZoom: true,
    scrollWheelZoom: true,
    doubleClickZoom: true,
    boxZoom: true,
    keyboard: true,
    tap: true,
    bounceAtZoomLimits: false
  });

  // Add tile layer (theme-aware)
  switchVehicleTiles();

  // Ensure map dragging is enabled after initialization
  if (playbackMap.dragging) {
    playbackMap.dragging.enable();
  }

  // Force map to recalculate size and interactions
  setTimeout(() => {
    playbackMap.invalidateSize();
    
    // Ensure all map panes have proper pointer events
    const mapContainer = playbackMap.getContainer();
    if (mapContainer) {
      mapContainer.style.cursor = 'grab';
      mapContainer.style.pointerEvents = 'auto';
      mapContainer.style.touchAction = 'none';
    }

    // Ensure all map panes have proper pointer events
    const mapPane = playbackMap.getPane('mapPane');
    if (mapPane) {
      mapPane.style.pointerEvents = 'auto';
    }

    const overlayPane = playbackMap.getPane('overlayPane');
    if (overlayPane) {
      overlayPane.style.pointerEvents = 'auto';
    }
  
  }, 100);

  // Add geofences to vehicle map
  addGeofences(playbackMap);

  // Corridor is Ultratech-specific — only show for that project
  const _pathParts = window.location.pathname.split('/').filter(Boolean);
  const _isUltratech = !(_pathParts.length >= 2 && _pathParts[1] === 'livetracker') ||
                       _pathParts[0].toLowerCase() === 'ultratech';
  if (_isUltratech) {
    addCorridorToggleButton();
    try { toggleCorridorOverlay(); } catch (_) {}
  }
}

// ===================================================
// PLAYBACK CONTROLS SETUP
// ===================================================
function _scrubberColors() {
  const dark = document.body.classList.contains('dark-theme');
  return {
    panel:  dark ? '#0a160f' : '#ffffff',
    inset:  dark ? '#0c1a12' : '#eef1f5',
    line:   dark ? '#16271d' : '#e3e7ee',
    ink:    dark ? '#e6edf6' : '#0d1220',
    ink2:   dark ? '#aab4c4' : '#3f4a61',
    ink3:   dark ? '#7a8699' : '#5c687e',
    signal: dark ? '#38e1c4' : '#0d9488',
  };
}

function setupPlaybackControls() {
  const controlsContainer = document.getElementById('playbackControls');
  if (!controlsContainer) {
    console.error('❌ Playback controls container not found!');
    return;
  }

  const startTime = new Date(playbackData[0].gps_time);
  const endTime   = new Date(playbackData[playbackData.length - 1].gps_time);
  const journeyDurationMs = endTime - startTime;
  const c = _scrubberColors();

  controlsContainer.innerHTML = `
<div style="display:flex;align-items:center;gap:8px;width:100%;font-family:'Space Grotesk',sans-serif;">

  <!-- Transport buttons -->
  <div style="display:flex;align-items:center;gap:3px;flex-shrink:0;">
    <button id="resetBtn" title="Restart"
      style="width:26px;height:26px;display:flex;align-items:center;justify-content:center;border-radius:5px;border:1px solid ${c.line};background:transparent;color:${c.ink2};cursor:pointer;transition:all .15s;">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polygon points="19 20 9 12 19 4 19 20"/><line x1="5" y1="19" x2="5" y2="5"/></svg>
    </button>
    <button id="playBtn" title="Play"
      style="width:30px;height:30px;display:flex;align-items:center;justify-content:center;border-radius:6px;border:none;background:${c.signal};color:#fff;cursor:pointer;box-shadow:0 0 10px ${c.signal}55;flex-shrink:0;">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
    </button>
    <button id="pauseBtn" title="Pause"
      style="width:30px;height:30px;display:none;align-items:center;justify-content:center;border-radius:6px;border:none;background:${c.signal};color:#fff;cursor:pointer;box-shadow:0 0 10px ${c.signal}55;flex-shrink:0;">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
    </button>
    <button id="stopBtn" title="Stop"
      style="width:26px;height:26px;display:flex;align-items:center;justify-content:center;border-radius:5px;border:1px solid ${c.line};background:transparent;color:${c.ink2};cursor:pointer;transition:all .15s;">
      <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>
    </button>
  </div>

  <!-- Divider -->
  <div style="width:1px;height:18px;background:${c.line};flex-shrink:0;"></div>

  <!-- Speed dropdown -->
  <div id="_speedDropWrap" style="position:relative;flex-shrink:0;">
    <button id="_speedDropBtn" title="Playback speed"
      style="display:flex;align-items:center;gap:3px;padding:2px 7px;border-radius:5px;border:1px solid ${c.line};background:transparent;color:${c.ink};font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:600;cursor:pointer;white-space:nowrap;">
      <span id="_speedDropLabel">3×</span>
      <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="${c.ink3}" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
    </button>
    <div id="_speedDropMenu" style="display:none;position:absolute;bottom:calc(100% + 4px);left:0;min-width:68px;background:${c.panel};border:1px solid ${c.line};border-radius:6px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.22);z-index:9999;">
      ${['0.5','1','2','3','5','10','50'].map(v =>
        `<button data-spd="${v}"
          style="display:block;width:100%;padding:5px 12px;text-align:left;background:transparent;border:none;color:${c.ink2};font-family:'JetBrains Mono',monospace;font-size:11px;cursor:pointer;"
          onmouseover="this.style.background='${c.inset}'" onmouseout="this.style.background='transparent'"
          onclick="window._vaSetSpeed(${v})">${v}×</button>`
      ).join('')}
    </div>
  </div>

  <!-- Divider -->
  <div style="width:1px;height:18px;background:${c.line};flex-shrink:0;"></div>

  <!-- Timeline scrubber (fills remaining space) -->
  <div style="flex:1;min-width:0;position:relative;height:20px;">
    <input type="range" id="progressSlider" min="0" max="10000" value="0"
      style="position:absolute;inset:0;width:100%;height:100%;opacity:0;z-index:20;cursor:pointer;margin:0;padding:0;">
    <div id="_timelineTrack" style="position:relative;height:100%;background:${c.inset};border-radius:4px;border:1px solid ${c.line};overflow:visible;">
      <div id="eventsContainer" style="position:absolute;inset:0;border-radius:4px;overflow:hidden;display:flex;align-items:center;"></div>
      <div style="position:absolute;inset:0;display:flex;align-items:center;pointer-events:none;">
        ${generateTickMarks(journeyDurationMs)}
      </div>
      <div id="progressIndicator"
        style="position:absolute;width:2px;background:${c.signal};top:6%;bottom:6%;left:0%;pointer-events:none;z-index:30;box-shadow:0 0 6px ${c.signal}cc;transition:none;">
        <div style="position:absolute;top:-4px;left:50%;transform:translateX(-50%);width:10px;height:10px;border-radius:50%;background:${c.signal};border:2px solid ${c.panel};box-shadow:0 0 8px ${c.signal};"></div>
      </div>
    </div>
  </div>

  <!-- Readout (right edge) -->
  <div id="scrubberReadout"
    style="font-family:'JetBrains Mono',monospace;font-size:10px;color:${c.ink3};white-space:nowrap;flex-shrink:0;letter-spacing:0.01em;">
    — · — · —
  </div>

</div>
  `;

  // Speed dropdown logic
  const speedDropBtn  = document.getElementById('_speedDropBtn');
  const speedDropMenu = document.getElementById('_speedDropMenu');
  speedDropBtn?.addEventListener('click', e => {
    e.stopPropagation();
    speedDropMenu.style.display = speedDropMenu.style.display === 'none' ? 'block' : 'none';
  });
  document.addEventListener('click', () => { if (speedDropMenu) speedDropMenu.style.display = 'none'; }, true);
  window._vaSetSpeed = function(v) {
    playbackSpeed = parseFloat(v);
    const lbl = document.getElementById('_speedDropLabel');
    if (lbl) lbl.textContent = `${v}×`;
    if (speedDropMenu) speedDropMenu.style.display = 'none';
  };
  // Also expose legacy speedSelect shim for any external code
  window.speedSelect = { value: '3', onchange: null };

  // Hover readout on slider
  const slider = document.getElementById('progressSlider');
  if (slider) {
    slider.addEventListener('mousemove', e => {
      const r = slider.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
      updateScrubberReadout(Math.round(ratio * (playbackData.length - 1)));
    });
    slider.addEventListener('mouseleave', () => updateScrubberReadout(currentIndex));
  }

  // Document-flow bar: reset any floating styles, keep width/transform explicit
  controlsContainer.style.position  = 'static';
  controlsContainer.style.bottom    = 'auto';
  controlsContainer.style.left      = 'auto';
  controlsContainer.style.right     = 'auto';
  controlsContainer.style.transform = 'none';
  controlsContainer.style.maxWidth  = 'none';
  controlsContainer.style.width     = '100%';
  controlsContainer.style.display   = 'block';
  controlsContainer.style.backdropFilter = 'none';
  controlsContainer.style.WebkitBackdropFilter = 'none';

  // Button handlers
  document.getElementById('playBtn')?.addEventListener('click',  playPlayback);
  document.getElementById('pauseBtn')?.addEventListener('click', pausePlayback);
  document.getElementById('stopBtn')?.addEventListener('click',  stopPlayback);
  document.getElementById('resetBtn')?.addEventListener('click', resetPlayback);

  setTimeout(setupSliderInteraction, 100);

  // Expose a refresh hook for theme toggle
  window.refreshScrubberTheme = function() {
    const fresh = _scrubberColors();
    const ind = document.getElementById('progressIndicator');
    if (ind) {
      ind.style.background   = fresh.signal;
      ind.style.boxShadow    = `0 0 6px ${fresh.signal}cc`;
      const dot = ind.firstElementChild;
      if (dot) { dot.style.background = fresh.signal; dot.style.border = `2px solid ${fresh.panel}`; dot.style.boxShadow = `0 0 10px ${fresh.signal}`; }
    }
    const pb = document.getElementById('playBtn');
    if (pb) { pb.style.background = fresh.signal; pb.style.boxShadow = `0 0 12px ${fresh.signal}55`; }
    const pau = document.getElementById('pauseBtn');
    if (pau) { pau.style.background = fresh.signal; pau.style.boxShadow = `0 0 12px ${fresh.signal}55`; }
  };
}

/**
 * Populates the ride summary panel with data and makes it visible.
 * @param {object} summary - The summary data object.
 */
/**
 * ===================================================
 * RIDE SUMMARY POPULATION
 * ===================================================
 * Populates the ride summary panel with calculated time data.
 * Called by vehicle_analytics.js after analytics are loaded.
 * 
 * @param {Object} summary - Ride summary with formatted time strings
 * @param {string} summary.totalRideTime - Total ride duration (HH:MM:SS)
 * @param {string} summary.totalStopTime - Total stopped time (HH:MM:SS)
 * @param {string} summary.totalMovingTime - Total moving time (HH:MM:SS)
 * @param {string} summary.totalChargingTime - Total charging time (HH:MM:SS)
 */
function populateRideSummary(summary) {
  
  if (!summary) {
    console.warn('⚠️ No summary data provided to populateRideSummary');
    return;
  }

  const elements = {
    panel: document.getElementById('rideSummaryPanel'),
    totalRideTime: document.getElementById('summaryTotalRideTime'),
    totalStopTime: document.getElementById('summaryTotalStopTime'),
    totalMovingTime: document.getElementById('summaryTotalMovingTime'),
    totalChargingTime: document.getElementById('summaryTotalChargingTime')
  };
  if (elements.totalRideTime) {
    elements.totalRideTime.textContent = summary.totalRideTime || '--:--:--';
  }
  
  if (elements.totalStopTime) {
    elements.totalStopTime.textContent = summary.totalStopTime || '--:--:--';
  }
  
  if (elements.totalMovingTime) {
    elements.totalMovingTime.textContent = summary.totalMovingTime || '--:--:--';
  }
  
  if (elements.totalChargingTime) {
    elements.totalChargingTime.textContent = summary.totalChargingTime || '--:--:--';
  }

  // Make the panel visible
  if (elements.panel) {
    elements.panel.classList.remove('hidden');
  } else {
    console.error('❌ rideSummaryPanel element not found in DOM!');
    console.error('💡 Hint: Make sure setupPlaybackControls() has been called first');
  }
}

// Expose to global window for analytics integration
window.populateRideSummary = populateRideSummary;

// ===================================================
// TIMELINE GENERATION HELPERS - ADAPTIVE INTERVALS
// ===================================================
/**
 * Generate tick marks at time-proportional positions (2-hour intervals).
 */
function generateTickMarks(journeyDurationMs) {
  const intervalMs = 2 * 60 * 60 * 1000; // 2-hour intervals
  const startMs = new Date(playbackData[0].gps_time).getTime();
  const endMs   = new Date(playbackData[playbackData.length - 1].gps_time).getTime();
  let ticks = '';
  // First tick at the next even 2h boundary after start
  let tickMs = Math.ceil(startMs / intervalMs) * intervalMs;
  while (tickMs <= endMs) {
    const position = ((tickMs - startMs) / journeyDurationMs) * 100;
    ticks += `<div style="position:absolute;left:${position.toFixed(2)}%;width:1px;height:55%;top:22.5%;transform:translateX(-0.5px);background:rgba(140,150,170,0.4);"></div>`;
    tickMs += intervalMs;
  }
  return ticks;
}

/**
 * Generate time labels with continuous intervals aligned to actual clock times.
 * Dynamically adjusts interval based on duration to prevent overlap.
 * If journey starts at 12:30, shows: 12:30, 2:00, 4:00, 6:00, etc.
 */
function generateTimeLabels(startTime, endTime, journeyDurationMs) {
  const durationHours = journeyDurationMs / (1000 * 60 * 60);
  
  // Dynamic interval calculation based on duration
  let intervalHours;
  if (durationHours <= 6) {
    intervalHours = 1;      // 1-hour intervals for short trips
  } else if (durationHours <= 12) {
    intervalHours = 2;      // 2-hour intervals for medium trips
  } else if (durationHours <= 24) {
    intervalHours = 3;      // 3-hour intervals for long trips
  } else {
    intervalHours = 4;      // 4-hour intervals for very long trips
  }
  
  const labels = [];
  const minSpacingPercent = 8; // Minimum 8% spacing between labels to prevent overlap
  
  // Always show start time
  labels.push({
    time: startTime,
    position: 0
  });
  
  // Generate labels at continuous intervals (2:00, 4:00, 6:00, etc.)
  const startHour = startTime.getHours();
  const startMinutes = startTime.getMinutes();
  
  // Find the next even interval hour after start time
  let nextLabelHour = Math.ceil((startHour + startMinutes / 60) / intervalHours) * intervalHours;
  
  // Generate labels until we reach or pass the end time
  let currentLabelTime = new Date(startTime);
  currentLabelTime.setHours(nextLabelHour % 24, 0, 0, 0);
  
  // If next label is before start time (due to day rollover), add a day
  if (currentLabelTime < startTime) {
    currentLabelTime.setDate(currentLabelTime.getDate() + 1);
  }
  
  while (currentLabelTime < endTime) {
    // Calculate position as percentage
    const elapsed = currentLabelTime - startTime;
    const position = (elapsed / journeyDurationMs) * 100;
    
    // Only add if it's far enough from previous label and not too close to end
    const lastPosition = labels[labels.length - 1].position;
    const distanceFromEnd = 100 - position;
    
    if (position > 0 && position < 100 && 
        (position - lastPosition) >= minSpacingPercent && 
        distanceFromEnd >= minSpacingPercent) {
      labels.push({
        time: new Date(currentLabelTime),
        position: position
      });
    }
    
    // Move to next interval
    currentLabelTime = new Date(currentLabelTime.getTime() + intervalHours * 60 * 60 * 1000);
  }
  
  // Only add end time if it's far enough from the last label
  const lastPosition = labels[labels.length - 1].position;
  if ((100 - lastPosition) >= minSpacingPercent) {
    labels.push({
      time: endTime,
      position: 100
    });
  }
  
  const isDark = document.body.classList.contains('dark-theme');
  const labelColor = isDark ? '#7a8699' : '#5c687e';
  // Generate HTML for labels
  return labels.map(label => `
    <div style="position:absolute;left:${label.position}%;transform:translateX(-50%);">
      <span style="white-space:nowrap;font-size:10.5px;font-weight:600;color:${labelColor};letter-spacing:-0.01em;font-family:'Space Grotesk',sans-serif;">${formatTime(label.time)}</span>
    </div>
  `).join('');
}

function formatTime(date) {
  const hours = date.getHours();
  const minutes = date.getMinutes();
  const ampm = hours >= 12 ? 'PM' : 'AM';
  const displayHours = hours % 12 || 12;
  const displayMinutes = minutes.toString().padStart(2, '0');
  return `${displayHours}:${displayMinutes} ${ampm}`;
}

// ===================================================
// EVENT DETECTION AND VISUALIZATION
// ===================================================

// ===================================================
// INDUSTRY-STANDARD COLOR CONVENTIONS
// ===================================================
// Following ISO 3864 and EV/UI industry standards:
// - Green = Moving (healthy operation)
// - Red = Stopped (urgent attention, exception)
// - Blue = Charging (EV/UI blue for electricity, charging points)
// - Orange/Amber = Idling (caution, inefficiency, semi-unhealthy state)

const INDUSTRY_COLORS = {
  MOVING: '#22c55e',        // Green - universally recognized for "go" / healthy operation
  STOPPED: '#ef4444',       // Red - urgent, attention, exception (ISO 3864)
  CHARGING: '#3b82f6',      // Blue - EV/UI blue for electricity, charging points
  IDLING: '#fb923c'         // Orange/Amber - caution, inefficiency
};

// Event detection thresholds (matching alert_constants.py)
const EVENT_THRESHOLDS = {
  UNPLANNED_STOP_SECONDS: 10 * 60,      // 10 minutes
  CHARGING_OVER_SECONDS: 90 * 60,       // 90 minutes
  LOADING_DWELL_SECONDS: 20 * 60,       // 20 minutes
  UNLOADING_DWELL_SECONDS: 15 * 60,     // 15 minutes
  FEED_GAP_SECONDS: 3 * 60,             // 3 minutes
  SPEED_THRESHOLD: 1,                   // km/h (below = stopped)
  CHARGING_SOC_INCREASE: 5              // Minimum SOC increase to consider charging
};

/**
 * Detect events from playback data
 * @param {Array} data - Array of playback data points
 * @returns {Array} Array of detected events
 */
function detectEventsFromData(data) {
  if (!data || data.length === 0) return [];
  
  const events = [];
  let currentEvent = null;
  
  for (let i = 0; i < data.length; i++) {
    const point = data[i];
    const nextPoint = data[i + 1];
    
    if (!point.gps_time) continue;
    
    const speed = parseFloat(point.speed) || 0;
    const status = point.vehicle_status || '';
    const soc = parseFloat(point.soc) || 0;
    const timestamp = new Date(point.gps_time);
    
    // Determine event type for this point using industry conventions
    let eventType = 'moving';
    let eventLabel = 'Moving';
    
    // Priority 1: Charging (Blue) - Check if actively charging
    if (status === 'Charging' || (speed < EVENT_THRESHOLDS.SPEED_THRESHOLD && soc > 0 && nextPoint && parseFloat(nextPoint.soc) > soc + EVENT_THRESHOLDS.CHARGING_SOC_INCREASE)) {
      eventType = 'charging';
      eventLabel = 'Charging';
    } 
    // Priority 2: Stopped (Red) - Completely stopped
    else if (speed < EVENT_THRESHOLDS.SPEED_THRESHOLD) {
      eventType = 'stopped';
      eventLabel = 'Stopped';
    } 
    // Priority 3: Idling (Orange) - Moving but very slow (inefficient)
    else if (speed < 5) {
      eventType = 'idling';
      eventLabel = 'Idling';
    }
    // Default: Moving (Green) - Normal operation
    else {
      eventType = 'moving';
      eventLabel = 'Moving';
    }
    
    // Group consecutive points of same type into events
    if (!currentEvent || currentEvent.type !== eventType) {
      // Save previous event if it exists
      if (currentEvent) {
        events.push(currentEvent);
      }
      
      // Start new event
      currentEvent = {
        type: eventType,
        label: eventLabel,
        startTime: timestamp,
        endTime: timestamp,
        startIndex: i,
        endIndex: i,
        points: [point]
      };
    } else {
      // Continue current event
      currentEvent.endTime = timestamp;
      currentEvent.endIndex = i;
      currentEvent.points.push(point);
    }
  }
  
  // Add final event
  if (currentEvent) {
    events.push(currentEvent);
  }
  
  // Post-process events to identify specific types
  const processedEvents = events.map(event => {
    const durationSeconds = (new Date(event.endTime) - new Date(event.startTime)) / 1000;
    
    // Classify stopped events
    if (event.type === 'stopped') {
      if (durationSeconds >= EVENT_THRESHOLDS.UNPLANNED_STOP_SECONDS) {
        event.label = `Unplanned Stop (${Math.round(durationSeconds / 60)}min)`;
        event.type = 'unplanned_stop';
      } else {
        event.label = `Brief Stop (${Math.round(durationSeconds / 60)}min)`;
      }
    }
    
    // Classify charging events
    if (event.type === 'charging') {
      if (durationSeconds >= EVENT_THRESHOLDS.CHARGING_OVER_SECONDS) {
        event.label = `Charging (${Math.round(durationSeconds / 60)}min - Extended)`;
      } else {
        event.label = `Charging (${Math.round(durationSeconds / 60)}min)`;
      }
    }
    
    event.duration = durationSeconds;
    return event;
  });
  
  return processedEvents;
}

/**
 * Add event blocks to the timeline
 * @param {Array} events - Array of event objects with {startTime, endTime, type, label}
 */
function addEventBlocksToTimeline(events) {
  const eventsContainer = document.getElementById('eventsContainer');
  
  
  if (!eventsContainer) {
    console.error('❌ eventsContainer not found!');
    return;
  }
  
  if (!playbackData.length) {
    console.error('❌ playbackData is empty!');
    return;
  }
  
  const journeyStart = new Date(playbackData[0].gps_time).getTime();
  const journeyEnd = new Date(playbackData[playbackData.length - 1].gps_time).getTime();
  const journeyDuration = journeyEnd - journeyStart;
  
  eventsContainer.innerHTML = '';
  
  // Industry-standard event type colors
  const eventColors = {
    'charging': 'bg-blue-500',            // Blue for charging (EV/UI standard)
    'moving': 'bg-green-500',             // Green for moving (healthy operation)
    'unplanned_stop': 'bg-red-600',       // Red for unplanned stops (urgent)
    'stopped': 'bg-red-500',              // Red for stopped (attention needed)
    'idling': 'bg-orange-400',            // Orange for  idling (caution/inefficiency)
    'idle': 'bg-orange-400',              // Orange for idle (caution/inefficiency)
    'maintenance': 'bg-purple-400'        // Purple for maintenance
  };
  
  events.forEach((event, index) => {
    const eventStart = new Date(event.startTime).getTime();
    const eventEnd = new Date(event.endTime).getTime();
    
    // Calculate position and width as percentage
    const leftPercent = ((eventStart - journeyStart) / journeyDuration) * 100;
    const widthPercent = Math.max(((eventEnd - eventStart) / journeyDuration) * 100, 0.5); // Minimum 0.5% width for visibility
    
    
    const colorClass = eventColors[event.type] || 'bg-gray-400';
    const eventBlock = document.createElement('div');
    eventBlock.className = `absolute ${colorClass} opacity-85 hover:opacity-100 transition-all duration-150 cursor-pointer z-10`;
    eventBlock.style.left = `${leftPercent}%`;
    eventBlock.style.width = `${widthPercent}%`;
    eventBlock.style.height = '100%';
    eventBlock.style.borderRadius = '4px';
    eventBlock.title = `${event.label}\n${formatTime(new Date(event.startTime))} - ${formatTime(new Date(event.endTime))}`;
    // Add subtle border for all events
    if (event.type === 'moving') {
      eventBlock.style.border = '1px solid rgba(255, 255, 255, 0.3)';
    } else {
      eventBlock.style.border = '1px solid rgba(0, 0, 0, 0.1)';
    }
    eventsContainer.appendChild(eventBlock);
  });
  
}

// Export for future use
window.addEventBlocksToTimeline = addEventBlocksToTimeline;
window.detectEventsFromData = detectEventsFromData;

// ===================================================
// PLAYBACK PATH VISUALIZATION WITH COLOR-CODED SEGMENTS
// ===================================================

function drawPlaybackPath() {
  if (!playbackData.length) return;

  // Clear existing layers
  if (playbackPolyline) {
    try { playbackMap.removeLayer(playbackPolyline); } catch (_) {}
    playbackPolyline = null;
  }
  playbackPolylineSegments.forEach(seg => {
    if (seg.polyline) { try { playbackMap.removeLayer(seg.polyline); } catch (_) {} }
    if (seg.dot)      { try { playbackMap.removeLayer(seg.dot); }     catch (_) {} }
  });
  playbackPolylineSegments = [];
  clearDeviationMarkers();
  if (playbackMarker) {
    try { playbackMap.removeLayer(playbackMarker); } catch (_) {}
  }

  // Collect all valid latlngs
  const latlngs = playbackData
    .map(p => [parseFloat(p.latitude), parseFloat(p.longitude)])
    .filter(c => !isNaN(c[0]) && !isNaN(c[1]));

  if (latlngs.length === 0) return;

  // 1 — Shadow glow underlay
  const glowLine = L.polyline(latlngs, {
    color: 'rgba(34,197,94,0.10)', weight: 14, lineCap: 'round', lineJoin: 'round', interactive: false
  }).addTo(playbackMap);
  playbackPolylineSegments.push({ polyline: glowLine });

  // 2 — Main route path
  playbackPolyline = L.polyline(latlngs, {
    color: '#22c55e', weight: 3, lineCap: 'round', lineJoin: 'round', opacity: 0.92
  }).addTo(playbackMap);

  // No path dots — heatmap (toggleStoppageHeatmap) handles stoppage visualization

  // Fit bounds
  playbackMap.fitBounds(playbackPolyline.getBounds(), { padding: [20, 20] });

  // Vehicle marker at start
  const sp = playbackData[0];
  if (sp && sp.latitude && sp.longitude) {
    const heading = parseFloat(sp.heading) || 0;
    playbackMarker = L.marker(
      [parseFloat(sp.latitude), parseFloat(sp.longitude)],
      { icon: getVehicleIcon('moving', heading) }
    ).addTo(playbackMap);
    playbackMarker.heading = heading;
    maybeReportDeviation(sp);
  }

  // Sync slider
  const progressSlider = document.getElementById('progressSlider');
  if (progressSlider) {
    progressSlider.max   = 10000;
    progressSlider.value = 0;
  }

  updateProgressDisplay();
}

// ===================================================
// PLAYBACK CONTROLS WITH EVENT-BASED MOVEMENT
// ===================================================
/**
 * Start playback with smooth interpolated animation matching actual GPS timestamps.
 * Playback speed is based on real time differences between GPS points.
 * Speed multiplier: 1x = real-time, 2x = twice as fast, etc.
 * Marker position is smoothly interpolated between GPS points.
 */
function playPlayback() {
  if (animationFrameId) return; // Already playing

  const playBtn = document.getElementById('playBtn');
  const pauseBtn = document.getElementById('pauseBtn');
  
  playBtn.style.display  = 'none';
  pauseBtn.style.display = 'flex';

  let lastUpdateTime = performance.now();
  let accumulatedTime = 0;
  
  function animate(currentTime) {
    const deltaTime = currentTime - lastUpdateTime;
    lastUpdateTime = currentTime;
    accumulatedTime += deltaTime;
    
    // Check if we can advance or interpolate
    if (currentIndex < playbackData.length - 1) {
      const currentPoint = playbackData[currentIndex];
      const nextPoint = playbackData[currentIndex + 1];
      
      // Calculate actual time difference between GPS points (in milliseconds)
      const currentGpsTime = new Date(currentPoint.gps_time).getTime();
      const nextGpsTime = new Date(nextPoint.gps_time).getTime();
      const realTimeDiff = nextGpsTime - currentGpsTime;
      
      // Apply speed multiplier (higher speed = shorter wait time)
      const scaledTimeDiff = realTimeDiff / playbackSpeed;
      
      // Calculate interpolation progress (0 to 1)
      const progress = Math.min(accumulatedTime / scaledTimeDiff, 1);
      
      // Smooth interpolation between current and next point
      if (playbackMarker && currentPoint.latitude && nextPoint.latitude) {
        const currentLat = parseFloat(currentPoint.latitude);
        const currentLng = parseFloat(currentPoint.longitude);
        const nextLat = parseFloat(nextPoint.latitude);
        const nextLng = parseFloat(nextPoint.longitude);
        
        // Linear interpolation (lerp) for smooth movement
        const interpLat = currentLat + (nextLat - currentLat) * progress;
        const interpLng = currentLng + (nextLng - currentLng) * progress;
        
        playbackMarker.setLatLng([interpLat, interpLng]);
        
        // Update popup with interpolated data
        const displayNumber = getDisplayVehicleNumber(currentPoint.registration_number || 'Vehicle');
        const interpSpeed = currentPoint.speed + (nextPoint.speed - currentPoint.speed) * progress;
        
        const popupContent = buildPlaybackPopupHTML(
          displayNumber,
          new Date(currentPoint.gps_time).toLocaleString(),
          interpSpeed.toFixed(1) || 0,
          currentPoint.soc || 0,
          ''
        );
        if (playbackMarker.getPopup()) {
          playbackMarker.getPopup().setContent(popupContent);
        }
      }
      
      // Update progress indicator smoothly (time-normalized)
      if (playbackData.length > 1) {
        const progressSlider = document.getElementById('progressSlider');
        const progressIndicator = document.getElementById('progressIndicator');
        const startMs  = new Date(playbackData[0].gps_time).getTime();
        const endMs    = new Date(playbackData[playbackData.length - 1].gps_time).getTime();
        const currMs   = new Date(currentPoint.gps_time).getTime();
        const nextMs   = new Date(nextPoint.gps_time).getTime();
        const interpMs = currMs + (nextMs - currMs) * progress;
        const t = (endMs > startMs) ? (interpMs - startMs) / (endMs - startMs) : 0;
        // Slider is time-based (0–10000)
        if (progressSlider) progressSlider.value = Math.round(t * 10000);
        if (progressIndicator) {
          progressIndicator.style.transition = 'none';
          progressIndicator.style.left = `${Math.max(0, Math.min(100, t * 100))}%`;
        }
      }
      
      // If enough time has passed, move to next point
      if (accumulatedTime >= scaledTimeDiff) {
        accumulatedTime = 0;
        currentIndex++;
        updateMarkerPosition(); // Full update with address lookup
        updateProgressDisplay();
      }
    } else {
      // Reached the end
      pausePlayback();
      return;
    }
    
    // Only continue animation if still playing
    if (animationFrameId !== null) {
      animationFrameId = requestAnimationFrame(animate);
    }
  }
  
  animationFrameId = requestAnimationFrame(animate);
}


function pausePlayback() {
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
  }

  // Toggle button visibility
  const playBtn = document.getElementById('playBtn');
  const pauseBtn = document.getElementById('pauseBtn');
  
  pauseBtn.style.display = 'none';
  playBtn.style.display  = 'flex';
}

function stopPlayback() {
  pausePlayback();
  currentIndex = 0;
  updateMarkerPosition();
  updateProgressDisplay();
}

function resetPlayback() {
  stopPlayback();
  drawPlaybackPath();
}

function seekToPosition(value) {
  // value is 0–10000 (time-fraction × 10000)
  const t = parseInt(value) / 10000;
  const startMs = new Date(playbackData[0].gps_time).getTime();
  const endMs   = new Date(playbackData[playbackData.length - 1].gps_time).getTime();
  const targetMs = startMs + t * (endMs - startMs);
  let nearest = 0, minDiff = Infinity;
  for (let i = 0; i < playbackData.length; i++) {
    const diff = Math.abs(new Date(playbackData[i].gps_time).getTime() - targetMs);
    if (diff < minDiff) { minDiff = diff; nearest = i; }
  }
  currentIndex = nearest;
  updateMarkerPosition();
  updateProgressDisplay();
}

// Expose globally for timeline slider
window.seekToPosition = seekToPosition;

function setupSliderInteraction() {
  const slider = document.getElementById('progressSlider');
  if (!slider) return;
  
  slider.addEventListener('input', (e) => {
    seekToPosition(e.target.value);
  });
}

// ===================================================
// MARKER UPDATES & ANALYTICS INTEGRATION
// ===================================================
function updateMarkerPosition() {
  if (!playbackMarker || !playbackData[currentIndex]) return;

  const point = playbackData[currentIndex];
  const lat = parseFloat(point.latitude);
  const lng = parseFloat(point.longitude);
  const heading = parseFloat(point.heading) || 0;

  if (isNaN(lat) || isNaN(lng)) return;

  playbackMarker.setLatLng([lat, lng]);
  
  // Update icon with new heading
  playbackMarker.setIcon(getVehicleIcon('moving', heading));
  playbackMarker.heading = heading;
  
  const displayNumber = getDisplayVehicleNumber(point.registration_number || 'Vehicle');

  const popupOpts = { className: 'tv-popup', maxWidth: 240, autoPan: false };
  playbackMarker.bindPopup(
    buildPlaybackPopupHTML(displayNumber, new Date(point.gps_time).toLocaleString(), point.speed || 0, point.soc || 0, 'Loading…'),
    popupOpts
  ).openPopup();

  getAddressFromCoords(lat, lng).then(address => {
    const updated = buildPlaybackPopupHTML(
      displayNumber, new Date(point.gps_time).toLocaleString(), point.speed || 0, point.soc || 0, address
    );
    playbackMarker.bindPopup(updated, popupOpts);
    if (playbackMarker.isPopupOpen()) playbackMarker.getPopup().setContent(updated);
  });

  updatePlaybackAnalytics(point, currentIndex);
  // Broadcast to telemetry charts
  document.dispatchEvent(new CustomEvent('va:frame', {
    detail: {
      timeMs:  new Date(point.gps_time).getTime(),
      index:   currentIndex,
      total:   playbackData.length,
      point,
    }
  }));
  // Check and report deviation if any
  maybeReportDeviation(point);
}

// ===================================================
// REAL-TIME ANALYTICS UPDATE DURING PLAYBACK
// ===================================================
function updatePlaybackAnalytics(currentPoint, currentIdx) {
  if (currentPoint) {
    const spd   = parseFloat(currentPoint.speed) || 0;
    const state = currentPoint.vehicle_status || (spd > 1 ? 'Moving' : 'Stopped');
    // Use colored pill if available
    if (window._updateStatusPill) {
      window._updateStatusPill(state);
    } else {
      updateElement('vehicleStatus', state);
    }
    const soc = parseFloat(currentPoint.soc);
    updateElement('vehicleBattery', (!isNaN(soc) && soc > 0) ? `${soc.toFixed(0)}%` : null);
    updateElement('lastUpdate', formatDateTime(currentPoint.gps_time));
  }

  const dataFromStartToCurrent = playbackData.slice(0, currentIdx + 1);
  if (dataFromStartToCurrent.length > 1) {
    const m = calculateTripMetrics(dataFromStartToCurrent);
    updateElement('totalDistance', m.totalDistance > 0 ? `${m.totalDistance.toFixed(1)} km`  : null);
    updateElement('tripDuration',  m.duration > 0      ? formatDurationToHours(m.duration)    : null);
    updateElement('avgSpeed',      m.avgSpeed  > 0     ? `${m.avgSpeed.toFixed(1)} km/h`      : null);
  }
}

// ===================================================
// ANALYTICS CALCULATION FUNCTIONS (FOR PLAYBACK)
// ===================================================
function calculateTripMetrics(data) {
  if (!data || data.length === 0) {
    return { totalDistance: 0, duration: 0, avgSpeed: 0, maxSpeed: 0, stopsCount: 0 };
  }
  
  let totalDistance = 0;
  let maxSpeed = 0;
  let stopsCount = 0;
  let totalSpeed = 0;
  let speedCount = 0;
  
  // Calculate distance between consecutive points
  for (let i = 1; i < data.length; i++) {
    const prev = data[i-1];
    const curr = data[i];
    
    if (prev.latitude && prev.longitude && curr.latitude && curr.longitude) {
      const distance = calculateDistance(
        prev.latitude, prev.longitude,
        curr.latitude, curr.longitude
      );
      totalDistance += distance;
    }
    
    // Track speeds — only average over moving points (speed > 1 km/h)
    if (curr.speed) {
      maxSpeed = Math.max(maxSpeed, curr.speed);
      if (curr.speed > 1) {
        totalSpeed += curr.speed;
        speedCount++;
      }
      // Count stops (speed < 1 km/h)
      if (curr.speed < 1 && (i === 1 || data[i-1].speed >= 1)) {
        stopsCount++;
      }
    }
  }

  // Calculate duration (difference between first and last timestamp)
  const startTime = new Date(data[0].gps_time);
  const endTime = new Date(data[data.length - 1].gps_time);
  const durationMs = endTime - startTime;
  const duration = Math.max(0, Math.round(durationMs / (1000 * 60))); // minutes, ensure positive

  // Moving average (excludes stopped intervals)
  const avgSpeed = speedCount > 0 ? totalSpeed / speedCount : 0;
  
  return {
    totalDistance,
    duration,
    avgSpeed,
    maxSpeed,
    stopsCount
  };
}

function calculateDistance(lat1, lon1, lat2, lon2) {
  const R = 6371; // Earth's radius in km
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon/2) * Math.sin(dLon/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return R * c;
}

function updateElement(id, value) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = value;
  }
}

function formatDateTime(dateString) {
  if (!dateString) return 'N/A';
  try {
    return new Date(dateString).toLocaleString();
  } catch {
    return 'Invalid Date';
  }
}

/**
 * Format duration from minutes to hours display
 * Matches the format used by analytics API
 * @param {number} minutes - Duration in minutes
 * @returns {string} Formatted string like "2.5 hrs" or "0.8 hrs"
 */
function formatDurationToHours(minutes) {
  if (!minutes || minutes === 0) return '0.0 hrs';
  const hours = minutes / 60;
  return `${hours.toFixed(1)} hrs`;
}

function updateScrubberReadout(index) {
  const readout = document.getElementById('scrubberReadout');
  if (!readout) return;
  const point = playbackData[index];
  if (!point) { readout.textContent = '— · — · —'; return; }
  const time  = point.gps_time ? new Date(point.gps_time).toLocaleTimeString('en-US', { hour12: false }) : '—';
  const spd   = parseFloat(point.speed) || 0;
  const state = point.vehicle_status || (spd > 1 ? 'Moving' : 'Stopped');
  const spdTxt = spd > 0 ? `${spd.toFixed(1)} km/h` : '—';
  readout.textContent = `${time} · ${state} · ${spdTxt}`;
}

function updateProgressDisplay() {
  const progressSlider    = document.getElementById('progressSlider');
  const progressIndicator = document.getElementById('progressIndicator');

  if (playbackData.length > 1) {
    const startMs = new Date(playbackData[0].gps_time).getTime();
    const endMs   = new Date(playbackData[playbackData.length - 1].gps_time).getTime();
    const currMs  = new Date(playbackData[currentIndex].gps_time).getTime();
    const t = (endMs > startMs) ? (currMs - startMs) / (endMs - startMs) : 0;
    // Slider is time-based (0–10000)
    if (progressSlider) progressSlider.value = Math.round(t * 10000);
    if (progressIndicator) {
      progressIndicator.style.transition = 'none';
      progressIndicator.style.left = `${Math.max(0, Math.min(100, t * 100))}%`;
    }
  }

  updateScrubberReadout(currentIndex);
}

// ===================================================
// UTILITY FUNCTIONS
// ===================================================
function showSpinner(show, message = 'Please wait') {
  // Use global loading functions from base.html
  if (show) {
    window.showLoading?.(message);
  } else {
    window.hideLoading?.();
  }
}

// ===================================================
// GLOBAL ACCESS
// ===================================================
window.initializeVehiclePlayback  = initializeVehiclePlayback;
window.seekToPosition             = seekToPosition;
window.toggleStoppageHeatmap      = toggleStoppageHeatmap;
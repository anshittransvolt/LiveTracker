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
    alert('No stoppage points to show on heatmap.');
    return;
  }
  if (stoppageHeatmapLayer) {
    playbackMap.removeLayer(stoppageHeatmapLayer);
    stoppageHeatmapLayer = null;
  }
  // Only use red for heatmap
  const points = pointsMeta.map(p => [p.lat, p.lng, 1]);
  stoppageHeatmapLayer = L.heatLayer(points, {
    radius: 25,
    blur: 18,
    maxZoom: 17,
    minOpacity: 0.4,
    gradient: {0.4: 'red', 0.7: 'red', 1: 'red'}
  });
  stoppageHeatmapLayer.addTo(playbackMap);
  // Add markers for each stoppage with duration popup
  pointsMeta.forEach(meta => {
    const marker = L.circleMarker([meta.lat, meta.lng], {
      radius: 8,
      color: '#b91c1c',
      fillColor: '#ef4444',
      fillOpacity: 0.85,
      weight: 2
    }).addTo(playbackMap);
    let popupContent = `<b>Stoppage</b><br/>`;
    if (meta.duration !== null) {
      popupContent += `Duration: <b>${meta.duration} min</b><br/>`;
    }
    if (meta.point && meta.point.gps_time) {
      popupContent += `Start: ${meta.point.gps_time}`;
    }
    marker.bindPopup(popupContent);
    marker.on('mouseover', function() { marker.openPopup(); });
    marker.on('mouseout', function() { marker.closePopup(); });
    // Store marker for later removal if needed
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
  // Add a button to the map (below trip summary on the left)
  if (!playbackMap) return;
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

/**
 * Create arrow icon for vehicle marker (matching map.js style)
 * @param {number} heading - Vehicle heading in degrees (0 = North)
 * @returns {L.DivIcon} Leaflet div icon with arrow
 */
function createBusIcon(heading = 0) {
  const size = 45; // Fixed size for playback
  const color = '#3b82f6'; // Blue color for playback

  return L.divIcon({
    className: "custom-bus-icon",
    html: `
      <div style="
        width: ${size}px;
        height: ${size}px;
        display: flex;
        align-items: center;
        justify-content: center;
        transform: rotate(${heading}deg);
        transition: transform 0.3s ease;
        opacity: 0.85;
        z-index: 400;
        position: relative;
      ">
        <svg width="${size}" height="${size}" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <!-- Classic Arrow with Tail -->
          <path 
            d="M12 2 
               L20 10 
               H15 
               V22 
               H9 
               V10 
               H4 
               Z"
            fill="${color}"
            stroke="black"
            stroke-width="1.6"
            stroke-linejoin="round"
          />
        </svg>
      </div>
    `,
    iconSize: [size, size],
    iconAnchor: [size / 2, size * 0.75],
    popupAnchor: [0, -size * 0.75],
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
    // console.log(`🎬 Initializing playback for ${registrationNumber}${historicalDate ? ` on ${historicalDate}` : ''}...`);
    // console.log('📅 Historical Date Parameter:', historicalDate);
    // console.log('📅 Type of historicalDate:', typeof historicalDate);
    // console.log('📅 historicalDate is null?', historicalDate === null);
    // console.log('📅 historicalDate is empty string?', historicalDate === '');
    // console.log('🔍 Checking if detectEventsFromData exists:', typeof detectEventsFromData);
    // console.log('🔍 Checking if addEventBlocksToTimeline exists:', typeof addEventBlocksToTimeline);
    
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

    // Fetch playback data (with optional historical date)
    console.log('🌐 About to call fetchVehicleOneDay with:', registrationNumber, historicalDate);
    const data = await fetchVehicleOneDay(registrationNumber, historicalDate);
    console.log('📊 Fetched data:', data ? data.length : 0, 'points');
    console.log('📊 First data point:', data && data.length > 0 ? data[0] : 'No data');

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

    // Reverse the data to show journey from START to END (oldest to newest)
    playbackData = data.reverse();
    currentVehicleNumber = registrationNumber;
    // console.log('🔄 Reversed playback data, first point:', playbackData[0]);
    
    // Detect events from playback data
    // console.log('🔍 Detecting events from playback data...');
    // console.log('🔍 playbackData before detection:', playbackData.length, 'points');
    
    try {
      detectedEvents = detectEventsFromData(playbackData);
      // console.log(`✅ Detected ${detectedEvents.length} events:`, detectedEvents);
    } catch (eventError) {
      console.error('❌ Error detecting events:', eventError);
      detectedEvents = [];
    }
    
    // Create floating header with vehicle info
    createVehicleInfoHeader(registrationNumber, playbackData[0]);
    
    // console.log('🎮 Setting up playback controls...');
    setupPlaybackControls();
    
    // Add event visualization to timeline after DOM is ready
    setTimeout(() => {
      // console.log('⏰ Timeout fired - adding events to timeline');
      if (detectedEvents && detectedEvents.length > 0) {
        // console.log('🎨 Adding event blocks to timeline...');
        try {
          addEventBlocksToTimeline(detectedEvents);
        } catch (timelineError) {
          console.error('❌ Error adding events to timeline:', timelineError);
        }
      } else {
        console.warn('⚠️ No events to add to timeline');
      }
    }, 100);
    
    // console.log('🗺️ Drawing playback path...');
    drawPlaybackPath();
    showSpinner(false);
    
    // Add heatmap after map is ready and show heatmap if enabled by default
    // Use longer timeout to ensure events and path are fully rendered
    setTimeout(() => {
      addHeatmapToggleButton();
      if (heatmapVisible) {
        // console.log('🗺️ Auto-showing heatmap on load...');
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
  
  // Show loading state initially
  header.innerHTML = `
    <div class="flex items-center gap-3">
      <div class="flex items-center gap-2">
        
        <div>
          <div class="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Vehicle</div>
          <div class="text-sm font-bold text-slate-900">${displayNumber}</div>
        </div>
      </div>
      
      <div class="h-8 w-px bg-slate-300"></div>
      
      <div class="flex items-center gap-2">
        
        <div>
          <div class="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Driver</div>
          <div class="text-sm font-bold text-slate-900">Loading...</div>
        </div>
      </div>
    </div>
  `;
  
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
  
  // Fetch driver info from service
  try {
    const response = await fetch(`/roster/api/driver/${encodeURIComponent(registrationNumber)}/`);
    const driverData = await response.json();
    
    const driverName = driverData.driver_name || 'Not Assigned';
    const driverPhone = driverData.driver_phone || '';
    
    // Update header with actual driver info
    header.innerHTML = `
      <div class="flex items-center gap-2.5 text-base">
        <div class="flex items-center gap-2">
          <i data-lucide="truck" class="w-4.5 h-4.5 text-blue-600"></i>
          <span class="font-bold text-slate-900">${displayNumber}</span>
        </div>
        <span class="text-slate-400">•</span>
        <div class="flex items-center gap-2">
          <i data-lucide="user" class="w-4.5 h-4.5 text-green-600"></i>
          <span class="font-semibold text-slate-900">${driverName}</span>
        </div>
        ${driverPhone && driverPhone !== 'N/A' ? `
        <span class="text-slate-400">•</span>
        <div class="flex items-center gap-2">
          <i data-lucide="phone" class="w-4.5 h-4.5 text-slate-600"></i>
          <span class="font-medium text-slate-700">${driverPhone}</span>
        </div>
        ` : ''}
      </div>
    `;
  } catch (error) {
    console.error('Failed to fetch driver info:', error);
    // Show error state
    header.innerHTML = `
      <div class="flex items-center gap-2.5 text-base">
        <div class="flex items-center gap-2">
          <i data-lucide="truck" class="w-4.5 h-4.5 text-blue-600"></i>
          <span class="font-bold text-slate-900">${displayNumber}</span>
        </div>
        <span class="text-slate-400">•</span>
        <div class="flex items-center gap-2">
          <i data-lucide="user-x" class="w-4.5 h-4.5 text-slate-400"></i>
          <span class="font-medium text-slate-500">Not Available</span>
        </div>
      </div>
    `;
  }
  
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
    // console.log('📍 Map already initialized, reusing existing map');
    return;
  }
  
  // Check if the element already has a Leaflet map
  if (mapEl._leaflet_id) {
    // console.log('📍 Map container already has Leaflet instance, clearing it');
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

  // Add tile layer
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors'
  }).addTo(playbackMap);

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
  // Add corridor toggle button
  addCorridorToggleButton();
  // Auto-show corridor overlay on init
  try { toggleCorridorOverlay(); } catch (_) {}
}

// ===================================================
// PLAYBACK CONTROLS SETUP
// ===================================================
function setupPlaybackControls() {
  const controlsContainer = document.getElementById('playbackControls');
  if (!controlsContainer) {
    console.error('❌ Playback controls container not found!');
    return;
  }

  // console.log('🎮 Setting up playback controls...');

  // Calculate journey start and end times
  const startTime = new Date(playbackData[0].gps_time);
  const endTime = new Date(playbackData[playbackData.length - 1].gps_time);
  const journeyDurationMs = endTime - startTime;

  controlsContainer.innerHTML = `
    <div class="flex flex-col gap-2 w-full">
      <!-- Top Row: Playback Controls, Speed, Timeline -->
      <div class="flex items-start w-full gap-2">
        <!-- Left: Playback Control Buttons + Speed -->
        <div class="flex items-center gap-2 flex-shrink-0">
          <div class="flex items-center gap-0.5">
            <button id="resetBtn" 
                    class="w-8 h-8 flex items-center justify-center rounded-full hover:bg-slate-100 text-slate-700 transition-all group"
                    title="Reset to start">
              <i data-lucide="skip-back" class="w-4 h-4 group-hover:scale-110 transition-transform"></i>
            </button>
            <button id="playBtn" 
                    class="w-8 h-8 flex items-center justify-center rounded-full bg-blue-600 hover:bg-blue-700 text-white transition-all shadow-md hover:shadow-lg group"
                    title="Play">
              <i data-lucide="play" class="w-5 h-5 ml-0.5 group-hover:scale-110 transition-transform"></i>
            </button>
            <button id="pauseBtn" 
                    class="w-8 h-8 hidden items-center justify-center rounded-full bg-blue-600 hover:bg-blue-700 text-white transition-all shadow-md hover:shadow-lg group"
                    title="Pause">
              <i data-lucide="pause" class="w-5 h-5 group-hover:scale-110 transition-transform"></i>
            </button>
            <button id="stopBtn" 
                    class="w-8 h-8 flex items-center justify-center rounded-full hover:bg-slate-100 text-slate-700 transition-all group"
                    title="Stop">
              <i data-lucide="square" class="w-3.5 h-3.5 group-hover:scale-110 transition-transform"></i>
            </button>
          </div>
          <!-- Speed Control -->
          <div class="flex items-center gap-1.5 pl-1.5 border-l border-slate-300">
            <select id="speedSelect" 
                    class="px-2 py-1 border border-slate-300 rounded-lg text-xs font-medium bg-white hover:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all cursor-pointer">
              <option value="0.5">0.5×</option>
              <option value="1" selected>1×</option>
              <option value="2">2×</option>
              <option value="5">5×</option>
              <option value="10">10×</option>
              <option value="50">50×</option>
            </select>
          </div>
        </div>

        <!-- Center: Timeline -->
        <div class="flex-1 flex flex-col gap-1.5">
          <!-- Timeline Bar with Events Container -->
          <div class="relative w-full">
            <!-- Slider Input (Invisible but Interactive) -->
            <input type="range" id="progressSlider" min="0" max="${playbackData.length - 1}" value="0" 
                   class="absolute inset-0 w-full h-full opacity-0 z-20"
                   style="cursor: pointer !important;">
            <!-- Visual Timeline Track - Sleek Modern Design -->
            <div class="relative h-6 bg-gradient-to-b from-slate-50 via-slate-100 to-slate-150 rounded-lg border border-slate-200 shadow-inner overflow-visible"
                 style="box-shadow: inset 0 2px 4px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.05);">
              <!-- Events Container (will be populated dynamically with color-coded events) -->
              <div id="eventsContainer" class="absolute inset-0 flex items-center rounded-lg overflow-hidden">
                <!-- Event blocks will be added here dynamically -->
              </div>
              <!-- Tick Marks -->
              <div class="absolute inset-0 flex items-center justify-between px-1 pointer-events-none">
                ${generateTickMarks(journeyDurationMs)}
              </div>
              <!-- Current Position Indicator (Vertical Line with Playhead) - Sleek Design -->
              <div id="progressIndicator" 
                   class="absolute w-0.5 bg-gradient-to-b from-blue-600 to-blue-700 pointer-events-none z-30"
                   style="left: 0%; top: 12%; bottom: 12%; box-shadow: 0 0 6px rgba(59, 130, 246, 0.5), 0 0 2px rgba(59, 130, 246, 0.8);">
                <!-- Playhead circle at top - Enhanced with gradient and glow -->
                <div class="absolute -top-1.5 left-1/2 -translate-x-1/2 w-4 h-4 bg-gradient-to-br from-blue-500 to-blue-600 rounded-full border-2 border-white shadow-lg"
                     style="box-shadow: 0 2px 6px rgba(59, 130, 246, 0.4), 0 0 0 2px rgba(59, 130, 246, 0.1);"></div>
              
              </div>
            </div>
          </div>
          <!-- Timestamp Labels - Sleek Typography -->
          <div class="relative h-4 flex items-center justify-between px-1 text-xs text-slate-500 font-medium w-full">
            ${generateTimeLabels(startTime, endTime, journeyDurationMs)}
          </div>
          <!-- Current Time Display below timeline removed as requested -->
        </div>
      </div>
    </div>
  `;

  // Initialize Lucide icons
  if (typeof lucide !== 'undefined') {
    lucide.createIcons();
  }

  // Make sure the container is visible with sleek styling
  controlsContainer.style.display = 'block';
  controlsContainer.style.zIndex = '9999';
  controlsContainer.style.position = 'fixed';
  controlsContainer.style.backdropFilter = 'blur(12px)';
  controlsContainer.style.WebkitBackdropFilter = 'blur(12px)';
  
  // console.log('✅ Playback controls HTML set up and should be visible');
  // console.log('✅ rideSummaryPanel element added to DOM');

  // Bind event listeners
  const playBtn = document.getElementById('playBtn');
  const pauseBtn = document.getElementById('pauseBtn');
  const stopBtn = document.getElementById('stopBtn');
  const resetBtn = document.getElementById('resetBtn');
  const speedSelect = document.getElementById('speedSelect');
  
  if (playBtn) playBtn.onclick = playPlayback;
  if (pauseBtn) pauseBtn.onclick = pausePlayback;
  if (stopBtn) stopBtn.onclick = stopPlayback;
  if (resetBtn) resetBtn.onclick = resetPlayback;
  if (speedSelect) {
    speedSelect.onchange = (e) => {
      playbackSpeed = parseFloat(e.target.value);
      // console.log('🏃 Playback speed changed to:', playbackSpeed + 'x');
    };
  }
  
  // Setup slider interaction handlers
  setTimeout(setupSliderInteraction, 100);
  
  // console.log('✅ Event listeners bound to playback controls');
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
  // console.log('📊 populateRideSummary called with:', summary);
  
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
    // console.log('✅ Updated totalRideTime:', summary.totalRideTime);
  }
  
  if (elements.totalStopTime) {
    elements.totalStopTime.textContent = summary.totalStopTime || '--:--:--';
    // console.log('✅ Updated totalStopTime:', summary.totalStopTime);
  }
  
  if (elements.totalMovingTime) {
    elements.totalMovingTime.textContent = summary.totalMovingTime || '--:--:--';
    // console.log('✅ Updated totalMovingTime:', summary.totalMovingTime);
  }
  
  if (elements.totalChargingTime) {
    elements.totalChargingTime.textContent = summary.totalChargingTime || '--:--:--';
    // console.log('✅ Updated totalChargingTime:', summary.totalChargingTime);
  }

  // Make the panel visible
  if (elements.panel) {
    elements.panel.classList.remove('hidden');
    // console.log('✅ rideSummaryPanel is now visible');
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
 * Generate tick marks based on journey duration.
 * Adapts interval based on total duration (1hr or 2hr gaps).
 */
function generateTickMarks(journeyDurationMs) {
  const durationHours = journeyDurationMs / (1000 * 60 * 60);
  
  // Fixed 2-hour intervals for all journeys
  const intervalHours = 2;
  
  const tickCount = Math.ceil(durationHours / intervalHours);
  let ticks = '';
  
  for (let i = 0; i <= tickCount; i++) {
    const position = (i / tickCount) * 100;
    ticks += `<div class="absolute bg-slate-400 opacity-40" style="left: ${position}%; width: 1px; height: 55%; top: 22.5%; transform: translateX(-0.5px); box-shadow: 0 0 1px rgba(0,0,0,0.1);"></div>`;
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
  
  // Generate HTML for labels
  return labels.map(label => `
    <div class="absolute" style="left: ${label.position}%; transform: translateX(-50%);">
      <span class="whitespace-nowrap text-[10.5px] font-semibold text-slate-600 tracking-tight">${formatTime(label.time)}</span>
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
  
  // console.log(`✅ Detected ${processedEvents.length} events from ${data.length} data points`);
  return processedEvents;
}

/**
 * Add event blocks to the timeline
 * @param {Array} events - Array of event objects with {startTime, endTime, type, label}
 */
function addEventBlocksToTimeline(events) {
  const eventsContainer = document.getElementById('eventsContainer');
  
  // console.log('🎨 addEventBlocksToTimeline called with', events.length, 'events');
  // console.log('📦 eventsContainer:', eventsContainer);
  // console.log('📊 playbackData length:', playbackData.length);
  
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
    
    // console.log(`🎨 Event ${index + 1}/${events.length}: ${event.type} at ${leftPercent.toFixed(2)}% width ${widthPercent.toFixed(2)}%`);
    
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
  
  // console.log(`✅ Added ${events.length} event blocks to timeline`);
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
    playbackMap.removeLayer(playbackPolyline);
    playbackPolyline = null;
  }
  
  // Clear existing segments
  playbackPolylineSegments.forEach(segment => {
    if (segment.polyline) {
      playbackMap.removeLayer(segment.polyline);
    }
  });
  playbackPolylineSegments = [];
  // Clear deviation markers on redraw
  clearDeviationMarkers();
  
  if (playbackMarker) {
    playbackMap.removeLayer(playbackMarker);
  }

  // Industry-standard polyline colors (matching timeline and conventions)
  const eventPolylineColors = {
    'charging': INDUSTRY_COLORS.CHARGING,      // Blue for charging
    'moving': INDUSTRY_COLORS.MOVING,          // Green for normal movement
    'unplanned_stop': INDUSTRY_COLORS.STOPPED, // Red for unplanned stops
    'stopped': INDUSTRY_COLORS.STOPPED,        // Red for brief stops
    'idling': INDUSTRY_COLORS.IDLING,          // Orange for idling
    'idle': INDUSTRY_COLORS.IDLING,            // Orange for idle/slow
    'maintenance': '#a855f7'                   // Purple for maintenance
  };

  // Draw color-coded segments if events detected
  if (detectedEvents && detectedEvents.length > 0) {
    // console.log('🎨 Drawing color-coded route segments...');
    
    detectedEvents.forEach(event => {
      if (!event.points || event.points.length === 0) return;
      
      const latlngs = event.points.map(point => [
        parseFloat(point.latitude),
        parseFloat(point.longitude)
      ]).filter(coords => !isNaN(coords[0]) && !isNaN(coords[1]));
      
      if (latlngs.length < 2) return; // Need at least 2 points for a line
      
      const color = eventPolylineColors[event.type] || '#6b7280'; // Default gray
      
      const segment = L.polyline(latlngs, {
        color: color,
        weight: 5,
        opacity: 0.8,
        lineJoin: 'round',
        lineCap: 'round'
      }).addTo(playbackMap);
      
      // Add popup with event info
      segment.bindPopup(`
        <div class="font-sans">
          <div class="font-semibold text-sm">${event.label}</div>
          <div class="text-xs text-gray-600 mt-1">
            ${formatTime(new Date(event.startTime))} - ${formatTime(new Date(event.endTime))}
          </div>
          <div class="text-xs text-gray-500 mt-1">
            Duration: ${Math.round(event.duration / 60)} minutes
          </div>
        </div>
      `);
      
      playbackPolylineSegments.push({
        event: event,
        polyline: segment
      });
    });
    
    // console.log(`✅ Drew ${playbackPolylineSegments.length} color-coded route segments`);
    
    // Fit map to all segments
    if (playbackPolylineSegments.length > 0) {
      const group = L.featureGroup(playbackPolylineSegments.map(s => s.polyline));
      playbackMap.fitBounds(group.getBounds(), { padding: [20, 20] });
    }
    
  } else {
    // Fallback: Draw single blue polyline if no events detected
    // console.log('📍 Drawing single-color route (no events detected)');
    
    const latlngs = playbackData.map(point => [
      parseFloat(point.latitude),
      parseFloat(point.longitude)
    ]).filter(coords => !isNaN(coords[0]) && !isNaN(coords[1]));

    if (latlngs.length === 0) return;

    // Draw the full path
    playbackPolyline = L.polyline(latlngs, {
      color: '#3b82f6',
      weight: 4,
      opacity: 0.7
    }).addTo(playbackMap);

    // Fit map to path bounds
    playbackMap.fitBounds(playbackPolyline.getBounds(), { padding: [20, 20] });
  }

  // Create vehicle marker at starting position
  const startPoint = playbackData[0];
  if (startPoint && startPoint.latitude && startPoint.longitude) {
    const startPos = [parseFloat(startPoint.latitude), parseFloat(startPoint.longitude)];
    const heading = parseFloat(startPoint.heading) || 0;
    playbackMarker = L.marker(startPos, { icon: createBusIcon(heading) }).addTo(playbackMap);
    playbackMarker.heading = heading; // Store heading for updates
    // Evaluate deviation at start point
    maybeReportDeviation(startPoint);
  }

  // Update progress slider
  const progressSlider = document.getElementById('progressSlider');
  if (progressSlider) {
    progressSlider.max = playbackData.length - 1;
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
  
  playBtn.classList.add('hidden');
  pauseBtn.classList.remove('hidden');
  pauseBtn.classList.add('flex');

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
        
        const popupContent = `
          <strong>${displayNumber}</strong><br/>
          <strong>Time:</strong> ${new Date(currentPoint.gps_time).toLocaleString()}<br/>
          <strong>Speed:</strong> ${interpSpeed.toFixed(1) || 0} km/h<br/>
          <strong>Battery:</strong> ${currentPoint.soc || 'N/A'}%
        `;
        
        if (playbackMarker.getPopup()) {
          playbackMarker.getPopup().setContent(popupContent);
        }
      }
      
      // Update progress indicator smoothly
      if (playbackData.length > 0) {
        const progressSlider = document.getElementById('progressSlider');
        const progressIndicator = document.getElementById('progressIndicator');
        
        const smoothIndex = currentIndex + progress;
        const percentage = (smoothIndex / (playbackData.length - 1)) * 100;
        
        if (progressSlider) {
          progressSlider.value = smoothIndex;
        }
        
        if (progressIndicator) {
          progressIndicator.style.transition = 'none';
          progressIndicator.style.left = `${percentage}%`;
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
  
  pauseBtn.classList.add('hidden');
  pauseBtn.classList.remove('flex');
  playBtn.classList.remove('hidden');
  playBtn.classList.add('flex');
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
  currentIndex = parseInt(value);
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
  playbackMarker.setIcon(createBusIcon(heading));
  playbackMarker.heading = heading;
  
  const displayNumber = getDisplayVehicleNumber(point.registration_number || 'Vehicle');

  const initialPopup = `
    <strong>${displayNumber}</strong><br/>
    <strong>Time:</strong> ${new Date(point.gps_time).toLocaleString()}<br/>
    <strong>Speed:</strong> ${point.speed || 0} km/h<br/>
    <strong>Battery:</strong> ${point.soc || 'N/A'}%<br/>
    <strong>Location:</strong> Loading address...
  `;
  
  playbackMarker.bindPopup(initialPopup).openPopup();
  
  getAddressFromCoords(lat, lng).then(address => {
    const updatedPopup = `
      <strong>${displayNumber}</strong><br/>
      <strong>Time:</strong> ${new Date(point.gps_time).toLocaleString()}<br/>
      <strong>Speed:</strong> ${point.speed || 0} km/h<br/>
      <strong>Battery:</strong> ${point.soc || 'N/A'}%<br/>
      <strong>Location:</strong> ${address}
    `;
    playbackMarker.bindPopup(updatedPopup);
    if (playbackMarker.isPopupOpen()) {
      playbackMarker.getPopup().setContent(updatedPopup);
    }
  });

  updatePlaybackAnalytics(point, currentIndex);
  // Check and report deviation if any
  maybeReportDeviation(point);
}

// ===================================================
// REAL-TIME ANALYTICS UPDATE DURING PLAYBACK
// ===================================================
function updatePlaybackAnalytics(currentPoint, currentIdx) {
  // Update current status with playback position data
  if (currentPoint) {
    updateElement('vehicleStatus', currentPoint.speed > 1 ? 'Moving' : 'Stopped');
    updateElement('vehicleSpeed', `${currentPoint.speed || 0} km/h`);
    updateElement('vehicleBattery', `${currentPoint.soc || 'N/A'}%`);
    updateElement('lastUpdate', formatDateTime(currentPoint.gps_time));
  }

  // Update trip analytics FROM START (index 0) TO CURRENT POSITION
  // This shows cumulative distance/time as vehicle moves forward
  const dataFromStartToCurrent = playbackData.slice(0, currentIdx + 1);
  
  if (dataFromStartToCurrent.length > 1) {
    const tripMetrics = calculateTripMetrics(dataFromStartToCurrent);
    updateElement('totalDistance', `${tripMetrics.totalDistance.toFixed(1)} km`);
    updateElement('tripDuration', formatDurationToHours(tripMetrics.duration));
    updateElement('avgSpeed', `${tripMetrics.avgSpeed.toFixed(1)} km/h`);
    updateElement('maxSpeed', `${tripMetrics.maxSpeed} km/h`);
    updateElement('stopsCount', tripMetrics.stopsCount);
  } else {
    // At the very start (index 0), show 0 distance
    updateElement('totalDistance', '0.0 km');
    updateElement('tripDuration', '0.0 hrs');
    updateElement('avgSpeed', '0.0 km/h');
    updateElement('maxSpeed', '0 km/h');
    updateElement('stopsCount', 0);
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
    
    // Track speeds
    if (curr.speed) {
      maxSpeed = Math.max(maxSpeed, curr.speed);
      totalSpeed += curr.speed;
      speedCount++;
      
      // Count stops (speed < 1 km/h)
      if (curr.speed < 1 && (i === 1 || data[i-1].speed >= 1)) {
        stopsCount++;
      }
    }
  }
  
  // Calculate duration (difference between first and last timestamp)
  // After reversal: data[0] is START (oldest), data[last] is END (newest)
  const startTime = new Date(data[0].gps_time);
  const endTime = new Date(data[data.length - 1].gps_time);
  const durationMs = endTime - startTime;
  const duration = Math.max(0, Math.round(durationMs / (1000 * 60))); // minutes, ensure positive
  
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

function updateProgressDisplay() {
  const progressSlider = document.getElementById('progressSlider');
  const progressIndicator = document.getElementById('progressIndicator');

  if (progressSlider) {
    progressSlider.value = currentIndex;
  }

  if (progressIndicator && playbackData.length > 0) {
    const percentage = (currentIndex / (playbackData.length - 1)) * 100;
    progressIndicator.style.transition = 'none';
    progressIndicator.style.left = `${percentage}%`;
  }
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
window.initializeVehiclePlayback = initializeVehiclePlayback;
window.seekToPosition = seekToPosition;
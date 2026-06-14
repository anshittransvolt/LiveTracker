/**
 * Fetch stoppage heatmap points for a single vehicle for a given date (historical playback).
 * Groups consecutive stopped points at the same location and returns only stoppages > 5 min.
 * @param {string} reg_no - Vehicle registration number
 * @param {string} date - Date in YYYY-MM-DD format
 * @returns {Promise<Array>} Array of stoppage points with {latitude, longitude, duration, gps_time, ...}
 */
export async function fetchVehicleDayStoppageHeatmap(reg_no, date) {
  if (!reg_no || !date) return [];
  const url = API.HISTORICAL(date, reg_no);
  try {
    const rows = await fetchWithTimeout(url);
    if (!Array.isArray(rows) || rows.length === 0) return [];
    // Sort by time ascending
    rows.sort((a, b) => {
      const ta = new Date(a.last_connected || a.gps_time || a.timestamp || 0).getTime();
      const tb = new Date(b.last_connected || b.gps_time || b.timestamp || 0).getTime();
      return ta - tb;
    });
    const stoppagePoints = [];
    let i = 0;
    while (i < rows.length) {
      const row = rows[i];
      const coords = parseGPSCoordinates(row);
      if (!coords) { i++; continue; }
      const status = (row.vehicle_status || '').toLowerCase();
      if (!(status === 'stop' || status === 'stopped')) { i++; continue; }
      // Start of stoppage event
      let endIdx = i;
      let lastCoords = coords;
      while (
        endIdx + 1 < rows.length &&
        (rows[endIdx + 1].vehicle_status || '').toLowerCase() === status &&
        parseGPSCoordinates(rows[endIdx + 1]) &&
        Math.abs(parseFloat(rows[endIdx + 1].latitude) - lastCoords.latitude) < 0.001 &&
        Math.abs(parseFloat(rows[endIdx + 1].longitude) - lastCoords.longitude) < 0.001
      ) {
        lastCoords = parseGPSCoordinates(rows[endIdx + 1]);
        endIdx++;
      }
      // Calculate duration in minutes
      const tStart = new Date(row.last_connected || row.gps_time || row.timestamp || 0).getTime();
      const tEnd = new Date(rows[endIdx].last_connected || rows[endIdx].gps_time || rows[endIdx].timestamp || 0).getTime();
      if (!tStart || !tEnd || isNaN(tStart) || isNaN(tEnd)) { i = endIdx + 1; continue; }
      const durationMin = Math.round((tEnd - tStart) / 60000);
      if (durationMin > 5) {
        stoppagePoints.push({
          registration_number: reg_no,
          vehicle_no: reg_no,
          latitude: coords.latitude,
          longitude: coords.longitude,
          gps_time: row.last_connected || row.gps_time || row.timestamp || null,
          duration: durationMin,
          speed: safeParseNumber(row.gps_speed ?? row.speed),
          vehicle_status: row.vehicle_status ?? null,
          raw: row
        });
      }
      i = endIdx + 1;
    }
    return stoppagePoints;
  } catch (err) {
    return [];
  }
}
/**
 * ========================================
 * API HANDLER MODULE
 * ========================================
 * API wrapper for LiveTracker frontend with comprehensive error handling.
 * 
 * RESPONSIBILITIES:
 * - Fetch all vehicles data from TWINS API (via Django proxy)
 * - Fetch single vehicle data for playback
 * - Handle network errors, timeouts, and malformed data
 * - Provide graceful degradation on failures
 * 
 * EXPORTS:
 * - fetchAllVehicles() -> Object keyed by registration_number
 * - fetchVehicleOneDay(reg_no) -> Array of points (newest-first)
 * 
 * ERROR HANDLING:
 * - Network failures: Retry with exponential backoff
 * - Timeouts: Configurable timeout with clear error messages
 * - Malformed data: Validation and safe parsing
 * - Invalid GPS: Skip invalid points, log warnings
 */

// ===================================================
// CONFIGURATION
// ===================================================

/**
 * API endpoints configuration for secure backend proxies:
 * - TWINS API: Current/recent vehicle positions (via Django proxy)
 * - Telemetry API: Historical vehicle data (via Django proxy)
 * All authentication handled server-side - no credentials exposed to client
 */
// ===== SECURITY: All API authentication handled server-side =====
// Django backend proxies handle all external API authentication
// No API keys or credentials exposed to client-side code

// Reads the active project key from the dropdown, or falls back to the URL
// path slug (/<project>/livetracker/...) so vehicle-specific pages also work.
function getSPVFromContext() {
  const switcher = document.getElementById('projectSwitcher');
  if (switcher && switcher.value) return switcher.value;

  const parts = window.location.pathname.split('/').filter(Boolean);
  if (parts.length >= 2 && parts[1] === 'livetracker') {
    const slugMap = {
      ultratech: 'ULTRATECH', umt: 'UMT', mbmt: 'MBMT',
      nagpur: 'NAGPUR', vecv: 'VECV',
      star_cement: 'STAR_CEMENT', 'star-cement': 'STAR_CEMENT',
    };
    return slugMap[parts[0].toLowerCase()] || '';
  }
  return '';
}

/**
 * API endpoints using multiple backends
 */
const API = {
  ALL: (spv) => spv
    ? `/livetracker/api/twins/latest-points/?spv=${encodeURIComponent(spv)}`
    : `/livetracker/api/twins/latest-points/`,
  ONE_DAY: (reg) => {
    const spv = getSPVFromContext();
    const base = `/livetracker/api/twins/24hr-route/?registration_number=${encodeURIComponent(reg)}`;
    return spv ? `${base}&spv=${encodeURIComponent(spv)}` : base;
  },
  HISTORICAL: (date, vehicleNo) => {
    const spv = getSPVFromContext();
    let url = `/livetracker/api/vehicle/${encodeURIComponent(vehicleNo)}/historical/?start_date=${date}&end_date=${date}`;
    if (spv) url += `&spv=${encodeURIComponent(spv)}`;
    return url;
  },
};


const DEFAULT_TIMEOUT = 60000; // 60 seconds (matches backend timeout for large datasets)
const MAX_RETRIES = 3;
const RETRY_DELAY = 1000; // 1 second, will use exponential backoff

// ===================================================
// CUSTOM ERROR CLASSES
// ===================================================

class APIError extends Error {
  constructor(message, type, statusCode = null, url = null) {
    super(message);
    this.name = 'APIError';
    this.type = type; // 'network', 'timeout', 'parsing', 'validation', 'http'
    this.statusCode = statusCode;
    this.url = url;
    this.timestamp = new Date().toISOString();
  }
}

// ===================================================
// FETCH WITH TIMEOUT & RETRY
// ===================================================

/**
 * Fetch with timeout, retry logic, and proper error handling.
 * 
 * @param {string} url - URL to fetch
 * @param {Object} opts - Fetch options
 * @param {number} timeout - Timeout in milliseconds
 * @param {number} retries - Number of retries remaining
 * @returns {Promise<any>} Parsed JSON response
 * @throws {APIError} On failure after all retries
 */
async function fetchWithTimeout(url, opts = {}, timeout = DEFAULT_TIMEOUT, retries = MAX_RETRIES) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);
  
  try {
    // Validate URL
    if (!url || url.includes('undefined') || url.includes('null')) {
      throw new APIError(
        'Invalid API URL - BASE_URL may not be configured',
        'validation',
        null,
        url
      );
    }

    // Django backend proxies handle all authentication - no client-side credentials
    const headers = {
      'Content-Type': 'application/json',
      ...(opts.headers || {})
    };

    // Perform fetch
    const res = await fetch(url, { 
      signal: controller.signal,
      headers: headers,
      ...opts
    });
    
    clearTimeout(timeoutId);

    // Handle HTTP errors
    if (!res.ok) {
      const errorBody = await res.text().catch(() => 'No error details');
      throw new APIError(
        `HTTP ${res.status}: ${res.statusText}`,
        'http',
        res.status,
        url
      );
    }

    // Parse JSON with error handling
    try {
      const data = await res.json();
      return data;
    } catch (parseErr) {
      throw new APIError(
        `Failed to parse JSON response: ${parseErr.message}`,
        'parsing',
        res.status,
        url
      );
    }

  } catch (err) {
    clearTimeout(timeoutId);

    // Handle abort (timeout)
    if (err.name === 'AbortError') {
      const timeoutError = new APIError(
        `Request timeout after ${timeout}ms`,
        'timeout',
        null,
        url
      );
      
      // Retry on timeout
      if (retries > 0) {
        const delay = RETRY_DELAY * (MAX_RETRIES - retries + 1); // Exponential backoff
        // console.warn(`⚠️ Timeout, retrying in ${delay}ms... (${retries} retries left)`);
        await new Promise(resolve => setTimeout(resolve, delay));
        return fetchWithTimeout(url, opts, timeout, retries - 1);
      }
      
      // console.error(`❌ ${timeoutError.message} for ${url}`);
      throw timeoutError;
    }

    // Handle network errors
    if (err.message.includes('fetch') || err.message.includes('network')) {
      const networkError = new APIError(
        `Network error: ${err.message}`,
        'network',
        null,
        url
      );
      
      // Retry on network error
      if (retries > 0) {
        const delay = RETRY_DELAY * (MAX_RETRIES - retries + 1);
        // console.warn(`⚠️ Network error, retrying in ${delay}ms... (${retries} retries left)`);
        await new Promise(resolve => setTimeout(resolve, delay));
        return fetchWithTimeout(url, opts, timeout, retries - 1);
      }
      
      // console.error(`❌ ${networkError.message}`);
      throw networkError;
    }

    // Re-throw APIError instances
    if (err instanceof APIError) {
      // console.error(`❌ API Error [${err.type}]:`, err.message);
      throw err;
    }

    // Wrap unknown errors
    const unknownError = new APIError(
      `Unexpected error: ${err.message}`,
      'unknown',
      null,
      url
    );
    // console.error(`❌ Unknown error for ${url}:`, err);
    throw unknownError;
  }
}

// ===================================================
// DATA VALIDATION HELPERS
// ===================================================

/**
 * Validate and parse GPS coordinates from various formats.
 * 
 * @param {Object} row - Data row with GPS information
 * @returns {Object|null} {latitude, longitude} or null if invalid
 */
function parseGPSCoordinates(row) {
  let latitude = null;
  let longitude = null;

  // Try gps_location string format "lat,lon"
  if (row.gps_location && typeof row.gps_location === 'string') {
    const parts = row.gps_location.split(',').map(s => s.trim());
    if (parts.length >= 2) {
      const lat = parseFloat(parts[0]);
      const lon = parseFloat(parts[1]);
      
      // Validate ranges: latitude [-90, 90], longitude [-180, 180]
      if (!isNaN(lat) && !isNaN(lon) && 
          lat >= -90 && lat <= 90 && 
          lon >= -180 && lon <= 180) {
        latitude = lat;
        longitude = lon;
      }
    }
  }

  // Try separate latitude/longitude fields
  if ((latitude === null || longitude === null) && row.latitude && row.longitude) {
    const lat = parseFloat(row.latitude);
    const lon = parseFloat(row.longitude);
    
    if (!isNaN(lat) && !isNaN(lon) && 
        lat >= -90 && lat <= 90 && 
        lon >= -180 && lon <= 180) {
      latitude = lat;
      longitude = lon;
    }
  }

  // Return null if coordinates are invalid
  if (latitude === null || longitude === null) {
    return null;
  }

  // Additional validation: reject (0, 0) as it's likely invalid data
  if (latitude === 0 && longitude === 0) {
    return null;
  }

  return { latitude, longitude };
}

/**
 * Safely parse numeric value with fallback.
 * 
 * @param {any} value - Value to parse
 * @param {number|null} defaultValue - Default if parsing fails
 * @returns {number|null} Parsed number or default
 */
function safeParseNumber(value, defaultValue = null) {
  if (value === null || value === undefined || value === '') {
    return defaultValue;
  }
  const parsed = parseFloat(value);
  return isNaN(parsed) ? defaultValue : parsed;
}

/**
 * Safely get vehicle identifier from various field names.
 * 
 * @param {Object} row - Data row
 * @returns {string|null} Vehicle identifier or null
 */
function getVehicleIdentifier(row) {
  return row.vehicle_no || 
         row.registration_number || 
         row.vehicle_number || 
         row.vehicleNo || 
         null;
}

// ===================================================
// HEADING CALCULATION
// ===================================================

/**
 * Calculate heading from GPS points using movement vectors.
 * Uses multiple points to get a smooth average direction.
 * 
 * @param {Array} points - Array of GPS points (newest first)
 * @returns {number|null} Heading in degrees (0-360) or null if insufficient data
 *                        0 = North, 90 = East, 180 = South, 270 = West
 */
function calculateVectorHeading(points) {
  if (!points || points.length < 2) return null;
  
  // Use up to 6 points to calculate average heading
  const pointsToUse = points.slice(0, Math.min(6, points.length));
  
  let totalDeltaX = 0;
  let totalDeltaY = 0;
  let validVectors = 0;
  
  // Calculate vectors between consecutive points
  for (let i = 0; i < pointsToUse.length - 1; i++) {
    const p1 = pointsToUse[i];     // newer point
    const p2 = pointsToUse[i + 1]; // older point
    
    const lat1 = parseFloat(p1.latitude);
    const lon1 = parseFloat(p1.longitude);
    const lat2 = parseFloat(p2.latitude);
    const lon2 = parseFloat(p2.longitude);
    
    if (isNaN(lat1) || isNaN(lon1) || isNaN(lat2) || isNaN(lon2)) continue;
    
    // Calculate delta (movement from p2 to p1, i.e., direction of travel)
    const deltaLat = lat1 - lat2;
    const deltaLon = lon1 - lon2;
    
    // Skip if no movement (stationary)
    if (Math.abs(deltaLat) < 0.00001 && Math.abs(deltaLon) < 0.00001) continue;
    
    // Convert to Cartesian coordinates for averaging
    // Adjust for longitude distortion at different latitudes
    const avgLat = (lat1 + lat2) / 2;
    const deltaX = deltaLon * Math.cos(avgLat * Math.PI / 180);
    const deltaY = deltaLat;
    
    totalDeltaX += deltaX;
    totalDeltaY += deltaY;
    validVectors++;
  }
  
  // If no valid movement vectors found
  if (validVectors === 0) return null;
  
  // Calculate average direction
  const avgDeltaX = totalDeltaX / validVectors;
  const avgDeltaY = totalDeltaY / validVectors;
  
  // Calculate heading using atan2 (returns angle in radians from -π to π)
  // atan2(deltaY, deltaX) gives angle from East (0°)
  // We need to convert to compass heading where North = 0°
  let headingRadians = Math.atan2(avgDeltaX, avgDeltaY);
  
  // Convert to degrees
  let headingDegrees = headingRadians * (180 / Math.PI);
  
  // Normalize to 0-360 range (0 = North, 90 = East, 180 = South, 270 = West)
  if (headingDegrees < 0) {
    headingDegrees += 360;
  }
  
  console.log(`📐 Calculated vector heading: ${headingDegrees.toFixed(1)}° from ${validVectors} movement vectors`);
  
  return headingDegrees;
}

// ===================================================
// FETCH ALL VEHICLES
// ===================================================

/**
 * Fetch all vehicles data (last 24h, up to 6 points per vehicle).
 * Groups flat array of rows by vehicle and returns object keyed by registration_number.
 * 
 * @returns {Promise<Object>} Object with vehicle data: { reg_no: { registration_number, points: [] } }
 * @throws {APIError} On API failure (after retries)
 * 
 * GRACEFUL DEGRADATION:
 * - Returns empty object {} on total failure
 * - Skips invalid rows but processes valid ones
 * - Validates GPS coordinates before including points
 */
export async function fetchAllVehicles(spv = '') {
  const url = API.ALL(spv);
  
  try {
    // Django proxy endpoint handles authentication server-side
    // No need to pass TWINS_API_TOKEN - the proxy already has backend credentials
    const response = await fetchWithTimeout(url);

    // Handle nested vehicle object structure from TWINS API
    // Response format: { vendor_filter, total_vehicles, vehicles: { reg: [points] } }
    let rows = [];
    
    if (Array.isArray(response)) {
      // Flat array format (fallback for older API)
      rows = response;
    } else if (response && typeof response === 'object' && response.vehicles) {
      // Nested object format from TWINS API
      // console.log(`📊 API returned ${response.total_vehicles || '?'} total vehicles`);
      
      // Flatten the nested structure: iterate vehicles object, collect all points
      for (const [reg, points] of Object.entries(response.vehicles)) {
        if (Array.isArray(points)) {
          // Add registration_number/vehicle_no to each point for reference
          rows.push(...points.map(p => ({
            ...p,
            registration_number: reg,
            vehicle_no: reg
          })));
        }
      }
      // console.log(`✅ Flattened ${rows.length} total points from nested vehicle structure`);
    } else {
      // console.error('❌ fetchAllVehicles: Unexpected response format:', response);
      throw new APIError(
        'Invalid API response format',
        'validation',
        null,
        url
      );
    }

    if (rows.length === 0) {
      // console.warn('⚠️ fetchAllVehicles: API returned no data');
      return {};
    }

    // API already filters to spv=ultratech, so no additional filtering needed
    const filteredRows = rows;

    if (filteredRows.length === 0) {
      // console.warn(`⚠️ fetchAllVehicles: API returned no vehicles for spv=ultratech`);
      return {};
    }

    // console.log(`✅ fetchAllVehicles: Got ${filteredRows.length} vehicles (spv=ultratech filtered at source)`);

    // Group rows by vehicle_no and transform into the payload shape used by map.js
    const grouped = {};
    let validPoints = 0;
    let invalidPoints = 0;

    for (const row of filteredRows) {
      try {
        // Get vehicle identifier
        const vehicle_no = getVehicleIdentifier(row);
        if (!vehicle_no) {
          invalidPoints++;
          continue;
        }

        // Parse and validate GPS coordinates
        const coords = parseGPSCoordinates(row);
        if (!coords) {
          // console.warn(`⚠️ Invalid GPS for vehicle ${vehicle_no}:`, row.gps_location);
          invalidPoints++;
          continue;
        }

        // Build point object with validated data
        const point = {
          registration_number: vehicle_no,
          vehicle_no: vehicle_no,
          latitude: coords.latitude,
          longitude: coords.longitude,
          gps_time: row.last_connected || row.gps_time || row.timestamp || null,
          speed: safeParseNumber(row.gps_speed ?? row.speed),
          gps_speed: safeParseNumber(row.gps_speed ?? row.speed),
          gps_heading: safeParseNumber(row.gps_heading ?? row.heading ?? row.direction),
          heading: safeParseNumber(row.gps_heading ?? row.heading ?? row.direction),
          odometer: safeParseNumber(row.vcu_odometer ?? row.end_odometer ?? row.odometer),
          start_odometer: safeParseNumber(row.start_odometer),
          end_odometer: safeParseNumber(row.end_odometer),
          soc: safeParseNumber(row.soc),
          battery_temp: safeParseNumber(row.battery_temp),
          battery_voltage: safeParseNumber(row.battery_voltage),
          vehicle_status: row.vehicle_status ?? null,
          chassis_no: row.chassis_no ?? null,
          driver_name: row.driver_name ?? null,
          last_connected: row.last_connected || row.gps_time || null,
          gps_location: row.gps_location ?? null,
          idle_mins: safeParseNumber(row.idle_mins),
          imei: row.imei ?? null,
          raw: row
        };

        // Group by vehicle
        if (!grouped[vehicle_no]) {
          grouped[vehicle_no] = { 
            registration_number: vehicle_no, 
            points: [] 
          };
        }
        
        grouped[vehicle_no].points.push(point);
        validPoints++;

      } catch (rowErr) {
        // console.warn(`⚠️ Error processing row:`, rowErr.message);
        invalidPoints++;
      }
    }

    console.log(`✅ Processed ${validPoints} valid points, skipped ${invalidPoints} invalid points`);

    // Sort each vehicle's points newest-first and calculate headings
    for (const vehicle_no of Object.keys(grouped)) {
      try {
        const vehicle = grouped[vehicle_no];
        
        // Sort points by timestamp (newest first)
        vehicle.points.sort((a, b) => {
          const ta = a.last_connected ? new Date(a.last_connected).getTime() : 0;
          const tb = b.last_connected ? new Date(b.last_connected).getTime() : 0;
          return tb - ta;
        });
        
        // Calculate vector-based heading for latest point if not available
        if (vehicle.points.length >= 2) {
          const latest = vehicle.points[0];
          
          if (!latest.heading && latest.latitude && latest.longitude) {
            try {
              const calculated = calculateVectorHeading(vehicle.points);
              if (calculated !== null) {
                latest.heading = calculated;
                latest.gps_heading = calculated;
              }
            } catch (headingErr) {
              // console.warn(`⚠️ Error calculating heading for ${vehicle_no}:`, headingErr.message);
            }
          }
        }
      } catch (sortErr) {
        // console.warn(`⚠️ Error sorting points for ${vehicle_no}:`, sortErr.message);
      }
    }

    console.log(`✅ Successfully fetched data for ${Object.keys(grouped).length} vehicles`);
    return grouped;

  } catch (err) {
    // Log detailed error
    if (err instanceof APIError) {
      // console.error(`❌ fetchAllVehicles failed [${err.type}]:`, err.message);
    } else {
      // console.error('❌ fetchAllVehicles failed with unexpected error:', err);
    }
    
    // Graceful degradation: return empty object instead of throwing
    // This prevents the entire map from breaking if API is down
    // console.warn('⚠️ Returning empty vehicle data due to error');
    return {};
  }
}

// ===================================================
// FETCH SINGLE VEHICLE DATA
// ===================================================

/**
 * Fetch one vehicle's points for the last 24 hours.
 * Returns all data points sorted newest-first for playback.
 * 
 * @param {string} reg_no - Vehicle registration number
 * @param {string} [date] - Optional date in YYYY-MM-DD format for historical data
 * @returns {Promise<Array>} Array of points (newest-first) or empty array on failure
 * @throws {APIError} On API failure (after retries)
 * 
 * GRACEFUL DEGRADATION:
 * - Returns empty array [] on total failure
 * - Skips invalid points but processes valid ones
 * - Validates all GPS coordinates and numeric values
 */
export async function fetchVehicleOneDay(reg_no, date = null) {
  // Validate input
  if (!reg_no || typeof reg_no !== 'string') {
    console.error('❌ Invalid registration number:', reg_no);
    return [];
  }

  // Use historical endpoint if date is provided, otherwise use live endpoint
  const url = date ? API.HISTORICAL(date, reg_no) : API.ONE_DAY(reg_no);
  
  // Django backend handles all API authentication - no client-side keys needed
  const opts = {};
  
  console.log('🌐 fetchVehicleOneDay called with:');
  console.log('  - reg_no:', reg_no);
  console.log('  - date:', date);
  console.log('  - date type:', typeof date);
  console.log('  - date is null:', date === null);
  console.log('  - date is empty string:', date === '');
  console.log('  - Using URL:', url);
  console.log(date ? `📅 Fetching historical data for ${reg_no} on ${date}...` : `📊 Fetching live data for ${reg_no}...`);
  
  try {
    console.log('🔄 Starting fetch request...');
    let response = await fetchWithTimeout(url, opts);
    console.log('✅ Fetch completed, received:', response ? (Array.isArray(response) ? `${response.length} rows` : typeof response) : 'null/undefined');

    // Handle two response formats:
    // 1. Direct array from Telemetry API: [record1, record2, ...]
    // 2. Object with points key from Django API: {points: [...], count: ..., registration_number: ...}
    let rows;
    if (Array.isArray(response)) {
      rows = response;
    } else if (response && typeof response === 'object' && Array.isArray(response.points)) {
      rows = response.points;
    } else {
      throw new APIError(
        `Invalid API response format for vehicle ${reg_no}: expected array or {points: [...]}`,
        'validation',
        null,
        url
      );
    }

    if (rows.length === 0) {
      console.warn(`⚠️ No data available for vehicle ${reg_no}`);
      return [];
    }

    console.log(`📊 Processing ${rows.length} data points for vehicle ${reg_no}...`);

    // Map rows into playback points with validation
    const points = [];
    let validCount = 0;
    let invalidCount = 0;

    for (const row of rows) {
      try {
        // Parse and validate GPS coordinates
        const coords = parseGPSCoordinates(row);
        if (!coords) {
          console.warn(`⚠️ Skipping point with invalid GPS:`, row.gps_location);
          invalidCount++;
          continue;
        }

        const point = {
          registration_number: row.vehicle_no ?? reg_no,
          vehicle_no: row.vehicle_no ?? reg_no,
          latitude: coords.latitude,
          longitude: coords.longitude,
          gps_time: row.last_connected || row.gps_time || row.timestamp || null,
          speed: safeParseNumber(row.gps_speed ?? row.speed),
          gps_speed: safeParseNumber(row.gps_speed ?? row.speed),
          gps_heading: safeParseNumber(row.gps_heading ?? row.heading ?? row.direction),
          heading: safeParseNumber(row.gps_heading ?? row.heading ?? row.direction),
          odometer: safeParseNumber(row.vcu_odometer ?? row.end_odometer ?? row.odometer),
          start_odometer: safeParseNumber(row.start_odometer),
          end_odometer: safeParseNumber(row.end_odometer),
          soc: safeParseNumber(row.soc),
          battery_temp: safeParseNumber(row.battery_temp),
          battery_voltage: safeParseNumber(row.battery_voltage),
          vehicle_status: row.vehicle_status ?? null,
          chassis_no: row.chassis_no ?? null,
          driver_name: row.driver_name ?? null,
          last_connected: row.gps_time || row.last_connected || null,
          event_datetime: row.event_datetime ?? row.last_connected ?? null,
          gps_location: row.gps_location ?? null,
          idle_mins: safeParseNumber(row.idle_mins),
          imei: row.imei ?? null,
          raw: row
        };

        points.push(point);
        validCount++;

      } catch (rowErr) {
        // console.warn(`⚠️ Error processing row:`, rowErr.message);
        invalidCount++;
      }
    }

    console.log(`✅ Processed ${validCount} valid points, skipped ${invalidCount} invalid points for ${reg_no}`);

    if (points.length === 0) {
      // console.warn(`⚠️ No valid points found for vehicle ${reg_no}`);
      return [];
    }

    // Sort newest-first by timestamp
    points.sort((a, b) => {
      const ta = a.last_connected ? new Date(a.last_connected).getTime() : 0;
      const tb = b.last_connected ? new Date(b.last_connected).getTime() : 0;
      return tb - ta;
    });
    
    // Calculate vector-based heading for the latest point if not available
    if (points.length >= 2) {
      const latest = points[0];
      
      if (!latest.heading && latest.latitude && latest.longitude) {
        try {
          const calculated = calculateVectorHeading(points);
          if (calculated !== null) {
            latest.heading = calculated;
            latest.gps_heading = calculated;
          }
        } catch (headingErr) {
          // console.warn(`⚠️ Error calculating heading for ${reg_no}:`, headingErr.message);
        }
      }
    }

    console.log(`✅ Successfully fetched ${points.length} points for vehicle ${reg_no}`);
    return points;

  } catch (err) {
    // Log detailed error
    if (err instanceof APIError) {
      console.error(`❌ fetchVehicleOneDay failed for ${reg_no} [${err.type}]:`, err.message);
      console.error(`   Status: ${err.statusCode}, URL: ${err.url}`);
    } else {
      console.error(`❌ fetchVehicleOneDay failed for ${reg_no} with unexpected error:`, err);
      console.error(`   Message: ${err.message}`);
      console.error(`   Stack: ${err.stack}`);
    }
    
    // Graceful degradation: return empty array instead of throwing
    // This prevents playback from breaking if API is down
    console.warn(`⚠️ Returning empty data for vehicle ${reg_no} due to error`);
    return [];
  }
}

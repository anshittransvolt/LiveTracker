// ===================================================
// map.js - LiveTracker Vehicle Map Manager
// ===================================================
// Features:
// - Real-time vehicle plotting with markers and trails
// - Smart state-aware vehicle cards (Charging/Moving/Stopped)
// - Quick analytics panel with comprehensive vehicle data
// - Sidebar search and filtering
// - Geofence visibility controls
// - Interactive hover popups and click handlers
// ===================================================

import { fetchAllVehicles } from './api_handler.js';
import { addGeofences } from './geofence.js';
import { getDisplayVehicleNumber } from './vehicle_mapping.js';


// =======================
// 1️⃣ GLOBAL ELEMENTS
// =======================
// Note: Loading overlay is now in base.html template
// Use window.showLoading() and window.hideLoading() functions

// Helper function to show/hide loading with custom message
function toggleLoading(show = true, message = 'Loading vehicle data...') {
  if (show) {
    window.showLoading?.(message);
  } else {
    window.hideLoading?.();
  }
  // console.log(show ? `🌀 Showing loading: ${message}` : '✅ Hiding loading.');
}

// Export for compatibility
export const showSpinner = toggleLoading;

// =======================
// 2️⃣ MAP + SEARCH BAR SETUP
// =======================
const mapEl = document.getElementById('map');
const refreshBtn = document.getElementById('refreshBtn');

let map, markers = {}, polylines = {}, allVehicles = [];
let sidebarSearchInput;
let geofenceLayerGroup = null; // To manage geofence visibility
let markerClusterGroup = null; // Marker cluster group for grouping nearby vehicles

// Check if we're on a vehicle-specific page (not the main fleet view)
const isVehiclePage = window.location.pathname.match(/\/livetracker\/[^\/]+\/?$/);

// Skip map initialization if on vehicle page (vehicle_playback.js will handle it)
if (mapEl && !isVehiclePage) {
  // console.log('🗺️ Initializing main fleet map...');

  // =======================
  // GEOCODING CACHE - Prevent excessive API calls
  // =======================
  const geocodingCache = new Map(); // Store addresses by coordinates
  const GEOCODING_CACHE_TTL = 3600000; // 1 hour cache
  const pendingGeocodeRequests = new Map(); // Deduplicate simultaneous requests
  
  /**
   * Get cache key for coordinates (rounded to 4 decimals ~11m precision)
   */
  function getGeocodeKey(lat, lng) {
    return `${lat.toFixed(4)},${lng.toFixed(4)}`;
  }
  
  // Reverse geocode helper using Django backend proxy (solves CORS issues)
  async function fetchReverseGeocode(lat, lng) {
    try {
      // Validate coordinates
      if (typeof lat !== 'number' || typeof lng !== 'number') {
        console.error('❌ Invalid coordinate types:', typeof lat, typeof lng);
        return null;
      }
      
      if (isNaN(lat) || isNaN(lng)) {
        console.error('❌ NaN coordinates:', lat, lng);
        return null;
      }
      
      if (lat < -90 || lat > 90 || lng < -180 || lng > 180) {
        console.error('❌ Coordinates out of range:', lat, lng);
        return null;
      }
      
      // Check cache first (1 hour TTL)
      const cacheKey = getGeocodeKey(lat, lng);
      const cached = geocodingCache.get(cacheKey);
      if (cached && (Date.now() - cached.timestamp < GEOCODING_CACHE_TTL)) {
        // console.log(`✅ Geocoding cache hit: ${cacheKey}`);
        return cached.address;
      }
      
      // Deduplicate simultaneous requests for same coordinates
      if (pendingGeocodeRequests.has(cacheKey)) {
        // console.log(`⏳ Reusing pending geocode request: ${cacheKey}`);
        return pendingGeocodeRequests.get(cacheKey);
      }
      
      // Create the geocoding request promise
      const geocodePromise = (async () => {
        // Use Django backend proxy to avoid CORS issues
        const url = `/livetracker/api/geocode/?lat=${lat}&lon=${lng}`;
        // console.log(`🌐 Fetching geocode via backend proxy: ${cacheKey}`);
        
        // Add timeout to fetch request (20 seconds to account for backend retries)
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 20000);
      
      const response = await fetch(url, {
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      if (!response.ok) {
        console.error(`❌ Geocoding HTTP error: ${response.status} ${response.statusText}`);
        
        // Handle specific error codes
        if (response.status === 429) {
          console.warn('⚠️ Rate limit exceeded - using fallback');
          return 'Location temporarily unavailable (rate limit)';
        }
        
        if (response.status === 503) {
          console.warn('⚠️ Geocoding service unavailable');
          return 'Location service unavailable';
        }
        
        if (response.status === 504) {
          console.warn('⚠️ Geocoding timeout - using fallback');
          return 'Location temporarily unavailable';
        }
        
        return null;
      }
      
        const data = await response.json();
        // console.log('📍 Geocoding response:', data);
        
        if (!data.success) {
          console.error('❌ Geocoding API error:', data.error);
          return 'Address unavailable';
        }
        
        const address = data.address || 'Address unavailable';
        
        // Cache successful result for 1 hour
        geocodingCache.set(cacheKey, {
          address: address,
          timestamp: Date.now()
        });
        
        return address;
      })();
      
      // Store in pending requests map
      pendingGeocodeRequests.set(cacheKey, geocodePromise);
      
      try {
        const result = await geocodePromise;
        return result;
      } finally {
        // Clean up pending request
        pendingGeocodeRequests.delete(cacheKey);
      }
      
    } catch (error) {
      // Handle abort/timeout errors
      if (error.name === 'AbortError') {
        console.error('❌ Reverse geocoding timeout after 20s');
        return 'Location temporarily unavailable (timeout)';
      }
      
      console.error('❌ Reverse geocoding error:', error);
      return 'Address unavailable';
    }
  }

  // Get sidebar search input
  sidebarSearchInput = document.getElementById('sidebarSearchInput');

  // =======================
  // 3️⃣ MAP SETUP
  // =======================
  const TILE_LAYERS = {
    day:  L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
      maxZoom: 20, attribution: '&copy; <a href="https://carto.com/">CARTO</a>'
    }),
    dark: L.tileLayer('https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png', {
      maxZoom: 20, attribution: '&copy; <a href="https://stadiamaps.com/">Stadia Maps</a>'
    }),
  };

  let currentMapStyle = localStorage.getItem('mapStyle') || 'dark'; // dark is default
  map = L.map('map').setView([20.59, 78.96], 5);
  TILE_LAYERS[currentMapStyle].addTo(map);
  document.body.classList.toggle('dark-theme', currentMapStyle === 'dark');

  function _updateStyleBtn(style) {
    const btn = document.getElementById('mapStyleToggle');
    if (!btn) return;
    const sun = `<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>`;
    const moon = `<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>`;
    btn.innerHTML = style === 'dark'
      ? `${sun}<span class="text-xs font-semibold hidden sm:inline">Light</span>`
      : `${moon}<span class="text-xs font-semibold hidden sm:inline">Dark</span>`;
    btn.title = style === 'dark' ? 'Switch to Light Map' : 'Switch to Dark Map';
  }
  _updateStyleBtn(currentMapStyle);

  window.toggleMapStyle = function () {
    const next = currentMapStyle === 'day' ? 'dark' : 'day';
    map.removeLayer(TILE_LAYERS[currentMapStyle]);
    TILE_LAYERS[next].addTo(map);
    currentMapStyle = next;
    localStorage.setItem('mapStyle', next);
    document.body.classList.toggle('dark-theme', next === 'dark');
    _updateStyleBtn(next);
  };

  // Initialize marker cluster group with custom options
  markerClusterGroup = L.markerClusterGroup({
    maxClusterRadius: 80, // Cluster markers within 80 pixels
    spiderfyOnMaxZoom: true, // Show individual markers on max zoom
    showCoverageOnHover: false, // Don't show cluster area on hover
    zoomToBoundsOnClick: true, // Zoom to cluster bounds on click
    disableClusteringAtZoom: 16, // Disable clustering at zoom level 16+
    // Only create cluster if 5 or more markers in the area
    iconCreateFunction: function(cluster) {
      const count = cluster.getChildCount();
      let sizeClass = 'small';
      let size = 32;
      if (count >= 50) { sizeClass = 'large'; size = 44; }
      else if (count >= 10) { sizeClass = 'medium'; size = 38; }
      return L.divIcon({
        html: `<div style="width:${size}px;height:${size}px;background:#1d4ed8;border:2px solid rgba(255,255,255,0.15);border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-weight:600;font-size:11px;box-shadow:0 0 0 4px rgba(29,78,216,0.2);">${count}</div>`,
        className: 'marker-cluster marker-cluster-' + sizeClass,
        iconSize: L.point(size, size)
      });
    }
  });
  
  map.addLayer(markerClusterGroup);
  console.log('✅ Marker clustering enabled (5+ vehicles)');


  // Add organization watermark - Constrained to map area only (excluding sidebar)
  const watermarkControl = L.Control.extend({
    options: {
      position: 'bottomleft'
    },
    onAdd: function(map) {
      const container = L.DomUtil.create('div', 'leaflet-watermark-pattern');
      
      // Sidebar width - adjust based on your sidebar width (typically 320px on desktop)
      const sidebarWidth = window.innerWidth >= 1024 ? '320px' : '0px'; // No sidebar on mobile
      
      // Create evenly distributed watermarks across map area (excluding sidebar)
      let watermarkHTML = '';
      const rows = 4; // Number of rows to cover full height
      const cols = 4; // Number of columns to cover full width
      
      for (let i = 0; i < rows; i++) {
        watermarkHTML += `
          <div style="
            display: flex;
            gap: 120px;
            margin-bottom: ${i < rows - 1 ? '80px' : '0'};
            justify-content: space-evenly;
            align-items: center;
          ">`;
        
        for (let j = 0; j < cols; j++) {
          watermarkHTML += `
            <img src="/static/livetracker/images/transvolt_logo.svg" alt="Transvolt" style="width: 180px; height: auto; opacity: 0.2;" />
          `;
        }
        
        watermarkHTML += `</div>`;
      }
      
      container.innerHTML = `
        <div style="
          position: fixed;
          top: 0;
          left: ${sidebarWidth};
          right: 0;
          bottom: 0;
          pointer-events: none;
          user-select: none;
          z-index: 400;
          display: flex;
          flex-direction: column;
          justify-content: space-evenly;
          padding: 40px;
          overflow: hidden;
        ">
          ${watermarkHTML}
        </div>
      `;
      
      // Make container cover the map area only (exclude sidebar)
      container.style.position = 'absolute';
      container.style.top = '0';
      container.style.left = '0';
      container.style.width = '100%';
      container.style.height = '100%';
      container.style.pointerEvents = 'none';
      container.style.zIndex = '400';
      
      return container;
    }
  });
  
  map.addControl(new watermarkControl());

  // =======================
  // 4️⃣ DYNAMIC ICON FUNCTIONS
  // =======================
  function getIconSize(zoom) {
    // Define minimum and maximum sizes
    const minSize = 35;
    const maxSize = 55;
    const scaleFactor = zoom / 14;
    const size = Math.max(minSize, Math.min(maxSize, minSize * scaleFactor));
    return [size, size];
  }

  /**
   * Determine arrow color based on direction (Dhar ↔ Dhule route)
   * Blue: Dhar to Dhule (generally southward, heading ~180°)
   * Purple: Dhule to Dhar (generally northward, heading ~0° or 360°)
   */
  function getArrowColor(heading, latitude) {
    // Dhar approximate latitude: 22.6°N
    // Dhule approximate latitude: 21.0°N
    // If heading is between 90° and 270°, vehicle is going south (Dhar → Dhule) = Blue
    // If heading is between 270° and 90° (through 0°), vehicle is going north (Dhule → Dhar) = Purple
    
    const normalizedHeading = ((heading % 360) + 360) % 360; // Normalize to 0-360
    
    if (normalizedHeading >= 90 && normalizedHeading <= 270) {
      return '#3b82f6'; // Blue - Dhar to Dhule (southward)
    } else {
      return 'rgb(177, 133, 167)'; // Purple - Dhule to Dhar (northward)
    }
  }


function createBusIcon(zoom, heading = 0, latitude = 0, status = 'Stopped') {
  const lowerStatus = (status || '').toLowerCase();
  let color, dotSize, shadow, pulseClass;

  if (lowerStatus === 'charging') {
    color = '#3b82f6'; dotSize = 12; shadow = 'rgba(59,130,246,0.4)'; pulseClass = 'charging-pulse';
  } else if (lowerStatus === 'moving') {
    color = '#22c55e'; dotSize = 12; shadow = 'rgba(34,197,94,0.3)'; pulseClass = '';
  } else {
    color = '#ef4444'; dotSize = 10; shadow = 'rgba(239,68,68,0.2)'; pulseClass = '';
  }

  const outer = dotSize + 8;
  return L.divIcon({
    className: 'custom-vehicle-dot',
    html: `<div class="${pulseClass}" style="width:${outer}px;height:${outer}px;display:flex;align-items:center;justify-content:center;"><div style="width:${dotSize}px;height:${dotSize}px;background:${color};border-radius:50%;border:2px solid rgba(255,255,255,0.9);box-shadow:0 0 0 3px ${shadow};"></div></div>`,
    iconSize: [outer, outer],
    iconAnchor: [outer / 2, outer / 2],
    popupAnchor: [0, -(outer / 2)],
  });
}




  // Add geofences to the map with layer group for easy toggle
  geofenceLayerGroup = L.layerGroup();
  addGeofences(map); // This will still add directly to map for now

  // Handle zoom changes to update marker icons (dot size is fixed, but preserves state)
  map.on('zoomend', () => {
    const currentZoom = map.getZoom();
    Object.keys(markers).forEach(reg => {
      const marker = markers[reg];
      marker.setIcon(createBusIcon(currentZoom, marker.heading || 0, marker.getLatLng().lat, marker.vehicleState || 'Stopped'));
    });
  });

  // Add geofence toggle functionality
  const geofenceToggleBtn = document.getElementById('geofenceToggle');
  let geofencesVisible = true;

  if (geofenceToggleBtn) {
    geofenceToggleBtn.addEventListener('click', () => {
      geofencesVisible = !geofencesVisible;

      // Find all geofence elements and toggle their visibility
      const geofenceElements = document.querySelectorAll('.geofence-marker, .geofence-circle, .geofence-polygon');
      geofenceElements.forEach(el => {
        if (geofencesVisible) {
          el.style.display = '';
          geofenceToggleBtn.innerHTML = `
            <i data-lucide="eye-off" class="w-3.5 h-3.5 md:w-4 md:h-4"></i>
            
          `;
          geofenceToggleBtn.classList.add('bg-green-100');
        } else {
          el.style.display = 'none';
          geofenceToggleBtn.innerHTML = `
            <i data-lucide="eye" class="w-3.5 h-3.5 md:w-4 md:h-4"></i>
            
          `;
          geofenceToggleBtn.classList.remove('bg-green-100');
        }
      });

      // Also toggle SVG paths for circles and polygons
      const svgPaths = map.getPane('overlayPane').querySelectorAll('path.geofence-circle, path.geofence-polygon');
      svgPaths.forEach(path => {
        path.style.display = geofencesVisible ? '' : 'none';
      });

      // Recreate icons
      if (typeof lucide !== 'undefined') lucide.createIcons();
    });
  }

  // Mobile menu toggle functionality
  const mobileMenuToggle = document.getElementById('mobileMenuToggle');
  const closeMobileSidebar = document.getElementById('closeMobileSidebar');
  const mobileSidebar = document.getElementById('mobileSidebar');

  if (mobileMenuToggle) {
    mobileMenuToggle.addEventListener('click', () => {
      if (mobileSidebar) {
        mobileSidebar.classList.remove('hidden');
        // Trigger icons refresh
        setTimeout(() => {
          if (typeof lucide !== 'undefined') lucide.createIcons();
        }, 100);
      }
    });
  }

  if (closeMobileSidebar) {
    closeMobileSidebar.addEventListener('click', () => {
      if (mobileSidebar) {
        mobileSidebar.classList.add('hidden');
      }
    });
  }

  // Close mobile sidebar when clicking overlay
  if (mobileSidebar) {
    mobileSidebar.addEventListener('click', (e) => {
      if (e.target === mobileSidebar) {
        mobileSidebar.classList.add('hidden');
      }
    });
  }  // =======================
  // SIDEBAR SEARCH LOGIC
  // =======================
  let currentStatusFilter = 'all'; // Track current filter state
  let currentRouteFilter = 'both'; // Track route filter: 'dhar-dhule', 'dhule-dhar', or 'both'

  if (sidebarSearchInput) {
    const clearSearchBtn = document.getElementById('clearSearchBtn');
    
    // Show/hide clear button based on input
    sidebarSearchInput.addEventListener('input', () => {
      if (sidebarSearchInput.value.trim()) {
        clearSearchBtn?.classList.remove('hidden');
      } else {
        clearSearchBtn?.classList.add('hidden');
      }
      applyFilters();
    });

    // Clear search button functionality
    if (clearSearchBtn) {
      clearSearchBtn.addEventListener('click', () => {
        sidebarSearchInput.value = '';
        clearSearchBtn.classList.add('hidden');
        sidebarSearchInput.focus();
        applyFilters();
      });
    }
  }

  /**
   * Determine vehicle route direction based on heading
   * Returns 'dhar-dhule' for southward (blue), 'dhule-dhar' for northward (purple)
   */
  function getVehicleRoute(heading) {
    const normalizedHeading = ((heading % 360) + 360) % 360;
    if (normalizedHeading >= 90 && normalizedHeading <= 270) {
      return 'dhar-dhule'; // Southward - Dhar to Dhule
    } else {
      return 'dhule-dhar'; // Northward - Dhule to Dhar
    }
  }

  // Status filter buttons
  const filterButtons = {
    filterAll: 'all',
    filterCharging: 'charging',
    filterMoving: 'moving',
    filterStopped: 'stopped',
    filterLowSoc: 'lowsoc'
  };

  Object.entries(filterButtons).forEach(([btnId, filterType]) => {
    const btn = document.getElementById(btnId);
    if (btn) {
      btn.addEventListener('click', () => {
        currentStatusFilter = filterType;

        // Update button styles
        Object.keys(filterButtons).forEach(id => {
          const button = document.getElementById(id);
          if (button) {
            if (id === btnId) {
              // Active state
              button.classList.add('bg-slate-100', 'border-slate-300');
              button.classList.remove('bg-white', 'hover:bg-green-50', 'hover:bg-blue-50', 'hover:bg-red-50', 'hover:bg-orange-50');
            } else {
              // Inactive state
              button.classList.remove('bg-slate-100', 'border-slate-300');
              button.classList.add('bg-white');
              if (id === 'filterCharging') button.classList.add('hover:bg-green-50');
              if (id === 'filterMoving') button.classList.add('hover:bg-blue-50');
              if (id === 'filterStopped') button.classList.add('hover:bg-red-50');
              if (id === 'filterLowSoc') button.classList.add('hover:bg-orange-50');
            }
          }
        });

        applyFilters();
      });
    }
  });

  // Route filter buttons (handles both mobile and desktop with data attributes)
  const routeFilterButtons = document.querySelectorAll('.route-filter-btn');
  console.log(`🔘 Found ${routeFilterButtons.length} route filter buttons`);

  routeFilterButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const filterType = btn.getAttribute('data-route-filter');
      console.log(`🎯 Route filter clicked: ${filterType}`);
      currentRouteFilter = filterType;

      // Update all route filter button styles (both mobile and desktop)
      routeFilterButtons.forEach(button => {
        const buttonFilter = button.getAttribute('data-route-filter');
        if (buttonFilter === filterType) {
          // Active state
          button.classList.add('bg-slate-100', 'border-slate-300');
          button.classList.remove('bg-white', 'hover:bg-blue-50', 'hover:bg-purple-50', 'hover:bg-slate-50');
        } else {
          // Inactive state
          button.classList.remove('bg-slate-100', 'border-slate-300');
          button.classList.add('bg-white');
          if (buttonFilter === 'dhar-dhule') button.classList.add('hover:bg-blue-50');
          if (buttonFilter === 'dhule-dhar') button.classList.add('hover:bg-purple-50');
          if (buttonFilter === 'both') button.classList.add('hover:bg-slate-50');
        }
      });

      applyFilters();
      
      // Re-initialize lucide icons after style changes
      if (typeof lucide !== 'undefined') lucide.createIcons();
    });
  });

  /**
   * Apply filters to both sidebar cards AND map markers
   * Filters by search term, vehicle status, and route direction
   */
  function applyFilters() {
    const searchTerm = sidebarSearchInput?.value.trim().toUpperCase() || '';
    const vehicleCards = document.querySelectorAll('#vehicleList > div');

    console.log(`🔍 Applying filters - Status: ${currentStatusFilter}, Route: ${currentRouteFilter}, Search: "${searchTerm}"`);

    // Track which vehicles should be visible on map
    const visibleVehicles = new Set();

    vehicleCards.forEach(card => {
      const displayNumber = card.querySelector('h3')?.textContent || '';
      const actualRegNumber = card.getAttribute('data-vehicle');
      const matchesSearch = !searchTerm || displayNumber.toUpperCase().includes(searchTerm);

      // Check status filter
      let matchesStatus = true;
      if (currentStatusFilter !== 'all') {
        if (currentStatusFilter === 'lowsoc') {
          const socElement = card.querySelector('[data-soc]');
          const soc = parseInt(socElement?.getAttribute('data-soc') || '100');
          matchesStatus = soc < 30;
        } else {
          const statusBadge = card.querySelector('span[class*="rounded-full"]');
          const statusText = statusBadge?.textContent.trim().toLowerCase() || '';
          matchesStatus = statusText === currentStatusFilter;
        }
      }

      // Check route filter - get actual registration number from data attribute
      let matchesRoute = true;
      if (currentRouteFilter !== 'both') {
        if (actualRegNumber && markers[actualRegNumber]) {
          const heading = markers[actualRegNumber].heading || 0;
          const vehicleRoute = getVehicleRoute(heading);
          matchesRoute = vehicleRoute === currentRouteFilter;
          
          if (!matchesRoute) {
            console.log(`❌ ${displayNumber} filtered out - heading: ${heading}°, route: ${vehicleRoute}, filter: ${currentRouteFilter}`);
          }
        } else {
          console.warn(`⚠️ ${displayNumber} - No marker found for ${actualRegNumber}`);
        }
      }

      // Show/hide sidebar card
      const shouldShow = matchesSearch && matchesStatus && matchesRoute;
      card.style.display = shouldShow ? 'block' : 'none';

      // Track vehicles that should be visible on map (use actual reg number, not display number)
      if (shouldShow && actualRegNumber) {
        visibleVehicles.add(actualRegNumber);
      }
    });

    console.log(`✅ Visible vehicles after filter: ${visibleVehicles.size}`);

    // Update map markers and polylines visibility
    updateMapVisibility(visibleVehicles);
  }

  /**
   * Update map markers and polylines visibility based on filter
   * @param {Set<string>} visibleVehicles - Set of vehicle registration numbers that should be visible
   */
  function updateMapVisibility(visibleVehicles) {
    // Update markers visibility in cluster group
    Object.keys(markers).forEach(reg => {
      const marker = markers[reg];
      const shouldShow = visibleVehicles.has(reg);
      
      if (shouldShow) {
        if (!markerClusterGroup.hasLayer(marker)) {
          markerClusterGroup.addLayer(marker);
        }
      } else {
        if (markerClusterGroup.hasLayer(marker)) {
          markerClusterGroup.removeLayer(marker);
        }
      }
    });

    // Update polylines visibility
    Object.keys(polylines).forEach(reg => {
      const polyline = polylines[reg];
      const shouldShow = visibleVehicles.has(reg);
      
      if (shouldShow) {
        if (!map.hasLayer(polyline)) {
          polyline.addTo(map);
        }
      } else {
        if (map.hasLayer(polyline)) {
          map.removeLayer(polyline);
        }
      }
    });

    // Fit map bounds to visible vehicles only (if any visible)
    if (visibleVehicles.size > 0) {
      const visibleBounds = [];
      visibleVehicles.forEach(reg => {
        if (markers[reg]) {
          const latLng = markers[reg].getLatLng();
          visibleBounds.push([latLng.lat, latLng.lng]);
        }
      });

      if (visibleBounds.length > 0) {
        map.fitBounds(visibleBounds, {
          padding: [50, 50],
          maxZoom: 12
        });
      }
    }
  }

  // =======================
  // MARKER POPUP HELPERS WITH ADDRESS FETCHING
  // =======================
  
  /**
   * Create initial popup for a marker with "Loading address..."
   */
  function createMarkerPopup(marker, displayNumber, latest, lat, lng) {
    // Normalize status for display
    let displayStatus = latest.vehicle_status ?? 'N/A';
    if (typeof displayStatus === 'string' && ['stop', 'stopped'].includes(displayStatus.trim().toLowerCase())) {
      displayStatus = 'Stopped';
    }

    // Use gps_time as fallback if last_connected is not available
    const lastUpdateTime = latest.last_connected || latest.gps_time;

    // Create popup with coordinates initially
    const initialContent = buildPopupHTML(displayNumber, latest, displayStatus, `${lat.toFixed(4)}, ${lng.toFixed(4)}`, lastUpdateTime);
    
    marker.bindPopup(initialContent, { 
      autoClose: false, 
      closeOnClick: false,
      closeButton: false, 
      maxWidth: 260,
      className: 'simple-vehicle-popup',
      autoPan: false, // Prevent map from panning when popup opens
      offset: [0, -10] // Closer to marker, easier to reach with mouse
    });

    // Store the coordinates for which address was fetched (to detect location changes)
    marker.lastFetchedCoords = null;
    
    // Store close timeout on marker itself to persist across events
    marker.popupCloseTimeout = null;
    
    marker.on('mouseover', function() {
      // Clear any pending close timeout
      if (marker.popupCloseTimeout) {
        clearTimeout(marker.popupCloseTimeout);
        marker.popupCloseTimeout = null;
      }
      
      const currentCoords = `${lat.toFixed(4)},${lng.toFixed(4)}`;
      
      // Open popup
      marker.openPopup();
      
      // Only fetch if we haven't fetched for these exact coordinates yet
      if (marker.lastFetchedCoords !== currentCoords) {
        marker.lastFetchedCoords = currentCoords;
        
        fetchReverseGeocode(lat, lng).then(address => {
          if (address) {
            const updatedContent = buildPopupHTML(displayNumber, latest, displayStatus, address, lastUpdateTime);
            marker.getPopup().setContent(updatedContent);
            // If popup is currently open, refresh it
            if (marker.isPopupOpen()) {
              marker.getPopup().update();
            }
          }
        });
      }
    });
    
    marker.on('mouseout', function() {
      // Longer delay to allow hovering over the popup
      marker.popupCloseTimeout = setTimeout(() => {
        marker.closePopup();
      }, 1000); // 1 second - plenty of time to move mouse to popup
    });
    
    // Keep popup open when hovering over it
    marker.on('popupopen', function() {
      const popup = marker.getPopup();
      const popupElement = popup._container;
      
      if (popupElement) {
        // Remove pointer-events:none from popup to make it hoverable
        popupElement.style.pointerEvents = 'auto';
        
        // Mouse enter popup - cancel close
        const onPopupMouseEnter = function() {
          if (marker.popupCloseTimeout) {
            clearTimeout(marker.popupCloseTimeout);
            marker.popupCloseTimeout = null;
          }
        };
        
        // Mouse leave popup - close after delay
        const onPopupMouseLeave = function() {
          marker.popupCloseTimeout = setTimeout(() => {
            marker.closePopup();
          }, 500); // Increased delay for smoother UX
        };
        
        popupElement.addEventListener('mouseenter', onPopupMouseEnter);
        popupElement.addEventListener('mouseleave', onPopupMouseLeave);
        
        // Clean up event listeners when popup closes
        marker.once('popupclose', function() {
          popupElement.removeEventListener('mouseenter', onPopupMouseEnter);
          popupElement.removeEventListener('mouseleave', onPopupMouseLeave);
        });
      }
    });
  }

  /**
   * Update existing marker popup with new data
   * Detects location changes and resets address cache flag
   */
  function updateMarkerPopup(marker, displayNumber, latest, lat, lng) {
    // Normalize status for display
    let displayStatus = latest.vehicle_status ?? 'N/A';
    if (typeof displayStatus === 'string' && ['stop', 'stopped'].includes(displayStatus.trim().toLowerCase())) {
      displayStatus = 'Stopped';
    }

    // Use gps_time as fallback if last_connected is not available
    const lastUpdateTime = latest.last_connected || latest.gps_time;

    const currentCoords = `${lat.toFixed(4)},${lng.toFixed(4)}`;
    
    // Check if vehicle moved to new location (coordinates changed)
    if (marker.lastFetchedCoords && marker.lastFetchedCoords !== currentCoords) {
      // Location changed! Reset the flag so address will be re-fetched on next hover
      marker.lastFetchedCoords = null;
    }

    // If popup is currently open, fetch and update address
    if (marker.isPopupOpen()) {
      marker.lastFetchedCoords = currentCoords;
      fetchReverseGeocode(lat, lng).then(address => {
        const updatedContent = buildPopupHTML(displayNumber, latest, displayStatus, address || `${lat.toFixed(4)}, ${lng.toFixed(4)}`, lastUpdateTime);
        marker.getPopup().setContent(updatedContent);
      });
    } else {
      // Just update the popup content with coordinates, don't fetch address yet
      const updatedContent = buildPopupHTML(displayNumber, latest, displayStatus, `${lat.toFixed(4)}, ${lng.toFixed(4)}`, lastUpdateTime);
      marker.getPopup().setContent(updatedContent);
    }
  }

  /**
   * Build popup HTML content
   */
  function buildPopupHTML(displayNumber, latest, displayStatus, locationText, lastUpdateTime = null) {
    const isDark = document.body.classList.contains('dark-theme');
    const bg       = isDark ? '#0f1825' : '#ffffff';
    const border   = isDark ? '#1e2433' : '#e5e7eb';
    const textMain = isDark ? '#e2e8f0' : '#111827';
    const textMuted= isDark ? '#475569' : '#6b7280';
    const textSub  = isDark ? '#94a3b8' : '#374151';
    const badgeBg  = isDark ? 'rgba(255,255,255,0.05)' : '#f8fafc';

    const soc = latest.soc ?? 0;
    let batteryColor = isDark ? '#34d399' : '#059669';
    if (soc < 30) batteryColor = isDark ? '#f87171' : '#dc2626';
    else if (soc < 60) batteryColor = isDark ? '#fbbf24' : '#d97706';

    let statusColor = isDark ? '#64748b' : '#64748b';
    const ds = displayStatus.toLowerCase();
    if (ds.includes('charging')) statusColor = isDark ? '#34d399' : '#059669';
    else if (ds.includes('moving')) statusColor = isDark ? '#60a5fa' : '#2563eb';
    else if (ds.includes('stopped')) statusColor = isDark ? '#f87171' : '#dc2626';

    return `<div style="min-width:185px;max-width:200px;font-family:system-ui,sans-serif;color:${textMain};padding:8px 9px;background:${bg};border-radius:6px;border:1px solid ${border};">
  <div style="font-size:13px;font-weight:700;color:${textMain};margin-bottom:6px;padding-bottom:4px;border-bottom:1.5px solid ${border};">${displayNumber}</div>
  <div style="display:flex;gap:8px;margin-bottom:6px;">
    <div style="flex:1;text-align:center;">
      <div style="font-size:8.5px;color:${textMuted};font-weight:600;text-transform:uppercase;margin-bottom:2px;letter-spacing:0.3px;">Battery</div>
      <div style="font-size:16px;font-weight:700;color:${batteryColor};line-height:1;">${latest.soc ?? 'N/A'}<span style="font-size:10px;font-weight:500;color:${textMuted};">%</span></div>
    </div>
    <div style="width:1px;background:${border};margin:2px 0;"></div>
    <div style="flex:1;text-align:center;">
      <div style="font-size:8.5px;color:${textMuted};font-weight:600;text-transform:uppercase;margin-bottom:2px;letter-spacing:0.3px;">Speed</div>
      <div style="font-size:16px;font-weight:700;color:${textMain};line-height:1;">${latest.speed ?? 'N/A'}<span style="font-size:10px;font-weight:500;color:${textMuted};">km/h</span></div>
    </div>
  </div>
  <div style="display:inline-block;font-size:8.5px;font-weight:700;color:${statusColor};padding:3px 7px;border-radius:3px;background:${badgeBg};border-left:2.5px solid ${statusColor};margin-bottom:6px;letter-spacing:0.3px;text-transform:uppercase;">${displayStatus}</div>
  <div style="margin-bottom:5px;">
    <div style="font-size:8.5px;color:${textMuted};font-weight:600;text-transform:uppercase;margin-bottom:1px;letter-spacing:0.2px;">Location</div>
    <div style="font-size:10px;color:${textSub};font-weight:500;line-height:1.25;">${locationText}</div>
  </div>
  <div style="font-size:8.5px;color:${textMuted};padding-top:5px;border-top:1px solid ${border};">
    <span style="font-weight:600;text-transform:uppercase;letter-spacing:0.2px;">Updated:</span>
    <span style="color:${textMain};font-weight:500;margin-left:3px;">${formatTimeAgo(lastUpdateTime || latest.last_connected || latest.gps_time)}</span>
  </div>
</div>`;
  }

  // =======================
  // FETCH & RENDER VEHICLES
  // =======================
  async function loadAll(silent = false) {
    // Only show loading overlay if not a silent refresh
    if (!silent) {
      toggleLoading(true, 'Loading vehicle data...');
    }
    const messageEl = document.getElementById('vehicle-list-message');
    if(messageEl) messageEl.textContent = '';

    try {
      const spv = document.getElementById('projectSwitcher')?.value || '';
      const payload = await fetchAllVehicles(spv);
      window.lastPayload = payload;

      const activeRegs = new Set();
      allVehicles = [];
      const bounds = []; // Track all vehicle positions for bounds fitting

      for (const key in payload) {
        const { registration_number, points } = payload[key];
        if (!points?.length) continue;

        // Map trolley to truck number for display
        const displayNumber = getDisplayVehicleNumber(registration_number);

        activeRegs.add(registration_number);
        allVehicles.push(displayNumber);  // Store display number for UI

        const trail = points.slice(0, 5);
        const latest = trail[0];
        const lat = parseFloat(latest.latitude);
        const lng = parseFloat(latest.longitude);
        if (isNaN(lat) || isNaN(lng)) continue;

        // Get heading from GPS data (default to 0 if not available)
        const heading = parseFloat(latest.gps_heading || latest.heading || 0);

        // console.log(`🚛 ${displayNumber}: heading = ${heading}°, speed = ${latest.speed} km/h, lat = ${lat}`);

        bounds.push([lat, lng]); // Add to bounds array

        // Update or create marker
        const { state: vehicleState } = getVehicleState(latest);
        if (markers[registration_number]) {
          markers[registration_number].setLatLng([lat, lng]);
          markers[registration_number].heading = heading;
          markers[registration_number].vehicleState = vehicleState;
          markers[registration_number].setIcon(createBusIcon(map.getZoom(), heading, lat, vehicleState));

          // Update popup with fresh location data
          updateMarkerPopup(markers[registration_number], displayNumber, latest, lat, lng);
        } else {
          const marker = L.marker([lat, lng], { icon: createBusIcon(map.getZoom(), heading, lat, vehicleState) });
          marker.heading = heading;
          marker.vehicleState = vehicleState;

          // Create initial popup with "Loading address..."
          createMarkerPopup(marker, displayNumber, latest, lat, lng);

          marker.on('mouseover', function () { this.openPopup(); });
          marker.on('mouseout', function () { this.closePopup(); });
          marker.on('click', () => showQuickAnalytics(registration_number, latest));

          markers[registration_number] = marker;
          markerClusterGroup.addLayer(marker); // Add to cluster group instead of map
        }

        // Update or create trail polyline (shadow + route double layer)
        const latlngs = trail.map(pt => [parseFloat(pt.latitude), parseFloat(pt.longitude)]);
        if (polylines[registration_number]) {
          polylines[registration_number]._shadowLine.setLatLngs(latlngs);
          polylines[registration_number]._routeLine.setLatLngs(latlngs);
        } else {
          const shadowLine = L.polyline(latlngs, { color: 'rgba(34,197,94,0.12)', weight: 14, opacity: 1, lineCap: 'round', lineJoin: 'round' });
          const routeLine  = L.polyline(latlngs, { color: '#22c55e', weight: 4, opacity: 1, lineCap: 'round', lineJoin: 'round', className: 'trail-route-line' });
          const trailGroup = L.layerGroup([shadowLine, routeLine]).addTo(map);
          trailGroup._shadowLine = shadowLine;
          trailGroup._routeLine  = routeLine;
          polylines[registration_number] = trailGroup;
        }
      }

      // Clean up stale markers and polylines
      Object.keys(markers).forEach(reg => {
        if (!activeRegs.has(reg)) {
          markerClusterGroup.removeLayer(markers[reg]); // Remove from cluster group
          delete markers[reg];
        }
      });
      
      Object.keys(polylines).forEach(reg => {
        if (!activeRegs.has(reg)) {
          map.removeLayer(polylines[reg]);
          delete polylines[reg];
        }
      });

      // Fit map to show all vehicles with some padding
      if (bounds.length > 0) {
        map.fitBounds(bounds, {
          padding: [50, 50], // Add padding around bounds
          maxZoom: 12 // Don't zoom in too close for multiple vehicles
        });
      }

      updateVehicleList(payload);
      
      // Fetch all driver info in one bulk call (fast and efficient)
      const registrationNumbers = Array.from(activeRegs);
      if (registrationNumbers.length > 0) {
        fetchAllDriverInfo(registrationNumbers).catch(err => {
          console.error('⚠️ Failed to load driver info:', err);
          // Non-critical error, continue anyway
        });
      }
      
      if (!silent) {
        toggleLoading(false);
      }
    } catch (err) {
      console.error("❌ Vehicle data loading error:", err);
      if(messageEl) messageEl.textContent = 'Failed to load vehicle data. Please try again.';
      updateVehicleList({}); // Clear the list
      if (!silent) {
        toggleLoading(false);
      }
    }
  }

  // =======================
  // UPDATE VEHICLE LIST IN SIDEBAR
  // =======================
  function updateVehicleList(payload) {
    const vehicleListEl = document.getElementById('vehicleList');
    const mobileVehicleListEl = document.getElementById('mobileVehicleList');
    const messageEl = document.getElementById('vehicle-list-message');
    if (!vehicleListEl) return;

    const vehicles = Object.values(payload).filter(v => v.points?.length > 0);

    // Calculate counts
    const counts = {
      all: vehicles.length,
      charging: 0,
      moving: 0,
      stopped: 0,
      lowsoc: 0
    };

    vehicles.forEach(vehicle => {
      const latest = vehicle.points[0];
      const { state } = getVehicleState(latest);
      if (state === 'Charging') {
        counts.charging++;
      } else if (state === 'Moving') {
        counts.moving++;
      } else if (state === 'Stopped') {
        counts.stopped++;
      }

      const soc = latest.soc ?? 0;
      if (soc < 30) {
        counts.lowsoc++;
      }
    });

    // Update UI for counts
    updateElement('countAll', counts.all);
    updateElement('countCharging', counts.charging);
    updateElement('countMoving', counts.moving);
    updateElement('countStopped', counts.stopped);
    updateElement('countLowSoc', counts.lowsoc);

    // (map chips and bottom strip removed)

    // Show/hide Low SOC filter button based on count
    const lowSocBtn = document.getElementById('filterLowSoc');
    if (lowSocBtn) {
      lowSocBtn.classList.toggle('hidden', counts.lowsoc === 0);
    }


    if (vehicles.length === 0) {
        if(messageEl) messageEl.textContent = 'No vehicles with live data found.';
        vehicleListEl.innerHTML = '';
        if(mobileVehicleListEl) mobileVehicleListEl.innerHTML = '';
        return;
    }

    if(messageEl) messageEl.textContent = '';
    const vehicleHTML = vehicles.map(createVehicleCard).join('');

    vehicleListEl.innerHTML = vehicleHTML;

    // Sync mobile vehicle list
    if (mobileVehicleListEl) {
      mobileVehicleListEl.innerHTML = vehicleHTML;
    }

    if (typeof lucide !== 'undefined') lucide.createIcons();
  }  // Helper: Determine vehicle state
  function getVehicleState(latest) {
    const speed = latest.gps_speed ?? latest.speed ?? 0;
    const vehicleStatus = (latest.vehicle_status || '').toLowerCase();
    const isCharging = vehicleStatus.includes('charging') ||
      (speed < 1 && latest.battery_voltage > 300);

    if (isCharging) {
      return {
        state: 'Charging',
        class: 'bg-green-100 text-green-700 border-green-300',
        icon: 'plug-zap'
      };
    }

    if (speed > 1) {
      return {
        state: 'Moving',
        class: 'bg-blue-100 text-blue-700 border-blue-300',
        icon: 'truck'
      };
    }

    return {
      state: 'Stopped',
      class: 'bg-red-50 text-red-700 border-red-200',
      icon: 'octagon'
    };
  }

  // Helper: Generate metrics HTML based on state
  function getStateMetrics(state, speed, soc) {
    const metrics = {
      Charging: {
        primary: { icon: 'zap', color: 'text-green-700', text: 'Charging' },
        secondary: { icon: 'battery-charging', color: 'text-green-600', text: `${soc}%` }
      },
      Moving: {
        primary: { icon: 'gauge', color: 'text-blue-700', text: `${speed} km/h` },
        secondary: { icon: 'battery', color: 'text-yellow-600', text: `${soc}%` }
      },
      Stopped: {
        primary: { icon: 'octagon', color: 'text-red-700', text: 'Stopped' },
        secondary: { icon: 'battery', color: 'text-slate-500', text: `${soc}%` }
      }
    };

    const { primary, secondary } = metrics[state];
    return {
      primary: `
        <div class="flex items-center gap-1.5 ${primary.color}">
          <i data-lucide="${primary.icon}" class="w-3.5 h-3.5"></i>
          <span class="font-semibold">${primary.text}</span>
        </div>`,
      secondary: `
        <div class="flex items-center gap-1.5 text-slate-600">
          <i data-lucide="${secondary.icon}" class="w-3.5 h-3.5 ${secondary.color}"></i>
          <span class="font-medium">${secondary.text}</span>
        </div>`
    };
  }

  // Helper: Create vehicle card HTML
  function createVehicleCard(vehicle) {
    const latest = vehicle.points[0];
    const speed = latest.gps_speed ?? latest.speed ?? 0;
    const soc = latest.soc ?? 0;
    const { state, class: stateClass, icon: stateIcon } = getVehicleState(latest);
    const { primary, secondary } = getStateMetrics(state, speed, soc);
    const lastUpdate = formatTimeAgo(latest.last_connected || latest.gps_time);
    
    // Map trolley to truck number for display
    const displayNumber = getDisplayVehicleNumber(vehicle.registration_number);

    const driverName = latest.driver_name || latest.driver || '';
    const socBarColor = soc >= 60 ? '#22c55e' : soc >= 30 ? '#f59e0b' : '#ef4444';
    // Status pill colors — work on both light and dark backgrounds
    const stateColors = {
      Moving:  { pill:'rgba(34,197,94,0.12)',  text:'#16a34a', border:'rgba(34,197,94,0.3)',  textDark:'#4ade80' },
      Stopped: { pill:'rgba(239,68,68,0.1)',   text:'#dc2626', border:'rgba(239,68,68,0.3)',  textDark:'#f87171' },
      Charging:{ pill:'rgba(59,130,246,0.1)',  text:'#2563eb', border:'rgba(59,130,246,0.3)', textDark:'#60a5fa' },
    };
    const sc = stateColors[state] || stateColors.Stopped;
    const isDark = document.body.classList.contains('dark-theme');
    const pillText = isDark ? sc.textDark : sc.text;

    return `
      <div class="vehicle-card lv-card cursor-pointer rounded-lg"
           data-vehicle="${vehicle.registration_number}"
           data-soc="${soc}"
           data-status="${state}"
           style="border-left:3px solid ${pillText};padding:10px 12px;border-radius:8px;"
           onclick="showQuickAnalyticsFromList('${vehicle.registration_number}', ${JSON.stringify(latest).replace(/"/g, '&quot;')})">

        <!-- Top row: vehicle ID + status pill -->
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:7px;">
          <div>
            <div class="lv-vehicle-id" style="font-size:12px;font-weight:700;line-height:1;">${displayNumber}</div>
            ${driverName ? `<div class="lv-driver-name" style="font-size:10px;margin-top:2px;letter-spacing:0.01em;">${driverName}</div>` : ''}
          </div>
          <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;">
            <span style="font-size:9px;font-weight:700;padding:2px 8px;border-radius:20px;background:${sc.pill};color:${pillText};border:1px solid ${sc.border};letter-spacing:0.04em;">${state}</span>
            <span class="lv-timestamp" style="font-size:9px;letter-spacing:0.01em;">${lastUpdate}</span>
          </div>
        </div>

        <!-- Metrics row -->
        <div class="lv-metric-text" style="display:flex;gap:12px;margin-bottom:8px;font-size:11px;">
          ${primary}
        </div>

        <!-- SOC bar with gradient fill -->
        <div style="display:flex;align-items:center;gap:7px;">
          <div class="lv-soc-track" style="flex:1;height:4px;border-radius:9999px;overflow:hidden;">
            <div style="width:${soc}%;height:100%;background:linear-gradient(90deg,${socBarColor}cc,${socBarColor});border-radius:9999px;transition:width 0.5s ease;"></div>
          </div>
          <span style="font-size:9px;font-weight:700;color:${socBarColor};min-width:26px;text-align:right;">${soc}%</span>
        </div>
      </div>
    `;
  }

  // =======================
  // TIME FORMATTING UTILITIES
  // =======================
  function formatTimeAgo(timeString) {
    if (!timeString) return 'N/A';
    try {
      let dateObj = null;
      
      // Handle numeric timestamps
      if (typeof timeString === 'number') {
        // If < year 2100 in seconds (10-digit), treat as Unix seconds; otherwise milliseconds
        dateObj = timeString < 4102444800 ? new Date(timeString * 1000) : new Date(timeString);
      } else if (typeof timeString === 'string') {
        // Pure digit string = Unix timestamp in seconds
        if (/^\d{9,11}$/.test(timeString.trim())) {
          dateObj = new Date(parseInt(timeString) * 1000);
        } else {
          dateObj = new Date(timeString);
        }
      }
      
      // Validate parsed date
      if (!dateObj || isNaN(dateObj.getTime())) {
        return 'N/A';
      }
      
      const diffMs = new Date() - dateObj;
      const diffMins = Math.floor(diffMs / 60000);

      if (diffMins < 1) return 'Just now';
      if (diffMins < 60) return `${diffMins}m ago`;

      const diffHours = Math.floor(diffMins / 60);
      if (diffHours < 24) return `${diffHours}h ago`;

      return `${Math.floor(diffHours / 24)}d ago`;
    } catch {
      return 'N/A';
    }
  }

  // Format timestamp to IST (for quickLastUpdate display)
  function formatTimestampToIST(timeString) {
    if (!timeString) return 'N/A';
    try {
      let dateObj = null;
      
      // Handle numeric timestamps (milliseconds or seconds)
      if (typeof timeString === 'number') {
        // If timestamp is less than year 2100 in seconds, convert to milliseconds
        dateObj = timeString < 4102444800 ? new Date(timeString * 1000) : new Date(timeString);
      } else if (typeof timeString === 'string') {
        // Try parsing as ISO string or standard format
        dateObj = new Date(timeString);
      }
      
      // Validate parsed date
      if (!dateObj || isNaN(dateObj.getTime())) {
        return 'N/A';
      }
      
      // Format to IST (en-IN locale)
      return dateObj.toLocaleString('en-IN', {
        month: 'short', 
        day: 'numeric', 
        hour: '2-digit', 
        minute: '2-digit',
        second: '2-digit'
      });
    } catch {
      return 'N/A';
    }
  }

  // =======================
  // VEHICLE NAVIGATION HANDLERS
  // =======================
  window.showQuickAnalyticsFromList = function (registrationNumber, latestPointData) {
    showQuickAnalytics(registrationNumber, latestPointData);
  };

  // =======================
  // DRIVER INFO FETCHING - BULK OPTIMIZED
  // =======================
  const driverInfoCache = new Map(); // In-memory cache for driver info
  let driversLoaded = false; // Track if bulk fetch completed
  
  /**
   * Bulk fetch all driver info in one API call (fast and efficient)
   * Called once after vehicles load to populate cache
   */
  async function fetchAllDriverInfo(registrationNumbers) {
    if (!registrationNumbers || registrationNumbers.length === 0) {
      console.warn('⚠️ No vehicles to fetch driver info for');
      return;
    }
    
    console.log(`🚀 Fetching driver info for ${registrationNumbers.length} vehicles...`);
    
    try {
      const response = await fetch('/livetracker/api/drivers/bulk/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({ registration_numbers: registrationNumbers })
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      
      const driversData = await response.json();
      
      // Populate cache with all driver info
      for (const [regNum, driverInfo] of Object.entries(driversData)) {
        driverInfoCache.set(regNum, driverInfo);
      }
      
      driversLoaded = true;
      console.log(`✅ Loaded driver info for ${Object.keys(driversData).length} vehicles`);
      
    } catch (error) {
      console.error('❌ Error fetching bulk driver info:', error);
      // Don't fail the whole page, just mark as loaded
      driversLoaded = true;
    }
  }
  
  /**
   * Get driver info from cache (instant, no API call)
   * Call this after fetchAllDriverInfo() completes
   */
  function getDriverInfo(registrationNumber) {
    const cached = driverInfoCache.get(registrationNumber);
    if (cached) {
      return cached;
    }
    
    // Default fallback if not found
    return {
      driver_name: 'Not Assigned',
      driver_phone: 'N/A',
      has_driver: false
    };
  }

  // Update driver button based on assignment status
  function updateDriverButton(registrationNumber) {
    const editDriverBtn = document.getElementById('editDriverBtn');
    const editDriverBtnText = document.getElementById('editDriverBtnText');
    const driverNameEl = document.getElementById('quickDriverName');
    
    if (!editDriverBtn || !editDriverBtnText || !driverNameEl) return;
    
    const driverName = driverNameEl.textContent;
    const hasDriver = driverName && !['Loading...', 'Not Assigned', 'N/A', 'Error', 'Timeout'].includes(driverName);
    
    if (hasDriver) {
      editDriverBtnText.textContent = 'Edit';
      editDriverBtn.title = 'Edit driver assignment';
    } else {
      editDriverBtnText.textContent = 'Add';
      editDriverBtn.title = 'Add driver assignment';
    }
    
    editDriverBtn.classList.remove('hidden');
    editDriverBtn.onclick = () => openDriverAssignmentModal(registrationNumber, hasDriver);
  }

  // =======================
  // QUICK ANALYTICS PANEL
  // =======================
  function showQuickAnalytics(registrationNumber, latestPoint) {
    const quickAnalytics = document.getElementById('quickAnalytics');
    const selectedVehicleName = document.getElementById('selectedVehicleName');

    if (!quickAnalytics || !selectedVehicleName) {
      console.error('❌ Quick analytics panel elements not found');
      return;
    }
    
    // Map trolley to truck number for display
    const displayNumber = getDisplayVehicleNumber(registrationNumber);

    // Highlight the selected vehicle card
    document.querySelectorAll('.vehicle-card').forEach(card => {
      card.classList.remove('ring-2', 'ring-blue-500', 'border-blue-500', 'bg-blue-50');
    });
    const selectedCard = document.querySelector(`.vehicle-card[data-vehicle="${registrationNumber}"]`);
    if (selectedCard) {
      selectedCard.classList.add('ring-2', 'ring-blue-500', 'border-blue-500', 'bg-blue-50');
    }

    // Pan/zoom map to selected vehicle — avoid a big zoom jump that forces tile reload
    const marker = markers[registrationNumber];
    if (marker) {
      const latLng = marker.getLatLng();
      const currentZoom = map.getZoom();
      // Keep existing zoom if already reasonably close, otherwise go to 13
      const targetZoom = currentZoom >= 12 ? currentZoom : 13;
      map.flyTo(latLng, targetZoom, { animate: true, duration: 0.45, easeLinearity: 0.5, noMoveStart: true });

      // Open marker popup briefly after pan settles
      setTimeout(() => {
        marker.openPopup();
        setTimeout(() => marker.closePopup(), 2000);
      }, 600);
    }

    selectedVehicleName.textContent = displayNumber;  // Use display number

    // Calculate distance covered today
    const startOdo = latestPoint.start_odometer ?? 0;
    const endOdo = latestPoint.end_odometer ?? latestPoint.odometer ?? 0;
    const distanceCovered = endOdo - startOdo;

    // Format last update time - try gps_time first, then last_connected
    let lastUpdate = 'N/A';
    const timeToFormat = latestPoint.gps_time || latestPoint.last_connected;
    if (timeToFormat) {
      lastUpdate = formatTimestampToIST(timeToFormat);
    }

    // Parse coordinates - try multiple sources
    let lat = 'N/A';
    let lng = 'N/A';
    let latNum = null;
    let lngNum = null;
    
    // Priority 1: Try latitude/longitude from API
    if (latestPoint.latitude && latestPoint.longitude) {
      latNum = parseFloat(latestPoint.latitude);
      lngNum = parseFloat(latestPoint.longitude);
      if (!isNaN(latNum) && !isNaN(lngNum)) {
        lat = latNum.toFixed(5);
        lng = lngNum.toFixed(5);
      }
    }
    
    // Priority 2: Try lat/lng properties
    if (lat === 'N/A' && latestPoint.lat && latestPoint.lng) {
      latNum = parseFloat(latestPoint.lat);
      lngNum = parseFloat(latestPoint.lng);
      if (!isNaN(latNum) && !isNaN(lngNum)) {
        lat = latNum.toFixed(5);
        lng = lngNum.toFixed(5);
      }
    }
    
    // Priority 3: Parse from gps_location string
    if (lat === 'N/A' && latestPoint.gps_location && typeof latestPoint.gps_location === 'string') {
      const parts = latestPoint.gps_location.split(',').map(s => s.trim());
      if (parts.length >= 2) {
        latNum = parseFloat(parts[0]);
        lngNum = parseFloat(parts[1]);
        if (!isNaN(latNum) && !isNaN(lngNum)) {
          lat = latNum.toFixed(5);
          lng = lngNum.toFixed(5);
        }
      }
    }

    // console.log(`📍 Quick Analytics coordinates for ${registrationNumber}: lat=${lat}, lng=${lng}`);

    // Display driver information from cache (instant, no API call)
    const driverInfo = getDriverInfo(registrationNumber);
    updateElement('quickDriverName', driverInfo.driver_name);
    updateElement('quickDriverPhone', driverInfo.driver_phone);
    updateDriverButton(registrationNumber);

    // Normalize status for display
    let displayStatus = latestPoint.vehicle_status || 'Unknown';
    if (typeof displayStatus === 'string' && ['stop', 'stopped'].includes(displayStatus.trim().toLowerCase())) {
      displayStatus = 'Stopped';
    }
    updateElement('quickStatus', displayStatus);
    updateElement('quickBatteryTemp', latestPoint.battery_temp !== undefined ? `${latestPoint.battery_temp}°C` : 'N/A');
    updateElement('quickCurrentOdo', endOdo > 0 ? `${endOdo.toFixed(2)} km` : 'N/A');
    updateElement('quickDistanceCovered', distanceCovered > 0 ? `${distanceCovered.toFixed(2)} km` : '0 km');
    updateElement('quickLatitude', lat);
    updateElement('quickLongitude', lng);
    updateElement('quickLastUpdate', lastUpdate);

    // Fetch reverse geocoded address
    const addressEl = document.getElementById('quickAddress');
    if (lat !== 'N/A' && lng !== 'N/A' && latNum !== null && lngNum !== null) {
      addressEl.textContent = 'Loading address...';
      // console.log(`🌍 Fetching address for: ${latNum}, ${lngNum}`);
      
      fetchReverseGeocode(latNum, lngNum)
        .then(address => {
          if (address) {
            // console.log(`✅ Address found: ${address}`);
            addressEl.textContent = address;
          } else {
            console.warn('⚠️ No address returned from geocoding API');
            addressEl.textContent = 'Address unavailable';
          }
        })
        .catch((error) => {
          console.error('❌ Geocoding error:', error);
          addressEl.textContent = 'Address unavailable';
        });
    } else {
      console.warn('⚠️ Invalid coordinates, cannot fetch address');
      addressEl.textContent = 'Location unavailable';
    }

    // Show panel with slide-in animation
    quickAnalytics.classList.remove('hidden');
    
    // Trigger animation on next frame
    requestAnimationFrame(() => {
      quickAnalytics.classList.remove('-translate-x-full', 'opacity-0');
      quickAnalytics.classList.add('translate-x-0', 'opacity-100');
    });

    if (typeof lucide !== 'undefined') lucide.createIcons();

    setupAnalyticsHandlers(registrationNumber);
  }

  function setupAnalyticsHandlers(registrationNumber) {
    const closeHandler = () => {
      const quickAnalytics = document.getElementById('quickAnalytics');
      
      // Slide out animation
      quickAnalytics.classList.remove('translate-x-0', 'opacity-100');
      quickAnalytics.classList.add('-translate-x-full', 'opacity-0');
      
      // Hide after animation completes
      setTimeout(() => {
        quickAnalytics.classList.add('hidden');
      }, 300); // Match transition duration
      
      // Remove highlight when closing
      document.querySelectorAll('.vehicle-card').forEach(card => {
        card.classList.remove('ring-2', 'ring-blue-500', 'border-blue-500', 'bg-blue-50');
      });
    };

    // Copy coordinates handler
    const copyCoordinatesBtn = document.getElementById('copyCoordinates');
    if (copyCoordinatesBtn) {
      copyCoordinatesBtn.onclick = () => {
        const lat = document.getElementById('quickLatitude').textContent;
        const lng = document.getElementById('quickLongitude').textContent;

        if (lat && lng && lat !== '--' && lng !== '--') {
          const coordinates = `${lat}, ${lng}`;
          navigator.clipboard.writeText(coordinates).then(() => {
            // Visual feedback
            const icon = copyCoordinatesBtn.querySelector('i');
            const originalIcon = icon.getAttribute('data-lucide');
            icon.setAttribute('data-lucide', 'check');
            copyCoordinatesBtn.classList.add('text-green-600', 'bg-green-50');
            if (typeof lucide !== 'undefined') lucide.createIcons();

            setTimeout(() => {
              icon.setAttribute('data-lucide', originalIcon);
              copyCoordinatesBtn.classList.remove('text-green-600', 'bg-green-50');
              if (typeof lucide !== 'undefined') lucide.createIcons();
            }, 2000);
          }).catch(err => {
            console.error('Failed to copy coordinates:', err);
          });
        }
      };
    }

    // Open satellite view handler
    const openSatelliteBtn = document.getElementById('openSatelliteView');
    if (openSatelliteBtn) {
      openSatelliteBtn.onclick = () => {
        const lat = document.getElementById('quickLatitude').textContent;
        const lng = document.getElementById('quickLongitude').textContent;

        if (lat && lng && lat !== '--' && lng !== '--') {
          // Google Maps satellite view URL with zoom level 18
          const googleMapsUrl = `https://www.google.com/maps/@${lat},${lng},18z/data=!3m1!1e3`;
          window.open(googleMapsUrl, '_blank');
        }
      };
    }

    const handlers = {
      closeQuickAnalytics: closeHandler,
      viewFullAnalytics: () => window.open(`/livetracker/${encodeURIComponent(registrationNumber)}/`, '_blank'),
      viewHistoricalData: () => openHistoricalDatePicker(registrationNumber)
    };

    Object.entries(handlers).forEach(([id, handler]) => {
      const btn = document.getElementById(id);
      if (btn) btn.onclick = handler;
    });
  }

  // =======================
  // HISTORICAL DATE PICKER
  // =======================
  function openHistoricalDatePicker(registrationNumber) {
    const modal = document.getElementById('historicalDatePickerModal');
    const dateInput = document.getElementById('historicalDateInput');
    const loadBtn = document.getElementById('loadHistoricalData');
    const cancelBtn = document.getElementById('cancelHistoricalDatePicker');
    const closeBtn = document.getElementById('closeHistoricalDatePicker');

    if (!modal || !dateInput) {
      console.error('❌ Historical date picker elements not found');
      return;
    }

    // console.log('📅 Opening historical date picker for:', registrationNumber);

    // Set max date to today
    const today = new Date().toISOString().split('T')[0];
    dateInput.setAttribute('max', today);
    
    // Set default to yesterday
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    dateInput.value = yesterday.toISOString().split('T')[0];

    // Show modal
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    if (typeof lucide !== 'undefined') lucide.createIcons();

    // Load button handler
    loadBtn.onclick = () => {
      const selectedDate = dateInput.value;
      if (selectedDate) {
        // console.log(`Loading historical data for ${registrationNumber} on ${selectedDate}`);
        window.open(`/livetracker/vehicle/${encodeURIComponent(registrationNumber)}/history/${selectedDate}/`, '_blank');
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      } else {
        alert('Please select a date');
      }
    };

    // Cancel button handler
    const closeModal = () => {
      modal.classList.add('hidden');
      modal.classList.remove('flex');
    };

    cancelBtn.onclick = closeModal;
    closeBtn.onclick = closeModal;

    // Close on backdrop click
    modal.onclick = (e) => {
      if (e.target === modal) {
        closeModal();
      }
    };
  }

  function updateElement(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  // =======================
  // REFRESH BUTTON & AUTO-REFRESH
  // =======================
  
  // Manual refresh button with visual feedback
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      // console.log('🔄 Manual refresh triggered by user');
      
      // Visual feedback: spin the icon
      const icon = refreshBtn.querySelector('i[data-lucide="refresh-cw"]');
      if (icon) {
        icon.style.animation = 'spin 0.5s linear';
        setTimeout(() => {
          icon.style.animation = '';
        }, 500);
      }
      
      loadAll();
      resetAutoRefreshTimer(); // Reset the 2-minute timer
    });
  }

  // Auto-refresh every 2 minutes (120000ms)
  let autoRefreshInterval = null;
  let lastRefreshTime = Date.now();
  
  function startAutoRefresh() {
    // Clear any existing interval
    if (autoRefreshInterval) {
      clearInterval(autoRefreshInterval);
    }
    
    // Set up new interval for 2 minutes
    autoRefreshInterval = setInterval(() => {
      // console.log('🔄 Auto-refresh: Updating vehicle data (2-minute interval)');
      lastRefreshTime = Date.now();
      loadAll(true); // Silent refresh - no loading overlay
    }, 120000); // 2 minutes = 120000ms
    
    // console.log('✅ Auto-refresh enabled: Updates every 2 minutes');
  }
  
  function resetAutoRefreshTimer() {
    // Reset the timer when manual refresh is triggered
    lastRefreshTime = Date.now();
    startAutoRefresh();
    // console.log('🔄 Auto-refresh timer reset');
  }

  // Stop auto-refresh (useful for cleanup)
  function stopAutoRefresh() {
    if (autoRefreshInterval) {
      clearInterval(autoRefreshInterval);
      autoRefreshInterval = null;
      // console.log('⏸️ Auto-refresh stopped');
    }
  }

  // =======================
  // DRIVER ASSIGNMENT MODAL
  // =======================
  let availableDrivers = [];
  let currentAssignmentVehicle = null;
  
  async function loadAvailableDrivers() {
    try {
      const response = await fetch('/roster/api/drivers/');
      const data = await response.json();
      
      if (data.success && Array.isArray(data.drivers)) {
        availableDrivers = data.drivers;
        return availableDrivers;
      } else {
        console.error('Invalid driver data received');
        return [];
      }
    } catch (error) {
      console.error('Error loading drivers:', error);
      return [];
    }
  }
  
  function populateDriverSelect(drivers) {
    const select = document.getElementById('driverSelect');
    if (!select) return;
    
    select.innerHTML = '<option value="">-- Select a driver --</option>';
    
    drivers.forEach(driver => {
      const option = document.createElement('option');
      option.value = driver.employee_code;
      option.textContent = `${driver.employee_name} (${driver.employee_code})`;
      option.dataset.phone = driver.phone || 'N/A';
      option.dataset.active = driver.is_active;
      
      if (!driver.is_active) {
        option.textContent += ' - Inactive';
        option.disabled = true;
      }
      
      select.appendChild(option);
    });
  }
  
  async function openDriverAssignmentModal(vehicleNumber, hasExistingDriver) {
    const modal = document.getElementById('driverAssignmentModal');
    const modalTitle = document.getElementById('driverModalTitle');
    const assignmentVehicleNumber = document.getElementById('assignmentVehicleNumber');
    const displayVehicleNumber = document.getElementById('displayVehicleNumber');
    const driverSelect = document.getElementById('driverSelect');
    const errorMessage = document.getElementById('modalErrorMessage');
    
    if (!modal) return;
    
    currentAssignmentVehicle = vehicleNumber;
    
    // Update modal title
    modalTitle.textContent = hasExistingDriver ? 'Edit Driver Assignment' : 'Assign Driver';
    
    // Set vehicle number
    assignmentVehicleNumber.value = vehicleNumber;
    displayVehicleNumber.value = getDisplayVehicleNumber(vehicleNumber);
    
    // Hide error message
    errorMessage.classList.add('hidden');
    
    // Load drivers if not already loaded
    if (availableDrivers.length === 0) {
      driverSelect.innerHTML = '<option value="">Loading drivers...</option>';
      availableDrivers = await loadAvailableDrivers();
    }
    
    populateDriverSelect(availableDrivers);
    
    // Show modal
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    lucide.createIcons();
  }
  
  function closeDriverAssignmentModal() {
    const modal = document.getElementById('driverAssignmentModal');
    const driverDetailsPreview = document.getElementById('driverDetailsPreview');
    const errorMessage = document.getElementById('modalErrorMessage');
    const driverSelect = document.getElementById('driverSelect');
    
    if (modal) {
      modal.classList.add('hidden');
      modal.classList.remove('flex');
    }
    
    if (driverDetailsPreview) {
      driverDetailsPreview.classList.add('hidden');
    }
    
    if (errorMessage) {
      errorMessage.classList.add('hidden');
    }
    
    if (driverSelect) {
      driverSelect.value = '';
    }
    
    currentAssignmentVehicle = null;
  }
  
  function showDriverPreview() {
    const driverSelect = document.getElementById('driverSelect');
    const preview = document.getElementById('driverDetailsPreview');
    const codeEl = document.getElementById('previewDriverCode');
    const phoneEl = document.getElementById('previewDriverPhone');
    const statusEl = document.getElementById('previewDriverStatus');
    
    if (!driverSelect || !preview) return;
    
    const selectedOption = driverSelect.options[driverSelect.selectedIndex];
    
    if (!selectedOption || !selectedOption.value) {
      preview.classList.add('hidden');
      return;
    }
    
    codeEl.textContent = selectedOption.value;
    phoneEl.textContent = selectedOption.dataset.phone || 'N/A';
    
    const isActive = selectedOption.dataset.active === 'true';
    statusEl.textContent = isActive ? 'Active' : 'Inactive';
    statusEl.className = isActive ? 'font-semibold text-green-700' : 'font-semibold text-red-700';
    
    preview.classList.remove('hidden');
    lucide.createIcons();
  }
  
  async function saveDriverAssignment() {
    const vehicleNumber = document.getElementById('assignmentVehicleNumber').value;
    const driverCode = document.getElementById('driverSelect').value;
    const errorMessage = document.getElementById('modalErrorMessage');
    const errorText = document.getElementById('modalErrorText');
    const saveBtn = document.getElementById('saveDriverAssignment');
    
    if (!driverCode) {
      errorText.textContent = 'Please select a driver';
      errorMessage.classList.remove('hidden');
      lucide.createIcons();
      return;
    }
    
    // Disable button and show loading
    const originalHTML = saveBtn.innerHTML;
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>Saving...</span>';
    lucide.createIcons();
    
    try {
      const response = await fetch('/roster/api/assign-driver/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({
          horse_number: vehicleNumber,
          driver_code: driverCode
        })
      });
      
      const data = await response.json();
      
      if (data.success) {
        // Clear cache for this vehicle
        driverInfoCache.delete(vehicleNumber);
        
        // Get driver details from selection
        const driverSelect = document.getElementById('driverSelect');
        const selectedOption = driverSelect.options[driverSelect.selectedIndex];
        const driverName = selectedOption.text.split(' (')[0]; // Extract name before employee code
        const driverPhone = selectedOption.dataset.phone || 'N/A';
        
        // Close modal first
        closeDriverAssignmentModal();
        
        // Immediately update Quick Analytics panel if it's visible
        const quickAnalytics = document.getElementById('quickAnalytics');
        const isQuickAnalyticsOpen = quickAnalytics && !quickAnalytics.classList.contains('hidden');
        
        if (isQuickAnalyticsOpen) {
          const driverNameEl = document.getElementById('quickDriverName');
          const driverPhoneEl = document.getElementById('quickDriverPhone');
          
          // Immediate visual update with animation
          if (driverNameEl) {
            driverNameEl.style.transition = 'all 0.3s ease';
            driverNameEl.style.transform = 'scale(1.1)';
            driverNameEl.style.color = '#16a34a'; // green
            driverNameEl.textContent = driverName;
            
            setTimeout(() => {
              driverNameEl.style.transform = 'scale(1)';
              driverNameEl.style.color = '';
            }, 300);
          }
          
          if (driverPhoneEl) {
            driverPhoneEl.style.transition = 'all 0.3s ease';
            driverPhoneEl.style.transform = 'scale(1.1)';
            driverPhoneEl.style.color = '#16a34a'; // green
            driverPhoneEl.textContent = driverPhone;
            
            setTimeout(() => {
              driverPhoneEl.style.transform = 'scale(1)';
              driverPhoneEl.style.color = '';
            }, 300);
          }
          
          // Update cache with new data
          driverInfoCache.set(vehicleNumber, {
            driver_name: driverName,
            driver_phone: driverPhone,
            timestamp: Date.now(),
            hasDriver: true
          });
          
          // Update button text from "Add" to "Edit"
          updateDriverButton(vehicleNumber);
        }
        
        // Show success notification with better UX
        showSuccessNotification(`Driver ${driverName} assigned successfully!`);
        
      } else {
        errorText.textContent = data.message || 'Failed to update assignment';
        errorMessage.classList.remove('hidden');
        lucide.createIcons();
      }
    } catch (error) {
      console.error('Error saving driver assignment:', error);
      errorText.textContent = 'An error occurred. Please try again.';
      errorMessage.classList.remove('hidden');
      lucide.createIcons();
    } finally {
      saveBtn.disabled = false;
      saveBtn.innerHTML = originalHTML;
      lucide.createIcons();
    }
  }
  
  // Helper function to get CSRF token
  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }
  
  // Success notification function
  function showSuccessNotification(message) {
    // Remove any existing notifications
    const existingNotif = document.getElementById('successNotification');
    if (existingNotif) existingNotif.remove();
    
    // Create notification element
    const notification = document.createElement('div');
    notification.id = 'successNotification';
    notification.className = 'fixed top-20 right-4 bg-green-500 text-white px-6 py-3 rounded-lg shadow-lg z-[9999] flex items-center gap-3 animate-slide-in-right';
    notification.innerHTML = `
      <i data-lucide="check-circle" class="w-5 h-5"></i>
      <span class="font-medium">${message}</span>
    `;
    
    document.body.appendChild(notification);
    
    // Initialize lucide icons
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    // Auto-remove after 3 seconds
    setTimeout(() => {
      notification.style.transition = 'all 0.3s ease-out';
      notification.style.opacity = '0';
      notification.style.transform = 'translateX(100%)';
      setTimeout(() => notification.remove(), 300);
    }, 3000);
  }
  
  // Set up modal event listeners
  const closeDriverModalBtn = document.getElementById('closeDriverModal');
  const cancelDriverAssignmentBtn = document.getElementById('cancelDriverAssignment');
  const saveDriverAssignmentBtn = document.getElementById('saveDriverAssignment');
  const driverSelectEl = document.getElementById('driverSelect');
  
  if (closeDriverModalBtn) {
    closeDriverModalBtn.addEventListener('click', closeDriverAssignmentModal);
  }
  
  if (cancelDriverAssignmentBtn) {
    cancelDriverAssignmentBtn.addEventListener('click', closeDriverAssignmentModal);
  }
  
  if (saveDriverAssignmentBtn) {
    saveDriverAssignmentBtn.addEventListener('click', saveDriverAssignment);
  }
  
  if (driverSelectEl) {
    driverSelectEl.addEventListener('change', showDriverPreview);
  }

  // =======================
  // ADD NOTIFICATION ANIMATION STYLES
  // =======================
  const notificationStyles = document.createElement('style');
  notificationStyles.textContent = `
    @keyframes slide-in-right {
      from {
        transform: translateX(100%);
        opacity: 0;
      }
      to {
        transform: translateX(0);
        opacity: 1;
      }
    }
    
    .animate-slide-in-right {
      animation: slide-in-right 0.3s ease-out;
    }
  `;
  document.head.appendChild(notificationStyles);

  // =======================
  // INITIAL LOAD & EXPORTS
  // =======================
  loadAll();
  startAutoRefresh(); // Start automatic updates
  
  window.LiveMap = { 
    map, 
    loadAll, 
    markers, 
    polylines,
    startAutoRefresh,
    stopAutoRefresh
  };
  
  // Export loading function for other modules
  window.showSpinner = toggleLoading;
} else if (isVehiclePage) {
  // console.log('🚗 Vehicle page detected - skipping main map initialization (vehicle_playback.js will handle it)');
}

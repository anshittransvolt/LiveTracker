// ===================================================
// 🧭 geofence.js
// Utility to render always-visible geofence markers
// Using image icons for maximum visibility at all zoom levels
// ===================================================

export function addGeofences(map) {
  // console.log("Adding charging zone geofences with persistent markers...");

  // Create persistent icon markers for all geofences using local images
  const chargingIcon = L.icon({
    iconUrl: '/static/livetracker/images/charger1.png',
    iconSize: [36, 36],
    iconAnchor: [18, 18],
    popupAnchor: [0, -18],
    className: 'geofence-charging-icon'
  });

  const unloadingIcon = L.icon({
    iconUrl: '/static/livetracker/images/unloading.png',
    iconSize: [36, 36],
    iconAnchor: [18, 18],
    popupAnchor: [0, -18],
    className: 'geofence-unloading-icon'
  });

  const borderIcon = L.icon({
    iconUrl: '/static/livetracker/images/border.png',
    iconSize: [40, 40],
    iconAnchor: [20, 20],
    popupAnchor: [0, -20],
    className: 'geofence-border-icon'
  });

  const generalIcon = L.icon({
    iconUrl: 'https://cdn-icons-png.flaticon.com/512/2776/2776067.png',
    iconSize: [32, 32],
    iconAnchor: [16, 16],
    popupAnchor: [0, -16],
    className: 'geofence-general-icon'
  });

  // Store all markers for zoom-based visibility control
  const geofenceMarkers = [];
  const MIN_ZOOM_FOR_MARKERS = 10; // Show markers only when zoomed to level 10 or higher

  // --- Circle geofences with enhanced visibility ---
  const circleGeofences = [
    ["Dhule Gate", 21.156063, 74.853409, 50, "border"],
    ["Dhule Unloading area", 21.15111842, 74.84979354, 100, "unloading"],
    ["Maha Border", 21.427817, 74.980463, 500, "border"],
    ["D1 Jhulwania (20 m)", 21.871537, 75.215380, 50, "general"],
    ["D2 Jhulwania (20 m)", 21.870432, 75.213483, 50, "general"],
    ["Manawar Out Area", 22.262448, 75.128085, 50, "general"],
    ["Manawar Tarpulien", 22.271049, 75.133974, 30, "general"],
    ["Manawar Charging Point", 22.265636, 75.127046, 100, "charging"],
    ["Manawar Weighing Area", 22.269420, 75.133556, 50, "general"],
    ["Dharampuri", 22.152785, 75.341519, 150, "general"],
    ["Dabhashi", 21.265904, 74.847418, 150, "general"]
  ];

  circleGeofences.forEach(([name, lat, lon, radius, type]) => {
    // console.log(`📍 Circle Geofence: ${name} → (${lat}, ${lon}), Radius: ${radius}m`);

    // Use green color for all geofence types
    const color = "#10b981"; // green for all geofences
    const fillColor = "#10b981"; // green fill for all geofences

    // Create circle geofence
    const circle = L.circle([lat, lon], {
      color: color,
      fillColor: fillColor,
      fillOpacity: 0.15,
      radius: radius,
      weight: 3,
      interactive: true,
      className: 'geofence-circle'
    }).addTo(map);

    // Create visible marker with appropriate icon
    let icon;
    switch(type) {
      case "charging":
        icon = chargingIcon;
        break;
      case "unloading":
        icon = unloadingIcon;
        break;
      case "border":
        icon = borderIcon;
        break;
      default:
        icon = generalIcon;
    }

    const marker = L.marker([lat, lon], { 
      icon: icon,
      zIndexOffset: 1000, // Ensure markers appear above other elements
      riseOnHover: true
    });

    // Don't add marker to map yet - will be controlled by zoom level
    geofenceMarkers.push(marker);

    // Make sure marker is always visible by setting permanent visibility
    marker.options.bubblingMouseEvents = false;
    
    // console.log(`✅ Added persistent marker for ${name} at zoom-independent visibility`);

    // Enhanced popup with more information
    const popupContent = `
      <div class="geofence-popup">
        <h4 class="font-bold text-lg mb-2">${name}</h4>
        <div class="space-y-1 text-sm">
          <div><strong>Type:</strong> ${type.charAt(0).toUpperCase() + type.slice(1)}</div>
          <div><strong>Radius:</strong> ${radius} m</div>
          <div><strong>Coordinates:</strong> ${lat.toFixed(6)}, ${lon.toFixed(6)}</div>
          <div><strong>Area:</strong> ${(Math.PI * radius * radius / 10000).toFixed(2)} hectares</div>
        </div>
      </div>
    `;

    // Bind popup to both circle and marker
    circle.bindPopup(popupContent);
    marker.bindPopup(popupContent);

    // Add hover effects
    circle.on('mouseover', function() {
      this.setStyle({
        weight: 5,
        fillOpacity: 0.3
      });
    });

    circle.on('mouseout', function() {
      this.setStyle({
        weight: 3,
        fillOpacity: 0.15
      });
    });

    // 🌟 Add green glowing animation using CSS
    const circleEl = circle.getElement();
    if (circleEl) {
      circleEl.classList.add("geofence-glow-green");
    }
  });

  // --- Polygon geofences with enhanced visibility ---
  const polygons = [
    ["Charging Fence Dhule (Outlined)", [
      [21.150138, 74.850055],
      [21.148732, 74.849582],
      [21.149454, 74.847823],
      [21.150652, 74.848260]
    ], "charging"],
    ["Jhulwania Charging Point (Outlined)", [
      [21.870919, 75.214750],
      [21.870419, 75.213876],
      [21.869145, 75.214469],
      [21.869929, 75.215546]
    ], "charging"],
    ["Manawar Loading Area", [
        [22.271683, 75.138225],
        [22.268312, 75.128871],
        [22.262503, 75.128803],
        [22.262364, 75.139468],
    ], "loading"],
  ];

  polygons.forEach(([name, coords, type]) => {
    // console.log(`📍 Polygon Geofence: ${name}`, coords);

    const color = "#10b981"; // Green for all polygon geofences
    
    const polygon = L.polygon(coords, {
      color: color,
      fillColor: color,
      weight: 3,
      fillOpacity: 0.15,
      className: 'geofence-polygon'
    }).addTo(map);

    // Add center marker for polygon (always visible) - using appropriate icons
    const bounds = polygon.getBounds();
    const center = bounds.getCenter();
    const icon = type === "charging" ? chargingIcon : generalIcon;
    
    const marker = L.marker([center.lat, center.lng], { 
      icon: icon,
      zIndexOffset: 1000,
      riseOnHover: true
    });

    // Don't add marker to map yet - will be controlled by zoom level
    geofenceMarkers.push(marker);

    // console.log(`✅ Added persistent polygon marker for ${name} at zoom-independent visibility`);

    const popupContent = `
      <div class="geofence-popup">
        <h4 class="font-bold text-lg mb-2">${name}</h4>
        <div class="space-y-1 text-sm">
          <div><strong>Type:</strong> ${type.charAt(0).toUpperCase() + type.slice(1)} Zone</div>
          <div><strong>Shape:</strong> Polygon</div>
          <div><strong>Points:</strong> ${coords.length}</div>
        </div>
      </div>
    `;

    polygon.bindPopup(popupContent);
    marker.bindPopup(popupContent);

    // Add hover effects
    polygon.on('mouseover', function() {
      this.setStyle({
        weight: 5,
        fillOpacity: 0.3
      });
    });

    polygon.on('mouseout', function() {
      this.setStyle({
        weight: 3,
        fillOpacity: 0.15
      });
    });

    const polygonEl = polygon.getElement();
    if (polygonEl) {
      polygonEl.classList.add("geofence-glow");
    }
  });

  // --- Maharashtra Border Line ---
  // Add a horizontal line to mark the Maharashtra border
  const mahaBorderLat = 21.427817;
  const mahaBorderLon = 74.980463;
  const lineLength = 0.35; // Degrees (~35-40 km extended for better visibility)
  
  const borderLine = L.polyline([
    [mahaBorderLat, mahaBorderLon - lineLength],
    [mahaBorderLat, mahaBorderLon + lineLength]
  ], {
    color: '#ef4444', // Red color for border
    weight: 5,
    opacity: 0.95,
    dashArray: '15, 10',
    lineCap: 'round',
    className: 'maharashtra-border-line'
  }).addTo(map);

  // Add popup to the border line
  borderLine.bindPopup(`
    <div style="text-align: center; padding: 4px;">
      <strong style="color: #ef4444; font-size: 13px;">Maharashtra Border</strong>
    </div>
  `);

  // Function to show/hide geofence markers based on zoom level
  function updateGeofenceMarkerVisibility() {
    const currentZoom = map.getZoom();
    
    geofenceMarkers.forEach(marker => {
      if (currentZoom >= MIN_ZOOM_FOR_MARKERS) {
        // Zoom level high enough - show markers
        if (!map.hasLayer(marker)) {
          marker.addTo(map);
        }
      } else {
        // Zoom level too low - hide markers to prevent clutter
        if (map.hasLayer(marker)) {
          map.removeLayer(marker);
        }
      }
    });
    
    // console.log(`🔍 Zoom level ${currentZoom}: Geofence markers ${currentZoom >= MIN_ZOOM_FOR_MARKERS ? 'visible' : 'hidden'}`);
  }

  // Set initial visibility based on current zoom
  updateGeofenceMarkerVisibility();

  // Update marker visibility when zoom changes
  map.on('zoomend', updateGeofenceMarkerVisibility);

  // console.log("✅ Geofences added successfully with zoom-based marker visibility (min zoom: " + MIN_ZOOM_FOR_MARKERS + ")");
}

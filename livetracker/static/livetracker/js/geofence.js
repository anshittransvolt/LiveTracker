// ===================================================
// geofence.js — zoom-responsive geofence markers
// Icons scale up when zoomed out, return to base size when zoomed in
// ===================================================

export function addGeofences(map) {
  const BASE_SIZE   = 32;   // px at or above BASE_ZOOM
  const BASE_ZOOM   = 12;   // zoom level where icons are at base size
  const SCALE_STEP  = 5;    // px added per zoom level below BASE_ZOOM
  const MAX_SIZE    = 64;   // cap so icons don't go enormous at zoom 1

  const ICON_URLS = {
    charging:  '/static/livetracker/images/charger1.png',
    unloading: '/static/livetracker/images/unloading.png',
    border:    '/static/livetracker/images/border.png',
    general:   'https://cdn-icons-png.flaticon.com/512/2776/2776067.png',
  };

  function computeSize(zoom) {
    return Math.min(MAX_SIZE, Math.max(BASE_SIZE, BASE_SIZE + (BASE_ZOOM - zoom) * SCALE_STEP));
  }

  function makeIcon(type, zoom) {
    const s = computeSize(zoom);
    return L.icon({
      iconUrl:     ICON_URLS[type] || ICON_URLS.general,
      iconSize:    [s, s],
      iconAnchor:  [s / 2, s / 2],
      popupAnchor: [0, -s / 2],
      className:   `geofence-${type}-icon`,
    });
  }

  // All markers stored as {marker, type} so we can update on zoom
  const tracked = [];

  function addMarker(lat, lng, type, popupHtml) {
    const marker = L.marker([lat, lng], {
      icon: makeIcon(type, map.getZoom()),
      zIndexOffset: 1000,
      riseOnHover: true,
    }).addTo(map);
    marker.bindPopup(popupHtml);
    marker.options.bubblingMouseEvents = false;
    tracked.push({ marker, type });
    return marker;
  }

  // ── CIRCLE GEOFENCES ──────────────────────────────────────────────
  const circleGeofences = [
    ["Dhule Gate",               21.156063,    74.853409,    50,  "border"],
    ["Dhule Unloading area",     21.15111842,  74.84979354, 100,  "unloading"],
    ["Maha Border",              21.427817,    74.980463,   500,  "border"],
    ["D1 Jhulwania (20 m)",      21.871537,    75.215380,    50,  "general"],
    ["D2 Jhulwania (20 m)",      21.870432,    75.213483,    50,  "general"],
    ["Manawar Out Area",         22.262448,    75.128085,    50,  "general"],
    ["Manawar Tarpulien",        22.271049,    75.133974,    30,  "general"],
    ["Manawar Charging Point",   22.265636,    75.127046,   100,  "charging"],
    ["Manawar Weighing Area",    22.269420,    75.133556,    50,  "general"],
    ["Dharampuri",               22.152785,    75.341519,   150,  "general"],
    ["Dabhashi",                 21.265904,    74.847418,   150,  "general"],
  ];

  circleGeofences.forEach(([name, lat, lon, radius, type]) => {
    const circle = L.circle([lat, lon], {
      color:       '#10b981',
      fillColor:   '#10b981',
      fillOpacity: 0.15,
      radius,
      weight:      3,
      interactive: true,
      className:   'geofence-circle',
    }).addTo(map);

    const popup = `
      <div class="geofence-popup">
        <h4 style="font-weight:700;font-size:13px;margin-bottom:6px;">${name}</h4>
        <div style="font-size:12px;line-height:1.6;">
          <div><b>Type:</b> ${type.charAt(0).toUpperCase() + type.slice(1)}</div>
          <div><b>Radius:</b> ${radius} m</div>
          <div><b>Coords:</b> ${lat.toFixed(5)}, ${lon.toFixed(5)}</div>
        </div>
      </div>`;

    circle.bindPopup(popup);
    circle.on('mouseover', function() { this.setStyle({ weight: 5, fillOpacity: 0.3 }); });
    circle.on('mouseout',  function() { this.setStyle({ weight: 3, fillOpacity: 0.15 }); });

    addMarker(lat, lon, type, popup);
  });

  // ── POLYGON GEOFENCES ─────────────────────────────────────────────
  const polygons = [
    ["Charging Fence Dhule (Outlined)", [
      [21.150138, 74.850055], [21.148732, 74.849582],
      [21.149454, 74.847823], [21.150652, 74.848260],
    ], "charging"],
    ["Jhulwania Charging Point (Outlined)", [
      [21.870919, 75.214750], [21.870419, 75.213876],
      [21.869145, 75.214469], [21.869929, 75.215546],
    ], "charging"],
    ["Manawar Loading Area", [
      [22.271683, 75.138225], [22.268312, 75.128871],
      [22.262503, 75.128803], [22.262364, 75.139468],
    ], "general"],
  ];

  polygons.forEach(([name, coords, type]) => {
    const polygon = L.polygon(coords, {
      color:       '#10b981',
      fillColor:   '#10b981',
      weight:      3,
      fillOpacity: 0.15,
      className:   'geofence-polygon',
    }).addTo(map);

    const bounds = polygon.getBounds();
    const center = bounds.getCenter();

    const popup = `
      <div class="geofence-popup">
        <h4 style="font-weight:700;font-size:13px;margin-bottom:6px;">${name}</h4>
        <div style="font-size:12px;line-height:1.6;">
          <div><b>Type:</b> ${type.charAt(0).toUpperCase() + type.slice(1)} Zone</div>
          <div><b>Shape:</b> Polygon (${coords.length} pts)</div>
        </div>
      </div>`;

    polygon.bindPopup(popup);
    polygon.on('mouseover', function() { this.setStyle({ weight: 5, fillOpacity: 0.3 }); });
    polygon.on('mouseout',  function() { this.setStyle({ weight: 3, fillOpacity: 0.15 }); });

    addMarker(center.lat, center.lng, type, popup);
  });

  // ── MAHARASHTRA BORDER LINE ───────────────────────────────────────
  const mahaBorderLat = 21.427817;
  const mahaBorderLon = 74.980463;
  L.polyline([
    [mahaBorderLat, mahaBorderLon - 0.35],
    [mahaBorderLat, mahaBorderLon + 0.35],
  ], {
    color:     '#ef4444',
    weight:    5,
    opacity:   0.95,
    dashArray: '15, 10',
    lineCap:   'round',
    className: 'maharashtra-border-line',
  }).addTo(map).bindPopup(`
    <div style="text-align:center;padding:4px;">
      <strong style="color:#ef4444;font-size:13px;">Maharashtra Border</strong>
    </div>`);

  // ── ZOOM-RESPONSIVE ICON RESIZE ───────────────────────────────────
  map.on('zoomend', () => {
    const zoom = map.getZoom();
    tracked.forEach(({ marker, type }) => {
      marker.setIcon(makeIcon(type, zoom));
    });
  });
}

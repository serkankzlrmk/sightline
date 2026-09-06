// ═══════════════════════════════════════════════════════════════
// map-config.js — server-rendered basemap configuration for the crisis map.
//
// CSP forbids inline scripts, so the Flask route injects the CARTO basemap
// API key via a data attribute on the <script> tag (same pattern as
// adsense-loader.js / analytics.js). This file must load BEFORE the app
// bundle (defer order in index.html).
//
// CARTO requires an API key for basemaps.cartocdn.com since Aug 2026
// (https://carto.com/basemaps/apikey/). Keyless raster requests return HTTP
// 200 with an "API key required" watermark image instead of a real tile.
// The map code reads window.__mapBasemap.cartoKey: with a key it prefers
// CARTO tiles; without one it prefers OpenStreetMap tiles.
// ═══════════════════════════════════════════════════════════════
(function () {
  'use strict';
  var el = document.getElementById('sightline-map-config');
  window.__mapBasemap = {
    cartoKey: (el && el.getAttribute('data-carto-key')) || '',
  };
})();
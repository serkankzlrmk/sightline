/* ── Sightline 3D Landing — Sketchfab Scroll-Driven Camera ── */

(function() {
  'use strict';

  // ── Mobile gate ──
  if (window.innerWidth <= 768) {
    var gate = document.getElementById('mobile-gate');
    if (gate) gate.classList.add('active');
    return;
  }

  var MODEL_UID = '2b691638fa034aca919abb9e4d77c632';
  var NUM_SECTIONS = 7;
  var api = null;
  var currentSection = -1;
  var scrollProgress = 0;

  var iframe = document.getElementById('sketchfab-viewer');
  var loader = document.getElementById('loading-screen');

  function hideLoader() {
    if (loader) loader.classList.add('hidden');
  }

  function initSketchfab() {
    if (typeof Sketchfab === 'undefined') {
      console.warn('[Sightline 3D] Sketchfab API not loaded, using embed only');
      hideLoader();
      initScroll();
      return;
    }

    var client = new Sketchfab('1.12.1', iframe);

    client.init(MODEL_UID, {
      autostart: 1,
      preload: 1,
      max_texture_size: 2048,
      ui_infos: 0,
      ui_controls: 0,
      ui_watermark: 0,
      ui_inspector: 0,
      ui_settings: 0,
      ui_help: 0,
      ui_hints: 0,
      ui_annotations: 0,
      ui_stop: 0,
      ui_start: 0,
      ui_fullscreen: 0,
      ui_collapse: 0,
      transparent: 1,
      autospin: 0.5,
      success_cb: 'onSketchfabReady',

      success: function(_api) {
        api = _api;
        api.start();

        api.addEventListener('viewerready', function() {
          hideLoader();

          // Get camera eye for rotation control
          try {
            api.getCameraLookAt(function(result) {
              if (result) {
                window.__camEye = result.position || [0, 0, 5];
                window.__camTarget = result.target || [0, 0, 0];
              }
            });
          } catch(e) {}

          initScroll();
        });
      },

      error: function() {
        hideLoader();
        console.warn('[Sightline 3D] Sketchfab init failed, embed only');
        initScroll();
      }
    });
  }

  function rotateCamera(api, progress) {
    if (!api) return;
    try {
      var eye = window.__camEye || [0, 0, 5];
      var target = window.__camTarget || [0, 0, 0];
      var radius = Math.sqrt(eye[0]*eye[0] + eye[2]*eye[2]) || 5;
      var angle = progress * Math.PI * 2;
      var newEye = [
        Math.sin(angle) * radius,
        eye[1] + progress * 1.5,
        Math.cos(angle) * radius
      ];
      api.setCameraLookAt(newEye, target, 0.5);
    } catch(e) {
      console.warn('[Sightline 3D] Camera rotation failed:', e);
    }
  }

  // ── Scroll handler ──
  function initScroll() {
    var sections = document.querySelectorAll('.lp-section');
    var spFill = document.getElementById('sp-fill');
    var spDotsContainer = document.getElementById('sp-dots');
    var scrollHint = document.getElementById('scroll-hint');

    if (spDotsContainer) {
      for (var i = 0; i < NUM_SECTIONS; i++) {
        var dot = document.createElement('div');
        dot.className = 'sp-dot';
        spDotsContainer.appendChild(dot);
      }
    }
    var dots = spDotsContainer ? spDotsContainer.querySelectorAll('.sp-dot') : [];

    activateSection(0, sections, dots);

    var ticking = false;

    function onScroll() {
      if (!ticking) {
        requestAnimationFrame(updateScroll);
        ticking = true;
      }
    }

    function updateScroll() {
      var scrollY = window.scrollY;
      var maxScroll = document.body.scrollHeight - window.innerHeight;
      scrollProgress = maxScroll > 0 ? scrollY / maxScroll : 0;

      if (spFill) spFill.style.height = (scrollProgress * 100) + '%';
      if (scrollHint && scrollY > 50) scrollHint.classList.add('hidden');

      var section = Math.min(Math.floor(scrollProgress * NUM_SECTIONS), NUM_SECTIONS - 1);

      if (section !== currentSection) {
        activateSection(section, sections, dots);
        // Animate camera on section change
        if (api) {
          rotateCamera(api, scrollProgress);
        }
      }

      ticking = false;
    }

    window.addEventListener('scroll', onScroll, { passive: true });
  }

  function activateSection(index, sections, dots) {
    sections.forEach(function(s) { s.classList.remove('active'); });
    dots.forEach(function(d) { d.classList.remove('active'); });

    var target = sections[index];
    if (target) target.classList.add('active');
    if (dots[index]) dots[index].classList.add('active');

    currentSection = index;
  }

  // ── Start ──
  setTimeout(function() {
    hideLoader();
    if (typeof THREE === 'undefined' && typeof Sketchfab === 'undefined') {
      initScroll();
    }
  }, 10000);

  initSketchfab();

})();

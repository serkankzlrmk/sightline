/* ── Sightline 3D Landing — Sketchfab API + Scroll-Driven Camera ── */

(function() {
  'use strict';

  // ── Mobile gate ──
  if (window.innerWidth <= 768) {
    document.getElementById('mobile-gate').classList.add('active');
    return;
  }

  var MODEL_UID = '17cf917d160645b6a57a09c420ed647d';
  var NUM_SECTIONS = 7;
  var api = null;
  var annotations = [];
  var currentSection = -1;
  var isAnimating = false;

  // ── Initialize Sketchfab viewer ──
  var iframe = document.getElementById('sketchfab-viewer');
  var loader = document.getElementById('loading-screen');

  function initSketchfab() {
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
      autospin: 0,
      restricted: 1,
      success_cb: 'onSketchfabSuccess',

      success: function(_api) {
        api = _api;
        api.start();

        // Wait for model to load
        api.addEventListener('viewerready', function() {
          if (loader) loader.classList.add('hidden');

          // Try to get annotations
          try {
            api.getAnnotations(function(result) {
              if (result && result.data && result.data.length > 0) {
                annotations = result.data;
              }
            });
          } catch(e) {}

          initScroll();
        });
      },

      error: function() {
        if (loader) loader.classList.add('hidden');
        console.warn('[Sightline 3D] Sketchfab API init failed, using embed without camera control');
        initScroll();
      }
    });
  }

  // ── Scroll handler ──
  function initScroll() {
    var sections = document.querySelectorAll('.lp-section');
    var scrollContainer = document.getElementById('scroll-container');
    var spFill = document.getElementById('sp-fill');
    var spDotsContainer = document.getElementById('sp-dots');
    var scrollHint = document.getElementById('scroll-hint');

    // Create progress dots
    if (spDotsContainer) {
      for (var i = 0; i < NUM_SECTIONS; i++) {
        var dot = document.createElement('div');
        dot.className = 'sp-dot';
        spDotsContainer.appendChild(dot);
      }
    }
    var dots = spDotsContainer ? spDotsContainer.querySelectorAll('.sp-dot') : [];

    // Activate first section
    activateSection(0, sections, dots);

    // Throttle scroll
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
      var progress = maxScroll > 0 ? scrollY / maxScroll : 0;

      // Progress fill
      if (spFill) spFill.style.height = (progress * 100) + '%';

      // Hide scroll hint after first scroll
      if (scrollHint && scrollY > 50) scrollHint.classList.add('hidden');

      // Calculate active section
      var section = Math.min(Math.floor(progress * NUM_SECTIONS), NUM_SECTIONS - 1);

      if (section !== currentSection) {
        activateSection(section, sections, dots);

        // Animate camera to annotation[section] if available
        if (api && !isAnimating) {
          isAnimating = true;

          if (annotations.length > 0 && section < annotations.length) {
            // Use gotoAnnotation for predefined camera positions
            try {
              api.gotoAnnotation(section, { duration: 1.5 });
            } catch (e) {
              console.warn('[Sightline 3D] gotoAnnotation failed:', e);
            }
          } else {
            // Fallback: rotate camera based on progress
            try {
              var angle = progress * 360;
              var eye = [
                Math.cos(angle * Math.PI / 180) * 3,
                1 + progress * 2,
                Math.sin(angle * Math.PI / 180) * 3
              ];
              api.setCameraLookAt(eye, [0, 0, 0], 1.5);
            } catch (e) {
              console.warn('[Sightline 3D] setCameraLookAt failed:', e);
            }
          }

          setTimeout(function() { isAnimating = false; }, 800);
        }
      }

      ticking = false;
    }

    window.addEventListener('scroll', onScroll, { passive: true });
  }

  // ── Activate section (fade in/out) ──
  function activateSection(index, sections, dots) {
    // Remove active from all
    sections.forEach(function(s) { s.classList.remove('active'); });
    dots.forEach(function(d) { d.classList.remove('active'); });

    // Activate current
    var target = sections[index];
    if (target) target.classList.add('active');
    if (dots[index]) dots[index].classList.add('active');

    currentSection = index;
  }

  // ── Start ──
  // Timeout: if model doesn't load in 12s, hide loader and proceed
  setTimeout(function() {
    if (loader && !loader.classList.contains('hidden')) {
      loader.classList.add('hidden');
      console.warn('[Sightline 3D] Loading timeout — proceeding without 3D');
      initScroll();
    }
  }, 12000);

  if (typeof Sketchfab !== 'undefined') {
    initSketchfab();
  } else {
    // Sketchfab API not loaded — wait
    var checkCount = 0;
    var checkInterval = setInterval(function() {
      checkCount++;
      if (typeof Sketchfab !== 'undefined') {
        clearInterval(checkInterval);
        initSketchfab();
      } else if (checkCount > 20) {
        // Timeout — load without 3D
        clearInterval(checkInterval);
        if (loader) loader.classList.add('hidden');
        initScroll();
        console.warn('[Sightline 3D] Sketchfab API not available');
      }
    }, 200);
  }

})();

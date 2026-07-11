/* ── Sightline 3D Globe — Three.js Scroll-Driven ── */
/* Custom 3D earth, no Sketchfab dependency */

(function() {
  'use strict';

  // ── Mobile gate ──
  if (window.innerWidth <= 768) {
    var gate = document.getElementById('mobile-gate');
    if (gate) gate.classList.add('active');
    return;
  }

  var NUM_SECTIONS = 7;
  var currentSection = -1;
  var scrollProgress = 0;

  // ── Three.js setup ──
  var scene, camera, renderer, globe, atmosphere, stars;
  var container = document.getElementById('sketchfab-container');

  // Reuse the container div for our canvas
  if (!container) {
    container = document.createElement('div');
    container.id = 'sketchfab-container';
    document.body.insertBefore(container, document.body.firstChild);
  }
  container.innerHTML = '';
  container.style.cssText = 'position:fixed;inset:0;z-index:0;pointer-events:none;';

  function initThree() {
    // Load Three.js dynamically
    var script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js';
    script.onload = startScene;
    script.onerror = function() {
      console.warn('[Sightline 3D] Three.js failed to load');
      hideLoader();
      initScroll();
    };
    document.head.appendChild(script);
  }

  function startScene() {
    if (typeof THREE === 'undefined') {
      console.warn('[Sightline 3D] THREE not available');
      hideLoader();
      initScroll();
      return;
    }

    scene = new THREE.Scene();

    // Camera
    camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.set(0, 0, 3.5);

    // Renderer
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x050507, 1);
    container.appendChild(renderer.domElement);

    // ── Earth Globe ──
    // NASA Blue Marble texture (public domain)
    var loader = new THREE.TextureLoader();
    loader.crossOrigin = 'anonymous';

    // Use a simple colored sphere with a nice material as fallback
    var geometry = new THREE.SphereGeometry(1, 64, 64);

    // Try loading earth texture, fallback to solid color
    var earthTexture = loader.load(
      'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r160/examples/textures/planets/earth_atmos_2048.jpg',
      function() { hideLoader(); },
      undefined,
      function() {
        // Fallback: use a nice gradient material
        globe.material = new THREE.MeshPhongMaterial({
          color: 0x1a4d7a,
          emissive: 0x0a2a4a,
          shininess: 25,
          specular: 0x335577
        });
        hideLoader();
      }
    );

    globe = new THREE.Mesh(geometry, new THREE.MeshPhongMaterial({
      map: earthTexture,
      shininess: 15,
      specular: 0x222244
    }));
    scene.add(globe);

    // ── Atmosphere glow (outer sphere) ──
    var atmGeo = new THREE.SphereGeometry(1.08, 64, 64);
    var atmMat = new THREE.ShaderMaterial({
      vertexShader: [
        'varying vec3 vNormal;',
        'void main() {',
        '  vNormal = normalize(normalMatrix * normal);',
        '  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);',
        '}'
      ].join('\n'),
      fragmentShader: [
        'varying vec3 vNormal;',
        'void main() {',
        '  float intensity = pow(0.65 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 2.0);',
        '  gl_FragColor = vec4(0.3, 0.6, 1.0, 1.0) * intensity;',
        '}'
      ].join('\n'),
      blending: THREE.AdditiveBlending,
      side: THREE.BackSide,
      transparent: true
    });
    atmosphere = new THREE.Mesh(atmGeo, atmMat);
    scene.add(atmosphere);

    // ── Stars ──
    var starGeo = new THREE.BufferGeometry();
    var starCount = 3000;
    var positions = new Float32Array(starCount * 3);
    for (var i = 0; i < starCount * 3; i += 3) {
      var r = 50 + Math.random() * 100;
      var theta = Math.random() * Math.PI * 2;
      var phi = Math.random() * Math.PI;
      positions[i] = r * Math.sin(phi) * Math.cos(theta);
      positions[i + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i + 2] = r * Math.cos(phi);
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    var starMat = new THREE.PointsMaterial({
      color: 0xffffff,
      size: 0.15,
      transparent: true,
      opacity: 0.8,
      sizeAttenuation: true
    });
    stars = new THREE.Points(starGeo, starMat);
    scene.add(stars);

    // ── Lighting ──
    var ambient = new THREE.AmbientLight(0x404060, 0.5);
    scene.add(ambient);

    var sun = new THREE.DirectionalLight(0xffffff, 1.2);
    sun.position.set(5, 3, 5);
    scene.add(sun);

    var rim = new THREE.DirectionalLight(0x4488ff, 0.3);
    rim.position.set(-5, -2, -3);
    scene.add(rim);

    // ── Resize ──
    window.addEventListener('resize', function() {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    });

    // ── Animation loop ──
    animate();

    // Init scroll
    initScroll();
  }

  function animate() {
    requestAnimationFrame(animate);

    if (globe) {
      // Base slow rotation
      globe.rotation.y += 0.0008;

      // Scroll-driven rotation
      globe.rotation.x = scrollProgress * 0.5;
      globe.rotation.y += scrollProgress * 0.01;

      // Camera zoom: closer as you scroll down
      var targetZ = 3.5 - scrollProgress * 1.5;
      camera.position.z += (targetZ - camera.position.z) * 0.05;

      // Camera tilt
      camera.position.y = scrollProgress * 1.5;
      camera.lookAt(0, 0, 0);
    }

    if (stars) {
      stars.rotation.y += 0.0002;
    }

    if (renderer && scene && camera) {
      renderer.render(scene, camera);
    }
  }

  function hideLoader() {
    var loader = document.getElementById('loading-screen');
    if (loader) loader.classList.add('hidden');
  }

  // ── Scroll handler ──
  function initScroll() {
    var sections = document.querySelectorAll('.lp-section');
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
  // Timeout fallback
  setTimeout(function() {
    hideLoader();
    if (typeof THREE === 'undefined') {
      initScroll();
    }
  }, 8000);

  initThree();

})();

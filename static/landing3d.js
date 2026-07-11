/* ── Sightline 3D Globe — Three.js Premium Earth v3 ── */
/* 4K textures, night lights, custom shader for day/night blend, section transitions */

(function() {
  'use strict';

  if (window.innerWidth <= 768) {
    var gate = document.getElementById('mobile-gate');
    if (gate) gate.classList.add('active');
    return;
  }

  var NUM_SECTIONS = 8;
  var currentSection = -1;
  var scrollProgress = 0;

  var container = document.getElementById('sketchfab-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'sketchfab-container';
    document.body.insertBefore(container, document.body.firstChild);
  }
  container.innerHTML = '';
  container.style.cssText = 'position:fixed;inset:0;z-index:0;pointer-events:none;';

  var scene, camera, renderer, earth, clouds, atmosphere, starFields = [];
  var loader = document.getElementById('loading-screen');
  var texturesLoaded = 0;
  var totalTextures = 4;
  var dayMaterial, nightMaterial;

  function hideLoader() {
    if (loader) loader.classList.add('hidden');
  }

  function initThree() {
    var script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js';
    script.onload = startScene;
    script.onerror = function() { hideLoader(); initScroll(); };
    document.head.appendChild(script);
  }

  function startScene() {
    if (typeof THREE === 'undefined') { hideLoader(); initScroll(); return; }

    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(40, window.innerWidth / window.innerHeight, 0.1, 1000);
    // Hero: camera looking up at stars only, earth completely hidden
    camera.position.set(0, -8.0, 0.5);
    camera.lookAt(0, 10, 0);

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x030305, 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    container.appendChild(renderer.domElement);

    var texLoader = new THREE.TextureLoader();
    texLoader.crossOrigin = 'anonymous';

    // Local high-quality textures from Sketchfab "59-earth" model
    var base = '/static/textures/';

    function onTex() { texturesLoaded++; if (texturesLoaded >= totalTextures) hideLoader(); }

    // ── Day map (albedo) ──
    var dayTex = texLoader.load(base + 'earth_albedo.jpg', onTex);
    dayTex.colorSpace = THREE.SRGBColorSpace;
    dayTex.anisotropy = 16;

    // ── Night lights ──
    var nightTex = texLoader.load(base + 'earth_night_lights.png', onTex);
    nightTex.colorSpace = THREE.SRGBColorSpace;

    // ── Ocean mask (specular) ──
    var specTex = texLoader.load(base + 'earth_ocean_mask.png', onTex);
    specTex.anisotropy = 8;

    // ── Clouds ──
    var cloudsTex = texLoader.load(base + 'earth_clouds.png', onTex);
    cloudsTex.colorSpace = THREE.SRGBColorSpace;

    // ── Bump map (terrain elevation) ──
    var bumpTex = texLoader.load(base + 'earth_bump.jpg');

    // ── Earth: Custom shader for day/night blend with bump ──
    var earthGeo = new THREE.SphereGeometry(1, 128, 128);

    dayMaterial = new THREE.ShaderMaterial({
      uniforms: {
        dayTexture: { value: dayTex },
        nightTexture: { value: nightTex },
        specularMap: { value: specTex },
        bumpTexture: { value: bumpTex },
        sunDirection: { value: new THREE.Vector3(5, 3, 5).normalize() },
        nightMix: { value: 0.0 }
      },
      vertexShader: [
        'varying vec2 vUv;',
        'varying vec3 vNormal;',
        'void main() {',
        '  vUv = uv;',
        '  vNormal = normalize(normalMatrix * normal);',
        '  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);',
        '}'
      ].join('\n'),
      fragmentShader: [
        'uniform sampler2D dayTexture;',
        'uniform sampler2D nightTexture;',
        'uniform sampler2D specularMap;',
        'uniform sampler2D bumpTexture;',
        'uniform vec3 sunDirection;',
        'uniform float nightMix;',
        'varying vec2 vUv;',
        'varying vec3 vNormal;',
        'void main() {',
        '  vec3 dayColor = texture2D(dayTexture, vUv).rgb;',
        '  vec3 nightColor = texture2D(nightTexture, vUv).rgb * 2.5;',
        '  float specular = texture2D(specularMap, vUv).r;',
        '  float bump = texture2D(bumpTexture, vUv).r;',
        '',
        '  // Bump affects day color (terrain shading)',
        '  dayColor *= 0.8 + bump * 0.4;',
        '',
        '  // Day/night based on sun angle',
        '  float dayAmount = max(dot(vNormal, sunDirection), 0.0);',
        '  float nightAmount = 1.0 - dayAmount;',
        '',
        '  // Blend day and night',
        '  vec3 color = mix(nightColor, dayColor, smoothstep(0.0, 0.3, dayAmount));',
        '',
        '  // Ocean specular highlight (only on day side)',
        '  float specHighlight = pow(max(dot(reflect(-sunDirection, vNormal), vec3(0,0,1)), 0.0), 20.0) * specular * dayAmount;',
        '  color += vec3(0.8, 0.9, 1.0) * specHighlight * 0.5;',
        '',
        '  // Scroll-driven night mix',
        '  color = mix(color, nightColor * 0.8, nightMix);',
        '',
        '  gl_FragColor = vec4(color, 1.0);',
        '}'
      ].join('\n')
    });

    earth = new THREE.Mesh(earthGeo, dayMaterial);
    scene.add(earth);

    // ── Clouds layer ──
    var cloudsGeo = new THREE.SphereGeometry(1.015, 96, 96);
    clouds = new THREE.Mesh(cloudsGeo, new THREE.MeshPhongMaterial({
      map: cloudsTex,
      transparent: true,
      opacity: 0.45,
      depthWrite: false,
      blending: THREE.NormalBlending
    }));
    scene.add(clouds);

    // ── Inner atmosphere haze ──
    var innerAtm = new THREE.Mesh(
      new THREE.SphereGeometry(1.02, 64, 64),
      new THREE.ShaderMaterial({
        vertexShader: 'varying vec3 vNormal; void main() { vNormal = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
        fragmentShader: 'varying vec3 vNormal; void main() { float i = pow(0.75 - dot(vNormal, vec3(0,0,1)), 3.0); gl_FragColor = vec4(vec3(0.2,0.4,0.8)*i + vec3(0.4,0.7,1.0)*i, i*0.6); }',
        blending: THREE.AdditiveBlending, side: THREE.FrontSide, transparent: true
      })
    );
    scene.add(innerAtm);

    // ── Outer atmosphere glow ──
    atmosphere = new THREE.Mesh(
      new THREE.SphereGeometry(1.15, 64, 64),
      new THREE.ShaderMaterial({
        vertexShader: 'varying vec3 vNormal; void main() { vNormal = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
        fragmentShader: 'varying vec3 vNormal; void main() { float i = pow(0.6 - dot(vNormal, vec3(0,0,1)), 2.5); gl_FragColor = vec4(vec3(0.15,0.45,0.9)*i, i*0.8); }',
        blending: THREE.AdditiveBlending, side: THREE.BackSide, transparent: true
      })
    );
    scene.add(atmosphere);

    // ── Stars (3 parallax layers) ──
    var starConfigs = [
      { count: 1200, dist: 40, size: 0.08, color: 0xffffff, opacity: 0.9 },
      { count: 800, dist: 60, size: 0.12, color: 0xccddff, opacity: 0.6 },
      { count: 400, dist: 80, size: 0.18, color: 0xffeecc, opacity: 0.4 }
    ];
    starConfigs.forEach(function(cfg) {
      var geo = new THREE.BufferGeometry();
      var pos = new Float32Array(cfg.count * 3);
      for (var i = 0; i < cfg.count; i++) {
        var theta = Math.random() * Math.PI * 2;
        var phi = Math.acos(2 * Math.random() - 1);
        pos[i*3] = cfg.dist * Math.sin(phi) * Math.cos(theta);
        pos[i*3+1] = cfg.dist * Math.sin(phi) * Math.sin(theta);
        pos[i*3+2] = cfg.dist * Math.cos(phi);
      }
      geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      var mat = new THREE.PointsMaterial({
        color: cfg.color, size: cfg.size, transparent: true, opacity: cfg.opacity,
        sizeAttenuation: true, blending: THREE.AdditiveBlending, depthWrite: false
      });
      var field = new THREE.Points(geo, mat);
      starFields.push(field);
      scene.add(field);
    });

    // ── Lighting ──
    scene.add(new THREE.AmbientLight(0x12121f, 0.2));
    var sun = new THREE.DirectionalLight(0xfff0e0, 1.8);
    sun.position.set(5, 3, 5);
    scene.add(sun);
    var fill = new THREE.DirectionalLight(0x1a3866, 0.35);
    fill.position.set(-5, -2, -4);
    scene.add(fill);

    // ── Resize ──
    window.addEventListener('resize', function() {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    });

    animate();
    initScroll();
  }

  function animate() {
    requestAnimationFrame(animate);

    if (earth) earth.rotation.y += 0.0005;
    if (clouds) clouds.rotation.y += 0.0007;
    for (var i = 0; i < starFields.length; i++) {
      starFields[i].rotation.y += 0.00003 * (i + 1);
    }

    // ── Scroll-driven camera ──
    if (camera && earth) {
      var startAngle = 35 * Math.PI / 180; // Turkey meridian
      var angle, radius, targetX, targetY, targetZ;
      var earthVisible = true;

      if (scrollProgress < 0.12) {
        // Hero: camera looking up at stars, earth not visible
        var heroT = scrollProgress / 0.12;
        radius = 6.0;
        angle = startAngle;
        targetX = Math.sin(angle) * radius;
        targetZ = Math.cos(angle) * radius;
        targetY = -8.0 + heroT * 5.5; // slowly pan down from deep below
        earthVisible = false;
        if (clouds) clouds.visible = false;
        if (atmosphere) atmosphere.visible = false;
      } else if (scrollProgress < 0.85) {
        // Main orbit: earth rises into view, camera orbits
        earthVisible = true;
        if (clouds) clouds.visible = true;
        if (atmosphere) atmosphere.visible = true;
        var mainT = (scrollProgress - 0.12) / 0.73; // 0 → 1
        angle = startAngle + mainT * Math.PI * 1.7;
        radius = 5.2 - mainT * 1.8; // zoom in
        targetX = Math.sin(angle) * radius;
        targetZ = Math.cos(angle) * radius;
        targetY = -1.5 + mainT * 2.8; // rises from bottom to upper
      } else {
        // Final section: keep earth visible but fade container
        var endT = (scrollProgress - 0.85) / 0.15; // 0 → 1
        angle = startAngle + Math.PI * 1.7;
        radius = 3.4 + endT * 1.0;
        targetX = Math.sin(angle) * radius;
        targetZ = Math.cos(angle) * radius;
        targetY = 1.3 + endT * 0.3;
      }

      camera.position.x += (targetX - camera.position.x) * 0.04;
      camera.position.y += (targetY - camera.position.y) * 0.04;
      camera.position.z += (targetZ - camera.position.z) * 0.04;
      camera.lookAt(0, 0, 0);

      if (earth) earth.visible = earthVisible;
      earth.rotation.x = scrollProgress * 0.2;

      // ── SITREP section transition: darken earth ──
      if (dayMaterial && dayMaterial.uniforms) {
        var sitrepStart = 2 / NUM_SECTIONS;
        var sitrepEnd = 3 / NUM_SECTIONS;
        var sitrepProgress = 0;
        if (scrollProgress >= sitrepStart && scrollProgress <= sitrepEnd) {
          sitrepProgress = (scrollProgress - sitrepStart) / (sitrepEnd - sitrepStart);
        } else if (scrollProgress > sitrepEnd) {
          sitrepProgress = 1.0 - Math.min((scrollProgress - sitrepEnd) / 0.1, 1.0);
        }
        dayMaterial.uniforms.nightMix.value = Math.max(0, sitrepProgress) * 0.6;
      }

      // ── Final section: fade out 3D globe, fade in hologram ──
      var hologramContainer = document.getElementById('hologram-container');
      var threeContainer = document.getElementById('sketchfab-container');
      if (scrollProgress > 0.80) {
        var holoT = Math.min((scrollProgress - 0.80) / 0.20, 1.0);

        // Load hologram iframe early (at 75% progress)
        if (hologramContainer && !hologramContainer.dataset.loaded) {
          hologramContainer.dataset.loaded = '1';
          var hologramFrame = document.getElementById('hologram-viewer');
          if (hologramFrame) {
            hologramFrame.src = 'https://sketchfab.com/models/7d9805604f744974baebbd9d6dcfd868/embed?autostart=1&preload=1&ui_infos=0&ui_controls=0&ui_watermark=0&ui_inspector=0&ui_settings=0&ui_help=0&ui_hints=0&ui_annotations=0&ui_stop=0&ui_start=0&ui_fullscreen=0&ui_collapse=0&autospin=0.5&transparent=1';
          }
        }

        // Fade in hologram
        if (hologramContainer) hologramContainer.style.opacity = holoT;
        // Fade out 3D globe
        if (threeContainer) threeContainer.style.opacity = 1 - holoT;
      } else {
        if (hologramContainer) hologramContainer.style.opacity = 0;
        if (threeContainer) threeContainer.style.opacity = 1;
      }
    }

    if (renderer && scene && camera) renderer.render(scene, camera);
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
      if (!ticking) { requestAnimationFrame(updateScroll); ticking = true; }
    }
    function updateScroll() {
      var scrollY = window.scrollY;
      var maxScroll = document.body.scrollHeight - window.innerHeight;
      scrollProgress = maxScroll > 0 ? scrollY / maxScroll : 0;
      if (spFill) spFill.style.height = (scrollProgress * 100) + '%';
      if (scrollHint && scrollY > 50) scrollHint.classList.add('hidden');
      var section = Math.min(Math.floor(scrollProgress * NUM_SECTIONS), NUM_SECTIONS - 1);
      if (section !== currentSection) activateSection(section, sections, dots);
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
  setTimeout(function() { hideLoader(); if (typeof THREE === 'undefined') initScroll(); }, 8000);
  initThree();
})();

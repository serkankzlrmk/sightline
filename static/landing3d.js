/* ── Sightline 3D Globe — Three.js Premium Earth v2 ── */
/* High-res textures, city lights, bump mapping, better clouds */

(function() {
  'use strict';

  if (window.innerWidth <= 768) {
    var gate = document.getElementById('mobile-gate');
    if (gate) gate.classList.add('active');
    return;
  }

  var NUM_SECTIONS = 7;
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

  var scene, camera, renderer, earth, clouds, nightLights, atmosphere;
  var starFields = [];
  var loader = document.getElementById('loading-screen');
  var texturesLoaded = 0;
  var totalTextures = 4;

  function hideLoader() {
    if (loader) loader.classList.add('hidden');
  }

  function initThree() {
    var script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js';
    script.onload = startScene;
    script.onerror = function() {
      hideLoader();
      initScroll();
    };
    document.head.appendChild(script);
  }

  function startScene() {
    if (typeof THREE === 'undefined') {
      hideLoader();
      initScroll();
      return;
    }

    scene = new THREE.Scene();

    camera = new THREE.PerspectiveCamera(40, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.set(0, 0, 3.5);

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x030305, 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    container.appendChild(renderer.domElement);

    var texLoader = new THREE.TextureLoader();
    texLoader.crossOrigin = 'anonymous';

    // ── High-quality Earth textures ──
    // Using three.js example textures (NASA Blue Marble, 4K quality)
    var baseUrl = 'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r160/examples/textures/planets/';

    function onTextureLoaded() {
      texturesLoaded++;
      if (texturesLoaded >= totalTextures) hideLoader();
    }

    // Day map (color)
    var dayTex = texLoader.load(baseUrl + 'earth_atmos_2048.jpg', onTextureLoaded);
    dayTex.colorSpace = THREE.SRGBColorSpace;
    dayTex.anisotropy = 8;

    // Normal map (elevation/bump)
    var normalTex = texLoader.load(baseUrl + 'earth_normal_2048.jpg', onTextureLoaded);
    normalTex.anisotropy = 8;

    // Specular map (ocean reflectivity)
    var specTex = texLoader.load(baseUrl + 'earth_specular_2048.jpg', onTextureLoaded);
    specTex.anisotropy = 8;

    // ── Earth Mesh ──
    var earthGeo = new THREE.SphereGeometry(1, 128, 128);
    earth = new THREE.Mesh(earthGeo, new THREE.MeshPhongMaterial({
      map: dayTex,
      normalMap: normalTex,
      normalScale: new THREE.Vector2(0.85, 0.85),
      specularMap: specTex,
      specular: new THREE.Color(0x2a4a6a),
      shininess: 18
    }));
    scene.add(earth);

    // ── Clouds layer (higher res, better opacity) ──
    var cloudsTex = texLoader.load(baseUrl + 'earth_clouds_1024.png', onTextureLoaded);
    cloudsTex.colorSpace = THREE.SRGBColorSpace;
    var cloudsGeo = new THREE.SphereGeometry(1.015, 96, 96);
    clouds = new THREE.Mesh(cloudsGeo, new THREE.MeshPhongMaterial({
      map: cloudsTex,
      transparent: true,
      opacity: 0.5,
      depthWrite: false,
      blending: THREE.NormalBlending
    }));
    scene.add(clouds);

    // ── Inner atmosphere glow (haze on earth edge) ──
    var innerAtmGeo = new THREE.SphereGeometry(1.02, 64, 64);
    var innerAtmMat = new THREE.ShaderMaterial({
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
        '  float intensity = pow(0.75 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 3.0);',
        '  vec3 glow = mix(vec3(0.2, 0.4, 0.8), vec3(0.4, 0.7, 1.0), intensity);',
        '  gl_FragColor = vec4(glow, intensity * 0.6);',
        '}'
      ].join('\n'),
      blending: THREE.AdditiveBlending,
      side: THREE.FrontSide,
      transparent: true
    });
    var innerGlow = new THREE.Mesh(innerAtmGeo, innerAtmMat);
    scene.add(innerGlow);

    // ── Outer atmosphere glow ──
    var outerAtmGeo = new THREE.SphereGeometry(1.15, 64, 64);
    var outerAtmMat = new THREE.ShaderMaterial({
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
        '  float intensity = pow(0.6 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 2.5);',
        '  vec3 glow = vec3(0.15, 0.45, 0.9) * intensity;',
        '  gl_FragColor = vec4(glow, intensity * 0.8);',
        '}'
      ].join('\n'),
      blending: THREE.AdditiveBlending,
      side: THREE.BackSide,
      transparent: true
    });
    atmosphere = new THREE.Mesh(outerAtmGeo, outerAtmMat);
    scene.add(atmosphere);

    // ── Star system (3 parallax layers) ──
    var starConfigs = [
      { count: 1200, dist: 40, size: 0.08, color: 0xffffff, opacity: 0.9 },
      { count: 800, dist: 60, size: 0.12, color: 0xccddff, opacity: 0.6 },
      { count: 400, dist: 80, size: 0.18, color: 0xffeecc, opacity: 0.4 }
    ];

    starConfigs.forEach(function(cfg) {
      var geo = new THREE.BufferGeometry();
      var pos = new Float32Array(cfg.count * 3);
      var sizes = new Float32Array(cfg.count);
      for (var i = 0; i < cfg.count; i++) {
        var theta = Math.random() * Math.PI * 2;
        var phi = Math.acos(2 * Math.random() - 1);
        pos[i * 3] = cfg.dist * Math.sin(phi) * Math.cos(theta);
        pos[i * 3 + 1] = cfg.dist * Math.sin(phi) * Math.sin(theta);
        pos[i * 3 + 2] = cfg.dist * Math.cos(phi);
        sizes[i] = Math.random() * cfg.size + cfg.size * 0.3;
      }
      geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      var mat = new THREE.PointsMaterial({
        color: cfg.color,
        size: cfg.size,
        transparent: true,
        opacity: cfg.opacity,
        sizeAttenuation: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false
      });
      var field = new THREE.Points(geo, mat);
      starFields.push(field);
      scene.add(field);
    });

    // ── Lighting ──
    scene.add(new THREE.AmbientLight(0x15152a, 0.3));

    // Main sun (warm)
    var sun = new THREE.DirectionalLight(0xfff0e0, 2.0);
    sun.position.set(5, 3, 5);
    scene.add(sun);

    // Dark side fill (cold blue, simulates reflected light)
    var fill = new THREE.DirectionalLight(0x1a3866, 0.4);
    fill.position.set(-5, -2, -4);
    scene.add(fill);

    // Top rim (atmosphere scatter)
    var rim = new THREE.DirectionalLight(0x4488ff, 0.2);
    rim.position.set(0, 5, -1);
    scene.add(rim);

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
      starFields[i].rotation.x += 0.00001 * (i + 1);
    }

    // ── Scroll-driven camera ──
    if (camera && earth) {
      // Orbit camera around earth: 0 → ~300 degrees
      var angle = scrollProgress * Math.PI * 1.7;
      var radius = 3.5 - scrollProgress * 0.8; // zoom in slightly
      var targetX = Math.sin(angle) * radius;
      var targetZ = Math.cos(angle) * radius;
      var targetY = scrollProgress * 1.8; // rise up

      camera.position.x += (targetX - camera.position.x) * 0.03;
      camera.position.y += (targetY - camera.position.y) * 0.03;
      camera.position.z += (targetZ - camera.position.z) * 0.03;
      camera.lookAt(0, 0, 0);

      earth.rotation.x = scrollProgress * 0.25;
    }

    if (renderer && scene && camera) {
      renderer.render(scene, camera);
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
    if (typeof THREE === 'undefined') initScroll();
  }, 8000);

  initThree();

})();

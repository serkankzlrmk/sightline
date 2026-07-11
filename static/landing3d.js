/* ── Sightline 3D Globe — Three.js Premium Earth ── */
/* Real interactive 3D, no Sketchfab, no video */

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

  var container = document.getElementById('sketchfab-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'sketchfab-container';
    document.body.insertBefore(container, document.body.firstChild);
  }
  container.innerHTML = '';
  container.style.cssText = 'position:fixed;inset:0;z-index:0;pointer-events:none;';

  var scene, camera, renderer, earth, clouds, atmosphere, stars, glow;
  var loader = document.getElementById('loading-screen');

  function hideLoader() {
    if (loader) loader.classList.add('hidden');
  }

  function initThree() {
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
      hideLoader();
      initScroll();
      return;
    }

    scene = new THREE.Scene();

    camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.set(0, 0, 3.2);

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x050507, 1);
    container.appendChild(renderer.domElement);

    var texLoader = new THREE.TextureLoader();
    texLoader.crossOrigin = 'anonymous';

    // ── Earth (day map) ──
    var earthRadius = 1;
    var earthGeo = new THREE.SphereGeometry(earthRadius, 96, 96);

    // NASA Blue Marble textures from three.js examples CDN
    var dayMap = texLoader.load(
      'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r160/examples/textures/planets/earth_atmos_2048.jpg',
      function() { hideLoader(); },
      undefined,
      function() {
        // Fallback: solid blue globe
        if (earth) {
          earth.material = new THREE.MeshPhongMaterial({
            color: 0x0d4d80, emissive: 0x062238, shininess: 20
          });
        }
        hideLoader();
      }
    );

    var normalMap = texLoader.load(
      'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r160/examples/textures/planets/earth_normal_2048.jpg'
    );

    var specularMap = texLoader.load(
      'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r160/examples/textures/planets/earth_specular_2048.jpg'
    );

    earth = new THREE.Mesh(earthGeo, new THREE.MeshPhongMaterial({
      map: dayMap,
      normalMap: normalMap,
      specularMap: specularMap,
      shininess: 25,
      specular: new THREE.Color(0x333333)
    }));
    scene.add(earth);

    // ── Clouds layer ──
    var cloudsMap = texLoader.load(
      'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r160/examples/textures/planets/earth_clouds_1024.png'
    );
    var cloudsGeo = new THREE.SphereGeometry(earthRadius * 1.01, 64, 64);
    clouds = new THREE.Mesh(cloudsGeo, new THREE.MeshPhongMaterial({
      map: cloudsMap,
      transparent: true,
      opacity: 0.4,
      depthWrite: false
    }));
    scene.add(clouds);

    // ── Atmosphere glow (shader) ──
    var atmGeo = new THREE.SphereGeometry(earthRadius * 1.12, 64, 64);
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
        '  float intensity = pow(0.7 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 2.5);',
        '  vec3 glow = vec3(0.3, 0.6, 1.0) * intensity;',
        '  gl_FragColor = vec4(glow, intensity);',
        '}'
      ].join('\n'),
      blending: THREE.AdditiveBlending,
      side: THREE.BackSide,
      transparent: true
    });
    atmosphere = new THREE.Mesh(atmGeo, atmMat);
    scene.add(atmosphere);

    // ── Stars (5 layers for parallax) ──
    var starColors = [0xffffff, 0xffeecc, 0xccddff, 0xffffff, 0xffccaa];
    stars = [];
    for (var layer = 0; layer < 5; layer++) {
      var starGeo = new THREE.BufferGeometry();
      var count = 800 + layer * 200;
      var positions = new Float32Array(count * 3);
      var dist = 30 + layer * 20;
      for (var i = 0; i < count * 3; i += 3) {
        var theta = Math.random() * Math.PI * 2;
        var phi = Math.random() * Math.PI;
        positions[i] = dist * Math.sin(phi) * Math.cos(theta);
        positions[i + 1] = dist * Math.sin(phi) * Math.sin(theta);
        positions[i + 2] = dist * Math.cos(phi);
      }
      starGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      var starMat = new THREE.PointsMaterial({
        color: starColors[layer],
        size: 0.1 + layer * 0.05,
        transparent: true,
        opacity: 0.4 + layer * 0.1,
        sizeAttenuation: true
      });
      var starField = new THREE.Points(starGeo, starMat);
      stars.push(starField);
      scene.add(starField);
    }

    // ── Lighting ──
    scene.add(new THREE.AmbientLight(0x202030, 0.4));

    var sun = new THREE.DirectionalLight(0xfff5e0, 1.5);
    sun.position.set(5, 2, 4);
    scene.add(sun);

    // Dark side rim light
    var darkLight = new THREE.DirectionalLight(0x1a3a6a, 0.3);
    darkLight.position.set(-4, -1, -3);
    scene.add(darkLight);

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

    if (earth) {
      // Base slow rotation
      earth.rotation.y += 0.0006;
    }

    if (clouds) {
      // Clouds rotate slightly faster
      clouds.rotation.y += 0.0009;
    }

    if (stars.length) {
      for (var i = 0; i < stars.length; i++) {
        stars[i].rotation.y += 0.00005 * (i + 1);
        stars[i].rotation.x += 0.00002 * (i + 1);
      }
    }

    // Scroll-driven camera movement
    if (camera && earth) {
      // Camera orbits around earth as user scrolls
      var angle = scrollProgress * Math.PI * 1.8; // ~324 degrees
      var targetX = Math.sin(angle) * 3.2;
      var targetZ = Math.cos(angle) * 3.2;
      var targetY = 0.5 + scrollProgress * 2.0; // moves up as scrolling down

      camera.position.x += (targetX - camera.position.x) * 0.04;
      camera.position.y += (targetY - camera.position.y) * 0.04;
      camera.position.z += (targetZ - camera.position.z) * 0.04;
      camera.lookAt(0, 0, 0);

      // Tilt earth slightly based on scroll for drama
      earth.rotation.x = scrollProgress * 0.3;
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

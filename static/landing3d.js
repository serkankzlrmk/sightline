/* ── Sightline 3D Landing — Final Version ── */
/* Scroll-snap sections + Three.js + IntersectionObserver + video redirect */

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

  var container = document.getElementById('sketchfab-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'sketchfab-container';
    document.body.insertBefore(container, document.body.firstChild);
  }
  container.innerHTML = '';
  container.style.cssText = 'position:fixed;inset:0;z-index:0;pointer-events:none;transition:opacity 1s ease;';

  var scene, camera, renderer, earth, clouds, atmosphere;
  var starFields = [];
  var loader = document.getElementById('loading-screen');
  var dayMaterial;
  var targetCameraPos = { x: 0, y: -4, z: 0.5 };
  var targetLookAt = { x: 0, y: 5, z: 0 };
  var currentLookAt = { x: 0, y: 5, z: 0 };
  var earthVisible = false;

  // Camera positions for each section
  // Camera starts at angle 0 (facing prime meridian / Greenwich)
  // Earth texture is rotated -35° so Turkey (35°E) faces camera at start
  // Earth rotates eastward (positive Y) = west to east (natural)
  var turkeyOffset = -120 * Math.PI / 180; // Turkey/Europe faces camera (rotate ~120° east)
  var sectionCameras = [
    // Section 0: Hero — looking up at stars, earth hidden
    { pos: { x: 0, y: -4, z: 0.5 }, look: { x: 0, y: 5, z: 0 }, earth: false },
    // Section 1-5: Earth visible, camera fixed looking at earth, it keeps spinning
    { pos: { x: 0, y: 0, z: 2.2 }, look: { x: 0, y: 0, z: 0 }, earth: true },
    { pos: { x: 0, y: 0, z: 2.2 }, look: { x: 0, y: 0, z: 0 }, earth: true },
    { pos: { x: 0, y: 0, z: 2.2 }, look: { x: 0, y: 0, z: 0 }, earth: true },
    { pos: { x: 0, y: 0, z: 2.2 }, look: { x: 0, y: 0, z: 0 }, earth: true },
    { pos: { x: 0, y: 0, z: 2.2 }, look: { x: 0, y: 0, z: 0 }, earth: true },
    // Section 6: CTA — back to stars, earth hidden
    { pos: { x: 0, y: -4, z: 0.5 }, look: { x: 0, y: 5, z: 0 }, earth: false }
  ];

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
    camera.position.set(0, -4, 0.5);
    camera.lookAt(0, 5, 0);

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x0a0515, 1); // Deep purple-black (milky way)
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.8;
    container.appendChild(renderer.domElement);

    var texLoader = new THREE.TextureLoader();
    texLoader.crossOrigin = 'anonymous';
    var base = '/static/textures/';

    var texturesLoaded = 0;
    var totalTextures = 5; // albedo + night + ocean + clouds + bump

    function onTex() {
      texturesLoaded++;
      if (texturesLoaded >= totalTextures) {
        hideLoader();
        initScroll();
      }
    }

    var dayTex = texLoader.load(base + 'earth_albedo.jpg', onTex);
    dayTex.colorSpace = THREE.SRGBColorSpace;
    dayTex.anisotropy = 16;

    var nightTex = texLoader.load(base + 'earth_night_lights.png', onTex);
    nightTex.colorSpace = THREE.SRGBColorSpace;

    var specTex = texLoader.load(base + 'earth_ocean_mask.png', onTex);
    specTex.anisotropy = 8;

    var cloudsTex = texLoader.load(base + 'earth_clouds.jpg', onTex);
    cloudsTex.colorSpace = THREE.SRGBColorSpace;

    var bumpTex = texLoader.load(base + 'earth_bump.jpg', onTex);

    // ── Earth shader ──
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
        '  vec3 dayColor = texture2D(dayTexture, vUv).rgb * 1.3;',
        '  vec3 nightColor = texture2D(nightTexture, vUv).rgb * 1.2;',
        '  float specular = texture2D(specularMap, vUv).r;',
        '  float bump = texture2D(bumpTexture, vUv).r;',
        '  dayColor *= 0.8 + bump * 0.4;',
        '  float dayAmount = max(dot(vNormal, sunDirection), 0.0);',
        '  vec3 color = mix(nightColor, dayColor, smoothstep(0.0, 0.7, dayAmount));',
        '  float specHighlight = pow(max(dot(reflect(-sunDirection, vNormal), vec3(0,0,1)), 0.0), 20.0) * specular * dayAmount;',
        '  color += vec3(0.6, 0.7, 0.9) * specHighlight * 0.2;',
        '  color = mix(color, nightColor * 0.5, nightMix);',
        '  gl_FragColor = vec4(color, 1.0);',
        '}'
      ].join('\n')
    });

    earth = new THREE.Mesh(earthGeo, dayMaterial);
    earth.rotation.y = turkeyOffset; // -35° so Turkey faces camera
    earth.visible = false;
    scene.add(earth);

    // ── Clouds ──
    var cloudsGeo = new THREE.SphereGeometry(1.015, 96, 96);
    clouds = new THREE.Mesh(cloudsGeo, new THREE.MeshPhongMaterial({
      map: cloudsTex, transparent: true, opacity: 0.25, depthWrite: false, blending: THREE.NormalBlending
    }));
    clouds.visible = false;
    scene.add(clouds);

    // ── Atmosphere ──
    atmosphere = new THREE.Mesh(
      new THREE.SphereGeometry(1.15, 64, 64),
      new THREE.ShaderMaterial({
        vertexShader: 'varying vec3 vNormal; void main() { vNormal = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
        fragmentShader: 'varying vec3 vNormal; void main() { float i = pow(0.4 - dot(vNormal, vec3(0,0,1)), 3.0); gl_FragColor = vec4(vec3(0.1,0.3,0.7)*i, i*0.5); }',
        blending: THREE.AdditiveBlending, side: THREE.BackSide, transparent: true
      })
    );
    atmosphere.visible = false;
    scene.add(atmosphere);

    // Inner atmosphere haze
    var innerGlow = new THREE.Mesh(
      new THREE.SphereGeometry(1.02, 64, 64),
      new THREE.ShaderMaterial({
        vertexShader: 'varying vec3 vNormal; void main() { vNormal = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
        fragmentShader: 'varying vec3 vNormal; void main() { float i = pow(0.5 - dot(vNormal, vec3(0,0,1)), 3.5); gl_FragColor = vec4(vec3(0.1,0.3,0.6)*i, i*0.4); }',
        blending: THREE.AdditiveBlending, side: THREE.FrontSide, transparent: true
      })
    );
    innerGlow.visible = false;
    innerGlow.name = 'innerGlow';
    scene.add(innerGlow);

    // ── Nebula cloud (purple/magenta diffuse particles) ──
    var nebulaGeo = new THREE.BufferGeometry();
    var nebulaCount = 800;
    var nebulaPos = new Float32Array(nebulaCount * 3);
    var nebulaColors = new Float32Array(nebulaCount * 3);
    for (var i = 0; i < nebulaCount; i++) {
      // Spread in a band (galactic plane)
      var theta = Math.random() * Math.PI * 2;
      var radius = 30 + Math.random() * 40;
      var height = (Math.random() - 0.5) * 15;
      nebulaPos[i*3] = radius * Math.cos(theta);
      nebulaPos[i*3+1] = height;
      nebulaPos[i*3+2] = radius * Math.sin(theta);
      // Purple to pink to blue gradient
      var t = Math.random();
      if (t < 0.4) { // purple
        nebulaColors[i*3] = 0.5; nebulaColors[i*3+1] = 0.2; nebulaColors[i*3+2] = 0.8;
      } else if (t < 0.7) { // pink/magenta
        nebulaColors[i*3] = 0.9; nebulaColors[i*3+1] = 0.3; nebulaColors[i*3+2] = 0.7;
      } else { // blue
        nebulaColors[i*3] = 0.3; nebulaColors[i*3+1] = 0.4; nebulaColors[i*3+2] = 0.9;
      }
    }
    nebulaGeo.setAttribute('position', new THREE.BufferAttribute(nebulaPos, 3));
    nebulaGeo.setAttribute('color', new THREE.BufferAttribute(nebulaColors, 3));
    var nebulaMat = new THREE.PointsMaterial({
      size: 3.0,
      transparent: true,
      opacity: 0.08,
      sizeAttenuation: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      vertexColors: true
    });
    var nebula = new THREE.Points(nebulaGeo, nebulaMat);
    starFields.push(nebula);
    scene.add(nebula);
    var starConfigs = [
      { count: 1500, dist: 40, size: 0.08, color: 0xffffff, opacity: 0.9 },
      { count: 1000, dist: 60, size: 0.12, color: 0xddccff, opacity: 0.6 }, // purple tint
      { count: 500, dist: 80, size: 0.18, color: 0xffaadd, opacity: 0.4 }   // pink/magenta
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
    scene.add(new THREE.AmbientLight(0x606080, 1.0));
    var sun = new THREE.DirectionalLight(0xfff5e0, 3.5);
    sun.position.set(5, 3, 5);
    scene.add(sun);
    var fill = new THREE.DirectionalLight(0x6699ff, 0.8);
    fill.position.set(-5, -2, -4);
    scene.add(fill);

    // ── Resize ──
    window.addEventListener('resize', function() {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    });

    // ── Set initial camera (Section 0: intro image + stars) ──
    targetCameraPos = { x: 0, y: -4, z: 0.5 };
    targetLookAt = { x: 0, y: 5, z: 0 };
    currentSection = 0;

    // Show intro image on LAST section (section 6), not first
    // First section: stars + galaxy colors (purple/milky way)
    var introImg = document.getElementById('intro-bg');
    if (introImg) introImg.style.opacity = '0'; // hidden on first load

    // Start animation loop immediately (renders stars while textures load)
    animate();
    // initScroll() is called when all textures finish loading (onTex callback)
  }

  function animate() {
    requestAnimationFrame(animate);

    if (earth) earth.rotation.y += 0.0005;
    if (clouds) clouds.rotation.y += 0.0007;
    for (var i = 0; i < starFields.length; i++) {
      starFields[i].rotation.y += 0.00003 * (i + 1);
    }

    // Smooth camera lerp — faster for responsive feel
    camera.position.x += (targetCameraPos.x - camera.position.x) * 0.06;
    camera.position.y += (targetCameraPos.y - camera.position.y) * 0.06;
    camera.position.z += (targetCameraPos.z - camera.position.z) * 0.06;

    currentLookAt.x += (targetLookAt.x - currentLookAt.x) * 0.06;
    currentLookAt.y += (targetLookAt.y - currentLookAt.y) * 0.06;
    currentLookAt.z += (targetLookAt.z - currentLookAt.z) * 0.06;
    camera.lookAt(currentLookAt.x, currentLookAt.y, currentLookAt.z);

    // Earth visibility
    if (earth) earth.visible = earthVisible;
    if (clouds) clouds.visible = earthVisible;
    if (atmosphere) atmosphere.visible = earthVisible;
    var ig = scene.getObjectByName('innerGlow');
    if (ig) ig.visible = earthVisible;

    // SITREP section darken
    if (dayMaterial && dayMaterial.uniforms && currentSection === 2) {
      dayMaterial.uniforms.nightMix.value += (0.5 - dayMaterial.uniforms.nightMix.value) * 0.05;
    } else if (dayMaterial && dayMaterial.uniforms) {
      dayMaterial.uniforms.nightMix.value += (0.0 - dayMaterial.uniforms.nightMix.value) * 0.05;
    }

    if (renderer && scene && camera) renderer.render(scene, camera);
  }

  // ── Scroll + IntersectionObserver ──
  function initScroll() {
    var sections = document.querySelectorAll('.lp-section');
    var spFill = document.getElementById('sp-fill');
    var spDotsContainer = document.getElementById('sp-dots');
    var scrollContainer = document.getElementById('scroll-container');

    // Create progress dots
    if (spDotsContainer) {
      for (var i = 0; i < NUM_SECTIONS; i++) {
        var dot = document.createElement('div');
        dot.className = 'sp-dot' + (i === 0 ? ' active' : '');
        spDotsContainer.appendChild(dot);
      }
    }
    var dots = spDotsContainer ? spDotsContainer.querySelectorAll('.sp-dot') : [];

    // Section 0 is already active
    currentSection = 0;

    // IntersectionObserver for section detection — trigger early for smooth transitions
    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting && entry.intersectionRatio > 0.25) {
          var section = parseInt(entry.target.dataset.section);
          if (section !== currentSection) {
            activateSection(section, sections, dots);
          }
        }
      });
    }, {
      root: scrollContainer,
      threshold: [0, 0.25, 0.5, 0.75, 1]
    });

    sections.forEach(function(s) { observer.observe(s); });

    // Progress bar + nav hide + scroll hint hide
    if (scrollContainer) {
      scrollContainer.addEventListener('scroll', function() {
        var max = scrollContainer.scrollHeight - scrollContainer.clientHeight;
        var progress = max > 0 ? scrollContainer.scrollTop / max : 0;
        if (spFill) spFill.style.height = (progress * 100) + '%';
        // Hide nav login button after scrolling past hero
        var nav = document.querySelector('.lp-nav');
        if (nav) {
          if (scrollContainer.scrollTop > 100) {
            nav.style.opacity = '0';
            nav.style.pointerEvents = 'none';
          } else {
            nav.style.opacity = '1';
            nav.style.pointerEvents = 'auto';
          }
        }
        // Hide "Explore" hint after scrolling
        var hint = document.getElementById('scroll-hint-hero');
        if (hint) {
          if (scrollContainer.scrollTop > 50) {
            hint.style.opacity = '0';
          } else {
            hint.style.opacity = '1';
          }
        }
      }, { passive: true });
    }

    // ── Video overlay: Start Free buttons ──
    var ctaButtons = document.querySelectorAll('.lp-cta-start');
    ctaButtons.forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        e.preventDefault();

        // Check if intro video exists
        var video = document.getElementById('intro-video');
        var source = video ? video.querySelector('source') : null;

        if (video && source && source.src) {
          // Try to play video
          var overlay = document.getElementById('video-overlay');
          if (overlay) {
            overlay.classList.add('active');
            video.play().then(function() {
              // Video playing
              video.onended = function() {
                window.location.href = '/app';
              };
            }).catch(function() {
              // Video failed — go directly to app
              window.location.href = '/app';
            });

            // Fallback: if video doesn't end in 15s, redirect
            setTimeout(function() {
              if (overlay.classList.contains('active')) {
                window.location.href = '/app';
              }
            }, 15000);
          }
        } else {
          // No video — go directly to app
          window.location.href = '/app';
        }
      });
    });

    // Nav login
    var navLogin = document.querySelector('.lp-nav-cta a');
    if (navLogin) {
      navLogin.addEventListener('click', function(e) {
        // Normal link behavior — go to /app
      });
    }
  }

  function activateSection(index, sections, dots) {
    // Update sections
    sections.forEach(function(s) { s.classList.remove('active'); });
    if (sections[index]) sections[index].classList.add('active');

    // Update dots
    dots.forEach(function(d) { d.classList.remove('active'); });
    if (dots[index]) dots[index].classList.add('active');

    // Update camera target
    var cam = sectionCameras[index];
    if (cam) {
      targetCameraPos = { x: cam.pos.x, y: cam.pos.y, z: cam.pos.z };
      targetLookAt = { x: cam.look.x, y: cam.look.y, z: cam.look.z };
      earthVisible = cam.earth;
    }

    // Fade intro image in on LAST section, out on others
    var introImg = document.getElementById('intro-bg');
    if (introImg) {
      if (index === 6) {
        introImg.style.opacity = '1';
      } else {
        introImg.style.opacity = '0';
      }
    }

    currentSection = index;
  }

  // ── Start ──
  // Fallback: if textures don't load in 15s, proceed anyway
  setTimeout(function() {
    hideLoader();
    if (currentSection === 0 && typeof THREE !== 'undefined') {
      initScroll();
    }
  }, 15000);

  initThree();

})();

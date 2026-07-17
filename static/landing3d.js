/* ── Sightline 3D Landing — Final Version ── */
/* Scroll-snap sections + Three.js + IntersectionObserver + video redirect */

(function() {
  'use strict';

  // ── Rose Curve Loading Animation ──
  var SVG_NS = 'http://www.w3.org/2000/svg';
  var roseConfig = {
    rotate: true,
    particleCount: 64,
    trailSpan: 0.38,
    durationMs: 4600,
    rotationDurationMs: 28000,
    pulseDurationMs: 4200,
    strokeWidth: 5.5,
    baseRadius: 7,
    detailAmplitude: 3,
    petalCount: 7,
    curveScale: 3.9,
    point: function(progress, detailScale, config) {
      var t = progress * Math.PI * 2;
      var petals = Math.round(config.petalCount);
      var x = config.baseRadius * Math.cos(t) - config.detailAmplitude * detailScale * Math.cos(petals * t);
      var y = config.baseRadius * Math.sin(t) - config.detailAmplitude * detailScale * Math.sin(petals * t);
      return { x: 50 + x * config.curveScale, y: 50 + y * config.curveScale };
    }
  };

  var roseGroup = document.querySelector('#ls-group');
  var rosePath = document.querySelector('#ls-path');
  var roseParticles = [];
  var roseStartedAt = 0;
  var roseActive = true;

  if (rosePath) {
    rosePath.setAttribute('stroke-width', String(roseConfig.strokeWidth));
    for (var i = 0; i < roseConfig.particleCount; i++) {
      var circle = document.createElementNS(SVG_NS, 'circle');
      circle.setAttribute('fill', 'currentColor');
      roseGroup.appendChild(circle);
      roseParticles.push(circle);
    }
    roseStartedAt = performance.now();
    requestAnimationFrame(renderRose);
  }

  function normalizeProgress(progress) {
    return ((progress % 1) + 1) % 1;
  }

  function getDetailScale(time) {
    var pulseProgress = (time % roseConfig.pulseDurationMs) / roseConfig.pulseDurationMs;
    var pulseAngle = pulseProgress * Math.PI * 2;
    return 0.52 + ((Math.sin(pulseAngle + 0.55) + 1) / 2) * 0.48;
  }

  function getRoseRotation(time) {
    if (!roseConfig.rotate) return 0;
    return -((time % roseConfig.rotationDurationMs) / roseConfig.rotationDurationMs) * 360;
  }

  function buildRosePath(detailScale, steps) {
    steps = steps || 480;
    var points = [];
    for (var i = 0; i <= steps; i++) {
      var p = roseConfig.point(i / steps, detailScale, roseConfig);
      points.push((i === 0 ? 'M' : 'L') + ' ' + p.x.toFixed(2) + ' ' + p.y.toFixed(2));
    }
    return points.join(' ');
  }

  function getRoseParticle(index, progress, detailScale) {
    var tailOffset = index / (roseConfig.particleCount - 1);
    var p = roseConfig.point(normalizeProgress(progress - tailOffset * roseConfig.trailSpan), detailScale, roseConfig);
    var fade = Math.pow(1 - tailOffset, 0.56);
    return {
      x: p.x, y: p.y,
      radius: 0.9 + fade * 2.7,
      opacity: 0.04 + fade * 0.96
    };
  }

  function renderRose(now) {
    if (!roseActive) return;
    var time = now - roseStartedAt;
    var progress = (time % roseConfig.durationMs) / roseConfig.durationMs;
    var detailScale = getDetailScale(time);
    roseGroup.setAttribute('transform', 'rotate(' + getRoseRotation(time) + ' 50 50)');
    rosePath.setAttribute('d', buildRosePath(detailScale));
    for (var i = 0; i < roseParticles.length; i++) {
      var p = getRoseParticle(i, progress, detailScale);
      roseParticles[i].setAttribute('cx', p.x.toFixed(2));
      roseParticles[i].setAttribute('cy', p.y.toFixed(2));
      roseParticles[i].setAttribute('r', p.radius.toFixed(2));
      roseParticles[i].setAttribute('opacity', p.opacity.toFixed(3));
    }
    requestAnimationFrame(renderRose);
  }

  function stopRose() {
    roseActive = false;
  }

  var NUM_SECTIONS = 7;
  var currentSection = -1;
  var scrollInitialized = false;
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var lowPowerDevice = window.innerWidth <= 600 || (navigator.deviceMemory && navigator.deviceMemory <= 4) || (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 4);

  function preferredPixelRatio() {
    return Math.min(window.devicePixelRatio || 1, lowPowerDevice ? 1.2 : 1.5);
  }

  var container = document.getElementById('sketchfab-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'sketchfab-container';
    document.body.insertBefore(container, document.body.firstChild);
  }
  container.innerHTML = '';
  container.style.cssText = 'position:fixed;inset:0;z-index:1;pointer-events:none;transition:opacity 1s ease;';

  var scene, camera, renderer, earth, clouds, horizonGroup, horizonSurface;
  var horizonWorld, horizonWire, horizonChromeLight;
  var horizonSignalNodes = [];
  var horizonMaterials = [];
  var horizonBaseScale = 1;
  var horizonOpacity = 0;
  var horizonTargetOpacity = 0;
  var horizonHover = 0;
  var horizonHoverTarget = 0;
  var portalProximity = 0;
  var portalProximityTarget = 0;
  var pointerTarget = { x: 0, y: 0 };
  var pointerCurrent = { x: 0, y: 0 };
  var pointerVelocity = { x: 0, y: 0 };
  var pointerVelocityTarget = { x: 0, y: 0 };
  var lastPointer = { x: window.innerWidth / 2, y: window.innerHeight / 2, time: performance.now() };
  var portalButton = null;
  var starFields = [];
  var sectionVisualRoot, sectionVisuals = [];
  var heroEarthShadow, heroEarthShadowMaterial, heroSignalGroup;
  var heroSignalNodes = [];
  var heroSignalCoreMaterial, heroSignalGlowMaterial;
  var heroDetailOpacity = 1;
  var loader = document.getElementById('loading-screen');
  var dayMaterial;
  var targetCameraPos = { x: 0, y: 0, z: 7.2 };
  var targetLookAt = { x: 0, y: 0, z: 0 };
  var currentLookAt = { x: 0, y: 0, z: 0 };
  var targetEarthScale = 1;
  var targetEarthPosition = { x: 0, y: 0, z: 0 };
  var finalConvergenceStartedAt = 0;
  var earthVisible = false;

  // Camera positions for each section
  // Camera starts at angle 0 (facing prime meridian / Greenwich)
  // Earth texture is rotated -35° so Turkey (35°E) faces camera at start
  // Earth rotates eastward (positive Y) = west to east (natural)
  var turkeyOffset = -120 * Math.PI / 180; // Turkey/Europe faces camera (rotate ~120° east)
  var sectionCameras = [
    // Section 0: the same earth starts in the pearl studio hero.
    { pos: { x: 0, y: 0, z: 7.2 }, look: { x: 0, y: 0, z: 0 }, earth: true },
    // Section 1-5: one locked observatory composition. Scroll changes the story, not the globe frame.
    { pos: { x: 0.34, y: 0.20, z: 3.55 }, look: { x: -0.72, y: 0.02, z: 0 }, earth: true },
    { pos: { x: 0.34, y: 0.20, z: 3.55 }, look: { x: -0.72, y: 0.02, z: 0 }, earth: true },
    { pos: { x: 0.34, y: 0.20, z: 3.55 }, look: { x: -0.72, y: 0.02, z: 0 }, earth: true },
    { pos: { x: 0.34, y: 0.20, z: 3.55 }, look: { x: -0.72, y: 0.02, z: 0 }, earth: true },
    { pos: { x: 0.34, y: 0.20, z: 3.55 }, look: { x: -0.72, y: 0.02, z: 0 }, earth: true },
    // Section 6: the earth recedes into the final signal lockup.
    { pos: { x: 0, y: 0.08, z: 7.8 }, look: { x: 0, y: 0.48, z: 0 }, earth: true }
  ];

  function hideLoader() {
    if (loader) loader.classList.add('hidden');
    stopRose();
  }

  function initThree() {
    if (window.THREE) {
      startScene();
      return;
    }
    var script = document.createElement('script');
    script.src = '/static/vendor/three.min.js';
    script.onload = startScene;
    script.onerror = function() { hideLoader(); initScroll(); };
    document.head.appendChild(script);
  }

  function rememberHorizonMaterial(material, baseOpacity) {
    material.transparent = true;
    material.opacity = baseOpacity;
    material.userData.baseOpacity = baseOpacity;
    horizonMaterials.push(material);
    return material;
  }

  function globePoint(latitude, longitude, radius) {
    var lat = latitude * Math.PI / 180;
    var lon = longitude * Math.PI / 180;
    return new THREE.Vector3(
      radius * Math.cos(lat) * Math.sin(lon),
      radius * Math.sin(lat),
      radius * Math.cos(lat) * Math.cos(lon)
    );
  }

  function createGlowTexture(colorStops) {
    var canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 128;
    var context = canvas.getContext('2d');
    var gradient = context.createRadialGradient(64, 64, 0, 64, 64, 64);
    for (var stopIndex = 0; stopIndex < colorStops.length; stopIndex++) {
      gradient.addColorStop(colorStops[stopIndex][0], colorStops[stopIndex][1]);
    }
    context.fillStyle = gradient;
    context.fillRect(0, 0, 128, 128);
    var texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;
    return texture;
  }

  function createHorizon() {
    horizonGroup = new THREE.Group();
    horizonGroup.name = 'sightline-world';
    scene.add(horizonGroup);

    horizonWorld = new THREE.Group();
    horizonWorld.rotation.set(0.04, -0.18, -0.07);
    horizonGroup.add(horizonWorld);

    var textureLoader = new THREE.TextureLoader();
    var oceanMap = textureLoader.load('/static/textures/earth_ocean_mask.png');
    oceanMap.anisotropy = 8;
    var bumpMap = textureLoader.load('/static/textures/earth_bump.jpg');
    bumpMap.anisotropy = 8;
    var globeSegments = window.innerWidth <= 600 ? 72 : 144;
    var globeGeometry = new THREE.SphereGeometry(1.58, globeSegments, globeSegments);
    var globeMaterial = rememberHorizonMaterial(new THREE.ShaderMaterial({
      uniforms: {
        oceanMap: { value: oceanMap },
        bumpMap: { value: bumpMap },
        keyDirection: { value: new THREE.Vector3(-0.55, 0.72, 0.85).normalize() },
        pointerLight: { value: new THREE.Vector3(-0.4, 0.35, 1).normalize() },
        opacity: { value: 1 }
      },
      vertexShader: [
        'uniform sampler2D oceanMap;',
        'uniform sampler2D bumpMap;',
        'varying vec2 vUv;',
        'varying vec3 vNormal;',
        'varying vec3 vViewPosition;',
        'varying float vLand;',
        'void main() {',
        '  vUv = uv;',
        '  float ocean = texture2D(oceanMap, uv).r;',
        '  vLand = smoothstep(0.34, 0.68, ocean);',
        '  float relief = texture2D(bumpMap, uv).r;',
        '  vec3 displaced = position + normal * (vLand * (0.018 + relief * 0.035));',
        '  vec4 mvPosition = modelViewMatrix * vec4(displaced, 1.0);',
        '  vViewPosition = -mvPosition.xyz;',
        '  vNormal = normalize(mat3(modelMatrix) * normal);',
        '  gl_Position = projectionMatrix * mvPosition;',
        '}'
      ].join('\n'),
      fragmentShader: [
        'uniform sampler2D oceanMap;',
        'uniform vec3 keyDirection;',
        'uniform vec3 pointerLight;',
        'uniform float opacity;',
        'varying vec2 vUv;',
        'varying vec3 vNormal;',
        'varying vec3 vViewPosition;',
        'varying float vLand;',
        'void main() {',
        '  vec3 n = normalize(vNormal);',
        '  vec3 viewDir = normalize(vViewPosition);',
        '  float key = max(dot(n, keyDirection), 0.0);',
        '  float follow = pow(max(dot(n, pointerLight), 0.0), 2.0);',
        '  float rim = pow(1.0 - max(dot(n, viewDir), 0.0), 2.5);',
        '  float latitude = abs(fract(vUv.y * 18.0) - 0.5);',
        '  float longitude = abs(fract(vUv.x * 36.0) - 0.5);',
        '  float grid = (1.0 - smoothstep(0.46, 0.5, max(latitude, longitude))) * 0.055;',
        '  float landMask = smoothstep(0.22, 0.78, texture2D(oceanMap, vUv).r);',
        '  vec3 ocean = vec3(0.035, 0.043, 0.052) + key * vec3(0.075, 0.085, 0.10);',
        '  vec3 land = vec3(0.34, 0.36, 0.39) + key * vec3(0.40, 0.41, 0.43) + follow * 0.08;',
        '  vec3 color = mix(ocean, land, landMask);',
        '  color += vec3(grid) + rim * vec3(0.22, 0.24, 0.27);',
        '  gl_FragColor = vec4(color, opacity);',
        '}'
      ].join('\n'),
      transparent: true
    }), 1);
    globeMaterial.userData.opacityUniform = globeMaterial.uniforms.opacity;
    horizonSurface = new THREE.Mesh(globeGeometry, globeMaterial);
    horizonSurface.rotation.y = -2.08;
    horizonSurface.renderOrder = 1;
    horizonWorld.add(horizonSurface);

    var wireMaterial = rememberHorizonMaterial(new THREE.MeshBasicMaterial({
      color: 0xc9cdd4,
      wireframe: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    }), 0.07);
    wireMaterial.userData.hoverBoost = 0.06;
    horizonWire = new THREE.Mesh(new THREE.SphereGeometry(1.615, 32, 18), wireMaterial);
    horizonWire.rotation.y = 0.035;
    horizonWorld.add(horizonWire);

    var shellMaterial = rememberHorizonMaterial(new THREE.MeshPhysicalMaterial({
      color: 0x68717e,
      metalness: 0.05,
      roughness: 0.12,
      transmission: 0.12,
      clearcoat: 1,
      clearcoatRoughness: 0.08,
      depthWrite: false,
      side: THREE.FrontSide
    }), 0.14);
    shellMaterial.userData.hoverBoost = 0.04;
    var shell = new THREE.Mesh(new THREE.SphereGeometry(1.635, 72, 72), shellMaterial);
    shell.renderOrder = 3;
    horizonWorld.add(shell);

    var nodeGlowTexture = createGlowTexture([
      [0, 'rgba(255, 116, 133, 0.95)'],
      [0.18, 'rgba(232, 54, 78, 0.58)'],
      [0.52, 'rgba(232, 54, 78, 0.14)'],
      [1, 'rgba(232, 54, 78, 0)']
    ]);
    var nodeLocations = [
      { lat: 47, lon: -38, size: 0.15, phase: 0.4, speed: 0.0017 },
      { lat: 24, lon: -12, size: 0.12, phase: 2.1, speed: 0.0021 },
      { lat: -7, lon: 15, size: 0.18, phase: 4.8, speed: 0.0014 },
      { lat: 34, lon: 31, size: 0.11, phase: 1.2, speed: 0.0024 },
      { lat: -31, lon: -24, size: 0.13, phase: 3.5, speed: 0.0019 },
      { lat: 4, lon: 45, size: 0.095, phase: 5.6, speed: 0.0026 },
      { lat: 58, lon: 8, size: 0.085, phase: 2.9, speed: 0.0022 }
    ];
    for (var nodeIndex = 0; nodeIndex < nodeLocations.length; nodeIndex++) {
      var nodeConfig = nodeLocations[nodeIndex];
      var nodeCoreMaterial = rememberHorizonMaterial(new THREE.MeshBasicMaterial({
        color: 0xff6f82,
        depthTest: false,
        depthWrite: false
      }), 0.86);
      nodeCoreMaterial.userData.isSignal = true;
      var nodeCore = new THREE.Mesh(new THREE.SphereGeometry(0.018, 16, 16), nodeCoreMaterial);
      nodeCore.renderOrder = 7;

      var nodeGlowMaterial = rememberHorizonMaterial(new THREE.SpriteMaterial({
        map: nodeGlowTexture,
        color: 0xffffff,
        transparent: true,
        depthTest: false,
        depthWrite: false,
        blending: THREE.AdditiveBlending
      }), 0.5);
      nodeGlowMaterial.userData.isSignal = true;
      var nodeGlow = new THREE.Sprite(nodeGlowMaterial);
      nodeGlow.scale.setScalar(nodeConfig.size);
      nodeGlow.renderOrder = 6;

      var node = new THREE.Group();
      node.position.copy(globePoint(nodeConfig.lat, nodeConfig.lon, 1.67));
      node.add(nodeGlow);
      node.add(nodeCore);
      node.userData.phase = nodeConfig.phase;
      node.userData.speed = nodeConfig.speed;
      node.userData.baseSize = nodeConfig.size;
      node.userData.coreMaterial = nodeCoreMaterial;
      node.userData.glowMaterial = nodeGlowMaterial;
      horizonSignalNodes.push(node);
      horizonWorld.add(node);
    }

    horizonChromeLight = new THREE.PointLight(0xf2f3f5, 4.8, 8, 2);
    horizonChromeLight.position.set(-1.2, 1.8, 2.8);
    horizonGroup.add(horizonChromeLight);

    var groundTexture = createGlowTexture([
      [0, 'rgba(255, 255, 255, 0.5)'],
      [0.38, 'rgba(255, 255, 255, 0.2)'],
      [0.78, 'rgba(255, 255, 255, 0.04)'],
      [1, 'rgba(255, 255, 255, 0)']
    ]);
    var groundMaterial = rememberHorizonMaterial(new THREE.MeshBasicMaterial({
      map: groundTexture,
      color: 0x354152,
      transparent: true,
      depthWrite: false,
      depthTest: false
    }), 0.28);
    var groundReflection = new THREE.Mesh(new THREE.PlaneGeometry(3.9, 1.02), groundMaterial);
    groundReflection.position.set(0, -1.69, -0.56);
    groundReflection.renderOrder = -1;
    horizonGroup.add(groundReflection);

    var shadowTexture = createGlowTexture([
      [0, 'rgba(0, 0, 0, 0.72)'],
      [0.36, 'rgba(0, 0, 0, 0.44)'],
      [0.72, 'rgba(0, 0, 0, 0.12)'],
      [1, 'rgba(0, 0, 0, 0)']
    ]);
    var shadowMaterial = rememberHorizonMaterial(new THREE.MeshBasicMaterial({
      map: shadowTexture,
      color: 0x05070a,
      transparent: true,
      depthWrite: false,
      depthTest: false
    }), 0.88);
    var shadow = new THREE.Mesh(new THREE.PlaneGeometry(3.2, 0.72), shadowMaterial);
    shadow.position.set(0, -1.66, -0.48);
    shadow.renderOrder = 0;
    horizonGroup.add(shadow);

    layoutHorizon();
    horizonGroup.visible = false;
  }

  function layoutHorizon() {
    if (!horizonGroup) return;
    if (window.innerWidth <= 900) {
      horizonGroup.position.set(0.08, -1.02, 0.08);
      horizonBaseScale = window.innerWidth <= 600 ? 0.58 : 0.69;
    } else {
      horizonGroup.position.set(2.05, 0.08, 0);
      horizonBaseScale = 0.92;
    }
    horizonGroup.scale.setScalar(horizonBaseScale);
    horizonGroup.rotation.set(0, 0, 0);
  }

  function clamp01(value) {
    return Math.max(0, Math.min(1, value));
  }

  function updatePointerInteraction(clientX, clientY) {
    var horizonCenterX = window.innerWidth <= 900 ? window.innerWidth * 0.54 : window.innerWidth * 0.76;
    var horizonCenterY = window.innerWidth <= 900 ? window.innerHeight * 0.7 : window.innerHeight * 0.49;
    var normalizedX = (clientX - horizonCenterX) / (window.innerWidth <= 900 ? window.innerWidth * 0.48 : window.innerWidth * 0.34);
    var normalizedY = (clientY - horizonCenterY) / (window.innerHeight * 0.31);
    var horizonDistance = Math.sqrt(normalizedX * normalizedX + normalizedY * normalizedY);
    horizonHoverTarget = currentSection === 0 ? clamp01(1 - horizonDistance) : 0;

    if (!portalButton || currentSection !== 0) {
      portalProximityTarget = 0;
      return;
    }

    var portalRect = portalButton.getBoundingClientRect();
    var portalCenterX = portalRect.left + portalRect.width / 2;
    var portalCenterY = portalRect.top + portalRect.height / 2;
    var portalDeltaX = clientX - portalCenterX;
    var portalDeltaY = clientY - portalCenterY;
    var portalDistance = Math.hypot(portalDeltaX, portalDeltaY);
    portalProximityTarget = clamp01(1 - portalDistance / 260);

    var pullX = Math.max(-9, Math.min(9, portalDeltaX * 0.04 * portalProximityTarget));
    var pullY = Math.max(-5, Math.min(5, portalDeltaY * 0.03 * portalProximityTarget));
    portalButton.style.setProperty('--portal-shift-x', pullX.toFixed(2) + 'px');
    portalButton.style.setProperty('--portal-shift-y', pullY.toFixed(2) + 'px');
    document.body.classList.toggle('portal-armed', portalProximityTarget > 0.18);
  }

  function resetPointerInteraction() {
    horizonHoverTarget = 0;
    portalProximityTarget = 0;
    pointerVelocityTarget.x = 0;
    pointerVelocityTarget.y = 0;
    if (portalButton) {
      portalButton.style.setProperty('--portal-shift-x', '0px');
      portalButton.style.setProperty('--portal-shift-y', '0px');
    }
    document.body.classList.remove('portal-armed');
  }

  function getEarthStateForSection(index) {
    if (index === 0) {
      if (window.innerWidth <= 900) {
        return { scale: 0.92, position: { x: 0.12, y: -0.92, z: 0 } };
      }
      return { scale: 1.44, position: { x: 1.78, y: 0.04, z: 0 } };
    }
    if (index === 6) {
      return { scale: 0.62, position: { x: 0, y: 1.28, z: 0 } };
    }
    return { scale: 1, position: { x: 0, y: 0, z: 0 } };
  }

  function setEarthTargetForSection(index, immediate) {
    var earthState = getEarthStateForSection(index);
    targetEarthScale = earthState.scale;
    targetEarthPosition = earthState.position;
    if (!immediate || !earth) return;
    earth.scale.setScalar(targetEarthScale);
    earth.position.set(targetEarthPosition.x, targetEarthPosition.y, targetEarthPosition.z);
    if (clouds) {
      clouds.scale.copy(earth.scale);
      clouds.position.copy(earth.position);
    }
  }

  function createHeroEarthDetails() {
    var shadowTexture = createGlowTexture([
      [0, 'rgba(18, 22, 28, 0.5)'],
      [0.34, 'rgba(24, 29, 36, 0.32)'],
      [0.7, 'rgba(35, 40, 48, 0.1)'],
      [1, 'rgba(40, 44, 50, 0)']
    ]);
    heroEarthShadowMaterial = new THREE.MeshBasicMaterial({
      map: shadowTexture,
      color: 0x161b22,
      transparent: true,
      opacity: 0.24,
      depthWrite: false,
      depthTest: false
    });
    heroEarthShadow = new THREE.Mesh(new THREE.PlaneGeometry(3.2, 0.64), heroEarthShadowMaterial);
    heroEarthShadow.renderOrder = -2;
    scene.add(heroEarthShadow);

    heroSignalGroup = new THREE.Group();
    heroSignalGroup.name = 'hero-crisis-signals';
    earth.add(heroSignalGroup);

    heroSignalCoreMaterial = new THREE.MeshBasicMaterial({
      color: 0xd94258,
      transparent: true,
      opacity: 0.92,
      depthWrite: false
    });
    var signalGlowTexture = createGlowTexture([
      [0, 'rgba(226, 62, 84, 0.92)'],
      [0.2, 'rgba(218, 52, 75, 0.54)'],
      [0.58, 'rgba(205, 42, 66, 0.14)'],
      [1, 'rgba(205, 42, 66, 0)']
    ]);
    heroSignalGlowMaterial = new THREE.SpriteMaterial({
      map: signalGlowTexture,
      color: 0xd94258,
      transparent: true,
      opacity: 0.5,
      depthWrite: false,
      depthTest: true,
      blending: THREE.AdditiveBlending
    });

    var visibleSignalVectors = [
      [-0.48, 0.54, 0.72], [0.22, 0.66, 0.72], [0.62, 0.18, 0.76],
      [-0.12, 0.03, 0.99], [0.42, -0.38, 0.82], [-0.58, -0.24, 0.78],
      [0.06, -0.66, 0.76]
    ];
    for (var heroSignalIndex = 0; heroSignalIndex < visibleSignalVectors.length; heroSignalIndex++) {
      var signalVector = visibleSignalVectors[heroSignalIndex];
      var worldFacingPoint = new THREE.Vector3(signalVector[0], signalVector[1], signalVector[2]).normalize();
      worldFacingPoint.applyAxisAngle(new THREE.Vector3(0, 1, 0), -turkeyOffset).multiplyScalar(1.025);
      var signalNode = new THREE.Group();
      signalNode.position.copy(worldFacingPoint);
      signalNode.userData.phase = heroSignalIndex * 0.83;
      var core = new THREE.Mesh(new THREE.SphereGeometry(heroSignalIndex === 3 ? 0.023 : 0.016, 12, 12), heroSignalCoreMaterial);
      var glow = new THREE.Sprite(heroSignalGlowMaterial);
      glow.scale.setScalar(heroSignalIndex === 3 ? 0.17 : 0.125);
      signalNode.add(glow);
      signalNode.add(core);
      heroSignalGroup.add(signalNode);
      heroSignalNodes.push(signalNode);
    }
  }

  function animateHeroEarthDetails(time) {
    if (!heroEarthShadow || !heroSignalGroup) return;
    var targetDetailOpacity = currentSection === 0 ? 1 : 0;
    heroDetailOpacity += (targetDetailOpacity - heroDetailOpacity) * 0.075;
    heroEarthShadow.visible = heroDetailOpacity > 0.01;
    heroSignalGroup.visible = heroDetailOpacity > 0.01;
    heroEarthShadowMaterial.opacity = 0.24 * heroDetailOpacity;
    heroSignalCoreMaterial.opacity = 0.92 * heroDetailOpacity;
    heroSignalGlowMaterial.opacity = 0.5 * heroDetailOpacity;

    if (earth) {
      heroEarthShadow.position.set(earth.position.x, earth.position.y - earth.scale.y * 1.04, earth.position.z - 0.16);
      heroEarthShadow.scale.set(earth.scale.x * 1.16, earth.scale.y * 0.46, 1);
    }
    for (var signalIndex = 0; signalIndex < heroSignalNodes.length; signalIndex++) {
      var signalPulse = reduceMotion ? 1 : 0.88 + (Math.sin(time * 0.0022 + heroSignalNodes[signalIndex].userData.phase) + 1) * 0.12;
      heroSignalNodes[signalIndex].scale.setScalar(signalPulse);
    }
  }

  function visualMaterial(group, material, baseOpacity) {
    material.transparent = true;
    material.opacity = 0;
    material.depthWrite = false;
    material.userData.baseOpacity = baseOpacity;
    group.userData.materials.push(material);
    return material;
  }

  function makeEllipseLine(group, radiusX, radiusY, material, segments) {
    var positions = [];
    var count = segments || 128;
    for (var ellipseIndex = 0; ellipseIndex < count; ellipseIndex++) {
      var angle = ellipseIndex / count * Math.PI * 2;
      positions.push(Math.cos(angle) * radiusX, Math.sin(angle) * radiusY, 0);
    }
    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    var line = new THREE.LineLoop(geometry, material);
    group.add(line);
    return line;
  }

  function makeNode(group, position, radius, material) {
    var node = new THREE.Mesh(new THREE.SphereGeometry(radius, 12, 12), material);
    node.position.copy(position);
    group.add(node);
    return node;
  }

  function createSectionVisualGroup(name) {
    var group = new THREE.Group();
    group.name = name;
    group.visible = false;
    group.userData.opacity = 0;
    group.userData.materials = [];
    sectionVisualRoot.add(group);
    sectionVisuals.push(group);
    return group;
  }

  function createConnectedIntelligenceVisual() {
    var group = createSectionVisualGroup('connected-intelligence');
    group.scale.setScalar(0.9);
    var silver = visualMaterial(group, new THREE.LineBasicMaterial({ color: 0xaeb7c4, blending: THREE.AdditiveBlending }), 0.28);
    var faint = visualMaterial(group, new THREE.LineBasicMaterial({ color: 0x657080, blending: THREE.AdditiveBlending }), 0.17);
    var nodeMaterial = visualMaterial(group, new THREE.MeshBasicMaterial({ color: 0xb8c0cb }), 0.72);
    var signalMaterial = visualMaterial(group, new THREE.MeshBasicMaterial({ color: 0xd94359 }), 0.94);

    var orbitA = makeEllipseLine(group, 1.42, 1.18, silver, 144);
    orbitA.rotation.set(0.78, 0.22, 0.18);
    var orbitB = makeEllipseLine(group, 1.58, 1.03, faint, 144);
    orbitB.rotation.set(-0.54, 0.48, -0.22);
    var orbitC = makeEllipseLine(group, 1.33, 1.33, faint, 144);
    orbitC.rotation.set(1.18, -0.24, 0.38);
    group.userData.orbits = [orbitA, orbitB, orbitC];

    var nodePositions = [
      [-1.18, 0.72, 0.34], [-0.72, -1.18, 0.18], [0.16, 1.32, -0.22],
      [1.28, 0.62, 0.12], [1.46, -0.42, -0.18], [0.55, -1.24, 0.28],
      [-1.4, -0.18, -0.16], [0.92, 1.02, 0.2]
    ];
    group.userData.nodes = [];
    for (var connectedIndex = 0; connectedIndex < nodePositions.length; connectedIndex++) {
      var point = nodePositions[connectedIndex];
      group.userData.nodes.push(makeNode(group, new THREE.Vector3(point[0], point[1], point[2]), connectedIndex === 3 ? 0.045 : 0.025, connectedIndex === 3 ? signalMaterial : nodeMaterial));
    }
  }

  function createSitrepScanVisual() {
    var group = createSectionVisualGroup('sitrep-scan');
    group.scale.setScalar(0.93);
    var scanFill = visualMaterial(group, new THREE.MeshBasicMaterial({ color: 0x9faab8, side: THREE.DoubleSide, depthTest: true }), 0.055);
    var scanEdge = visualMaterial(group, new THREE.LineBasicMaterial({ color: 0xd84a60, blending: THREE.AdditiveBlending }), 0.72);
    var guideMaterial = visualMaterial(group, new THREE.LineBasicMaterial({ color: 0x738092, blending: THREE.AdditiveBlending }), 0.19);

    var plane = new THREE.Mesh(new THREE.CircleGeometry(1.38, 96), scanFill);
    plane.rotation.x = Math.PI / 2;
    group.add(plane);
    var ring = makeEllipseLine(group, 1.38, 1.38, scanEdge, 128);
    ring.rotation.x = Math.PI / 2;
    group.userData.scanPlane = plane;
    group.userData.scanRing = ring;

    for (var guideIndex = 0; guideIndex < 3; guideIndex++) {
      var guide = makeEllipseLine(group, 1.22 + guideIndex * 0.14, 1.22 + guideIndex * 0.14, guideMaterial, 128);
      guide.rotation.set(0.18 + guideIndex * 0.42, -0.35 + guideIndex * 0.3, guideIndex * 0.18);
    }
  }

  function createProposalStructureVisual() {
    var group = createSectionVisualGroup('proposal-structure');
    group.scale.setScalar(0.84);
    var frameMaterial = visualMaterial(group, new THREE.LineBasicMaterial({ color: 0xb7c0cc, blending: THREE.AdditiveBlending }), 0.4);
    var accentMaterial = visualMaterial(group, new THREE.LineBasicMaterial({ color: 0xd4485d, blending: THREE.AdditiveBlending }), 0.72);
    group.userData.frames = [];

    for (var frameIndex = 0; frameIndex < 4; frameIndex++) {
      var frameGeometry = new THREE.EdgesGeometry(new THREE.BoxGeometry(1.16, 1.62, 0.035));
      var frame = new THREE.LineSegments(frameGeometry, frameIndex === 2 ? accentMaterial : frameMaterial);
      frame.position.set(0.58 + frameIndex * 0.13, 0.05 - frameIndex * 0.055, -0.62 + frameIndex * 0.38);
      frame.rotation.set(-0.05, -0.34, 0.08);
      group.add(frame);
      group.userData.frames.push(frame);
    }

    var axisMaterial = visualMaterial(group, new THREE.LineBasicMaterial({ color: 0x647080 }), 0.2);
    var axisGeometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-1.3, -1.18, -0.2),
      new THREE.Vector3(1.48, 1.08, 0.28)
    ]);
    group.add(new THREE.Line(axisGeometry, axisMaterial));
  }

  function createWeeklyOrbitVisual() {
    var group = createSectionVisualGroup('weekly-orbit');
    group.scale.setScalar(0.9);
    var bandMaterial = visualMaterial(group, new THREE.MeshBasicMaterial({ color: 0x8e9aaa, side: THREE.DoubleSide }), 0.26);
    var guideMaterial = visualMaterial(group, new THREE.LineBasicMaterial({ color: 0xb8c0cb, blending: THREE.AdditiveBlending }), 0.25);
    var markerMaterial = visualMaterial(group, new THREE.MeshBasicMaterial({ color: 0xaeb7c4 }), 0.7);
    var activeMaterial = visualMaterial(group, new THREE.MeshBasicMaterial({ color: 0xd9475c }), 0.95);

    var band = new THREE.Mesh(new THREE.TorusGeometry(1.42, 0.016, 8, 128, Math.PI * 1.6), bandMaterial);
    band.rotation.set(1.1, 0.18, -0.48);
    group.add(band);
    var guide = makeEllipseLine(group, 1.52, 1.18, guideMaterial, 144);
    guide.rotation.set(1.1, 0.18, -0.48);
    group.userData.orbitBand = band;
    group.userData.weekMarkers = [];

    for (var weekIndex = 0; weekIndex < 7; weekIndex++) {
      var weekAngle = -1.05 + weekIndex * 0.34;
      var marker = makeNode(group, new THREE.Vector3(Math.cos(weekAngle) * 1.47, Math.sin(weekAngle) * 1.02, 0.28), weekIndex === 6 ? 0.042 : 0.025, weekIndex === 6 ? activeMaterial : markerMaterial);
      group.userData.weekMarkers.push(marker);
    }
  }

  function createQualityLatticeVisual() {
    var group = createSectionVisualGroup('quality-lattice');
    group.scale.setScalar(0.92);
    var latticeMaterial = visualMaterial(group, new THREE.LineBasicMaterial({ color: 0x9da8b7, blending: THREE.AdditiveBlending }), 0.24);
    var ringMaterial = visualMaterial(group, new THREE.LineBasicMaterial({ color: 0xc0c7d0, blending: THREE.AdditiveBlending }), 0.32);
    var accentMaterial = visualMaterial(group, new THREE.MeshBasicMaterial({ color: 0xd9475c }), 0.88);

    var lattice = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(1.35, 1)), latticeMaterial);
    lattice.rotation.set(0.12, -0.2, 0.08);
    group.add(lattice);
    group.userData.lattice = lattice;

    var qualityRingA = makeEllipseLine(group, 1.46, 1.46, ringMaterial, 144);
    qualityRingA.rotation.set(Math.PI / 2, 0.12, 0);
    var qualityRingB = makeEllipseLine(group, 1.46, 1.46, ringMaterial, 144);
    qualityRingB.rotation.set(0.08, Math.PI / 2, 0.26);
    group.userData.qualityRings = [qualityRingA, qualityRingB];
    makeNode(group, new THREE.Vector3(1.18, 0.78, 0.3), 0.045, accentMaterial);
  }

  function createFinalConvergenceVisual() {
    var group = createSectionVisualGroup('signal-convergence');
    group.scale.setScalar(0.64);
    group.position.set(0, 1.28, 0);
    var ringMaterial = visualMaterial(group, new THREE.LineBasicMaterial({ color: 0xaab4c2, blending: THREE.AdditiveBlending }), 0.34);
    var faintMaterial = visualMaterial(group, new THREE.LineBasicMaterial({ color: 0x687486, blending: THREE.AdditiveBlending }), 0.2);
    var signalMaterial = visualMaterial(group, new THREE.MeshBasicMaterial({ color: 0xdc465c, depthTest: false }), 0.96);
    var radii = [1.55, 1.31, 1.08, 0.87, 0.68];
    var rotations = [
      [0.92, 0.18, -0.34], [-0.64, 0.42, 0.2], [1.12, -0.28, 0.4],
      [-0.42, -0.5, -0.18], [0.7, 0.32, 0.12]
    ];
    group.userData.convergenceRings = [];
    group.userData.ringRotations = rotations;
    for (var convergenceIndex = 0; convergenceIndex < radii.length; convergenceIndex++) {
      var ring = makeEllipseLine(group, radii[convergenceIndex], radii[convergenceIndex], convergenceIndex < 2 ? ringMaterial : faintMaterial, 144);
      ring.rotation.set(rotations[convergenceIndex][0], rotations[convergenceIndex][1], rotations[convergenceIndex][2]);
      group.userData.convergenceRings.push(ring);
    }
    group.userData.convergenceSignal = makeNode(group, new THREE.Vector3(1.42, 0, 1.12), 0.07, signalMaterial);
  }

  function createSectionVisuals() {
    sectionVisualRoot = new THREE.Group();
    sectionVisualRoot.name = 'sightline-section-instruments';
    scene.add(sectionVisualRoot);
    createConnectedIntelligenceVisual();
    createSitrepScanVisual();
    createProposalStructureVisual();
    createWeeklyOrbitVisual();
    createQualityLatticeVisual();
    createFinalConvergenceVisual();
  }

  function animateSectionVisuals(time) {
    if (!sectionVisualRoot) return;
    var activeVisual = currentSection >= 1 && currentSection <= 6 ? currentSection - 1 : -1;
    for (var visualIndex = 0; visualIndex < sectionVisuals.length; visualIndex++) {
      var visual = sectionVisuals[visualIndex];
      var targetOpacity = visualIndex === activeVisual ? 1 : 0;
      visual.userData.opacity += (targetOpacity - visual.userData.opacity) * 0.075;
      visual.visible = visual.userData.opacity > 0.012;
      for (var materialIndex = 0; materialIndex < visual.userData.materials.length; materialIndex++) {
        var material = visual.userData.materials[materialIndex];
        material.opacity = material.userData.baseOpacity * visual.userData.opacity;
      }
    }

    if (activeVisual === 0) {
      var connected = sectionVisuals[0];
      connected.userData.orbits[0].rotation.z += reduceMotion ? 0 : 0.00055;
      connected.userData.orbits[1].rotation.z -= reduceMotion ? 0 : 0.00032;
      for (var nodeIndex = 0; nodeIndex < connected.userData.nodes.length; nodeIndex++) {
        var pulse = reduceMotion ? 1 : 0.92 + Math.sin(time * 0.0018 + nodeIndex) * 0.12;
        connected.userData.nodes[nodeIndex].scale.setScalar(pulse);
      }
    } else if (activeVisual === 1) {
      var scan = sectionVisuals[1];
      var scanY = reduceMotion ? 0.12 : Math.sin(time * 0.00072) * 1.12;
      var scanScale = Math.sqrt(Math.max(0.12, 1 - Math.pow(scanY / 1.32, 2)));
      scan.userData.scanPlane.position.y = scanY;
      scan.userData.scanRing.position.y = scanY;
      scan.userData.scanPlane.scale.setScalar(scanScale);
      scan.userData.scanRing.scale.setScalar(scanScale);
    } else if (activeVisual === 2) {
      var structure = sectionVisuals[2];
      for (var frameIndex = 0; frameIndex < structure.userData.frames.length; frameIndex++) {
        var frame = structure.userData.frames[frameIndex];
        frame.position.z += ((-0.62 + frameIndex * 0.38 + (reduceMotion ? 0 : Math.sin(time * 0.00065 + frameIndex) * 0.035)) - frame.position.z) * 0.06;
      }
    } else if (activeVisual === 3) {
      var weekly = sectionVisuals[3];
      if (!reduceMotion) weekly.userData.orbitBand.rotation.z += 0.0007;
      for (var weekIndex = 0; weekIndex < weekly.userData.weekMarkers.length; weekIndex++) {
        var markerPulse = reduceMotion ? 1 : 0.9 + Math.sin(time * 0.0022 - weekIndex * 0.55) * 0.16;
        weekly.userData.weekMarkers[weekIndex].scale.setScalar(markerPulse);
      }
    } else if (activeVisual === 4) {
      var quality = sectionVisuals[4];
      if (!reduceMotion) {
        quality.userData.lattice.rotation.y += 0.00048;
        quality.userData.qualityRings[0].rotation.z += 0.00034;
        quality.userData.qualityRings[1].rotation.x -= 0.00027;
      }
    } else if (activeVisual === 5) {
      var convergence = sectionVisuals[5];
      var convergenceProgress = reduceMotion ? 1 : Math.min(1, Math.max(0, (time - finalConvergenceStartedAt) / 2600));
      var easedProgress = 1 - Math.pow(1 - convergenceProgress, 3);
      for (var ringIndex = 0; ringIndex < convergence.userData.convergenceRings.length; ringIndex++) {
        var convergenceRing = convergence.userData.convergenceRings[ringIndex];
        var startRotation = convergence.userData.ringRotations[ringIndex];
        convergenceRing.rotation.x = startRotation[0] * (1 - easedProgress);
        convergenceRing.rotation.y = startRotation[1] * (1 - easedProgress);
        convergenceRing.rotation.z = startRotation[2] * (1 - easedProgress) + (reduceMotion ? 0 : time * 0.000035 * (ringIndex % 2 ? -1 : 1));
      }
      var signalRadius = 1.42 * (1 - easedProgress);
      var signalAngle = convergenceProgress * Math.PI * 2.4;
      convergence.userData.convergenceSignal.position.set(Math.cos(signalAngle) * signalRadius, Math.sin(signalAngle) * signalRadius, 1.12);
      var lockedPulse = reduceMotion ? 1 : 0.92 + Math.sin(time * 0.0024) * 0.12 * easedProgress;
      convergence.userData.convergenceSignal.scale.setScalar(lockedPulse);
    }
  }

  function startScene() {
    if (typeof THREE === 'undefined') { hideLoader(); initScroll(); return; }

    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(40, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.set(0, 0, 7.2);
    camera.lookAt(0, 0, 0);

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(preferredPixelRatio());
    renderer.setClearColor(0x090b0f, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.28;
    container.appendChild(renderer.domElement);

    // The legacy hero globe is intentionally not created. The shared earth drives every scene.
    hideLoader();
    initScroll();

    var texLoader = new THREE.TextureLoader();
    texLoader.crossOrigin = 'anonymous';
    var base = '/static/textures/';

    var texturesLoaded = 0;
    var totalTextures = 5; // albedo + night + ocean + clouds + bump

    function onTex() {
      texturesLoaded++;
      if (texturesLoaded >= totalTextures) texturesLoaded = totalTextures;
    }

    var dayTex = texLoader.load(base + 'earth_albedo_2k.webp', onTex);
    dayTex.colorSpace = THREE.SRGBColorSpace;
    dayTex.anisotropy = 16;

    var nightTex = texLoader.load(base + 'earth_night_lights_2k.webp', onTex);
    nightTex.colorSpace = THREE.SRGBColorSpace;

    var specTex = texLoader.load(base + 'earth_ocean_mask_2k.webp', onTex);
    specTex.anisotropy = 16;

    var cloudsTex = texLoader.load(base + 'earth_clouds_2k.webp', onTex);
    cloudsTex.colorSpace = THREE.SRGBColorSpace;

    var bumpTex = texLoader.load(base + 'earth_bump_2k.webp', onTex);
    bumpTex.anisotropy = 16;

    // ── Earth shader — high detail with proper bump mapping ──
    var earthSegments = lowPowerDevice ? 112 : 192;
    var earthGeo = new THREE.SphereGeometry(1, earthSegments, earthSegments);
    dayMaterial = new THREE.ShaderMaterial({
      uniforms: {
        dayTexture: { value: dayTex },
        nightTexture: { value: nightTex },
        specularMap: { value: specTex },
        bumpTexture: { value: bumpTex },
        sunDirection: { value: new THREE.Vector3(5, 3, 5).normalize() },
        nightMix: { value: 0.0 },
        heroMix: { value: 1.0 }
      },
      vertexShader: [
        'varying vec2 vUv;',
        'varying vec3 vNormal;',
        'varying vec3 vWorldPosition;',
        'void main() {',
        '  vUv = uv;',
        '  vNormal = normalize(normalMatrix * normal);',
        '  vec4 worldPos = modelMatrix * vec4(position, 1.0);',
        '  vWorldPosition = worldPos.xyz;',
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
        'uniform float heroMix;',
        'varying vec2 vUv;',
        'varying vec3 vNormal;',
        'varying vec3 vWorldPosition;',
        '',
        'vec3 perturbNormal(vec3 normal, vec2 uv, vec3 viewDir) {',
        '  vec2 texelSize = vec2(1.0 / 4096.0, 1.0 / 4096.0);',
        '  float b0 = texture2D(bumpTexture, uv).r;',
        '  float bx = texture2D(bumpTexture, uv + vec2(texelSize.x, 0.0)).r;',
        '  float by = texture2D(bumpTexture, uv + vec2(0.0, texelSize.y)).r;',
        '  vec3 perturbed = normal + vec3((b0 - bx) * 2.0, (b0 - by) * 2.0, 0.0);',
        '  return normalize(perturbed);',
        '}',
        '',
        'void main() {',
        '  vec3 viewDir = normalize(cameraPosition - vWorldPosition);',
        '',
        '  // Perturb normal with bump map for terrain detail',
        '  vec3 perturbedNormal = perturbNormal(vNormal, vUv, viewDir);',
        '',
        '  vec3 daySample = texture2D(dayTexture, vUv).rgb;',
        '  vec3 nightSample = texture2D(nightTexture, vUv).rgb;',
        '  float landMask = smoothstep(0.22, 0.72, texture2D(specularMap, vUv).r);',
        '  float bump = texture2D(bumpTexture, vUv).r;',
        '  float terrain = dot(daySample, vec3(0.299, 0.587, 0.114));',
        '  float nightSignal = dot(nightSample, vec3(0.299, 0.587, 0.114));',
        '',
        '  float dayAmount = max(dot(perturbedNormal, sunDirection), 0.0);',
        '  float keyLight = smoothstep(-0.12, 0.78, dayAmount);',
        '  vec3 ocean = mix(vec3(0.018, 0.024, 0.033), vec3(0.105, 0.125, 0.151), keyLight);',
        '  vec3 landDark = vec3(0.105, 0.113, 0.126);',
        '  vec3 landLight = vec3(0.54, 0.56, 0.59);',
        '  float landDetail = clamp(terrain * 0.58 + bump * 0.42, 0.0, 1.0);',
        '  vec3 land = mix(landDark, landLight, keyLight * (0.58 + landDetail * 0.42));',
        '  vec3 color = mix(ocean, land, landMask);',
        '',
        '  float oceanMask = 1.0 - landMask;',
        '  float specHighlight = pow(max(dot(reflect(-sunDirection, perturbedNormal), viewDir), 0.0), 26.0) * oceanMask * dayAmount;',
        '  color += vec3(0.55, 0.62, 0.72) * specHighlight * 0.22;',
        '  float rim = pow(1.0 - max(dot(perturbedNormal, viewDir), 0.0), 2.25);',
        '  color += vec3(0.24, 0.30, 0.38) * rim * 0.42;',
        '  float signal = smoothstep(0.23, 0.82, nightSignal) * (1.0 - keyLight);',
        '  color += vec3(0.72, 0.035, 0.075) * signal * (0.34 + nightMix * 0.44);',
        '',
        '  color *= 1.0 - nightMix * 0.14;',
        '  vec3 heroOcean = mix(vec3(0.10, 0.115, 0.135), vec3(0.29, 0.32, 0.36), keyLight);',
        '  vec3 heroLand = mix(vec3(0.27, 0.285, 0.31), vec3(0.76, 0.77, 0.78), keyLight * (0.72 + landDetail * 0.28));',
        '  vec3 heroColor = mix(heroOcean, heroLand, landMask);',
        '  heroColor += vec3(0.30, 0.33, 0.37) * rim * 0.34;',
        '  color = mix(color, heroColor, heroMix);',
        '  gl_FragColor = vec4(color, 1.0);',
        '}'
      ].join('\n')
    });

    earth = new THREE.Mesh(earthGeo, dayMaterial);
    earth.rotation.y = turkeyOffset; // -35° so Turkey faces camera
    earth.visible = true;
    scene.add(earth);

    // ── Clouds ──
    var cloudSegments = lowPowerDevice ? 72 : 128;
    var cloudsGeo = new THREE.SphereGeometry(1.015, cloudSegments, cloudSegments);
    clouds = new THREE.Mesh(cloudsGeo, new THREE.MeshPhongMaterial({
      map: cloudsTex, color: 0xaeb5bf, transparent: true, opacity: 0.11, depthWrite: false, blending: THREE.NormalBlending
    }));
    clouds.visible = true;
    scene.add(clouds);
    earthVisible = true;
    setEarthTargetForSection(0, true);
    createHeroEarthDetails();

    createSectionVisuals();

    // ── No atmosphere glow (removed — was causing artifacts) ──
    // ── No nebula (removed — was causing square artifacts) ──

    // ── Stars (3 parallax layers — simple, clean) ──
    var starConfigs = [
      { count: 520, dist: 40, size: 0.09, color: 0xd8d9dd, opacity: 0.34, driftY: 0.000072, driftZ: 0.000008 },
      { count: 190, dist: 62, size: 0.13, color: 0x8f939b, opacity: 0.18, driftY: -0.000026, driftZ: -0.000004 }
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
      field.userData.driftY = cfg.driftY;
      field.userData.driftZ = cfg.driftZ;
      starFields.push(field);
      scene.add(field);
    });

    // ── Lighting ──
    scene.add(new THREE.AmbientLight(0x6f7582, 1.2));
    var sun = new THREE.DirectionalLight(0xf4f5f7, 4.2);
    sun.position.set(5, 3, 5);
    scene.add(sun);
    var fill = new THREE.DirectionalLight(0x7d8390, 1.1);
    fill.position.set(-5, -2, -4);
    scene.add(fill);
    var edge = new THREE.DirectionalLight(0xa72b3d, 0.28);
    edge.position.set(1, -3, 4);
    scene.add(edge);

    // ── Resize ──
    window.addEventListener('resize', function() {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
      renderer.setPixelRatio(preferredPixelRatio());
      layoutHorizon();
      if (currentSection === 0) setEarthTargetForSection(0, false);
    });

    window.addEventListener('pointermove', function(event) {
      if (reduceMotion) return;
      var now = performance.now();
      var elapsed = Math.max(8, now - lastPointer.time);
      pointerTarget.x = (event.clientX / window.innerWidth - 0.5) * 2;
      pointerTarget.y = (event.clientY / window.innerHeight - 0.5) * 2;
      pointerVelocityTarget.x = Math.max(-1, Math.min(1, ((event.clientX - lastPointer.x) / elapsed) * 0.16));
      pointerVelocityTarget.y = Math.max(-1, Math.min(1, ((event.clientY - lastPointer.y) / elapsed) * 0.16));
      lastPointer.x = event.clientX;
      lastPointer.y = event.clientY;
      lastPointer.time = now;
      updatePointerInteraction(event.clientX, event.clientY);
    }, { passive: true });
    document.documentElement.addEventListener('pointerleave', resetPointerInteraction, { passive: true });

    // ── Set initial camera (Section 0: intro image + stars) ──
    targetCameraPos = { x: 0, y: 0, z: 7.2 };
    targetLookAt = { x: 0, y: 0, z: 0 };
    currentSection = 0;

    // Show hero-bg (milky way) on first load, intro on last section
    var heroBg = document.getElementById('hero-bg');
    var introImg = document.getElementById('intro-bg');
    if (heroBg) heroBg.style.opacity = '1'; // visible on load
    if (introImg) introImg.style.opacity = '0'; // hidden on load

    // Start animation immediately. Earth textures continue loading in the background.
    animate();
  }

  function animate() {
    requestAnimationFrame(animate);

    if (document.hidden) return;

    var animationTime = performance.now();

    pointerCurrent.x += (pointerTarget.x - pointerCurrent.x) * 0.035;
    pointerCurrent.y += (pointerTarget.y - pointerCurrent.y) * 0.035;
    pointerVelocity.x += (pointerVelocityTarget.x - pointerVelocity.x) * 0.09;
    pointerVelocity.y += (pointerVelocityTarget.y - pointerVelocity.y) * 0.09;
    pointerVelocityTarget.x *= 0.88;
    pointerVelocityTarget.y *= 0.88;
    horizonHover += (horizonHoverTarget - horizonHover) * 0.08;
    portalProximity += (portalProximityTarget - portalProximity) * 0.1;

    if (earth) {
      earth.rotation.y += reduceMotion ? 0.00012 : 0.00042;
      var heroTiltX = currentSection === 0 && !reduceMotion ? -0.035 - pointerCurrent.y * 0.06 : -0.035;
      var heroTiltZ = currentSection === 0 && !reduceMotion ? pointerCurrent.x * 0.032 : 0;
      earth.rotation.x += (heroTiltX - earth.rotation.x) * 0.035;
      earth.rotation.z += (heroTiltZ - earth.rotation.z) * 0.035;
      earth.scale.x += (targetEarthScale - earth.scale.x) * 0.055;
      earth.scale.y += (targetEarthScale - earth.scale.y) * 0.055;
      earth.scale.z += (targetEarthScale - earth.scale.z) * 0.055;
      earth.position.x += (targetEarthPosition.x - earth.position.x) * 0.055;
      earth.position.y += (targetEarthPosition.y - earth.position.y) * 0.055;
      earth.position.z += (targetEarthPosition.z - earth.position.z) * 0.055;
    }
    if (clouds) {
      clouds.rotation.y += reduceMotion ? 0.00016 : 0.00058;
      clouds.rotation.x = earth ? earth.rotation.x : 0;
      clouds.rotation.z = earth ? earth.rotation.z : 0;
      clouds.scale.copy(earth.scale);
      clouds.position.copy(earth.position);
    }
    for (var i = 0; i < starFields.length; i++) {
      if (!reduceMotion) {
        starFields[i].rotation.y += starFields[i].userData.driftY;
        starFields[i].rotation.z += starFields[i].userData.driftZ;
      }
    }
    animateHeroEarthDetails(animationTime);
    animateSectionVisuals(animationTime);

    if (horizonGroup) {
      var pointerInfluence = 0.28 + horizonHover * 0.72;
      horizonGroup.rotation.y = pointerCurrent.x * 0.11 * pointerInfluence + pointerVelocity.x * 0.026;
      horizonGroup.rotation.x = -pointerCurrent.y * 0.085 * pointerInfluence - pointerVelocity.y * 0.02 + portalProximity * 0.012;
      horizonGroup.rotation.z = pointerVelocity.x * -0.01;
      var interactiveScale = horizonBaseScale * (1 + horizonHover * 0.018 + portalProximity * 0.008);
      horizonGroup.scale.setScalar(interactiveScale);

      if (horizonWorld && !reduceMotion) {
        horizonWorld.rotation.y += 0.0009 + Math.abs(pointerVelocity.x) * 0.0014;
      }
      if (horizonWire && !reduceMotion) {
        horizonWire.rotation.y -= 0.00018;
        horizonWire.rotation.x += 0.00005;
      }

      if (horizonSurface && horizonSurface.material.uniforms) {
        var pointerLight = horizonSurface.material.uniforms.pointerLight.value;
        pointerLight.x += (pointerCurrent.x * 0.9 - pointerLight.x) * 0.055;
        pointerLight.y += (-pointerCurrent.y * 0.7 + 0.25 - pointerLight.y) * 0.055;
        pointerLight.z += (1 - pointerLight.z) * 0.055;
        pointerLight.normalize();
      }

      for (var nodeIndex = 0; nodeIndex < horizonSignalNodes.length; nodeIndex++) {
        var signalNode = horizonSignalNodes[nodeIndex];
        var nodePulse = reduceMotion ? 0.72 : 0.58 + (Math.sin(performance.now() * signalNode.userData.speed + signalNode.userData.phase) + 1) * 0.21;
        var nodeScale = 0.86 + nodePulse * 0.34 + horizonHover * 0.12;
        signalNode.children[0].scale.setScalar(signalNode.userData.baseSize * nodeScale);
        signalNode.userData.coreMaterial.opacity = (0.58 + nodePulse * 0.34) * horizonOpacity;
        signalNode.userData.glowMaterial.opacity = (0.18 + nodePulse * 0.36 + horizonHover * 0.08) * horizonOpacity;
      }

      if (horizonChromeLight) {
        horizonChromeLight.position.x += (pointerCurrent.x * 2.2 - horizonChromeLight.position.x) * 0.06;
        horizonChromeLight.position.y += (-pointerCurrent.y * 1.5 + 1.2 - horizonChromeLight.position.y) * 0.06;
        horizonChromeLight.intensity = 4.8 + horizonHover * 1.2 + portalProximity * 0.4;
      }

      horizonOpacity += (horizonTargetOpacity - horizonOpacity) * 0.09;
      horizonGroup.visible = horizonOpacity > 0.01;
      for (var materialIndex = 0; materialIndex < horizonMaterials.length; materialIndex++) {
        var horizonMaterial = horizonMaterials[materialIndex];
        if (horizonMaterial.userData.isSignal) continue;
        var hoverBoost = horizonMaterial.userData.hoverBoost || 0;
        var materialOpacity = Math.min(1, horizonMaterial.userData.baseOpacity + hoverBoost * horizonHover) * horizonOpacity;
        horizonMaterial.opacity = materialOpacity;
        if (horizonMaterial.userData.opacityUniform) {
          horizonMaterial.userData.opacityUniform.value = materialOpacity;
        }
      }
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

    // SITREP section darken
    if (dayMaterial && dayMaterial.uniforms && currentSection === 2) {
      dayMaterial.uniforms.nightMix.value += (0.5 - dayMaterial.uniforms.nightMix.value) * 0.05;
    } else if (dayMaterial && dayMaterial.uniforms) {
      dayMaterial.uniforms.nightMix.value += (0.0 - dayMaterial.uniforms.nightMix.value) * 0.05;
    }
    if (dayMaterial && dayMaterial.uniforms && dayMaterial.uniforms.heroMix) {
      var targetHeroMix = currentSection === 0 ? 1 : 0;
      dayMaterial.uniforms.heroMix.value += (targetHeroMix - dayMaterial.uniforms.heroMix.value) * 0.05;
    }

    if (renderer && scene && camera) renderer.render(scene, camera);
  }

  // ── Scroll + IntersectionObserver ──
  function initScroll() {
    if (scrollInitialized) return;
    scrollInitialized = true;

    var sections = document.querySelectorAll('.lp-section');
    var spFill = document.getElementById('sp-fill');
    var spDotsContainer = document.getElementById('sp-dots');
    var scrollContainer = document.getElementById('scroll-container');
    var scrollProgress = document.querySelector('.scroll-progress');
    var worldTrigger = document.getElementById('hero-world-trigger');

    portalButton = document.getElementById('hero-portal');
    if (scrollContainer && sections[1]) {
      var openSightlineSystem = function() {
        document.body.classList.add('portal-opening');
        horizonTargetOpacity = 0;
        setTimeout(function() {
          sections[1].scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
        }, reduceMotion ? 0 : 180);
        setTimeout(function() {
          document.body.classList.remove('portal-opening');
        }, reduceMotion ? 20 : 1200);
      };
      if (portalButton) portalButton.addEventListener('click', openSightlineSystem);
      if (worldTrigger) worldTrigger.addEventListener('click', openSightlineSystem);
    }

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
        if (scrollProgress) scrollProgress.style.opacity = scrollContainer.scrollTop > scrollContainer.clientHeight * 0.45 ? '1' : '0';
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
        var deferredSource = source ? source.getAttribute('data-src') : '';

        if (video && source && !source.getAttribute('src') && deferredSource) {
          source.setAttribute('src', deferredSource);
          video.load();
        }

        if (video && source && source.getAttribute('src')) {
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

  }

  function activateSection(index, sections, dots) {
    document.body.classList.toggle('hero-light', index === 0);
    document.body.classList.toggle('observatory-mode', index > 0 && index < 6);
    document.body.classList.toggle('final-quiet', index === 6);

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
    setEarthTargetForSection(index, false);
    if (index === 6) finalConvergenceStartedAt = performance.now();
    horizonTargetOpacity = 0;
    if (index !== 0) resetPointerInteraction();

    // Fade the pearl hero away after Section 0. The finale stays intentionally image-free.
    var heroBg = document.getElementById('hero-bg');
    var introImg = document.getElementById('intro-bg');
    if (heroBg) {
      heroBg.style.opacity = (index === 0) ? '1' : '0';
    }
    if (introImg) introImg.style.opacity = '0';

    currentSection = index;
  }

  // ── Start ──
  // Keep the landing usable even if WebGL or a texture fails.
  setTimeout(function() {
    hideLoader();
    initScroll();
  }, 1400);

  initThree();

})();

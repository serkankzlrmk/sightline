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

  var container = document.getElementById('sketchfab-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'sketchfab-container';
    document.body.insertBefore(container, document.body.firstChild);
  }
  container.innerHTML = '';
  container.style.cssText = 'position:fixed;inset:0;z-index:1;pointer-events:none;transition:opacity 1s ease;';

  var scene, camera, renderer, earth, clouds, horizonGroup, horizonSurface;
  var horizonChromeLight, horizonSignalSegments = [];
  var horizonContourLines = [];
  var horizonMaterials = [];
  var horizonBaseScale = 1;
  var horizonOpacity = 1;
  var horizonTargetOpacity = 1;
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
  var loader = document.getElementById('loading-screen');
  var dayMaterial;
  var targetCameraPos = { x: 0, y: 0, z: 7.2 };
  var targetLookAt = { x: 0, y: 0, z: 0 };
  var currentLookAt = { x: 0, y: 0, z: 0 };
  var earthVisible = false;

  // Camera positions for each section
  // Camera starts at angle 0 (facing prime meridian / Greenwich)
  // Earth texture is rotated -35° so Turkey (35°E) faces camera at start
  // Earth rotates eastward (positive Y) = west to east (natural)
  var turkeyOffset = -120 * Math.PI / 180; // Turkey/Europe faces camera (rotate ~120° east)
  var sectionCameras = [
    // Section 0: Signal Horizon, earth hidden
    { pos: { x: 0, y: 0, z: 7.2 }, look: { x: 0, y: 0, z: 0 }, earth: false },
    // Section 1-5: Earth visible, camera offset right so earth is on right side
    { pos: { x: 1.0, y: 0.8, z: 2.2 }, look: { x: 0, y: 0, z: 0 }, earth: true },
    { pos: { x: 1.0, y: 0.8, z: 2.2 }, look: { x: 0, y: 0, z: 0 }, earth: true },
    { pos: { x: 1.0, y: 0.8, z: 2.2 }, look: { x: 0, y: 0, z: 0 }, earth: true },
    { pos: { x: 1.0, y: 0.8, z: 2.2 }, look: { x: 0, y: 0, z: 0 }, earth: true },
    { pos: { x: 1.0, y: 0.8, z: 2.2 }, look: { x: 0, y: 0, z: 0 }, earth: true },
    // Section 6: quiet wide camera, earth hidden
    { pos: { x: 0, y: 0, z: 7.2 }, look: { x: 0, y: 0, z: 0 }, earth: false }
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

  function terrainHeight(x, z) {
    var longWave = Math.sin(x * 1.12 + z * 0.7) * 0.16;
    var detail = Math.sin(x * 2.55 - z * 1.9) * 0.055;
    var ridgeA = Math.exp(-Math.pow(x + 0.65, 2) * 1.7) * 0.34;
    var ridgeB = Math.exp(-Math.pow(x - 1.45, 2) * 3.1) * 0.24;
    var depthSlope = (z + 0.72) * 0.09;
    return longWave + detail + ridgeA + ridgeB + depthSlope - 0.18;
  }

  function createTerrainGeometry(xSegments, zSegments) {
    var positions = [];
    var indices = [];
    var base = [];
    for (var zIndex = 0; zIndex <= zSegments; zIndex++) {
      var zRatio = zIndex / zSegments;
      var z = -0.72 + zRatio * 1.44;
      for (var xIndex = 0; xIndex <= xSegments; xIndex++) {
        var xRatio = xIndex / xSegments;
        var x = -2.75 + xRatio * 5.5;
        var taperedZ = z * (0.76 + xRatio * 0.24);
        var y = terrainHeight(x, taperedZ);
        positions.push(x, y, taperedZ);
        base.push(x, y, taperedZ);
      }
    }
    for (var row = 0; row < zSegments; row++) {
      for (var column = 0; column < xSegments; column++) {
        var a = row * (xSegments + 1) + column;
        var b = a + 1;
        var c = a + xSegments + 1;
        var d = c + 1;
        indices.push(a, c, b, b, c, d);
      }
    }
    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setIndex(indices);
    geometry.computeVertexNormals();
    geometry.userData.basePositions = new Float32Array(base);
    return geometry;
  }

  function createHorizon() {
    horizonGroup = new THREE.Group();
    horizonGroup.name = 'sightline-signal-horizon';
    scene.add(horizonGroup);

    var titanium = rememberHorizonMaterial(new THREE.MeshPhysicalMaterial({
      color: 0x747982,
      metalness: 0.96,
      roughness: 0.2,
      clearcoat: 0.72,
      clearcoatRoughness: 0.12
    }), 0.98);
    var darkMetal = rememberHorizonMaterial(new THREE.MeshPhysicalMaterial({
      color: 0x1a1e25,
      metalness: 0.82,
      roughness: 0.26,
      clearcoat: 0.78,
      clearcoatRoughness: 0.16,
      side: THREE.DoubleSide
    }), 0.96);
    var glass = rememberHorizonMaterial(new THREE.MeshPhysicalMaterial({
      color: 0x2a3340,
      metalness: 0.08,
      roughness: 0.2,
      transmission: 0.12,
      thickness: 0.42,
      clearcoat: 1,
      clearcoatRoughness: 0.08,
      side: THREE.DoubleSide,
      depthWrite: false
    }), 0.52);
    var contourMaterial = rememberHorizonMaterial(new THREE.LineBasicMaterial({
      color: 0xd2d6de,
      depthTest: false,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    }), 0.34);
    contourMaterial.userData.hoverBoost = 0.14;
    var underlay = new THREE.Mesh(createTerrainGeometry(72, 18), darkMetal);
    underlay.position.y = -0.085;
    underlay.scale.set(1.012, 1, 1.045);
    horizonGroup.add(underlay);

    horizonSurface = new THREE.Mesh(createTerrainGeometry(72, 18), glass);
    horizonSurface.position.y = 0.015;
    horizonGroup.add(horizonSurface);

    for (var contourIndex = 0; contourIndex < 10; contourIndex++) {
      var z = -0.61 + contourIndex * 0.135;
      var contourPoints = [];
      for (var pointIndex = 0; pointIndex <= 92; pointIndex++) {
        var ratio = pointIndex / 92;
        var x = -2.72 + ratio * 5.44;
        var taperedZ = z * (0.76 + ratio * 0.24);
        contourPoints.push(new THREE.Vector3(x, terrainHeight(x, taperedZ) + 0.045, taperedZ));
      }
      var contourGeometry = new THREE.BufferGeometry().setFromPoints(contourPoints);
      contourGeometry.userData.basePositions = new Float32Array(contourGeometry.attributes.position.array);
      var contour = new THREE.Line(contourGeometry, contourMaterial);
      contour.renderOrder = 4;
      horizonContourLines.push(contour);
      horizonGroup.add(contour);
    }

    for (var ribIndex = 0; ribIndex < 9; ribIndex++) {
      var ribRatio = (ribIndex + 1) / 10;
      var ribX = -2.72 + ribRatio * 5.44;
      var ribPoints = [];
      for (var ribPointIndex = 0; ribPointIndex <= 26; ribPointIndex++) {
        var ribDepthRatio = ribPointIndex / 26;
        var ribZ = (-0.64 + ribDepthRatio * 1.28) * (0.76 + ribRatio * 0.24);
        ribPoints.push(new THREE.Vector3(ribX, terrainHeight(ribX, ribZ) + 0.046, ribZ));
      }
      var ribGeometry = new THREE.BufferGeometry().setFromPoints(ribPoints);
      ribGeometry.userData.basePositions = new Float32Array(ribGeometry.attributes.position.array);
      var rib = new THREE.Line(ribGeometry, contourMaterial);
      rib.renderOrder = 4;
      horizonContourLines.push(rib);
      horizonGroup.add(rib);
    }

    var frontPoints = [];
    for (var edgeIndex = 0; edgeIndex <= 96; edgeIndex++) {
      var edgeRatio = edgeIndex / 96;
      var edgeX = -2.78 + edgeRatio * 5.56;
      var edgeZ = 0.72 * (0.76 + edgeRatio * 0.24);
      frontPoints.push(new THREE.Vector3(edgeX, terrainHeight(edgeX, edgeZ) - 0.01, edgeZ));
    }
    var frontCurve = new THREE.CatmullRomCurve3(frontPoints);
    horizonGroup.add(new THREE.Mesh(new THREE.TubeGeometry(frontCurve, 128, 0.032, 8, false), titanium));

    var signalPoints = [];
    for (var signalIndex = 0; signalIndex <= 88; signalIndex++) {
      var signalRatio = signalIndex / 88;
      var signalX = -2.6 + signalRatio * 5.2;
      var signalZ = 0.42 + Math.sin(signalX * 0.72) * 0.045;
      signalPoints.push(new THREE.Vector3(signalX, terrainHeight(signalX, signalZ) + 0.078, signalZ));
    }
    for (var segmentIndex = 0; segmentIndex < signalPoints.length - 1; segmentIndex++) {
      var segmentGeometry = new THREE.BufferGeometry().setFromPoints([signalPoints[segmentIndex], signalPoints[segmentIndex + 1]]);
      var segmentMaterial = rememberHorizonMaterial(new THREE.LineBasicMaterial({
        color: 0xec5b70,
        depthTest: false,
        depthWrite: false,
        blending: THREE.AdditiveBlending
      }), 0.32);
      segmentMaterial.userData.hoverBoost = 0.08;
      segmentMaterial.userData.isSignal = true;
      var segment = new THREE.Line(segmentGeometry, segmentMaterial);
      segment.renderOrder = 5;
      segment.userData.index = segmentIndex;
      horizonSignalSegments.push(segment);
      horizonGroup.add(segment);
    }

    horizonChromeLight = new THREE.PointLight(0xe9edf5, 6.2, 8, 2);
    horizonChromeLight.position.set(-1.8, 1.6, 2.4);
    horizonGroup.add(horizonChromeLight);

    var roseLight = new THREE.PointLight(0xb93349, 0.55, 5, 2);
    roseLight.position.set(0.8, 0.15, 1.1);
    horizonGroup.add(roseLight);

    layoutHorizon();
  }

  function layoutHorizon() {
    if (!horizonGroup) return;
    if (window.innerWidth <= 900) {
      horizonGroup.position.set(0.22, -1.12, 0.08);
      horizonBaseScale = window.innerWidth <= 600 ? 0.54 : 0.68;
    } else {
      horizonGroup.position.set(2.25, 0.02, 0);
      horizonBaseScale = 0.88;
    }
    horizonGroup.scale.setScalar(horizonBaseScale);
    horizonGroup.rotation.x = -0.62;
    horizonGroup.rotation.y = -0.08;
    horizonGroup.rotation.z = -0.025;
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

  function startScene() {
    if (typeof THREE === 'undefined') { hideLoader(); initScroll(); return; }

    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(40, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.set(0, 0, 7.2);
    camera.lookAt(0, 0, 0);

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    renderer.setClearColor(0x050607, 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.28;
    container.appendChild(renderer.domElement);

    createHorizon();
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

    var dayTex = texLoader.load(base + 'earth_albedo.jpg', onTex);
    dayTex.colorSpace = THREE.SRGBColorSpace;
    dayTex.anisotropy = 16;

    var nightTex = texLoader.load(base + 'earth_night_lights.png', onTex);
    nightTex.colorSpace = THREE.SRGBColorSpace;

    var specTex = texLoader.load(base + 'earth_ocean_mask.png', onTex);
    specTex.anisotropy = 16;

    var cloudsTex = texLoader.load(base + 'earth_clouds.jpg', onTex);
    cloudsTex.colorSpace = THREE.SRGBColorSpace;

    var bumpTex = texLoader.load(base + 'earth_bump.jpg', onTex);
    bumpTex.anisotropy = 16;

    // ── Earth shader — high detail with proper bump mapping ──
    var earthSegments = window.innerWidth <= 600 ? 96 : 192;
    var earthGeo = new THREE.SphereGeometry(1, earthSegments, earthSegments);
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
        '  vec3 dayColor = texture2D(dayTexture, vUv).rgb * 1.3;',
        '  vec3 nightColor = texture2D(nightTexture, vUv).rgb * 1.2;',
        '  float specular = texture2D(specularMap, vUv).r;',
        '  float bump = texture2D(bumpTexture, vUv).r;',
        '  dayColor *= 0.85 + bump * 0.3;',
        '',
        '  // Day/night based on perturbed normal',
        '  float dayAmount = max(dot(perturbedNormal, sunDirection), 0.0);',
        '  vec3 color = mix(nightColor, dayColor, smoothstep(0.0, 0.7, dayAmount));',
        '',
        '  // Ocean specular highlight with perturbed normal',
        '  float specHighlight = pow(max(dot(reflect(-sunDirection, perturbedNormal), viewDir), 0.0), 20.0) * specular * dayAmount;',
        '  color += vec3(0.6, 0.7, 0.9) * specHighlight * 0.2;',
        '',
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
    var cloudsGeo = new THREE.SphereGeometry(1.015, window.innerWidth <= 600 ? 64 : 128, window.innerWidth <= 600 ? 64 : 128);
    clouds = new THREE.Mesh(cloudsGeo, new THREE.MeshPhongMaterial({
      map: cloudsTex, transparent: true, opacity: 0.25, depthWrite: false, blending: THREE.NormalBlending
    }));
    clouds.visible = false;
    scene.add(clouds);

    // ── No atmosphere glow (removed — was causing artifacts) ──
    // ── No nebula (removed — was causing square artifacts) ──

    // ── Stars (3 parallax layers — simple, clean) ──
    var starConfigs = [
      { count: 360, dist: 40, size: 0.04, color: 0xd8d9dd, opacity: 0.16 },
      { count: 120, dist: 62, size: 0.055, color: 0x8f939b, opacity: 0.07 }
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
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
      layoutHorizon();
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

    if (earth) earth.rotation.y += 0.0005;
    if (clouds) clouds.rotation.y += 0.0007;
    for (var i = 0; i < starFields.length; i++) {
      starFields[i].rotation.y += 0.00003 * (i + 1);
    }

    if (horizonGroup) {
      pointerCurrent.x += (pointerTarget.x - pointerCurrent.x) * 0.035;
      pointerCurrent.y += (pointerTarget.y - pointerCurrent.y) * 0.035;
      pointerVelocity.x += (pointerVelocityTarget.x - pointerVelocity.x) * 0.09;
      pointerVelocity.y += (pointerVelocityTarget.y - pointerVelocity.y) * 0.09;
      pointerVelocityTarget.x *= 0.88;
      pointerVelocityTarget.y *= 0.88;
      horizonHover += (horizonHoverTarget - horizonHover) * 0.08;
      portalProximity += (portalProximityTarget - portalProximity) * 0.1;

      horizonGroup.rotation.y = -0.08 + pointerCurrent.x * 0.035 + pointerVelocity.x * 0.018;
      horizonGroup.rotation.x = -0.62 - pointerCurrent.y * 0.026 - pointerVelocity.y * 0.014 + portalProximity * 0.018;
      horizonGroup.rotation.z = -0.025 + pointerVelocity.x * -0.006;
      horizonGroup.scale.setScalar(horizonBaseScale * (1 + horizonHover * 0.012 + portalProximity * 0.008));

      if (horizonSurface && !reduceMotion && window.innerWidth > 900) {
        var positions = horizonSurface.geometry.attributes.position;
        var basePositions = horizonSurface.geometry.userData.basePositions;
        var bendCenterX = pointerCurrent.x * 2.5;
        var bendCenterZ = -pointerCurrent.y * 0.55;
        for (var vertexIndex = 0; vertexIndex < positions.count; vertexIndex++) {
          var baseOffset = vertexIndex * 3;
          var deltaX = basePositions[baseOffset] - bendCenterX;
          var deltaZ = basePositions[baseOffset + 2] - bendCenterZ;
          var influence = Math.exp(-(deltaX * deltaX * 0.7 + deltaZ * deltaZ * 3.2));
          var targetY = basePositions[baseOffset + 1] + influence * horizonHover * 0.11;
          positions.array[baseOffset + 1] += (targetY - positions.array[baseOffset + 1]) * 0.14;
        }
        positions.needsUpdate = true;
        if (Math.round(performance.now() / 16) % 3 === 0) horizonSurface.geometry.computeVertexNormals();

        for (var contourIndex = 0; contourIndex < horizonContourLines.length; contourIndex++) {
          var contourGeometry = horizonContourLines[contourIndex].geometry;
          var contourPositions = contourGeometry.attributes.position;
          var contourBase = contourGeometry.userData.basePositions;
          for (var contourPointIndex = 0; contourPointIndex < contourPositions.count; contourPointIndex++) {
            var contourOffset = contourPointIndex * 3;
            var contourDeltaX = contourBase[contourOffset] - bendCenterX;
            var contourDeltaZ = contourBase[contourOffset + 2] - bendCenterZ;
            var contourInfluence = Math.exp(-(contourDeltaX * contourDeltaX * 0.7 + contourDeltaZ * contourDeltaZ * 3.2));
            var contourTargetY = contourBase[contourOffset + 1] + contourInfluence * horizonHover * 0.11;
            contourPositions.array[contourOffset + 1] += (contourTargetY - contourPositions.array[contourOffset + 1]) * 0.14;
          }
          contourPositions.needsUpdate = true;
        }
      }

      var signalProgress = reduceMotion ? 0.55 : (performance.now() * 0.00012) % 1;
      for (var signalSegmentIndex = 0; signalSegmentIndex < horizonSignalSegments.length; signalSegmentIndex++) {
        var signalSegment = horizonSignalSegments[signalSegmentIndex];
        var segmentRatio = signalSegmentIndex / Math.max(1, horizonSignalSegments.length - 1);
        var distanceToSignal = Math.abs(segmentRatio - signalProgress);
        distanceToSignal = Math.min(distanceToSignal, 1 - distanceToSignal);
        var signalFocus = Math.exp(-distanceToSignal * distanceToSignal * 520);
        signalSegment.material.opacity = (0.3 + signalFocus * (0.62 + horizonHover * 0.08)) * horizonOpacity;
      }

      if (horizonChromeLight) {
        horizonChromeLight.position.x += (pointerCurrent.x * 2.7 - horizonChromeLight.position.x) * 0.06;
        horizonChromeLight.position.y += (-pointerCurrent.y * 1.7 + 0.8 - horizonChromeLight.position.y) * 0.06;
        horizonChromeLight.intensity = 6.2 + horizonHover * 1.5 + portalProximity * 0.6;
      }

      horizonOpacity += (horizonTargetOpacity - horizonOpacity) * 0.09;
      horizonGroup.visible = horizonOpacity > 0.01;
      for (var materialIndex = 0; materialIndex < horizonMaterials.length; materialIndex++) {
        var horizonMaterial = horizonMaterials[materialIndex];
        if (horizonMaterial.userData.isSignal) continue;
        var hoverBoost = horizonMaterial.userData.hoverBoost || 0;
        horizonMaterial.opacity = Math.min(1, horizonMaterial.userData.baseOpacity + hoverBoost * horizonHover) * horizonOpacity;
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

    portalButton = document.getElementById('hero-portal');
    if (portalButton && scrollContainer && sections[1]) {
      portalButton.addEventListener('click', function() {
        document.body.classList.add('portal-opening');
        horizonTargetOpacity = 0;
        setTimeout(function() {
          sections[1].scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
        }, reduceMotion ? 0 : 180);
        setTimeout(function() {
          document.body.classList.remove('portal-opening');
        }, reduceMotion ? 20 : 1200);
      });
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
    horizonTargetOpacity = index === 0 ? 1 : 0;
    if (index !== 0) resetPointerInteraction();

    // Fade hero-bg (milky way) out after Section 0, intro image in on Section 6
    var heroBg = document.getElementById('hero-bg');
    var introImg = document.getElementById('intro-bg');
    if (heroBg) {
      heroBg.style.opacity = (index === 0) ? '1' : '0';
    }
    if (introImg) {
      introImg.style.opacity = (index === 6) ? '1' : '0';
    }

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

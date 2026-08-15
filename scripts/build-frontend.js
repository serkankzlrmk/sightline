// ═══════════════════════════════════════════════════════════════════════════
// build-frontend.js — production frontend build
//
// Concats the plain script-tag modules (global scope must be preserved —
// files call each other's functions directly), minifies with esbuild, and
// writes a content-hash version file for cache invalidation.
//
//   node scripts/build-frontend.js
//
// Output:
//   static/dist/app.js          — shared+chat+database+sitrep-ui+admin+dashboard+map+bulletin+app (minified)
//   static/dist/proposal.js     — proposal wizard (minified, separate: window.* contract)
//   static/dist/landing3d.js    — landing page 3D globe (minified)
//   static/dist/style.css       — css/*.css modules + proposal-logframe.css (minified)
//   static/dist/version.json    — { "app": "<sha8>", "css": "<sha8>", "built": <ts> }
// ═══════════════════════════════════════════════════════════════════════════
import { build } from 'esbuild';
import { readFileSync, writeFileSync, mkdirSync } from 'fs';
import { createHash } from 'crypto';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
const SRC = join(ROOT, 'static');
const DIST = join(SRC, 'dist');

// Order matters: shared.js first (api/toast/esc), then feature modules,
// app.js last (init + event delegation). proposal.js stays separate.
const APP_BUNDLE = [
  'shared.js',
  'chat/chat-core.js',
  'chat/chat-list.js',
  'database.js',
  'sitrep/sitrep-pipeline.js',
  'sitrep/sitrep-reports.js',
  'sitrep/sitrep-controls.js',
  'admin.js',
  'dashboard.js',
  'map/map-core.js',
  'map/map-init.js',
  'bulletin.js',
  'app.js',
];

function sha8(content) {
  return createHash('sha256').update(content).digest('hex').slice(0, 8);
}

function minify(js, entryName) {
  return build({
    stdin: { contents: js, sourcefile: entryName, loader: 'js' },
    minify: true,
    write: false,
    target: ['es2020'],
  }).then(r => r.outputFiles[0].text);
}

mkdirSync(DIST, { recursive: true });

const version = {};
const built = Date.now();

// ── app.js bundle (concat then minify — preserves global scope) ─────────────
const appSource = APP_BUNDLE.map(f => readFileSync(join(SRC, f), 'utf8')).join('\n;\n');
const appMin = await minify(appSource, 'app.js');
version.app = sha8(appMin);
writeFileSync(join(DIST, 'app.js'), appMin);

// ── proposal.js (modular — concat proposal/*.js in order, then minify) ──────
// All functions are declarations (hoisted), so order only matters for the
// const dependency resolution at the top of proposal-wizard.js.
const PROPOSAL_BUNDLE = [
  'proposal/proposal-wizard.js',
  'proposal/proposal-advisor.js',
  'proposal/proposal-export.js',
  'proposal/proposal-guided.js',
];
const propSource = PROPOSAL_BUNDLE.map(f => readFileSync(join(SRC, f), 'utf8')).join('\n;\n');
const propMin = await minify(propSource, 'proposal.js');
version.proposal = sha8(propMin);
writeFileSync(join(DIST, 'proposal.js'), propMin);

// ── landing3d.js ─────────────────────────────────────────────────────────────
let landMin = '';
if (readFileSync(join(SRC, 'landing3d.js'), 'utf8').length > 0) {
  const landSource = readFileSync(join(SRC, 'landing3d.js'), 'utf8');
  landMin = await minify(landSource, 'landing3d.js');
  version.landing3d = sha8(landMin);
  writeFileSync(join(DIST, 'landing3d.js'), landMin);
}

// ── CSS (app bundle — modular css/ + proposal-logframe; landing.css SEPARATE!) ──
// Landing is an independent page with its own body rules; merging it into the
// app bundle caused body{...} conflicts (app's height:100vh/overflow:hidden
// leaked into landing, and --bg vars clashed with landing gradients).
//
// CSS modules are concatenated in order: base (variables/reset) first,
// then feature modules, then proposal-logframe overrides.
const CSS_BUNDLE = [
  'css/base.css',
  'css/layout.css',
  'css/database.css',
  'css/chat.css',
  'css/auth.css',
  'css/sitrep.css',
  'css/responsive.css',
  'css/bulletin.css',
  'css/proposal.css',
  'css/wizard.css',
  'proposal-logframe.css',
];
const cssSource = CSS_BUNDLE.map(f => readFileSync(join(SRC, f), 'utf8')).join('\n');
const cssMin = await build({
  stdin: { contents: cssSource, sourcefile: 'style.css', loader: 'css' },
  minify: true,
  write: false,
}).then(r => r.outputFiles[0].text);
version.css = sha8(cssMin);
writeFileSync(join(DIST, 'style.css'), cssMin);

// ── landing.css (separate — own bundle + own hash) ──────────────────────────
const landCssSource = readFileSync(join(SRC, 'landing.css'), 'utf8');
const landCssMin = await build({
  stdin: { contents: landCssSource, sourcefile: 'landing.css', loader: 'css' },
  minify: true,
  write: false,
}).then(r => r.outputFiles[0].text);
version.landing = sha8(landCssMin);
writeFileSync(join(DIST, 'landing.css'), landCssMin);

version.built = built;
writeFileSync(join(DIST, 'version.json'), JSON.stringify(version, null, 2));

console.log('✅ Frontend build complete');
console.log(`   app.js       ${version.app}  (${(appMin.length / 1024).toFixed(1)} KB)`);
console.log(`   proposal.js  ${version.proposal}  (${(propMin.length / 1024).toFixed(1)} KB)`);
console.log(`   landing3d.js ${version.landing3d || '—'}  (${((landMin?.length || 0) / 1024).toFixed(1)} KB)`);
console.log(`   style.css    ${version.css}  (${(cssMin.length / 1024).toFixed(1)} KB)`);

// ═══════════════════════════════════════════════════════════════
// sitrep-ui.js — TAB 3: SITREP Pipeline UI — extracted from app.js
// Loaded via <script> tag after shared.js, before app.js
// ═══════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// TAB 3 — SITREP PIPELINE
// ═══════════════════════════════════════════════════════════════════════════

const STEPS = [
  { id: 0, name: "Chroma Connection", icon: "1" },
  { id: 1, name: "Chunk Loading", icon: "2" },
  { id: 2, name: "Clustering", icon: "3" },
  { id: 3, name: "Question Generation", icon: "4" },
  { id: 4, name: "Question Filtering", icon: "5" },
  { id: 5, name: "RAG Answering", icon: "6" },
  { id: 6, name: "Citation Validation", icon: "7" },
  { id: 7, name: "Cluster Summary", icon: "8" },
  { id: 8, name: "Exec + Narrative", icon: "9" },
  { id: 9, name: "Report Assembly", icon: "10" },
];

const STEP_RE = /\[INFO\]\s+pipeline:\s+\[(\d)\]/;
const CACHE_RE = /\[CHECKPOINT\]/;

function buildStepsGrid() {
  const grid = document.getElementById('steps-grid');
  if (!grid) return;
  grid.innerHTML = '';
  STEPS.forEach((s) => {
    const div = document.createElement('div');
    div.className = 'step-card waiting';
    div.id = `step-card-${s.id}`;
    div.innerHTML = `
      <div class="step-num">STEP ${s.id}</div>
      <div class="step-name">${s.name}</div>
      <div class="step-icon">${s.icon}</div>`;
    grid.appendChild(div);
  });
}

function setSitrepStepState(idx, state) {
  if (idx < 0 || idx >= STEPS.length) return;
  sitrepState.stepStates[idx] = state;
  const card = document.getElementById(`step-card-${idx}`);
  if (!card) return;
  card.className = `step-card ${state}`;
  const iconMap = { waiting: STEPS[idx].icon, active: '○', cached: '⚡', done: '✓', error: '✗' };
  card.querySelector('.step-icon').textContent = iconMap[state] || STEPS[idx].icon;
}

function advanceToStep(n) {
  if (n <= sitrepState.currentStep) return;
  if (sitrepState.currentStep >= 0) setSitrepStepState(sitrepState.currentStep, 'done');
  sitrepState.currentStep = n;
  setSitrepStepState(n, 'active');
}

function logClass(line) {
  if (/^\[GPU_WARN\]/i.test(line)) return 'gpu-warn';
  if (STEP_RE.test(line)) return 'step';
  if (/completed successfully|pipeline.*done/i.test(line)) return 'done-line';
  if (CACHE_RE.test(line)) return 'cached';
  if (/\[warning\]/i.test(line)) return 'warn';
  if (/\[error\]/i.test(line) || /traceback/i.test(line)) return 'error';
  if (/\[info\]/i.test(line)) return 'info';
  return 'debug';
}

function appendLog(line) {
  const cons = document.getElementById('log-console');
  if (!cons) return;
  const div = document.createElement('div');
  div.className = `log-line ${logClass(line)}`;
  div.textContent = line;
  cons.appendChild(div);
  cons.scrollTop = cons.scrollHeight;

  const m = line.match(STEP_RE);
  if (m) {
    const n = parseInt(m[1]);
    if (CACHE_RE.test(line)) {
      setSitrepStepState(n, 'cached');
      sitrepState.currentStep = n;
    } else {
      advanceToStep(n);
    }
  }
  if (CACHE_RE.test(line) && !m && sitrepState.currentStep >= 0) {
    setSitrepStepState(sitrepState.currentStep, 'cached');
  }
}

function connectSSE(jobId, nonce) {
  sitrepState.activeJobId = jobId;
  const es = new EventSource(`/api/sitrep/stream/${jobId}?nonce=${encodeURIComponent(nonce || '')}`);
  const dot = document.getElementById('log-dot');

  es.onmessage = (e) => {
    const data = e.data;
    if (data === '__PING__') return;
    if (data.startsWith('__DONE__')) {
      const status = data.replace('__DONE__', '');
      es.close();
      if (dot) dot.className = status === 'done' ? 'log-dot done' : 'log-dot error';
      const spinner = document.getElementById('pipeline-spinner');
      if (spinner) { spinner.className = ''; spinner.textContent = status === 'done' ? '✓' : '✗'; }

      if (status === 'done') {
        for (let i = 0; i <= sitrepState.currentStep; i++)
          if (sitrepState.stepStates[i] !== 'cached') setSitrepStepState(i, 'done');
        appendLog('─── Pipeline completed successfully ───');
        setTimeout(() => loadSitrepReportsList(), 1500);
      } else {
        setSitrepStepState(sitrepState.currentStep, 'error');
        appendLog('─── Pipeline failed with error ───');
        appendLog('Tip: Check the log above for error details. You can re-run with "Skip cache" to restart from scratch.');
      }
      sitrepState.activeJobId = null;
      document.getElementById('btn-run').disabled = false;
      return;
    }
    appendLog(data);
  };

  es.onerror = () => {
    es.close();
    appendLog('[Connection lost]');
  };
}

async function runPipeline() {
  const country = document.getElementById('inp-country').value.trim();
  const event = document.getElementById('inp-event').value.trim();
  if (!country) { alert('Country name is required.'); return; }

  // Check chunk preview warning
  const cpEl = document.getElementById('chunk-preview');
  if (cpEl && cpEl.classList.contains('err')) {
    if (!confirm('No matching data found for the selected filters. Run anyway?')) return;
  }

  const dateFrom = document.getElementById('inp-date-from').value || '';
  const dateTo = document.getElementById('inp-date-to').value || '';
  const skipCache = document.getElementById('chk-skip-cache').checked;
  const themesRaw = document.getElementById('inp-themes')?.value || '';
  const themes = themesRaw.split(',').map(t => t.trim()).filter(Boolean);

  document.getElementById('btn-run').disabled = true;

  // Reset progress
  sitrepState.currentStep = -1;
  sitrepState.stepStates = new Array(STEPS.length).fill('waiting');
  buildStepsGrid();
  const cons = document.getElementById('log-console');
  if (cons) cons.innerHTML = '';
  const dot = document.getElementById('log-dot');
  if (dot) dot.className = 'log-dot running';
  const spinner = document.getElementById('pipeline-spinner');
  if (spinner) { spinner.className = 'spin'; spinner.textContent = ''; }
  const titleEl = document.getElementById('pipeline-title-text');
  if (titleEl) titleEl.textContent = `${country} / ${event || country}  —  running…`;

  showSitrepView('pipeline');
  deactivateSitrepItems();

  try {
    const resp = await api('/api/sitrep/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ country, event, themes, skip_cache: skipCache, date_from: dateFrom, date_to: dateTo }),
    });
    // Anonymous visitors can browse reports but generation is premium —
    // prompt sign-in instead of showing a raw error.
    if (resp.status === 401) {
      if (window.showLoginPanel) window.showLoginPanel();
      document.getElementById('btn-run').disabled = false;
      return;
    }
    const { job_id, stream_nonce, error } = await resp.json();
    if (error) { alert('Error: ' + error); document.getElementById('btn-run').disabled = false; return; }
    connectSSE(job_id, stream_nonce);
  } catch (err) {
    alert('Server error: ' + err);
    document.getElementById('btn-run').disabled = false;
  }
}


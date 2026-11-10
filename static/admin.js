// ═══════════════════════════════════════════════════════════════
// admin.js — Admin Panel (role management, analytics) — extracted from app.js
// Loaded via <script> tag after shared.js, before app.js
// ═══════════════════════════════════════════════════════════════

// ═════════════════════════════════════════════════════════════════════════
// ADMIN PANEL — User role management
// ═════════════════════════════════════════════════════════════════════════

async function loadAdminUsers() {
  const tbody = document.getElementById('admin-user-tbody');
  if (!tbody) return;
  const tok = window.getIdToken ? window.getIdToken() : '';
  if (!tok) { tbody.innerHTML = '<tr><td colspan="4">Not authenticated</td></tr>'; return; }
  try {
    const resp = await fetch('/api/admin/users', { headers: { 'Authorization': 'Bearer ' + tok } });
    if (!resp.ok) { tbody.innerHTML = '<tr><td colspan="4">Failed to load users</td></tr>'; return; }
    const data = await resp.json();
    const users = data.users || [];
    if (!users.length) { tbody.innerHTML = '<tr><td colspan="4">No users found</td></tr>'; return; }
    tbody.innerHTML = users.map(u => {
      const roleClass = u.role === 'admin' ? 'role-admin' : u.role === 'premium' ? 'role-premium' : 'role-free';
      return `<tr>
        <td>${esc(u.email || u.uid)}</td>
        <td>${esc(u.displayName || '—')}</td>
        <td><span class="admin-role-badge ${roleClass}">${u.role}</span></td>
        <td class="admin-actions">
          ${u.role !== 'free' ? `<button class="btn btn-xs" data-action="set-role" data-uid="${esc(u.uid)}" data-role="free">Free</button>` : ''}
          ${u.role !== 'premium' ? `<button class="btn btn-xs btn-premium" data-action="set-role" data-uid="${esc(u.uid)}" data-role="premium">Premium</button>` : ''}
          ${u.role !== 'admin' ? `<button class="btn btn-xs btn-admin" data-action="set-role" data-uid="${esc(u.uid)}" data-role="admin">Admin</button>` : ''}
        </td>
      </tr>`;
    }).join('');
  } catch {
    tbody.innerHTML = '<tr><td colspan="4">Error loading users</td></tr>';
  }
}

async function setUserRole(uid, role) {
  const tok = window.getIdToken ? window.getIdToken() : '';
  if (!tok) return;
  if (!confirm(`Set role to "${role}" for user ${uid.substring(0, 8)}...?`)) return;
  try {
    const resp = await fetch(`/api/admin/users/${uid}/role`, {
      method: 'PUT',
      headers: { 'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    });
    if (!resp.ok) { const err = await resp.json(); toast(err.error || 'Failed', 'error'); return; }
    toast(`Role set to ${role}`, 'success');
    loadAdminUsers();
  } catch {
    toast('Failed to set role', 'error');
  }
}
window.loadAdminUsers = loadAdminUsers;
window.setUserRole = setUserRole;

// ─────────────────────────────────────────────────────────────────────────────
// ANALYTICS DASHBOARD
// ─────────────────────────────────────────────────────────────────────────────

async function loadAnalytics() {
  const tok = window.getIdToken ? window.getIdToken() : '';
  if (!tok) return;
  loadIngestStatus();
  loadSearchConsole();
  try {
    const resp = await fetch('/api/admin/analytics', {
      headers: { 'Authorization': 'Bearer ' + tok }
    });
    if (!resp.ok) throw new Error('Failed to load analytics');
    const data = await resp.json();

    // KPI Cards
    const kpiContainer = document.getElementById('analytics-kpi-cards');
    if (kpiContainer) {
      kpiContainer.innerHTML = [
        { label: 'Total Users', value: data.users.total, icon: '👥' },
        { label: 'DAU (24h)', value: data.users.dau, icon: '🔥' },
        { label: 'WAU (7d)', value: data.users.wau, icon: '📅' },
        { label: 'New This Week', value: data.users.new_this_week, icon: '✨' },
      ].map(k => `
        <div class="kpi-card">
          <div class="kpi-value">${k.value}</div>
          <div class="kpi-label">${k.icon} ${k.label}</div>
        </div>
      `).join('');
    }

    // DAU Trend Chart
    renderLineChart('chart-dau', data.dau_trend.map(d => d.day).reverse(),
      data.dau_trend.map(d => d.users).reverse(), 'DAU');

    // Event Timeline Chart
    renderBarChart('chart-events', data.events.timeline.map(d => d.day).reverse(),
      data.events.timeline.map(d => d.count).reverse(), 'Events');

    // Top Events Chart
    renderDoughnutChart('chart-top-events',
      data.events.top_events.map(e => e.event),
      data.events.top_events.map(e => e.count));

    // SITREP Runs Chart
    renderBarChart('chart-sitrep',
      data.sitrep_runs.map(s => s.country),
      data.sitrep_runs.map(s => s.count), 'Runs');

    // Recent Users Table
    const tbody = document.querySelector('#analytics-recent-users tbody');
    if (tbody) {
      tbody.innerHTML = data.recent_users.map(u => {
        const roleClass = u.role === 'admin' ? 'role-admin' : u.role === 'premium' ? 'role-premium' : 'role-free';
        return `<tr>
          <td>${esc(u.email || '—')}</td>
          <td><span class="admin-role-badge ${roleClass}">${u.role}</span></td>
          <td>${u.created_at ? new Date(u.created_at * 1000).toLocaleDateString() : '—'}</td>
          <td>${u.last_seen ? new Date(u.last_seen * 1000).toLocaleDateString() : '—'}</td>
        </tr>`;
      }).join('');
    }
  } catch (e) {
    console.error('Analytics load error:', e);
  }
}
window.loadAnalytics = loadAnalytics;

async function loadIngestStatus() {
  const container = document.getElementById('ingest-status-cards');
  const tok = window.getIdToken ? window.getIdToken() : '';
  if (!container || !tok) return;
  try {
    const resp = await fetch('/api/ingest/status', {
      headers: { 'Authorization': 'Bearer ' + tok }
    });
    if (!resp.ok) throw new Error('Failed to load ingest status');
    const data = await resp.json();
    const database = data.database || {};
    const lastRun = data.last_run || {};
    const age = database.age_days == null ? 'Unknown' : `${database.age_days}d`;
    container.innerHTML = [
      { label: 'Source freshness', value: database.status || 'unknown' },
      { label: 'Coverage through', value: database.latest_report_date || '—' },
      { label: 'Source lag', value: age },
      { label: 'Reports available', value: database.report_count || 0 },
      { label: 'Last ingest run', value: lastRun.status || 'unknown' },
      { label: 'Ingest target', value: lastRun.target_date || '—' },
    ].map(item => `
      <div class="kpi-card">
        <div class="kpi-value">${esc(item.value)}</div>
        <div class="kpi-label">${esc(item.label)}</div>
      </div>
    `).join('');
  } catch (error) {
    console.error('Ingest status load error:', error);
    container.innerHTML = '<div class="kpi-card"><div class="kpi-value">Unavailable</div><div class="kpi-label">Data pipeline</div></div>';
  }
}
window.loadIngestStatus = loadIngestStatus;

async function loadSearchConsole() {
  const cards = document.getElementById('gsc-kpi-cards');
  const queryBody = document.querySelector('#gsc-query-table tbody');
  const pageBody = document.querySelector('#gsc-page-table tbody');
  const tok = window.getIdToken ? window.getIdToken() : '';
  if (!cards || !queryBody || !pageBody || !tok) return;
  try {
    const resp = await fetch('/api/admin/growth/search-console', {
      headers: { 'Authorization': 'Bearer ' + tok }
    });
    if (!resp.ok) throw new Error('Failed to load Search Console data');
    const data = await resp.json();
    const snapshot = data.snapshot;
    if (!snapshot) {
      const label = data.configured ? 'Awaiting first sync' : 'Integration disabled';
      cards.innerHTML = `<div class="kpi-card"><div class="kpi-value">${esc(data.status || 'unavailable')}</div><div class="kpi-label">${label}</div></div>`;
      return;
    }

    const integer = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
    const decimal = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
    cards.innerHTML = [
      { label: 'Organic clicks', value: integer.format(snapshot.clicks || 0) },
      { label: 'Search impressions', value: integer.format(snapshot.impressions || 0) },
      { label: 'Search CTR', value: `${decimal.format((snapshot.ctr || 0) * 100)}%` },
      { label: 'Average position', value: decimal.format(snapshot.position || 0) },
      { label: 'Coverage start', value: snapshot.start_date || '—' },
      { label: 'Coverage end', value: snapshot.end_date || '—' },
    ].map(item => `
      <div class="kpi-card">
        <div class="kpi-value">${esc(item.value)}</div>
        <div class="kpi-label">${esc(item.label)}</div>
      </div>
    `).join('');

    queryBody.innerHTML = (data.top_queries || []).map(item => `<tr>
      <td>${esc(item.value)}</td>
      <td>${integer.format(item.clicks || 0)}</td>
      <td>${integer.format(item.impressions || 0)}</td>
      <td>${decimal.format(item.position || 0)}</td>
    </tr>`).join('') || '<tr><td colspan="4">No query data in this period</td></tr>';

    pageBody.innerHTML = (data.top_pages || []).map(item => `<tr>
      <td>${esc(item.value)}</td>
      <td>${integer.format(item.clicks || 0)}</td>
      <td>${integer.format(item.impressions || 0)}</td>
      <td>${decimal.format((item.ctr || 0) * 100)}%</td>
    </tr>`).join('') || '<tr><td colspan="4">No page data in this period</td></tr>';
  } catch (error) {
    console.error('Search Console load error:', error);
    cards.innerHTML = '<div class="kpi-card"><div class="kpi-value">Unavailable</div><div class="kpi-label">Search Console</div></div>';
  }
}
window.loadSearchConsole = loadSearchConsole;

// ─────────────────────────────────────────────────────────────────────────────
// OBSERVABILITY DASHBOARD (LLM/RAG telemetry — obs.db)
// ─────────────────────────────────────────────────────────────────────────────

function _obsPct(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function _obsFmtTime(epochSeconds) {
  if (!epochSeconds) return '—';
  try {
    return new Date(epochSeconds * 1000).toLocaleString();
  } catch {
    return '—';
  }
}

function renderObsKpis(summary) {
  const el = document.getElementById('obs-kpi-cards');
  if (!el) return;
  const items = [
    { label: 'Turns (7d)', value: summary.turns ?? 0 },
    { label: 'Error rate', value: _obsPct(summary.error_rate) },
    { label: 'P95 latency', value: `${summary.latency_p95_ms ?? 0} ms` },
    { label: 'Cost (7d)', value: `$${Number(summary.cost || 0).toFixed(4)}` },
    { label: 'Tool calls', value: summary.tool_calls ?? 0 },
    { label: 'Tool errors', value: summary.tool_errors ?? 0 },
    { label: 'Citation rate', value: _obsPct(summary.citation_rate) },
    { label: 'No-answer rate', value: _obsPct(summary.no_answer_rate) },
  ];
  el.innerHTML = items.map(item => `
    <div class="kpi-card">
      <div class="kpi-value">${esc(String(item.value))}</div>
      <div class="kpi-label">${esc(item.label)}</div>
    </div>
  `).join('');
}

function renderObsHealth(health, summary) {
  const el = document.getElementById('obs-health-line');
  if (!el) return;
  const mcp = health.mcp || {};
  const mcpText = mcp.ready ? `MCP ready · ${mcp.tool_count || 0} tools` : 'MCP not ready yet';
  el.textContent = `Telemetry DB: ${health.db_path || '—'} · ${summary.turns || 0} turns stored · ${mcpText}`;
}

function renderObsTools(tools) {
  const tbody = document.querySelector('#obs-tool-table tbody');
  if (!tbody) return;
  if (!tools.length) {
    tbody.innerHTML = '<tr><td colspan="6">No tool calls recorded yet</td></tr>';
    return;
  }
  tbody.innerHTML = tools.slice(0, 40).map(t => `<tr>
    <td>${esc(t.tool)}</td>
    <td>${esc(t.group || '—')}${t.server && t.server !== 'native' ? ` / ${esc(t.server)}` : ''}</td>
    <td>${t.calls}</td>
    <td>${_obsPct(t.error_rate)}</td>
    <td>${t.p95_ms}</td>
    <td>${t.avg_result_chars}</td>
  </tr>`).join('');
}

function renderObsModels(models) {
  const tbody = document.querySelector('#obs-model-table tbody');
  if (!tbody) return;
  if (!models.length) {
    tbody.innerHTML = '<tr><td colspan="7">No turns recorded yet</td></tr>';
    return;
  }
  tbody.innerHTML = models.map(m => `<tr>
    <td>${esc(m.model_key)}<br><span class="admin-hint">${esc(m.model_id || '')}</span></td>
    <td>${m.turns}</td>
    <td>${_obsPct(m.share)}</td>
    <td>${m.p95_ms}</td>
    <td>$${Number(m.cost || 0).toFixed(4)}</td>
    <td>${_obsPct(m.citation_rate)}</td>
    <td>${_obsPct(m.error_rate)}</td>
  </tr>`).join('');
}

function renderObsTurns(turns) {
  const tbody = document.querySelector('#obs-turn-table tbody');
  if (!tbody) return;
  if (!turns.length) {
    tbody.innerHTML = '<tr><td colspan="7">No turns recorded yet</td></tr>';
    return;
  }
  tbody.innerHTML = turns.map(t => `<tr>
    <td>${esc(_obsFmtTime(t.started_at))}</td>
    <td>${esc(t.model_key || '—')}</td>
    <td><span class="obs-status obs-status-${esc(t.status)}">${esc(t.status)}</span></td>
    <td>${t.latency_ms || 0} ms</td>
    <td>${t.tools_count || 0}</td>
    <td>${t.citations || 0}</td>
    <td>$${Number(t.cost || 0).toFixed(4)}</td>
  </tr>`).join('');
}

function renderObsCalibration(data) {
  const el = document.getElementById('obs-calibration-line');
  if (!el) return;
  const latest = data && data.latest;
  const labels = (data && data.human_labeled_turns) || 0;
  if (!latest) {
    el.textContent = `Judge-human calibration: not run yet (${labels} human-labeled turns). Use scripts/calibrate_judge.py.`;
    return;
  }
  el.textContent = `Judge-human calibration: QWK ${Number(latest.qwk || 0).toFixed(3)} `
    + `· Spearman ${Number(latest.spearman || 0).toFixed(3)} · MAE ${Number(latest.mae || 0).toFixed(2)} `
    + `· n=${latest.n} · judge ${latest.judge_model || '—'}`;
}

function renderObsEval(data) {
  const cards = document.getElementById('obs-eval-kpis');
  const tbody = document.querySelector('#obs-eval-table tbody');
  if (!cards || !tbody) return;
  const summary = (data && data.summary) || {};
  const fb = (data && data.feedback) || {};
  const items = [
    { label: 'Avg judge score', value: summary.avg != null ? `${summary.avg}/5` : '—' },
    { label: 'Scored turns', value: summary.count || 0 },
    { label: 'Low scores (<3)', value: summary.low_count || 0 },
    { label: 'Low-score rate', value: _obsPct(summary.low_rate) },
    { label: '👍 votes', value: fb.up || 0 },
    { label: '👎 votes', value: fb.down || 0 },
    { label: 'Positive rate', value: _obsPct(fb.positive_rate) },
  ];
  cards.innerHTML = items.map(item => `
    <div class="kpi-card">
      <div class="kpi-value">${esc(String(item.value))}</div>
      <div class="kpi-label">${esc(item.label)}</div>
    </div>
  `).join('');

  const rows = (data && data.recent) || [];
  tbody.innerHTML = rows.length ? rows.map(r => `<tr>
    <td>${esc(_obsFmtTime(r.created_at))}</td>
    <td>${esc(r.judge_model || '—')}</td>
    <td>${Number(r.score || 0).toFixed(2)}</td>
    <td>${esc((r.issues || []).join('; ') || '—')}</td>
    <td><code>${esc(r.turn_id)}</code></td>
  </tr>`).join('') : '<tr><td colspan="5">No judged turns yet — run an evaluation.</td></tr>';
}

function renderObsRetrieval(retrieval) {
  const el = document.getElementById('obs-retrieval-line');
  if (!el) return;
  const latest = retrieval && retrieval.latest;
  if (!latest) {
    el.textContent = 'No retrieval runs yet. Run scripts/eval_retrieval.py --gold … --apply';
    return;
  }
  const pct = (v) => `${(Number(v || 0) * 100).toFixed(1)}%`;
  el.textContent = `Latest (${_obsFmtTime(latest.created_at)}): Recall@${latest.k} ${pct(latest.mean_recall)} · `
    + `Recall@${latest.stage1_k} ceiling ${pct(latest.mean_recall_stage1)} · `
    + `nDCG@${latest.k} ${pct(latest.mean_ndcg)} · MRR ${pct(latest.mean_mrr)} · ${latest.queries} queries`;
}

async function runObsEval() {
  const btn = document.getElementById('obs-eval-run-btn');
  const status = document.getElementById('obs-eval-status');
  const dry = document.getElementById('obs-eval-dry');
  const tok = window.getIdToken ? window.getIdToken() : '';
  if (!tok || !btn || !status) return;
  btn.disabled = true;
  status.className = 'running';
  status.textContent = 'Starting evaluation…';
  try {
    const resp = await fetch('/api/admin/obs/eval/run', {
      method: 'POST',
      headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ sample: 10, samples: 3, days: 30, apply: !(dry && dry.checked) }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }
    const { job_id: jobId } = await resp.json();
    status.textContent = 'Evaluation running (judge calls)…';
    const deadline = Date.now() + 10 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 3000));
      const poll = await fetch(`/api/admin/obs/eval/run/status/${jobId}`, { headers: { Authorization: `Bearer ${tok}` } });
      if (!poll.ok) throw new Error(`status HTTP ${poll.status}`);
      const job = await poll.json();
      if (job.status === 'done') {
        const report = job.report || {};
        status.className = 'done';
        status.textContent = `Done: ${report.scored || 0}/${report.sampled || 0} scored · avg ${report.avg ?? '—'} · ${report.dry_run ? 'dry run' : 'saved'}`;
        break;
      }
      if (job.status === 'error') throw new Error(job.error || 'eval failed');
    }
    await loadObservability();
  } catch (err) {
    status.className = 'error';
    status.textContent = `Eval failed: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
}

// ── Human calibration: rate judged answers one by one (blind) ───────────────
const obsCalState = { queue: [], index: 0, selected: 0 };

async function _obsAdminFetch(url, options) {
  const tok = window.getIdToken ? window.getIdToken() : '';
  const headers = Object.assign({ Authorization: `Bearer ${tok}` }, (options && options.headers) || {});
  const resp = await fetch(url, Object.assign({}, options, { headers }));
  if (!resp.ok) {
    let msg = `HTTP ${resp.status}`;
    try { const err = await resp.json(); msg = err.error || msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return resp.json();
}

function _obsCalProgressText(progress) {
  if (!progress) return '';
  return `Judged: ${progress.judged || 0} · Labeled: ${progress.labeled || 0} · Remaining: ${progress.remaining || 0}`;
}

async function loadCalibrationQueue() {
  const progressEl = document.getElementById('obs-cal-progress');
  const resultEl = document.getElementById('obs-cal-result');
  const card = document.getElementById('obs-cal-card');
  if (resultEl) resultEl.textContent = 'Loading…';
  try {
    const data = await _obsAdminFetch('/api/admin/obs/calibration/queue?limit=10');
    obsCalState.queue = data.queue || [];
    obsCalState.index = 0;
    if (progressEl) progressEl.textContent = _obsCalProgressText(data.progress);
    if (!obsCalState.queue.length) {
      if (card) card.style.display = 'none';
      if (resultEl) resultEl.textContent = 'No unlabeled judged turns left. Run an evaluation first (or compute QWK).';
      return;
    }
    if (resultEl) resultEl.textContent = '';
    renderCalibrationCard();
  } catch (err) {
    if (resultEl) resultEl.textContent = `Queue error: ${err.message}`;
  }
}

function renderCalibrationCard() {
  const item = obsCalState.queue[obsCalState.index];
  const card = document.getElementById('obs-cal-card');
  if (!card) return;
  if (!item) {
    card.style.display = 'none';
    const resultEl = document.getElementById('obs-cal-result');
    if (resultEl) resultEl.textContent = 'Queue complete. Click "Compute QWK" to see agreement.';
    return;
  }
  card.style.display = '';
  obsCalState.selected = 0;
  const meta = document.getElementById('obs-cal-meta');
  const question = document.getElementById('obs-cal-question');
  const answer = document.getElementById('obs-cal-answer');
  const evidence = document.getElementById('obs-cal-evidence');
  const evidenceWrap = document.getElementById('obs-cal-evidence-wrap');
  const notes = document.getElementById('obs-cal-notes');
  const reveal = document.getElementById('obs-cal-reveal');
  if (meta) meta.textContent = `${obsCalState.index + 1}/${obsCalState.queue.length} · ${item.model_id || 'unknown model'} · turn ${item.turn_id}`;
  if (question) question.textContent = item.question || '';
  if (answer) answer.textContent = item.answer || '';
  if (evidence) evidence.textContent = item.evidence || '(no tool evidence stored for this turn)';
  if (evidenceWrap) evidenceWrap.open = false;
  if (notes) notes.value = '';
  if (reveal) { reveal.textContent = ''; reveal.className = 'admin-hint'; }
  const buttons = document.getElementById('obs-cal-buttons');
  if (buttons) {
    buttons.innerHTML = '';
    for (let score = 1; score <= 5; score++) {
      const btn = document.createElement('button');
      btn.className = 'btn btn-xs';
      btn.textContent = String(score);
      btn.title = `Rate ${score}/5`;
      btn.addEventListener('click', () => selectCalScore(score));
      buttons.appendChild(btn);
    }
  }
}

function selectCalScore(score) {
  obsCalState.selected = score;
  const buttons = document.getElementById('obs-cal-buttons');
  if (!buttons) return;
  buttons.querySelectorAll('button').forEach((btn, idx) => {
    btn.classList.toggle('active', idx + 1 === score);
  });
}

function nextCalibration() {
  obsCalState.index += 1;
  if (obsCalState.index >= obsCalState.queue.length) {
    renderCalibrationCard(); // hides card + completion message
    return;
  }
  renderCalibrationCard();
}

async function submitCalibration() {
  const item = obsCalState.queue[obsCalState.index];
  const reveal = document.getElementById('obs-cal-reveal');
  const notes = document.getElementById('obs-cal-notes');
  if (!item) return;
  if (!obsCalState.selected) {
    if (reveal) { reveal.className = 'admin-hint bad'; reveal.textContent = 'Pick 1–5 first.'; }
    return;
  }
  try {
    const data = await _obsAdminFetch('/api/admin/obs/calibration/label', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        turn_id: item.turn_id,
        score: obsCalState.selected,
        notes: notes ? notes.value : '',
      }),
    });
    if (reveal) {
      const sign = data.diff > 0 ? '+' : '';
      reveal.className = `admin-hint ${Math.abs(data.diff) >= 1 ? 'bad' : 'good'}`;
      reveal.textContent = `Judge: ${data.judge_score}/5 (${sign}${data.diff}) · ${data.judge_model}`;
    }
    const progressEl = document.getElementById('obs-cal-progress');
    if (progressEl) progressEl.textContent = _obsCalProgressText(data.progress);
    setTimeout(nextCalibration, 1400);
  } catch (err) {
    if (reveal) { reveal.className = 'admin-hint bad'; reveal.textContent = `Save failed: ${err.message}`; }
  }
}

async function computeCalibration() {
  const resultEl = document.getElementById('obs-cal-result');
  if (resultEl) resultEl.textContent = 'Computing…';
  try {
    const data = await _obsAdminFetch('/api/admin/obs/calibration/score', { method: 'POST' });
    const m = data.metrics || {};
    if (resultEl) {
      resultEl.textContent = `QWK ${Number(m.qwk || 0).toFixed(3)} · Spearman ${Number(m.spearman || 0).toFixed(3)} · MAE ${Number(m.mae || 0).toFixed(2)} · n=${m.n} · ${(m.interpretation || {}).verdict || ''}`;
    }
    const line = document.getElementById('obs-calibration-line');
    if (line) {
      line.textContent = `Judge-human calibration: QWK ${Number(m.qwk || 0).toFixed(3)} · Spearman ${Number(m.spearman || 0).toFixed(3)} · MAE ${Number(m.mae || 0).toFixed(2)} · n=${m.n} · judge ${data.judge_model || '—'}`;
    }
  } catch (err) {
    if (resultEl) resultEl.textContent = `Calibration error: ${err.message}`;
  }
}

function _bindObsCalibration() {
  const start = document.getElementById('obs-cal-start');
  if (start && !start.dataset.bound) {
    start.dataset.bound = '1';
    start.addEventListener('click', loadCalibrationQueue);
  }
  const scoreBtn = document.getElementById('obs-cal-score');
  if (scoreBtn && !scoreBtn.dataset.bound) {
    scoreBtn.dataset.bound = '1';
    scoreBtn.addEventListener('click', computeCalibration);
  }
  const submit = document.getElementById('obs-cal-submit');
  if (submit && !submit.dataset.bound) {
    submit.dataset.bound = '1';
    submit.addEventListener('click', submitCalibration);
  }
  const skip = document.getElementById('obs-cal-skip');
  if (skip && !skip.dataset.bound) {
    skip.dataset.bound = '1';
    skip.addEventListener('click', nextCalibration);
  }
}

// ── Error monitoring dashboard ──────────────────────────────────────────────
async function loadErrors() {
  const statusEl = document.getElementById('err-status');
  if (statusEl) { statusEl.className = 'admin-hint'; statusEl.textContent = 'Loading…'; }
  try {
    const [summary, groups, recent] = await Promise.all([
      _obsAdminFetch('/api/admin/errors/summary?days=7'),
      _obsAdminFetch('/api/admin/errors/groups?days=7'),
      _obsAdminFetch('/api/admin/errors/recent?days=7&limit=25'),
    ]);
    renderErrorKpis(summary);
    renderErrorGroups(groups.groups || []);
    renderErrorRecent(recent.events || []);
    const line = document.getElementById('err-health-line');
    if (line) {
      line.textContent = `Last 7d: ${summary.errors || 0} errors · ${summary.fingerprints || 0} groups · `
        + `${summary.users || 0} users · 5xx rate ${_obsPct(summary.error_rate)} · release ${window.SIGHTLINE_RELEASE || 'dev'}`;
    }
    if (statusEl) statusEl.textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (err) {
    if (statusEl) { statusEl.className = 'admin-hint bad'; statusEl.textContent = `Error dashboard unavailable: ${err.message}`; }
  }
  _bindErrors();
}

function renderErrorKpis(summary) {
  const el = document.getElementById('err-kpi-cards');
  if (!el) return;
  const items = [
    { label: 'Errors (7d)', value: summary.errors ?? 0 },
    { label: 'Unresolved', value: summary.unresolved ?? 0 },
    { label: 'Groups', value: summary.fingerprints ?? 0 },
    { label: 'Affected users', value: summary.users ?? 0 },
    { label: 'Requests (7d)', value: summary.requests ?? 0 },
    { label: '5xx rate', value: _obsPct(summary.error_rate) },
  ];
  el.innerHTML = items.map(item => `
    <div class="kpi-card">
      <div class="kpi-value">${esc(String(item.value))}</div>
      <div class="kpi-label">${esc(item.label)}</div>
    </div>
  `).join('');
}

function _errKindBadge(kind) {
  return `<span class="err-kind err-${esc(kind || 'backend')}">${esc(kind || 'backend')}</span>`;
}

function renderErrorGroups(groups) {
  const tbody = document.querySelector('#err-groups-table tbody');
  if (!tbody) return;
  if (!groups.length) {
    tbody.innerHTML = '<tr><td colspan="8">No errors recorded. Good news (or nothing exercised yet).</td></tr>';
    return;
  }
  tbody.innerHTML = groups.map(g => `<tr>
    <td>${_errKindBadge(g.kind)}</td>
    <td><code>${esc(g.route || '—')}</code></td>
    <td>${g.count || 0}</td>
    <td>${g.users || 0}</td>
    <td>${esc(_obsFmtTime(g.first_ts))}</td>
    <td>${esc(_obsFmtTime(g.last_ts))}</td>
    <td class="err-sample">${esc((g.sample_message || g.exception_type || '').slice(0, 120))}</td>
    <td>${g.resolved ? '<span class="admin-hint">resolved</span>' : `<button class="btn btn-xs" data-err-resolve="${esc(g.fingerprint)}">Resolve</button>`}</td>
  </tr>`).join('');
  tbody.querySelectorAll('[data-err-resolve]').forEach(btn => {
    btn.addEventListener('click', () => resolveError(btn.dataset.errResolve));
  });
}

function renderErrorRecent(events) {
  const tbody = document.querySelector('#err-recent-table tbody');
  if (!tbody) return;
  if (!events.length) {
    tbody.innerHTML = '<tr><td colspan="6">No recent error events.</td></tr>';
    return;
  }
  tbody.innerHTML = events.map(ev => `<tr>
    <td>${esc(_obsFmtTime(ev.ts))}</td>
    <td>${_errKindBadge(ev.kind)}</td>
    <td><code>${esc(ev.route || '—')}</code></td>
    <td>${ev.status || '—'}</td>
    <td><code>${esc(ev.request_id || '—')}</code></td>
    <td class="err-sample">${esc((ev.message || '').slice(0, 140))}</td>
  </tr>`).join('');
}

async function resolveError(fingerprint) {
  try {
    await _obsAdminFetch(`/api/admin/errors/${encodeURIComponent(fingerprint)}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resolved: true }),
    });
    await loadErrors();
  } catch (err) {
    const statusEl = document.getElementById('err-status');
    if (statusEl) { statusEl.className = 'admin-hint bad'; statusEl.textContent = `Resolve failed: ${err.message}`; }
  }
}

async function createTestError() {
  try {
    await _obsAdminFetch('/api/admin/errors/test', { method: 'POST' });
    await loadErrors();
  } catch (err) {
    const statusEl = document.getElementById('err-status');
    if (statusEl) { statusEl.className = 'admin-hint bad'; statusEl.textContent = `Test error failed: ${err.message}`; }
  }
}

function _bindErrors() {
  const refresh = document.getElementById('err-refresh-btn');
  if (refresh && !refresh.dataset.bound) {
    refresh.dataset.bound = '1';
    refresh.addEventListener('click', loadErrors);
  }
  const test = document.getElementById('err-test-btn');
  if (test && !test.dataset.bound) {
    test.dataset.bound = '1';
    test.addEventListener('click', createTestError);
  }
}

function _bindObsEvalButton() {
  const btn = document.getElementById('obs-eval-run-btn');
  if (btn && !btn.dataset.bound) {
    btn.dataset.bound = '1';
    btn.addEventListener('click', runObsEval);
  }
}

async function loadObservability() {
  const tok = window.getIdToken ? window.getIdToken() : '';
  if (!tok) return;
  const headers = { Authorization: `Bearer ${tok}` };
  const getJson = async (url) => {
    const resp = await fetch(url, { headers });
    if (!resp.ok) throw new Error(`${url} → HTTP ${resp.status}`);
    return resp.json();
  };
  try {
    const [summary, series, tools, models, turns, health, evalData, calibData] = await Promise.all([
      getJson('/api/admin/obs/summary?days=7'),
      getJson('/api/admin/obs/timeseries?days=14'),
      getJson('/api/admin/obs/tools?days=7'),
      getJson('/api/admin/obs/models?days=7'),
      getJson('/api/admin/obs/turns?limit=25'),
      getJson('/api/admin/obs/health'),
      getJson('/api/admin/obs/eval?days=30'),
      getJson('/api/admin/obs/calibration'),
    ]);
    renderObsKpis(summary);
    renderObsHealth(health, summary);
    const points = series.series || [];
    const labels = points.map(p => p.date.slice(5));
    renderLineChart('chart-obs-turns', labels, points.map(p => p.turns), 'Turns');
    renderLineChart('chart-obs-p50', labels, points.map(p => p.p50_ms), 'P50 ms');
    renderLineChart('chart-obs-p95', labels, points.map(p => p.p95_ms), 'P95 ms');
    renderLineChart('chart-obs-cost', labels, points.map(p => p.cost), 'USD');
    renderObsTools(tools.tools || []);
    renderObsModels(models.models || []);
    renderObsTurns(turns.turns || []);
    renderObsEval(evalData);
    renderObsCalibration(calibData);
    renderObsRetrieval(evalData.retrieval);
    _bindObsEvalButton();
    _bindObsCalibration();
  } catch (err) {
    console.error('Observability load error:', err);
    const cards = document.getElementById('obs-kpi-cards');
    if (cards) {
      cards.innerHTML = '<div class="kpi-card"><div class="kpi-value">Unavailable</div><div class="kpi-label">Observability API</div></div>';
    }
    const line = document.getElementById('obs-health-line');
    if (line) line.textContent = `Observability API unavailable: ${err.message}`;
  }
}
window.loadObservability = loadObservability;

// Chart.js helpers
function _getOrCreateChartCtx(canvasId) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;
  if (!window._analyticsCharts) window._analyticsCharts = {};
  if (window._analyticsCharts[canvasId]) window._analyticsCharts[canvasId].destroy();
  return ctx;
}

function renderLineChart(canvasId, labels, data, label) {
  const ctx = _getOrCreateChartCtx(canvasId);
  if (!ctx) return;
  window._analyticsCharts[canvasId] = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ label, data, borderColor: '#4f9eff', backgroundColor: 'rgba(79,158,255,0.1)', tension: 0.3 }] },
    options: { responsive: true, plugins: { legend: { display: false } } }
  });
}

function renderBarChart(canvasId, labels, data, label) {
  const ctx = _getOrCreateChartCtx(canvasId);
  if (!ctx) return;
  window._analyticsCharts[canvasId] = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ label, data, backgroundColor: '#4f9eff' }] },
    options: { responsive: true, plugins: { legend: { display: false } } }
  });
}

function renderDoughnutChart(canvasId, labels, data) {
  const ctx = _getOrCreateChartCtx(canvasId);
  if (!ctx) return;
  window._analyticsCharts[canvasId] = new Chart(ctx, {
    type: 'doughnut',
    data: { labels, datasets: [{ data, backgroundColor: ['#4f9eff', '#ff6b6b', '#4ecdc4', '#f7df1e', '#a55eea', '#fd7e14', '#26de81', '#fc5c65', '#45aaf2', '#fd9644'] }] },
    options: { responsive: true }
  });
}
window.renderLineChart = renderLineChart;
window.renderBarChart = renderBarChart;
window.renderDoughnutChart = renderDoughnutChart;

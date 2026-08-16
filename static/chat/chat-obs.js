// ═══════════════════════════════════════════════════════════════
// chat-obs.js — Observation panel (right-side agent trace, toggleable)
// Shows what the agent did, what it cost, and where it went.
//
// Consumes the SSE events emitted by /api/agent/chat:
//   llm          → addObsLlm        llm_done → finalizeObsLlm
//   tool_start   → addObsStep       tool_done → finalizeObsStep
//   error        → obsTraceError    done      → renderObsFooter + refreshObsTotals
//
// TOOL EXTENSION NOTE: adding a new tool group on the backend is picked up
// automatically — /api/agent/capabilities lists sources straight from
// TOOL_GROUP_MAP, and obsGroupHue() derives a stable color from the group
// name, so NO edits here are needed when a new data source ships.
// ═══════════════════════════════════════════════════════════════

const obsState = {
  open: false,
  capabilitiesLoaded: false,
  currentLlm: null,
};

function obsEl(id) { return document.getElementById(id); }

function setObsOpen(open) {
  obsState.open = !!open;
  const panel = obsEl('obs-panel');
  const toggle = obsEl('obs-toggle-btn');
  const chatMain = document.querySelector('#panel-agent .chat-main');
  if (panel) {
    panel.classList.toggle('open', obsState.open);
    panel.setAttribute('aria-hidden', String(!obsState.open));
  }
  if (toggle) {
    toggle.classList.toggle('active', obsState.open);
    toggle.classList.toggle('hidden', obsState.open);
  }
  if (chatMain) chatMain.classList.toggle('obs-open', obsState.open);
  try { localStorage.setItem('sightline.obsOpen', obsState.open ? '1' : '0'); } catch (e) { /* ignore */ }
}

function toggleObsPanel() {
  setObsOpen(!obsState.open);
  if (obsState.open) {
    renderObsOverview();
    updateObsModel();
  }
}

function obsGroupHue(group) {
  // Known groups keep curated colors; anything new gets a stable hue derived
  // from its name, so adding a tool group needs NO frontend change.
  const known = {
    ReliefWeb: 210, HDX: 160, News: 30, GDACS: 0, Weather: 260,
    WorldBank: 45, ACLED: 350, MCP: 200, Proposals: 120, SQL: 280,
  };
  if (known[group] != null) return known[group];
  if (!group) return 220;
  let h = 0;
  for (let i = 0; i < group.length; i++) h = (h * 31 + group.charCodeAt(i)) % 360;
  return h;
}

function obsGroupBadge(group) {
  if (!group) return '';
  const hue = obsGroupHue(group);
  return `<span class="obs-group-badge" style="background:hsla(${hue},70%,50%,.15);color:hsl(${hue},70%,42%)">${esc(group)}</span>`;
}

function resetObsTrace() {
  obsState.currentLlm = null;
  const trace = obsEl('obs-trace');
  if (trace) trace.innerHTML = '';
  const footer = obsEl('obs-footer');
  if (footer) footer.innerHTML = '';
  const overview = obsEl('obs-overview');
  if (overview) overview.style.display = 'none';
  if (trace) trace.style.display = '';
}

// One LLM iteration block — the agent's "reasoning" step in the loop.
function addObsLlm(iteration) {
  const trace = obsEl('obs-trace');
  if (!trace) return;
  const block = document.createElement('div');
  block.className = 'obs-llm pending';
  block.dataset.iteration = String(iteration);
  block.innerHTML =
    '<div class="obs-llm-head"><div class="spin"></div><span class="obs-llm-label">Thinking</span><span class="obs-llm-iter">#' + iteration + '</span></div>' +
    '<div class="obs-llm-tools"></div>';
  trace.appendChild(block);
  trace.scrollTop = trace.scrollHeight;
  obsState.currentLlm = block;
}

function finalizeObsLlm(iteration, data) {
  const trace = obsEl('obs-trace');
  if (!trace) return;
  let block = obsState.currentLlm;
  if (!block || block.dataset.iteration !== String(iteration)) {
    block = trace.querySelector('.obs-llm.pending[data-iteration="' + iteration + '"]');
  }
  if (!block) return;
  block.classList.remove('pending');
  block.classList.add('done');
  const spin = block.querySelector('.spin');
  if (spin) spin.remove();
  const usage = (data && data.usage) ? fmtTokens(data.usage.in || 0) + ' in / ' + fmtTokens(data.usage.out || 0) + ' out' : '';
  const head = block.querySelector('.obs-llm-head');
  if (usage) {
    let badge = block.querySelector('.obs-llm-usage');
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'obs-llm-usage';
      head.appendChild(badge);
    }
    badge.textContent = usage;
  }
  trace.scrollTop = trace.scrollHeight;
}

function addObsStep(name) {
  const trace = obsEl('obs-trace');
  if (!trace) return;
  const el = document.createElement('div');
  el.className = 'obs-step pending';
  el.dataset.toolName = name;
  el.innerHTML = '<div class="obs-step-row"><div class="spin"></div><span class="obs-step-name">' + esc(name) + '</span></div>';
  // Nest under the current LLM block when present (loop view), else straight into trace
  let container = trace;
  if (obsState.currentLlm) {
    const tc = obsState.currentLlm.querySelector('.obs-llm-tools');
    if (tc) container = tc;
  }
  container.appendChild(el);
  trace.scrollTop = trace.scrollHeight;
}

function finalizeObsStep(name, data) {
  const trace = obsEl('obs-trace');
  if (!trace) return;
  let el = null;
  const steps = trace.querySelectorAll('.obs-step');
  for (const s of steps) {
    if (s.dataset.toolName === name && s.classList.contains('pending')) { el = s; break; }
  }
  if (!el) return;
  el.classList.remove('pending');
  el.classList.add('done');
  if (data && data.status === 'error') el.classList.add('error');
  const group = (data && data.group) || '';
  const summary = (data && data.summary) || '';
  const durText = (data && data.duration_ms) ? (data.duration_ms / 1000).toFixed(1) + 's' : '';
  const mark = (data && data.status === 'error') ? '✗' : '✓';
  el.innerHTML =
    '<div class="obs-step-row"><span class="obs-step-mark">' + mark + '</span><span class="obs-step-name">' + esc(name) + '</span>' + obsGroupBadge(group) + '</div>' +
    (summary ? '<div class="obs-step-summary">' + esc(summary) + '</div>' : '') +
    (durText ? '<div class="obs-step-dur">' + durText + '</div>' : '');
  trace.scrollTop = trace.scrollHeight;
}

function obsTraceError(text) {
  const trace = obsEl('obs-trace');
  if (!trace) return;
  trace.querySelectorAll('.obs-llm.pending').forEach((el) => {
    el.classList.remove('pending');
    el.classList.add('error');
    const spin = el.querySelector('.spin');
    if (spin) spin.remove();
  });
  trace.querySelectorAll('.obs-step.pending').forEach((el) => {
    el.classList.remove('pending');
    el.classList.add('error');
    el.innerHTML =
      '<div class="obs-step-row"><span class="obs-step-mark">✗</span><span class="obs-step-name">' + esc(el.dataset.toolName || '') + '</span></div>' +
      '<div class="obs-step-summary">' + esc(text || '') + '</div>';
  });
}

function renderObsFooter(meta) {
  const footer = obsEl('obs-footer');
  if (!footer) return;
  const parts = [];
  if (meta && meta.tools && meta.tools.length) parts.push(meta.tools.length + ' tools');
  if (meta && meta.usage && (meta.usage.in || meta.usage.out)) {
    parts.push(fmtTokens(meta.usage.in) + ' in / ' + fmtTokens(meta.usage.out) + ' out');
  }
  if (meta && meta.cost != null) parts.push('$' + meta.cost.toFixed(4));
  if (meta && meta.latency_ms) parts.push((meta.latency_ms / 1000).toFixed(1) + 's');
  let sourcesHtml = '';
  if (meta && meta.sources) {
    const entries = Object.entries(meta.sources);
    if (entries.length) {
      sourcesHtml = '<div class="obs-sources-line">' + entries.map((pair) => esc(pair[0]) + ' (' + pair[1] + ')').join(' → ') + '</div>';
    }
  }
  footer.innerHTML = sourcesHtml + '<div class="obs-footer-stats">' + parts.join(' · ') + '</div>';
}

async function renderObsOverview() {
  // Sources: load once (the tool set rarely changes mid-session)
  if (!obsState.capabilitiesLoaded) {
    const sourcesEl = obsEl('obs-sources');
    if (sourcesEl) sourcesEl.innerHTML = '<div class="obs-hint">Loading…</div>';
    try {
      const res = await api('/api/agent/capabilities');
      const data = await res.json();
      if (Array.isArray(data.sources) && data.sources.length) {
        if (sourcesEl) {
          sourcesEl.innerHTML = data.sources.map((s) =>
            '<span class="obs-source-chip"><span class="obs-source-dot" style="background:hsl(' + obsGroupHue(s.name) + ',70%,50%)"></span>' + esc(s.name) + ' <span class="obs-source-count">' + s.count + '</span></span>'
          ).join('');
        }
      }
      obsState.capabilitiesLoaded = true;
    } catch (e) {
      if (sourcesEl) sourcesEl.innerHTML = '<div class="obs-hint">Unavailable</div>';
    }
  }
  // Cumulative totals: refresh every open (they grow with each message)
  const statsEl = obsEl('obs-stats');
  if (statsEl) statsEl.innerHTML = '<div class="obs-hint">Loading…</div>';
  await refreshObsTotals();
  updateObsModel();
}

function renderObsTotals(d) {
  const el = obsEl('obs-stats');
  if (!el || !d) return;
  const cost = d.total_cost != null ? '$' + Number(d.total_cost).toFixed(4) : '$0';
  const tin = (d.total_tokens && d.total_tokens.in) || 0;
  const tout = (d.total_tokens && d.total_tokens.out) || 0;
  el.innerHTML =
    '<div class="obs-stat"><span class="obs-stat-label">Cost</span><span class="obs-stat-value">' + esc(cost) + '</span></div>' +
    '<div class="obs-stat"><span class="obs-stat-label">Tokens</span><span class="obs-stat-value">' + esc(fmtTokens(tin) + ' in / ' + fmtTokens(tout) + ' out') + '</span></div>' +
    '<div class="obs-stat"><span class="obs-stat-label">Tools</span><span class="obs-stat-value">' + esc(String(d.total_tools || 0)) + '</span></div>' +
    '<div class="obs-stat"><span class="obs-stat-label">Chats</span><span class="obs-stat-value">' + esc(String(d.total_chats || 0)) + '</span></div>';
}

async function refreshObsTotals() {
  try {
    const ures = await api('/api/agent/usage');
    const udata = await ures.json();
    renderObsTotals(udata);
  } catch (e) { /* ignore */ }
}

function updateObsModel() {
  const modelEl = obsEl('obs-model');
  if (!modelEl) return;
  const labelEl = document.getElementById('model-selector-label');
  modelEl.textContent = labelEl ? labelEl.textContent.trim() : (chatState && chatState.selectedModel ? chatState.selectedModel : 'flash');
}

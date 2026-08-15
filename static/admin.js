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


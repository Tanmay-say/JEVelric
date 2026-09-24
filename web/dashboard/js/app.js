/**
 * JEVelric Console Dashboard — SPA
 * Hash-based routing: #/ = case list, #/case/HHG-xxx = case detail
 * Reads from /api/cases and /api/cases/{id}
 */
(function () {
  'use strict';

  const API_BASE = '/api';
  const $main = () => document.getElementById('dash-content');

  // ── Helpers ─────────────────────────────────────────────

  function formatUSD(n) {
    return '$' + Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function humanPattern(p) {
    const map = {
      card_testing: 'Card Testing',
      card_not_present_fraud: 'CNP Fraud',
      card_not_present_new_device: 'CNP + New Device',
      out_of_region_use: 'Out of Region',
      account_takeover: 'Account Takeover',
      undocumented: 'Undocumented',
      none: 'None',
    };
    return map[p] || p || 'None';
  }

  function humanStatus(s) {
    const map = {
      closed_fraud: 'Closed — Fraud',
      closed_legitimate: 'Closed — Legitimate',
      escalated: 'Escalated',
      open: 'Open',
    };
    return map[s] || s;
  }

  function verdictClass(v) {
    const map = { fraud: 'badge-fraud', legitimate: 'badge-legitimate', uncertain: 'badge-uncertain' };
    return map[v] || 'badge-escalated';
  }

  function statusDotClass(s) {
    return s || 'open';
  }

  function routeClass(r) {
    return 'pill-route-' + (r || 'auto').toLowerCase();
  }

  function escapeHTML(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }

  // ── API ─────────────────────────────────────────────────

  async function fetchJSON(url) {
    const resp = await fetch(API_BASE + url);
    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    return resp.json();
  }

  // ── Router ──────────────────────────────────────────────

  function getRoute() {
    const hash = location.hash || '#/';
    if (hash.startsWith('#/case/')) {
      return { view: 'detail', caseId: hash.replace('#/case/', '') };
    }
    return { view: 'list' };
  }

  async function route() {
    const r = getRoute();
    const el = $main();
    el.innerHTML = '<div class="loading-container"><div class="spinner"></div><div class="loading-text">Loading…</div></div>';
    try {
      if (r.view === 'detail') {
        await renderDetail(el, r.caseId);
      } else {
        await renderList(el);
      }
    } catch (err) {
      el.innerHTML = `<div class="error-state"><h2>Error</h2><p>${escapeHTML(err.message)}</p><p style="margin-top:12px"><a href="#/">← Back to case list</a></p></div>`;
    }
  }

  // ── Case List ───────────────────────────────────────────

  let _cachedCases = null;
  let _sortCol = 'case_id';
  let _sortAsc = true;
  let _filterVerdict = 'all';
  let _filterPattern = 'all';

  async function renderList(el) {
    if (!_cachedCases) {
      const data = await fetchJSON('/cases');
      _cachedCases = data.cases || [];
    }
    render();

    function render() {
      let cases = [..._cachedCases];

      // Filter
      if (_filterVerdict !== 'all') cases = cases.filter(c => c.verdict === _filterVerdict);
      if (_filterPattern !== 'all') cases = cases.filter(c => c.pattern === _filterPattern);

      // Sort
      cases.sort((a, b) => {
        let va = a[_sortCol], vb = b[_sortCol];
        if (typeof va === 'string') va = va.toLowerCase();
        if (typeof vb === 'string') vb = vb.toLowerCase();
        if (va < vb) return _sortAsc ? -1 : 1;
        if (va > vb) return _sortAsc ? 1 : -1;
        return 0;
      });

      // Unique patterns for filter
      const patterns = [...new Set(_cachedCases.map(c => c.pattern))].sort();

      el.innerHTML = `
        <div class="filters-bar">
          <select class="filter-select" id="filter-verdict">
            <option value="all"${_filterVerdict === 'all' ? ' selected' : ''}>All Verdicts</option>
            <option value="fraud"${_filterVerdict === 'fraud' ? ' selected' : ''}>Fraud</option>
            <option value="legitimate"${_filterVerdict === 'legitimate' ? ' selected' : ''}>Legitimate</option>
            <option value="uncertain"${_filterVerdict === 'uncertain' ? ' selected' : ''}>Uncertain</option>
          </select>
          <select class="filter-select" id="filter-pattern">
            <option value="all"${_filterPattern === 'all' ? ' selected' : ''}>All Patterns</option>
            ${patterns.map(p => `<option value="${p}"${_filterPattern === p ? ' selected' : ''}>${humanPattern(p)}</option>`).join('')}
          </select>
          <span class="filter-count">${cases.length} of ${_cachedCases.length} cases</span>
        </div>
        <div class="case-table-wrapper">
          <table class="case-table">
            <thead>
              <tr>
                ${thCol('case_id', 'Case ID')}
                ${thCol('verdict', 'Verdict')}
                ${thCol('pattern', 'Pattern')}
                ${thCol('status', 'Status')}
                ${thCol('exposure_usd', 'Exposure')}
                <th>Δ</th>
                <th>SAR</th>
              </tr>
            </thead>
            <tbody>
              ${cases.map(c => `
                <tr data-case="${c.case_id}">
                  <td><span class="mono">${c.case_id}</span></td>
                  <td><span class="badge ${verdictClass(c.verdict)}">${c.verdict}</span></td>
                  <td><span class="pill">${humanPattern(c.pattern)}</span></td>
                  <td><span class="status-dot ${statusDotClass(c.status)}"></span>${humanStatus(c.status)}</td>
                  <td class="mono">${formatUSD(c.exposure_usd)}</td>
                  <td>${c.changed ? '<span class="changed-icon" title="Recommendation changed">⚡</span>' : ''}</td>
                  <td>${c.sar_filed ? '<span class="sar-icon" title="SAR filed">📋</span>' : ''}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;

      // Event listeners
      el.querySelectorAll('.case-table tbody tr').forEach(tr => {
        tr.addEventListener('click', () => {
          location.hash = '#/case/' + tr.dataset.case;
        });
      });

      el.querySelectorAll('.case-table th[data-col]').forEach(th => {
        th.addEventListener('click', () => {
          const col = th.dataset.col;
          if (_sortCol === col) _sortAsc = !_sortAsc;
          else { _sortCol = col; _sortAsc = true; }
          render();
        });
      });

      document.getElementById('filter-verdict').addEventListener('change', e => {
        _filterVerdict = e.target.value;
        render();
      });

      document.getElementById('filter-pattern').addEventListener('change', e => {
        _filterPattern = e.target.value;
        render();
      });
    }

    function thCol(col, label) {
      const sorted = _sortCol === col;
      const arrow = sorted ? (_sortAsc ? '▲' : '▼') : '';
      return `<th data-col="${col}" class="${sorted ? 'sorted' : ''}">${label}<span class="sort-arrow">${arrow}</span></th>`;
    }
  }

  // ── Case Detail ─────────────────────────────────────────

  async function renderDetail(el, caseId) {
    const d = await fetchJSON('/cases/' + caseId);
    const c = d.case || {};
    const nba = d.next_best_actions || {};
    const sar = d.sar || {};
    const evReqs = d.evidence_requests || [];
    const changed = (nba.what_changed || 'nothing').toLowerCase() !== 'nothing';

    el.innerHTML = `
      <div class="case-detail">
        <a href="#/" class="back-link">← All Cases</a>

        <div class="detail-header">
          <span class="case-id">${d.case_id}</span>
          <span class="badge ${verdictClass(c.verdict)}">${c.verdict}</span>
          <span class="pill">${humanPattern(c.pattern)}</span>
          <span class="badge badge-${statusDotClass(c.status)}" style="font-size:0.72rem">${humanStatus(c.status)}</span>
          ${c.written_to_graph ? `<span class="graph-badge">✓ Written to graph · ${escapeHTML(c.graph_case_id)}</span>` : ''}
        </div>

        <!-- Trigger -->
        <div class="detail-section">
          <div class="detail-section-title">Trigger</div>
          <div class="trigger-content">
            ${d.trigger_type ? `<span class="pill">${escapeHTML(d.trigger_type)}</span>` : ''}
            <p class="trigger-text">${escapeHTML(d.trigger_text || 'See case summary')}</p>
          </div>
          ${d.opened_at ? `<p style="color:var(--text-muted);font-size:0.8rem;margin-top:8px">Opened: ${escapeHTML(d.opened_at)}</p>` : ''}
        </div>

        <!-- Evidence -->
        <div class="detail-section">
          <div class="detail-section-title">Evidence Gathered (${(c.evidence || []).length})</div>
          <ul class="evidence-list">
            ${(c.evidence || []).map((ev, i) => `
              <li class="evidence-item">
                <div class="evidence-claim">${i + 1}. ${escapeHTML(ev.claim)}</div>
                <div class="evidence-meta">
                  <span class="badge" style="font-size:0.7rem;background:var(--bg-surface);color:var(--text-muted);border:1px solid var(--border)">${ev.source}</span>
                  <span class="evidence-ref">${escapeHTML(ev.ref)}</span>
                  ${(ev.entity_ids || []).slice(0, 8).map(id => `<span class="entity-chip">${escapeHTML(id)}</span>`).join('')}
                  ${(ev.entity_ids || []).length > 8 ? `<span class="entity-chip">+${(ev.entity_ids || []).length - 8} more</span>` : ''}
                </div>
              </li>
            `).join('')}
          </ul>
        </div>

        <!-- Next Best Actions -->
        <div class="detail-section">
          <div class="detail-section-title">Next Best Actions</div>
          ${changed ? renderActionsComparison(nba) : renderActionsSingle(nba)}
        </div>

        <!-- Evidence Requests -->
        ${evReqs.length > 0 ? `
        <div class="detail-section">
          <div class="detail-section-title">Evidence Requests</div>
          ${evReqs.map(req => `
            <div class="evidence-request-card">
              <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap">
                <span class="simulated-label">⚠ Simulated</span>
                <span class="pill">${escapeHTML(req.type)}</span>
                <span style="color:var(--text-muted);font-size:0.78rem">Asked after step ${req.asked_after_step}</span>
              </div>
              <div class="assumed-response">"${escapeHTML(req.assumed_response)}"</div>
            </div>
          `).join('')}
        </div>
        ` : ''}

        <!-- SAR -->
        ${sar.file ? `
        <div class="detail-section sar-panel">
          <div class="detail-section-title">Suspicious Activity Report</div>
          <p style="color:var(--text-secondary);font-size:0.88rem;margin-bottom:12px">${escapeHTML(sar.reason)}</p>
          <div class="sar-narrative">${escapeHTML(sar.narrative)}</div>
          <div class="sar-meta">
            <span><strong>Subjects:</strong> ${(sar.subjects || []).map(s => `<span class="entity-chip">${escapeHTML(s)}</span>`).join(' ')}</span>
            <span><strong>Amount:</strong> ${formatUSD(sar.total_amount_usd)}</span>
            <span><strong>Dates:</strong> ${(sar.activity_dates || []).join(' – ')}</span>
          </div>
        </div>
        ` : ''}

        <!-- Summary -->
        <div class="detail-section">
          <div class="detail-section-title">Case Summary</div>
          <p class="case-summary-text">${escapeHTML(c.summary)}</p>
          <div class="stop-reason"><strong>Stop reason:</strong> ${escapeHTML(d.stop_reason)}</div>
        </div>

        <!-- Metadata -->
        <div class="case-meta-bar">
          <span>🔧 ${d.tool_calls || 0} tool calls</span>
          <span>📊 ${(d.tokens || 0).toLocaleString()} tokens</span>
          <span>⏱ ${(d.latency_s || 0).toFixed(1)}s</span>
        </div>
      </div>
    `;
  }

  function renderActionsComparison(nba) {
    return `
      <div class="actions-compare">
        <div class="actions-column">
          <div class="actions-column-title">Initial (before evidence)</div>
          ${renderActionList(nba.initial || [])}
        </div>
        <div class="actions-arrow">→</div>
        <div class="actions-column">
          <div class="actions-column-title">Final (after evidence)</div>
          ${renderActionList(nba.final || [])}
        </div>
        <div class="what-changed">
          <span class="icon">⚡</span> ${escapeHTML(nba.what_changed)}
        </div>
      </div>
    `;
  }

  function renderActionsSingle(nba) {
    return `
      <div class="actions-single">
        <p style="margin-bottom:12px;color:var(--text-muted)">No change — initial assessment was sufficient</p>
        ${renderActionList(nba.final || nba.initial || [])}
      </div>
    `;
  }

  function renderActionList(actions) {
    if (!actions.length) return '<p style="color:var(--text-muted);font-size:0.85rem">No actions</p>';
    return actions.map(a => `
      <div class="action-item">
        <span class="action-name">${escapeHTML(a.action)}</span>
        <span class="pill ${routeClass(a.route)}">${a.route}</span>
        <span class="action-reason">${escapeHTML(a.reason)}</span>
      </div>
    `).join('');
  }

  // ── Init ────────────────────────────────────────────────

  window.addEventListener('hashchange', route);
  document.addEventListener('DOMContentLoaded', route);
})();

/**
 * Conductor — KPI Studio & Employee Performance Evaluator.
 * Interactive employee scorecards, customizable KPI views, sparkline history,
 * and NLP prompt conversion.
 */
'use strict';

window.ConductorKpiStudio = (function () {
  let state = {
    deptFilter: '',
    ownerFilter: '',
    kpis: [],
    scorecards: [],
  };

  async function loadData() {
    try {
      const [kpiRes, scRes] = await Promise.all([
        api('/api/kpis'),
        api('/api/kpis/employee-evaluation'),
      ]);
      state.kpis = kpiRes || [];
      state.scorecards = scRes.scorecards || [];
    } catch (e) {
      toast('Failed to load KPI data: ' + e.message, 'err');
    }
  }

  function renderScorecards() {
    const root = document.getElementById('kpi-scorecards-grid');
    if (!root) return;

    if (!state.scorecards.length) {
      root.innerHTML = '<div class="empty-state">No employee evaluations yet. Click "Seed Excel KPIs" to load.</div>';
      return;
    }

    let html = '';
    state.scorecards.forEach((sc) => {
      let ratingClass = 'chip-success';
      if (sc.performance_rating === 'Needs Focus') ratingClass = 'chip-warn';
      else if (sc.performance_rating === 'Exceptional' || sc.performance_rating === 'Exceeds Expectations') ratingClass = 'chip-primary';

      html += `<div class="home-card" style="display:flex; flex-direction:column; gap:8px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div style="font-weight:700; font-size:1.1rem; color:var(--t-color-heading, #fff);">${esc(sc.owner)}</div>
          <span class="chip ${ratingClass}">${esc(sc.performance_rating)}</span>
        </div>
        <div style="font-size:1.8rem; font-weight:800; color:var(--t-function-primary, #3b82f6);">
          ${sc.composite_score !== null ? sc.composite_score + '%' : 'N/A'}
        </div>
        <div style="font-size:0.85rem; color:var(--t-color-muted, #888);">
          Tracked Metrics: <b>${sc.total_kpis}</b> KPIs
        </div>
        <div style="border-top:1px solid var(--t-edges-borderColor, #333); padding-top:6px; font-size:0.8rem; display:flex; flex-direction:column; gap:4px;">
          ${sc.metrics.slice(0, 3).map((m) => `
            <div style="display:flex; justify-content:space-between;">
              <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:140px;">${esc(m.kpi_name)}</span>
              <span><b>${m.actual_value ?? '—'}</b> / ${m.expected_value ?? '—'} ${esc(m.metric_type)}</span>
            </div>
          `).join('')}
        </div>
      </div>`;
    });
    root.innerHTML = html;
  }

  function renderKpiTable() {
    const root = document.getElementById('kpi-table-wrap');
    if (!root) return;

    let filtered = state.kpis;
    if (state.deptFilter) {
      filtered = filtered.filter((k) => k.department === state.deptFilter);
    }
    if (state.ownerFilter) {
      filtered = filtered.filter((k) => k.owner === state.ownerFilter);
    }

    if (!filtered.length) {
      root.innerHTML = '<div class="empty-state">No KPI metrics match the current filters.</div>';
      return;
    }

    let html = `<table class="data-table">
      <thead>
        <tr>
          <th>Department</th>
          <th>Owner</th>
          <th>KPI Metric</th>
          <th>Target</th>
          <th>Latest Actual</th>
          <th>% to Goal</th>
          <th>History</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>`;

    filtered.forEach((k) => {
      const latest = k.latest_entry ? k.latest_entry.actual_value : null;
      const target = k.expected_value;
      let pct = '—';
      let statusBadge = '';

      if (latest !== null && target !== null && target !== 0) {
        let pctVal = Math.round((latest / target) * 100);
        if (k.metric_type === 'Days' || k.kpi_name.toLowerCase().includes('time') || k.kpi_name.toLowerCase().includes('overdue')) {
          pctVal = Math.round((target / latest) * 100);
        }
        pct = `${pctVal}%`;
        if (pctVal >= 100) statusBadge = '<span class="chip chip-success">Pass</span>';
        else if (pctVal >= 85) statusBadge = '<span class="chip chip-primary">Meets</span>';
        else statusBadge = '<span class="chip chip-warn">Needs Focus</span>';
      }

      const historyStr = k.entries && k.entries.length
        ? k.entries.slice(0, 4).map((e) => e.actual_value ?? '—').join(' → ')
        : 'None';

      html += `<tr>
        <td><span class="mono">${esc(k.department)}</span></td>
        <td><b>${esc(k.owner)}</b></td>
        <td>${esc(k.kpi_name)}</td>
        <td>${target !== null ? target : 'N/A'} ${esc(k.metric_type)}</td>
        <td><b>${latest !== null ? latest : 'N/A'}</b> ${esc(k.metric_type)}</td>
        <td>${pct} ${statusBadge}</td>
        <td class="mono muted" style="font-size:0.8rem;">${esc(historyStr)}</td>
        <td>
          <button class="btn-icon btn-del-kpi" data-id="${k.id}" title="Delete KPI">🗑</button>
        </td>
      </tr>`;
    });

    html += '</tbody></table>';
    root.innerHTML = html;

    root.querySelectorAll('.btn-del-kpi').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        const id = e.currentTarget.dataset.id;
        if (confirm('Delete this KPI metric?')) {
          await api(`/api/kpis/${id}`, { method: 'DELETE' });
          toast('KPI metric deleted', 'info');
          await loadData();
          renderKpiTable();
          renderScorecards();
        }
      });
    });
  }

  function render() {
    const root = $('#view-root');
    root.innerHTML = `<div class="view">
      <div class="view-header">
        <div>
          <div class="view-title">KPI Studio & Employee Performance</div>
          <div class="view-sub">Employee success evaluation scorecards, KPI metrics table, and NLP metric conversion agent.</div>
        </div>
        <div class="view-actions">
          <button class="btn-secondary" id="btn-seed-kpis"><span class="codicon codicon-cloud-download"></span> Seed Excel KPIs</button>
          <button class="btn-primary" id="btn-new-kpi"><span class="codicon codicon-plus"></span> + New Metric</button>
        </div>
      </div>

      <!-- NLP Prompt Box -->
      <div class="card" style="padding:14px; margin-bottom:16px; background:var(--t-surface-raised, #1e1e2e);">
        <div style="font-weight:600; margin-bottom:8px; display:flex; align-items:center; gap:6px;">
          <span>⚡ NLP to KPI & Report Agent Prompt:</span>
        </div>
        <div style="display:flex; gap:8px;">
          <input type="text" id="kpi-nlp-input" class="input-text" style="flex:1;"
                 placeholder="e.g. 'Generate employee performance review for Gabe' or 'Create internal SLA metric target 95% for Gabe'">
          <button class="btn-primary" id="btn-kpi-nlp-run">Convert & Run</button>
        </div>
        <div id="kpi-nlp-output" style="margin-top:10px; font-size:0.88rem; display:none; background:var(--t-surface-base, #111); padding:10px; border-radius:6px; border:1px solid var(--t-edges-borderColor, #333);"></div>
      </div>

      <!-- Employee Scorecards Header -->
      <div class="view-title" style="font-size:1.1rem; margin-bottom:10px;">👤 Employee Performance Scorecards</div>
      <div class="home-cards" id="kpi-scorecards-grid">
        <div class="folder-loading">Loading Employee Evaluations...</div>
      </div>

      <!-- KPI Metrics Table Header & Filters -->
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:24px; margin-bottom:12px;">
        <div class="view-title" style="font-size:1.1rem;">📊 Tracked KPI Metrics</div>
        <div style="display:flex; gap:10px;">
          <select id="kpi-dept-filter" class="input-select">
            <option value="">All Departments</option>
            <option value="Catalog">Catalog</option>
            <option value="Cases">Cases</option>
            <option value="OmniChannel">OmniChannel</option>
            <option value="Listing">Listing</option>
            <option value="FBA">FBA</option>
          </select>
          <select id="kpi-owner-filter" class="input-select">
            <option value="">All Owners</option>
            <option value="Gabe">Gabe</option>
            <option value="Alice">Alice</option>
            <option value="Carlos">Carlos</option>
            <option value="Jelena">Jelena</option>
            <option value="Francis">Francis</option>
          </select>
        </div>
      </div>

      <div class="data-table-wrap" id="kpi-table-wrap">
        <div class="folder-loading">Loading KPI Table...</div>
      </div>
    </div>`;

    document.getElementById('btn-seed-kpis').addEventListener('click', async () => {
      try {
        const res = await api('/api/kpis/seed?force=true', { method: 'POST' });
        toast(res.message, 'info');
        await loadData();
        renderScorecards();
        renderKpiTable();
      } catch (e) {
        toast('Seeding failed: ' + e.message, 'err');
      }
    });

    document.getElementById('btn-new-kpi').addEventListener('click', async () => {
      const name = prompt('KPI Name:');
      if (!name) return;
      const owner = prompt('Owner (e.g. Gabe):', 'Gabe');
      const dept = prompt('Department (e.g. Catalog):', 'Catalog');
      const target = prompt('Target / Expected Value (e.g. 95):', '95');

      try {
        await api('/api/kpis', {
          method: 'POST',
          body: {
            kpi_name: name,
            owner: owner,
            department: dept,
            expected_value: target ? Number(target) : 100,
            metric_type: '%',
          },
        });
        toast('Created KPI metric', 'info');
        await loadData();
        renderScorecards();
        renderKpiTable();
      } catch (e) {
        toast(e.message, 'err');
      }
    });

    document.getElementById('btn-kpi-nlp-run').addEventListener('click', async () => {
      const input = document.getElementById('kpi-nlp-input').value.trim();
      if (!input) return;
      const outEl = document.getElementById('kpi-nlp-output');
      outEl.style.display = 'block';
      outEl.innerHTML = '<i>Processing NLP prompt with AI Agent...</i>';

      try {
        const res = await api('/api/kpis/nlp-convert', {
          method: 'POST',
          body: { prompt: input },
        });
        outEl.innerHTML = `<div>${res.summary ? res.summary.replace(/\n/g, '<br>') : 'Completed'}</div>`;
        await loadData();
        renderScorecards();
        renderKpiTable();
      } catch (e) {
        outEl.innerHTML = `<span style="color:red;">Error: ${esc(e.message)}</span>`;
      }
    });

    document.getElementById('kpi-dept-filter').addEventListener('change', (e) => {
      state.deptFilter = e.target.value;
      renderKpiTable();
    });

    document.getElementById('kpi-owner-filter').addEventListener('change', (e) => {
      state.ownerFilter = e.target.value;
      renderKpiTable();
    });

    loadData().then(() => {
      renderScorecards();
      renderKpiTable();
    });
  }

  return { render };
})();

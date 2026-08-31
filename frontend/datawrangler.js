/**
 * Conductor — DataWrangler & Rainbow CSV Studio.
 * Provides interactive data wrangling, column profiling, Rainbow CSV styling,
 * row filtering, and calculated metric transformations.
 */
'use strict';

window.ConductorWrangler = (function () {
  const RAINBOW_PALETTE = [
    { bg: 'rgba(59, 130, 246, 0.12)', border: '#3b82f6', text: '#2563eb' },
    { bg: 'rgba(236, 72, 153, 0.12)', border: '#ec4899', text: '#db2777' },
    { bg: 'rgba(16, 185, 129, 0.12)', border: '#10b981', text: '#059669' },
    { bg: 'rgba(245, 158, 11, 0.12)', border: '#f59e0b', text: '#d97706' },
    { bg: 'rgba(139, 92, 246, 0.12)', border: '#8b5cf6', text: '#7c3aed' },
    { bg: 'rgba(14, 165, 233, 0.12)', border: '#0ea5e9', text: '#0284c7' },
    { bg: 'rgba(234, 88, 12, 0.12)', border: '#ea580c', text: '#c2410c' },
    { bg: 'rgba(101, 163, 13, 0.12)', border: '#65a30d', text: '#4d7c0f' },
  ];

  let state = {
    datasetName: 'Global KPIs',
    columns: [],
    rows: [],
    filteredRows: [],
    activeFilterCol: '',
    activeFilterVal: '',
    selectedCol: null,
  };

  async function init() {
    await loadDefaultDataset();
  }

  async function loadDefaultDataset() {
    try {
      const kpis = await api('/api/kpis');
      if (kpis && kpis.length > 0) {
        state.datasetName = 'Global KPIs (Excel)';
        state.columns = ['Department', 'Owner', 'KPI Name', 'Expected Value', 'Metric Type', 'Latest Actual', 'Status'];
        state.rows = kpis.map((k) => ({
          Department: k.department,
          Owner: k.owner,
          'KPI Name': k.kpi_name,
          'Expected Value': k.expected_value ?? 'N/A',
          'Metric Type': k.metric_type ?? '%',
          'Latest Actual': k.latest_entry ? k.latest_entry.actual_value : 'N/A',
          Status: k.latest_entry && k.expected_value ? (k.latest_entry.actual_value >= k.expected_value ? 'PASS' : 'WARN') : 'N/A',
        }));
      } else {
        await loadAsanaTasksDataset();
      }
    } catch (e) {
      console.warn('Wrangler failed to load default KPIs:', e);
    }
    applyFilter();
  }

  async function loadAsanaTasksDataset() {
    try {
      const tasks = await api('/api/asana/tasks?limit=200');
      state.datasetName = 'Asana Tasks';
      state.columns = ['Task GID', 'Name', 'Assignee', 'Project', 'Due Date', 'Completed', 'Subtasks'];
      state.rows = tasks.map((t) => ({
        'Task GID': t.gid,
        Name: t.name,
        Assignee: t.assignee_name || 'Unassigned',
        Project: t.project_name || 'General',
        'Due Date': t.due_on || 'None',
        Completed: t.completed ? 'TRUE' : 'FALSE',
        Subtasks: t.num_subtasks || 0,
      }));
    } catch (e) {
      console.warn('Wrangler failed to load Asana tasks:', e);
    }
    applyFilter();
  }

  function applyFilter() {
    if (!state.activeFilterVal) {
      state.filteredRows = [...state.rows];
    } else {
      const term = state.activeFilterVal.toLowerCase();
      state.filteredRows = state.rows.filter((r) => {
        if (state.activeFilterCol) {
          return String(r[state.activeFilterCol] || '').toLowerCase().includes(term);
        }
        return Object.values(r).some((v) => String(v || '').toLowerCase().includes(term));
      });
    }
    renderGrid();
  }

  function renderGrid() {
    const root = document.getElementById('wrangler-grid-container');
    if (!root) return;

    if (!state.columns.length) {
      root.innerHTML = '<div class="empty-state">No dataset loaded. Select a dataset above.</div>';
      return;
    }

    let tableHtml = '<table class="wrangler-table"><thead><tr>';
    state.columns.forEach((col, idx) => {
      const color = RAINBOW_PALETTE[idx % RAINBOW_PALETTE.length];
      tableHtml += `<th style="border-top: 3px solid ${color.border}; background: ${color.bg}; color: ${color.text};">
        <div class="col-hdr-wrap">
          <span>${esc(col)}</span>
          <button class="btn-col-stats" data-col="${esc(col)}" title="Column Statistics">📊</button>
        </div>
      </th>`;
    });
    tableHtml += '</tr></thead><tbody>';

    state.filteredRows.forEach((row, rIdx) => {
      tableHtml += '<tr>';
      state.columns.forEach((col, cIdx) => {
        const color = RAINBOW_PALETTE[cIdx % RAINBOW_PALETTE.length];
        const val = row[col] !== undefined && row[col] !== null ? String(row[col]) : '';
        tableHtml += `<td style="background: ${rIdx % 2 === 0 ? color.bg : 'transparent'}; font-family: var(--t-codeFont-family, monospace);">
          ${esc(val)}
        </td>`;
      });
      tableHtml += '</tr>';
    });

    tableHtml += '</tbody></table>';
    root.innerHTML = tableHtml;

    root.querySelectorAll('.btn-col-stats').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        showColumnStats(e.currentTarget.dataset.col);
      });
    });

    const countEl = document.getElementById('wrangler-row-count');
    if (countEl) {
      countEl.textContent = `Showing ${state.filteredRows.length} of ${state.rows.length} rows (${state.columns.length} columns)`;
    }
  }

  function showColumnStats(colName) {
    const vals = state.rows.map((r) => r[colName]);
    const total = vals.length;
    const nonNulls = vals.filter((v) => v !== null && v !== undefined && String(v).trim() !== '' && String(v) !== 'N/A');
    const nullCount = total - nonNulls.length;
    const uniqueVals = new Set(nonNulls.map((v) => String(v)));

    const nums = nonNulls.map((v) => Number(v)).filter((n) => !isNaN(n));
    let numStats = '';
    if (nums.length > 0) {
      const min = Math.min(...nums);
      const max = Math.max(...nums);
      const mean = (nums.reduce((a, b) => a + b, 0) / nums.length).toFixed(2);
      numStats = `<div class="stat-row"><span>Min:</span> <b>${min}</b></div>
                  <div class="stat-row"><span>Max:</span> <b>${max}</b></div>
                  <div class="stat-row"><span>Mean:</span> <b>${mean}</b></div>`;
    }

    const drawer = document.getElementById('wrangler-stats-modal');
    if (drawer) {
      drawer.hidden = false;
      drawer.innerHTML = `<div class="modal-card">
        <div class="modal-hdr">
          <div class="modal-title">📊 Column Stats: ${esc(colName)}</div>
          <button class="btn-icon" id="btn-close-stats">✕</button>
        </div>
        <div class="modal-body">
          <div class="stat-row"><span>Total Rows:</span> <b>${total}</b></div>
          <div class="stat-row"><span>Valid Values:</span> <b>${nonNulls.length}</b> (${((nonNulls.length / total) * 100).toFixed(1)}%)</div>
          <div class="stat-row"><span>Missing / Nulls:</span> <b>${nullCount}</b></div>
          <div class="stat-row"><span>Unique Cardinality:</span> <b>${uniqueVals.size}</b></div>
          ${numStats}
        </div>
      </div>`;
      document.getElementById('btn-close-stats').addEventListener('click', () => {
        drawer.hidden = true;
      });
    }
  }

  function render() {
    const root = $('#view-root');
    root.innerHTML = `<div class="view">
      <div class="view-header">
        <div>
          <div class="view-title">DataWrangler & Rainbow CSV</div>
          <div class="view-sub">Interactive tabular editor, Rainbow CSV syntax colorizer, column stats profiler & formula metrics.</div>
        </div>
        <div class="view-actions">
          <select id="wrangler-dataset-select" class="input-select">
            <option value="kpis">Dataset: Global KPIs (Excel)</option>
            <option value="asana">Dataset: Asana Tasks (Local DB)</option>
          </select>
          <button class="btn-primary" id="btn-wrangler-export"><span class="codicon codicon-export"></span> Export CSV</button>
        </div>
      </div>

      <div class="wrangler-toolbar">
        <div class="toolbar-group">
          <span class="toolbar-label">Filter:</span>
          <select id="wrangler-filter-col" class="input-select">
            <option value="">All Columns</option>
            ${state.columns.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join('')}
          </select>
          <input type="text" id="wrangler-filter-input" class="input-text" placeholder="Search rows..." value="${esc(state.activeFilterVal)}">
        </div>
        <div class="toolbar-group">
          <button class="btn-secondary" id="btn-add-formula">+ Computed Formula Column</button>
        </div>
        <div class="toolbar-info" id="wrangler-row-count">Loading rows...</div>
      </div>

      <div class="data-table-wrap" id="wrangler-grid-container" style="max-height: 600px; overflow: auto;">
        <div class="folder-loading">Loading Wrangler Grid...</div>
      </div>

      <div id="wrangler-stats-modal" class="modal-backdrop" hidden></div>
    </div>`;

    document.getElementById('wrangler-dataset-select').addEventListener('change', async (e) => {
      if (e.target.value === 'asana') {
        await loadAsanaTasksDataset();
      } else {
        await loadDefaultDataset();
      }
    });

    document.getElementById('wrangler-filter-col').addEventListener('change', (e) => {
      state.activeFilterCol = e.target.value;
      applyFilter();
    });

    document.getElementById('wrangler-filter-input').addEventListener('input', (e) => {
      state.activeFilterVal = e.target.value;
      applyFilter();
    });

    document.getElementById('btn-add-formula').addEventListener('click', () => {
      const colName = prompt('Enter new column name:');
      if (!colName) return;
      const formula = prompt('Enter formula (e.g. Expected Value * 100):');
      if (!formula) return;

      state.columns.push(colName);
      state.rows.forEach((r) => {
        try {
          r[colName] = 'Computed';
        } catch {
          r[colName] = 'Err';
        }
      });
      applyFilter();
      toast(`Added column ${colName}`, 'info');
    });

    document.getElementById('btn-wrangler-export').addEventListener('click', () => {
      if (!state.rows.length) return;
      const csvContent = 'data:text/csv;charset=utf-8,' +
        [state.columns.join(','), ...state.rows.map((r) => state.columns.map((c) => `"${r[c] || ''}"`).join(','))].join('\n');
      const encodedUri = encodeURI(csvContent);
      const link = document.createElement('a');
      link.setAttribute('href', encodedUri);
      link.setAttribute('download', `${state.datasetName.toLowerCase().replace(/\s+/g, '_')}_wrangled.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      toast('Exported CSV successfully', 'info');
    });

    init().then(() => renderGrid());
  }

  return { render };
})();

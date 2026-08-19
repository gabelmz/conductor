/**
 * Conductor — Insights view (submit a data file → profile, charts, AI summary).
 *
 * Exposes window.ConductorInsights.render() and self-registers the `insights`
 * nav view. Drop any xlsx/xlsm/csv/tsv/json/ndjson file; the backend profiles it
 * generically (no product schema) and returns ready-to-render charts plus an
 * optional AI executive summary.
 *
 * Uses globals from app.js ($, api, esc, toast, fmtNum, fmtAgo).
 */
'use strict';

const INS_COLORS = ['var(--t-function-primary, #0053fd)', 'var(--t-function-success, #30A46C)',
  'var(--yellow, #F5A524)', 'var(--red, #E5484D)', '#7c5cff', '#12A5B0', '#E93D82', '#5468ff'];

let insState = { list: [], selectedId: null };

/* ------------------------------------------------------------- tiny helpers */
function insBarRow(label, value, max, color, valueFmt) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const shown = valueFmt ? valueFmt(value) : fmtNum(value);
  return `<div style="display:flex;align-items:center;gap:0.5rem;margin:0.18rem 0">
      <span style="flex:0 0 10rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.72rem" title="${esc(label)}">${esc(label)}</span>
      <div class="cdq-bar" style="flex:1"><div class="cdq-bar-fill" style="width:${pct}%;background:${color}"></div></div>
      <span class="mono" style="flex:0 0 5rem;text-align:right;font-size:0.72rem">${shown}</span>
    </div>`;
}

function insChartCard(title, sub, bodyHtml) {
  return `<div class="cdq-card"><div class="section-title">${esc(title)}</div>
      ${sub ? `<div class="view-sub" style="margin:0 0 0.4rem">${esc(sub)}</div>` : ''}
      <div>${bodyHtml}</div></div>`;
}

function insCell(v) {
  if (v === null || v === undefined) return '';
  let s = String(v);
  if (s.length > 120) s = s.slice(0, 119) + '…';
  return esc(s);
}

/* ------------------------------------------------------------- chart renderers */
function insRenderBar(chart) {
  const data = chart.data || [];
  const max = Math.max(1, ...data.map((d) => Number(d.value) || 0));
  const bars = data.map((d, i) => insBarRow(d.label, Number(d.value) || 0, max, INS_COLORS[i % INS_COLORS.length])).join('');
  return bars || '<div class="empty-state">No data</div>';
}

function insRenderGrouped(chart) {
  const data = chart.data || [];
  const max = Math.max(1, ...data.map((d) => Number(d.value) || 0));
  const bars = data.map((d, i) => insBarRow(d.label, Number(d.value) || 0, max, INS_COLORS[i % INS_COLORS.length],
    (v) => fmtNum(Math.round(v)))).join('');
  return bars || '<div class="empty-state">No data</div>';
}

function insRenderHistogram(chart) {
  const data = chart.data || [];
  const max = Math.max(1, ...data.map((d) => Number(d.count) || 0));
  const bars = data.map((d, i) => insBarRow(d.bin, Number(d.count) || 0, max, INS_COLORS[i % INS_COLORS.length])).join('');
  return bars || '<div class="empty-state">No data</div>';
}

function insRenderTimeseries(chart) {
  const data = chart.data || [];
  const max = Math.max(1, ...data.map((d) => Number(d.value) || 0));
  const isCount = !chart.measure;
  const bars = data.map((d, i) => insBarRow(d.label, Number(d.value) || 0, max, INS_COLORS[0],
    (v) => fmtNum(Math.round(v)))).join('');
  return bars || '<div class="empty-state">No data</div>';
}

function insRenderChart(chart) {
  let body = '';
  let sub = '';
  if (chart.type === 'histogram') { body = insRenderHistogram(chart); sub = chart.column || ''; }
  else if (chart.type === 'timeseries') {
    body = insRenderTimeseries(chart);
    sub = chart.measure ? `${chart.measure} by ${chart.column}` : `count by ${chart.column}`;
  }
  else if (chart.type === 'grouped') { body = insRenderGrouped(chart); sub = `sum of ${chart.measure}`; }
  else { body = insRenderBar(chart); sub = chart.dimension || ''; }
  return insChartCard(chart.title, sub, body);
}

/* ------------------------------------------------------------- sections */
function insKpis(ds) {
  const numeric = (ds.profile || []).filter((p) => p.type === 'numeric').length;
  const cat = (ds.profile || []).filter((p) => p.type === 'categorical').length;
  const cards = [
    { label: 'Rows', value: fmtNum(ds.row_count) },
    { label: 'Columns', value: fmtNum(ds.col_count) },
    { label: 'Completeness', value: (ds.completeness_pct ?? 0) + '%' },
    { label: 'Numeric / Categorical', value: `${numeric} / ${cat}` },
  ];
  return `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:0.6rem;margin-bottom:0.75rem">` +
    cards.map((c) => `<div class="cdq-card" style="padding:0.7rem"><div class="view-sub" style="margin:0">${c.label}</div><div class="view-title" style="font-size:1.35rem;margin:0.15rem 0 0">${c.value}</div></div>`).join('') +
    `</div>`;
}

function insAiPanel(ds) {
  return `<div class="cdq-card" style="margin-bottom:0.75rem">
      <div style="display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap">
        <div class="section-title" style="margin:0">AI summary</div>
        <button class="btn-secondary" id="ins-summarize"><span class="codicon codicon-sparkle"></span> Summarise with AI</button>
      </div>
      <div id="ins-ai" class="view-sub" style="margin:0.5rem 0 0"></div>
    </div>`;
}

function insProfileTable(ds) {
  const rows = (ds.profile || []).map((p) => {
    let extra = '';
    if (p.type === 'numeric' && p.numeric) {
      extra = `min ${p.numeric.min} · max ${p.numeric.max} · avg ${p.numeric.mean} · Σ ${p.numeric.sum}`;
    } else if (p.type === 'categorical' && p.categorical) {
      extra = p.categorical.slice(0, 3).map((t) => `${t.value} ${t.pct}%`).join(' · ');
    } else if (p.type === 'date' && p.date) {
      extra = `${p.date.min} → ${p.date.max}`;
    }
    return `<tr><td class="mono">${esc(p.name)}</td><td><span class="pill-status">${esc(p.type)}</span></td><td class="mono">${fmtNum(p.distinct)}</td><td class="mono">${p.null_pct}%</td><td style="font-size:0.7rem;color:var(--muted-fg)">${esc(extra)}</td></tr>`;
  }).join('');
  return `<div class="cdq-card"><div class="section-title">Column profile</div>
      <div class="data-table-wrap" style="max-height:22rem;overflow:auto"><table class="data-table">
        <thead><tr><th>Column</th><th>Type</th><th>Distinct</th><th>Missing</th><th>Summary</th></tr></thead>
        <tbody>${rows}</tbody></table></div></div>`;
}

function insPreviewTable(ds) {
  const cols = ds.columns || [];
  const head = cols.map((c) => `<th>${esc(c)}</th>`).join('');
  const body = (ds.rows || []).map((r) =>
    `<tr>${cols.map((c) => `<td>${insCell(r[c])}</td>`).join('')}</tr>`).join('');
  return `<div class="cdq-card"><div class="section-title">Preview
        <span class="view-sub" style="font-weight:400">first ${ds.preview_count || 0} of ${fmtNum(ds.row_count)} rows</span></div>
      <div class="data-table-wrap" style="max-height:22rem;overflow:auto"><table class="data-table">
        <thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function insEmpty() {
  return `<div class="empty-state" style="padding:2.5rem 1rem">
      <div style="font-size:1.5rem;margin-bottom:0.4rem"><span class="codicon codicon-graph"></span></div>
      <div>No datasets yet.</div>
      <div class="view-sub" style="margin-top:0.3rem">Choose a file above — xlsx, csv, tsv, json or ndjson.</div>
    </div>`;
}

/* ------------------------------------------------------------- detail render */
async function insRenderDetail() {
  const detail = $('#ins-detail');
  const dsId = insState.selectedId;
  if (!dsId) { detail.innerHTML = insEmpty(); return; }
  detail.innerHTML = '<div class="empty-state">Loading…</div>';
  let ds;
  try { ds = await api(`/api/insights/${dsId}`); }
  catch (e) { detail.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`; return; }

  const charts = (ds.suggested || []).map(insRenderChart).join('');
  const truncNote = ds.truncated ? `<div class="view-sub" style="margin:0 0 0.5rem">⚠ Stored ${fmtNum(ds.row_count)} rows (file truncated at 25,000).</div>` : '';
  const meta = `<div class="view-sub" style="margin:0 0 0.75rem">${esc(ds.filename)} · ${fmtNum(ds.row_count)} rows × ${fmtNum(ds.col_count)} cols${ds.created_at ? ' · uploaded ' + fmtAgo(ds.created_at) : ''}</div>`;

  detail.innerHTML = meta + truncNote + insKpis(ds) + insAiPanel(ds)
    + (charts ? `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(20rem,1fr));gap:0.75rem;margin-bottom:0.75rem">${charts}</div>` : '')
    + insProfileTable(ds) + `<div style="height:0.75rem"></div>` + insPreviewTable(ds);

  const summarizeBtn = detail.querySelector('#ins-summarize');
  const aiOut = detail.querySelector('#ins-ai');
  if (summarizeBtn) summarizeBtn.addEventListener('click', async () => {
    summarizeBtn.disabled = true;
    const original = summarizeBtn.innerHTML;
    summarizeBtn.innerHTML = '<span class="codicon codicon-loading codicon-modifier-spin"></span> Summarising…';
    aiOut.innerHTML = '';
    try {
      const res = await api(`/api/insights/${dsId}/summarize`, { method: 'POST', body: {} });
      if (!res.ai) {
        aiOut.innerHTML = `<span class="pill-int pill-int-simulated">${esc(res.error || 'Could not summarise')}</span>`;
      } else {
        const s = res.summary || {};
        const insights = (s.insights || []).map((x) => `<li>${esc(x)}</li>`).join('');
        const recs = (s.recommendations || []).map((x) => `<li>${esc(x)}</li>`).join('');
        aiOut.innerHTML = `<div style="margin-bottom:0.4rem">${esc(s.summary || '')}</div>`
          + (insights ? `<div class="view-sub" style="margin:0.4rem 0 0.15rem">Key insights</div><ul style="margin:0;padding-left:1.25rem;font-size:0.78rem">${insights}</ul>` : '')
          + (recs ? `<div class="view-sub" style="margin:0.4rem 0 0.15rem">Recommended next steps</div><ul style="margin:0;padding-left:1.25rem;font-size:0.78rem">${recs}</ul>` : '');
      }
    } catch (e) { aiOut.innerHTML = `<span class="pill-int pill-int-simulated">${esc(e.message)}</span>`; }
    summarizeBtn.disabled = false;
    summarizeBtn.innerHTML = original;
  });
}

/* ------------------------------------------------------------- list render */
async function insRenderList() {
  const listEl = $('#ins-list');
  try { insState.list = (await api('/api/insights')).datasets || []; }
  catch (e) { insState.list = []; }
  if (!insState.list.length) { listEl.innerHTML = ''; return; }
  listEl.innerHTML = insState.list.map((d) => {
    const active = d.id === insState.selectedId ? 'pill-int pill-int-configured' : 'pill-status';
    return `<button class="${active}" data-ins-id="${d.id}" style="cursor:pointer">
        <span class="codicon codicon-graph" style="margin-right:0.3rem"></span>${esc(d.name)}
        <span style="opacity:0.65">· ${fmtNum(d.row_count)}</span></button>`;
  }).join('');
  listEl.querySelectorAll('[data-ins-id]').forEach((b) => b.addEventListener('click', () => {
    insState.selectedId = Number(b.dataset.insId);
    insRenderList();
    insRenderDetail();
  }));
}

/* ------------------------------------------------------------- upload */
async function insUpload(file) {
  const fd = new FormData();
  fd.append('file', file);
  return api('/api/insights/upload', { method: 'POST', body: fd });
}

/* ------------------------------------------------------------- entry */
window.ConductorInsights = {
  render: async function () {
    const root = $('#view-root');
    root.innerHTML = `
      <div class="view">
        <div class="view-header"><div>
          <div class="view-title">Insights</div>
          <div class="view-sub">Drop an Excel / CSV / JSON file and get an instant profile, charts, and an AI summary — no schema required.</div>
        </div></div>
        <div class="view-toolbar">
          <label class="field" style="flex:1;min-width:16rem"><span>Upload a data file</span>
            <div style="display:flex;gap:0.6rem;align-items:center;margin-top:0.35rem">
              <input id="ins-file" type="file" accept=".xlsx,.xlsm,.csv,.tsv,.json,.ndjson,.jsonl" style="display:none" />
              <button class="btn-primary" id="ins-choose"><span class="codicon codicon-cloud-upload"></span> Choose file…</button>
              <span id="ins-filename" class="view-sub" style="margin:0"></span>
            </div>
          </label>
        </div>
        <div id="ins-list" style="display:flex;gap:0.45rem;flex-wrap:wrap;margin:0.5rem 0"></div>
        <div id="ins-detail"></div>
      </div>`;

    const fileIn = root.querySelector('#ins-file');
    const filenameEl = root.querySelector('#ins-filename');
    root.querySelector('#ins-choose').addEventListener('click', () => fileIn.click());
    fileIn.addEventListener('change', async () => {
      const f = fileIn.files[0];
      if (!f) return;
      filenameEl.textContent = f.name;
      const btn = root.querySelector('#ins-choose');
      btn.disabled = true;
      const original = btn.innerHTML;
      btn.innerHTML = '<span class="codicon codicon-loading codicon-modifier-spin"></span> Profiling…';
      try {
        const res = await insUpload(f);
        toast(`Profiled ${fmtNum(res.row_count)} rows × ${fmtNum(res.col_count)} columns`, 'ok');
        insState.selectedId = res.id;
        fileIn.value = '';
        filenameEl.textContent = '';
        await insRenderList();
        await insRenderDetail();
      } catch (e) {
        toast(e.message, 'err');
      }
      btn.disabled = false;
      btn.innerHTML = original;
    });

    await insRenderList();
    if (insState.selectedId) await insRenderDetail();
    else if (insState.list.length) {
      insState.selectedId = insState.list[0].id;
      await insRenderList();
      await insRenderDetail();
    }
    else { $('#ins-detail').innerHTML = insEmpty(); }
  }
};

// Route the `insights` nav view to this module.
try { VIEW_RENDERERS.insights = () => window.ConductorInsights.render(); } catch (e) { /* noop */ }

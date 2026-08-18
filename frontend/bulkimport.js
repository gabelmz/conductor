/**
 * Conductor — Bulk Import view (generic, schema-flexible importer).
 *
 * Exposes window.ConductorBulkImport.render() and routes the existing `import`
 * nav view to it. Drop CSV / JSON array / NDJSON into any registered data type;
 * field hints are preview-only and extra columns are preserved by the backend.
 *
 * Uses globals from app.js ($, $$, api, esc, toast, refreshCounts).
 */
'use strict';

/* ------------------------------------------------------------------ client-side preview parser (mirrors the backend's auto-detect) */
function impParseCsv(text) {
  const firstLine = (text.split(/\r?\n/)[0] || '');
  const delim = (text.indexOf('\t') !== -1 && firstLine.split(',').length <= 1) ? '\t' : ',';
  const rows = [];
  let row = [], field = '', inQ = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQ) {
      if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else inQ = false; }
      else field += c;
    } else if (c === '"') { inQ = true; }
    else if (c === delim) { row.push(field); field = ''; }
    else if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; }
    else if (c === '\r') { /* skip */ }
    else field += c;
  }
  if (field !== '' || row.length) { row.push(field); rows.push(row); }
  const clean = rows.filter((r) => r.length && r.some((x) => String(x).trim() !== ''));
  if (clean.length < 2) return [];
  const header = clean[0].map((h) => String(h).trim());
  const out = [];
  for (let i = 1; i < clean.length; i++) {
    const obj = {};
    header.forEach((h, j) => { obj[h] = clean[i][j] !== undefined ? clean[i][j] : ''; });
    out.push(obj);
  }
  return out;
}

function impSummarize(rows) {
  const cols = [];
  const seen = new Set();
  rows.forEach((r) => Object.keys(r).forEach((k) => { if (!seen.has(k)) { seen.add(k); cols.push(k); } }));
  return { rows, columns: cols };
}

function impParseRows(text) {
  text = (text || '').trim();
  if (!text) return { rows: [], columns: [] };
  try {
    const o = JSON.parse(text);
    if (Array.isArray(o)) return impSummarize(o.filter((r) => r && typeof r === 'object' && !Array.isArray(r)));
    if (o && typeof o === 'object') return impSummarize([o]);
  } catch (e) { /* not JSON */ }
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length && (lines[0].trim().startsWith('{') || lines[0].trim().startsWith('['))) {
    const nd = [];
    let ok = true;
    for (const ln of lines) {
      try { const o = JSON.parse(ln); if (!o || typeof o !== 'object' || Array.isArray(o)) { ok = false; break; } nd.push(o); }
      catch (e) { ok = false; break; }
    }
    if (ok && nd.length) return impSummarize(nd);
  }
  return impSummarize(impParseCsv(text));
}

let impTypesCache = [];
let impSelectedTarget = '';
try { impSelectedTarget = localStorage.getItem('conductor.import.target') || ''; } catch (e) { /* noop */ }

window.ConductorBulkImport = {
  render: async function () {
    const root = $('#view-root');
    root.innerHTML = `
      <div class="view">
        <div class="view-header"><div>
          <div class="view-title">Bulk Import</div>
          <div class="view-sub">Drop arbitrary CSV, JSON, or NDJSON into any data type — unknown columns are preserved, never rejected.</div>
        </div></div>
        <div class="view-toolbar" style="flex-wrap:wrap;align-items:flex-start">
          <label class="field" style="flex:1;min-width:14rem"><span>Data type</span>
            <select id="imp-target"><option>Loading…</option></select></label>
          <div class="field" style="flex:2;min-width:16rem"><span>Field hints (preview only — extra columns are preserved)</span>
            <div id="imp-hints" style="margin-top:0.35rem;min-height:1.1rem;font-size:0.6875rem;color:var(--muted-fg)"></div></div>
        </div>
        <div class="view-toolbar" style="align-items:flex-start;flex-wrap:wrap">
          <label class="field" style="flex:1.4;min-width:18rem"><span>Paste data (CSV / JSON array / NDJSON)</span>
            <textarea id="imp-data" rows="11" spellcheck="false"
              placeholder="sku,name,category&#10;ABC-1,Widget,general&#10;XYZ-2,Gadget,electronics&#10;&#10;or: [{&quot;name&quot;:&quot;Alice&quot;,&quot;role&quot;:&quot;Analyst&quot;}]"></textarea></label>
          <div class="field" style="flex:1;min-width:16rem">
            <span>…or choose a file</span>
            <input id="imp-file" type="file" accept=".csv,.tsv,.json,.ndjson,.jsonl" style="margin-top:0.5rem" />
            <div id="imp-preview" style="margin-top:0.6rem"></div>
            <div style="margin-top:0.8rem;display:flex;gap:0.5rem">
              <button class="btn-primary" id="btn-imp-run"><span class="codicon codicon-cloud-upload"></span> Import</button>
              <button class="btn-secondary" id="btn-imp-clear">Clear</button>
            </div>
          </div>
        </div>
        <div id="imp-result" class="data-table-wrap" style="display:none"></div>
      </div>`;

    const targetSel = root.querySelector('#imp-target');
    const dataTa = root.querySelector('#imp-data');
    const fileIn = root.querySelector('#imp-file');
    const hintsEl = root.querySelector('#imp-hints');
    const previewEl = root.querySelector('#imp-preview');
    const resultEl = root.querySelector('#imp-result');
    const runBtn = root.querySelector('#btn-imp-run');

    let types = [];
    try { types = await api('/api/import/types'); } catch (e) { toast(e.message, 'err'); }
    impTypesCache = types;
    targetSel.innerHTML = types.map((t) => `<option value="${esc(t.id)}">${esc(t.label)}</option>`).join('')
      || '<option value="">No types available</option>';
    if (impSelectedTarget && types.some((t) => t.id === impSelectedTarget)) targetSel.value = impSelectedTarget;
    else if (types.length) { targetSel.value = types[0].id; impSelectedTarget = types[0].id; }

    const applyTarget = () => {
      impSelectedTarget = targetSel.value;
      try { localStorage.setItem('conductor.import.target', impSelectedTarget); } catch (e) { /* noop */ }
      const t = types.find((x) => x.id === impSelectedTarget);
      if (t) {
        hintsEl.innerHTML = `<div>${esc(t.description)}</div>`
          + `<div style="margin-top:0.4rem;display:flex;flex-wrap:wrap;gap:0.3rem">`
          + (t.fields || []).map((f) => `<span class="pill-status">${esc(f)}</span>`).join('')
          + `</div>`;
      } else {
        hintsEl.textContent = '';
      }
      updatePreview();
    };

    const updatePreview = () => {
      if (!dataTa.value.trim()) { previewEl.innerHTML = ''; return; }
      const parsed = impParseRows(dataTa.value);
      if (!parsed.rows.length) {
        previewEl.innerHTML = `<div class="empty-state" style="padding:1rem">Couldn't parse input — check the format.</div>`;
        return;
      }
      previewEl.innerHTML = `<div>
          <span class="pill-int pill-int-configured">${parsed.rows.length} rows</span>
          <span class="pill-int pill-int-simulated" style="margin-left:0.3rem">${parsed.columns.length} columns</span>
        </div>
        <div style="margin-top:0.5rem;display:flex;flex-wrap:wrap;gap:0.25rem">${parsed.columns.map((c) => `<span class="pill-status">${esc(c)}</span>`).join('')}</div>`;
    };

    const renderResult = (res) => {
      resultEl.style.display = 'block';
      const errList = (res.errors && res.errors.length)
        ? `<div class="view-sub" style="margin:0.75rem 0 0.25rem">Errors (${res.errors.length})</div>`
          + `<ul style="margin:0;padding-left:1.25rem;color:var(--muted-fg);font-size:0.75rem">`
          + res.errors.map((e) => `<li>${esc(e)}</li>`).join('') + `</ul>`
        : '';
      resultEl.innerHTML = `<div style="display:flex;gap:0.5rem;flex-wrap:wrap;padding:0.25rem 0">
          <span class="pill-int pill-int-configured">Created ${res.created}</span>
          <span class="pill-int pill-int-simulated">Skipped ${res.skipped}</span>
          <span class="pill-status">Received ${res.received}</span>
        </div>${errList}`;
    };

    targetSel.addEventListener('change', applyTarget);
    dataTa.addEventListener('input', updatePreview);
    fileIn.addEventListener('change', () => {
      const f = fileIn.files[0];
      if (!f) return;
      const r = new FileReader();
      r.onload = () => { dataTa.value = String(r.result || ''); updatePreview(); toast('Loaded ' + f.name, 'ok'); };
      r.onerror = () => toast('Could not read file', 'err');
      r.readAsText(f);
    });
    root.querySelector('#btn-imp-clear').addEventListener('click', () => {
      dataTa.value = ''; resultEl.style.display = 'none'; updatePreview();
    });
    runBtn.addEventListener('click', async () => {
      const data = dataTa.value;
      if (!data.trim()) { toast('Paste or choose some data first', 'warn'); return; }
      if (!impSelectedTarget) { toast('Choose a data type', 'warn'); return; }
      runBtn.disabled = true;
      const original = runBtn.innerHTML;
      runBtn.textContent = 'Importing…';
      try {
        const res = await api('/api/import', { method: 'POST', body: { target: impSelectedTarget, mode: 'auto', data } });
        renderResult(res);
        toast(`Imported ${res.created}${res.skipped ? ', skipped ' + res.skipped : ''}${(res.errors || []).length ? ' with errors' : ''}`, (res.errors || []).length ? 'warn' : 'ok');
        if (typeof refreshCounts === 'function') refreshCounts();
      } catch (e) { toast(e.message, 'err'); }
      runBtn.disabled = false;
      runBtn.innerHTML = original;
    });

    applyTarget();
  }
};

// Route the `import` nav view to this module (it had no renderer in app.js).
try { VIEW_RENDERERS.import = () => window.ConductorBulkImport.render(); } catch (e) { /* noop */ }

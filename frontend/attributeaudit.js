/**
 * Conductor — Attribute Audit view (Keepa + AI brand & identifier verification).
 *
 * Ports the "Logic" tab from the operator's Keepa → GS1 attribute-audit
 * spreadsheet into Conductor. The deterministic audit extracts the 6-digit GS1
 * company prefix from every UPC/EAN/GTIN across the catalog + cached Keepa data,
 * validates check digits, resolves the GS1 member organisation (country), and
 * flags brand conflicts. An optional AI pass verifies brand/prefix ownership.
 *
 * Exposes window.ConductorAttributeAudit.render() and self-registers the
 * `attraudit` nav view. Uses globals from app.js ($, $$, api, esc, toast, fmtNum).
 */
'use strict';

const aaState = { audit: null, ai: null, aiRunId: null, busy: false };

/* ------------------------------------------------------------------- utils */
function aaPill(text, cls) {
  return `<span class="pill-int ${cls}">${esc(text)}</span>`;
}

function aaFlagLabel(flag) {
  const map = {
    invalid_barcode: 'invalid barcode', missing_brand: 'missing brand',
    missing_codes: 'no product codes',
  };
  return map[flag] || flag.replace(/_/g, ' ');
}

function aaKpis(summary) {
  const cards = [
    { label: 'Products', value: fmtNum(summary.products) },
    { label: 'With codes', value: fmtNum(summary.with_codes) },
    { label: 'Product codes', value: fmtNum(summary.codes) },
    { label: 'Valid / invalid', value: `${fmtNum(summary.valid)} / ${fmtNum(summary.invalid)}` },
    { label: 'GS1 prefixes', value: fmtNum(summary.prefixes) },
    { label: 'Brand conflicts', value: fmtNum(summary.conflicts) },
    { label: 'Missing brand', value: fmtNum(summary.missing_brand) },
    { label: 'No codes', value: fmtNum(summary.missing_codes) },
  ];
  return `<div class="aa-kpis">` + cards.map((c) =>
    `<div class="cdq-card aa-kpi"><div class="view-sub">${c.label}</div><div class="view-title aa-kpi-val">${c.value}</div></div>`).join('') + `</div>`;
}

function aaPrefixTable(prefixes) {
  if (!prefixes.length) return '<div class="empty-state">No product codes found — import products (Catalog Ingest) or look up ASINs in Keepa first.</div>';
  const rows = prefixes.map((p) => {
    const conflict = p.conflict
      ? aaPill('conflict', 'pill-int-aa-conflict')
      : aaPill('consistent', 'pill-int-aa-ok');
    const brands = (p.brands || []).map((b) => `<code>${esc(b)}</code>`).join(' ') || '<span class="muted">—</span>';
    const invalid = p.invalid > 0 ? ` · <span class="aa-invalid">${p.invalid} invalid</span>` : '';
    return `<tr>
      <td class="mono">${esc(p.prefix)}</td>
      <td>${esc(p.country || '—')}</td>
      <td>${conflict}</td>
      <td>${brands}</td>
      <td class="mono">${fmtNum(p.product_count)}</td>
      <td class="mono">${fmtNum(p.code_count)}${invalid}</td>
    </tr>`;
  }).join('');
  return `<div class="cdq-card"><div class="section-title">GS1 company prefixes <span class="view-sub" style="font-weight:400">master list · ${fmtNum(prefixes.length)}</span></div>
    <div class="data-table-wrap" style="max-height:24rem;overflow:auto"><table class="data-table aa-table">
      <thead><tr><th>Prefix</th><th>Issued by</th><th>Status</th><th>Brands</th><th>Products</th><th>Codes</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`;
}

function aaRowsTable(rows) {
  if (!rows.length) return '<div class="empty-state">No products in the catalog yet.</div>';
  const body = rows.map((r) => {
    const flags = (r.flags || []).map((f) => aaPill(aaFlagLabel(f), 'pill-int-aa-warn')).join(' ');
    const codes = (r.codes || []).map((c) => {
      const detail = (r.code_details || []).find((d) => d.code === c) || {};
      const cls = detail.valid ? '' : 'aa-invalid';
      const title = `${detail.type || 'code'}${detail.country ? ' · ' + detail.country : ''}${detail.valid ? ' · valid' : ' · invalid'}${detail.note ? ' · ' + detail.note : ''}`;
      return `<code class="${cls}" title="${esc(title)}">${esc(c)}</code>`;
    }).join(' ');
    const prefixes = (r.prefixes || []).map((p) => `<code class="aa-prefix">${esc(p)}</code>`).join(' ');
    return `<tr>
      <td class="mono">${esc(r.sku)}</td>
      <td>${esc(r.brand || '')}${r.sources && r.sources.length ? ` <span class="muted">(${esc(r.sources.join('+'))})</span>` : ''}</td>
      <td>${codes || '<span class="muted">—</span>'}</td>
      <td>${prefixes || '<span class="muted">—</span>'}</td>
      <td class="mono">${fmtNum(r.prefix_count)}</td>
      <td>${flags || aaPill('ok', 'pill-int-aa-ok')}</td>
    </tr>`;
  }).join('');
  return `<div class="cdq-card"><div class="section-title">Products <span class="view-sub" style="font-weight:400">${fmtNum(rows.length)} rows</span></div>
    <div class="data-table-wrap" style="max-height:26rem;overflow:auto"><table class="data-table aa-table">
      <thead><tr><th>ASIN / SKU</th><th>Brand</th><th>Product codes</th><th>GS1 prefixes</th><th>#</th><th>Flags</th></tr></thead>
      <tbody>${body}</tbody></table></div></div>`;
}

function aaAiPanel(ai) {
  if (!ai) return '';
  const verdicts = (ai.verdicts || []).map((v) => {
    const status = v.status === 'conflict' ? aaPill('conflict', 'pill-int-aa-conflict')
      : v.status === 'consistent' ? aaPill('consistent', 'pill-int-aa-ok')
      : aaPill(v.status || 'unknown', 'pill-int-unconfigured');
    return `<tr>
      <td class="mono">${esc(v.prefix || '')}</td>
      <td>${esc(v.country || '—')}</td>
      <td>${status}</td>
      <td>${esc(v.normalized_brand || (v.brands || []).join(', '))}</td>
      <td>${esc(v.reasoning || '')}</td>
    </tr>`;
  }).join('');
  const findings = (ai.findings || []).map((f) => {
    const sev = f.severity === 'blocker' ? 'pill-int-aa-conflict' : f.severity === 'warning' ? 'pill-int-aa-warn' : 'pill-int-unconfigured';
    return `<div class="aa-finding"><span class="pill-int ${sev}">${esc(f.severity || 'info')}</span> <span class="muted">${esc(f.kind || '')}</span> <span>${esc(f.message || '')}</span></div>`;
  }).join('');
  const recs = (ai.recommendations || []).map((r) => `<li>${esc(r)}</li>`).join('');

  return `<div class="cdq-card aa-ai">
    <div class="section-title">AI verification <span class="view-sub" style="font-weight:400">${ai.run_id ? 'run #' + ai.run_id : ''}</span></div>
    ${ai.summary ? `<div class="aa-ai-summary">${esc(ai.summary)}</div>` : ''}
    ${verdicts ? `<div class="data-table-wrap" style="max-height:22rem;overflow:auto;margin:0.5rem 0"><table class="data-table aa-table">
      <thead><tr><th>Prefix</th><th>Issued by</th><th>Status</th><th>Normalised brand</th><th>Reasoning</th></tr></thead>
      <tbody>${verdicts}</tbody></table></div>` : ''}
    ${findings ? `<div class="aa-findings">${findings}</div>` : ''}
    ${recs ? `<div class="view-sub" style="margin:0.5rem 0 0.15rem">Recommendations</div><ul class="aa-recs">${recs}</ul>` : ''}
  </div>`;
}

/* ------------------------------------------------------------ actions */
async function aaRunAudit() {
  if (aaState.busy) return;
  aaState.busy = true;
  const res = $('#aa-body');
  res.innerHTML = '<div class="empty-state">Auditing catalog + Keepa cache…</div>';
  try {
    aaState.audit = await api('/api/attribute-audit/audit', { method: 'POST', body: {} });
    aaRenderResult();
  } catch (e) {
    res.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`;
  }
  aaState.busy = false;
}

async function aaRunAi() {
  if (aaState.busy) return;
  aaState.busy = true;
  const btn = $('#aa-ai');
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="codicon codicon-loading codicon-modifier-spin"></span> Verifying…';
  const aiBox = $('#aa-ai-panel');
  aiBox.innerHTML = '<div class="empty-state">Running AI brand verification…</div>';
  try {
    const data = await api('/api/attribute-audit/ai', { method: 'POST', body: {} });
    if (!data.ai) {
      aiBox.innerHTML = `<div class="empty-state">${esc(data.error || 'No verification returned.')}</div>`;
      return;
    }
    aaState.ai = data;
    aiBox.innerHTML = aaAiPanel(data);
    toast('AI verification complete', 'ok');
  } catch (e) {
    aiBox.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`;
  }
  btn.disabled = false;
  btn.innerHTML = original;
  aaState.busy = false;
}

function aaRenderResult() {
  const a = aaState.audit;
  if (!a) return;
  const body = $('#aa-body');
  body.innerHTML = aaKpis(a.summary) + aaPrefixTable(a.prefixes) + `<div style="height:0.75rem"></div>` + aaRowsTable(a.rows);
  if (a.summary && a.summary.products === 0) {
    body.insertAdjacentHTML('afterbegin', '<div class="settings-note" style="margin-bottom:0.5rem">Catalog and Keepa cache are both empty — import products (Catalog Ingest) or look up ASINs in the Keepa view to populate the audit.</div>');
  }
}

/* ------------------------------------------------------------------ entry */
window.ConductorAttributeAudit = {
  render: async function () {
    const root = $('#view-root');
    root.innerHTML = `
      <div class="view">
        <div class="view-header"><div>
          <div class="view-title">Attribute Audit</div>
          <div class="view-sub">Keepa + AI brand &amp; identifier verification — extract the 6-digit GS1 company prefix from every UPC/EAN/GTIN, validate check digits, resolve the issuing member organisation, and flag brand conflicts.</div>
        </div>
        <div class="view-actions">
          <button class="btn-primary" id="aa-run"><span class="codicon codicon-shield"></span> Run audit</button>
          <button class="btn-secondary" id="aa-ai"><span class="codicon codicon-sparkle"></span> AI verify</button>
        </div></div>
        <div id="aa-body"></div>
        <div id="aa-ai-panel"></div>
      </div>`;

    root.querySelector('#aa-run').addEventListener('click', aaRunAudit);
    root.querySelector('#aa-ai').addEventListener('click', aaRunAi);

    // Auto-run the deterministic audit on entry (it's free + instant).
    await aaRunAudit();

    // Surface AI-provider readiness so the verify button isn't a mystery.
    try {
      const st = await api('/api/attribute-audit/status');
      if (!st.ai_ready) {
        $('#aa-ai-panel').insertAdjacentHTML('beforeend',
          '<div class="settings-note" style="margin-top:0.75rem">AI verification needs a provider key — add one in Settings → AI Chat, then click “AI verify”.</div>');
      }
    } catch { /* noop */ }
  }
};

// Route the `attraudit` nav view to this module.
try { VIEW_RENDERERS.attraudit = () => window.ConductorAttributeAudit.render(); } catch (e) { /* noop */ }

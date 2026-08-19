/**
 * Conductor — Product Pipelines view.
 *
 * Turns Amazon's SP-API `getDefinitionsProductType` schema into a staged product
 * pipeline: required attributes → attribute table → flat-file columns → attribute
 * guidelines → catalog readiness. Exposes window.ConductorProductPipeline.render()
 * and routes the `productpipeline` nav view to it. Uses globals provided by
 * app.js ($, $$, api, esc, toast) — loaded after app.js.
 */
'use strict';

window.ConductorProductPipeline = (function () {
  let state = { mode: 'list', pipelineId: null, markets: [], regions: [], requirements: [] };

  /* ------------------------------------------------------------ helpers */
  function pill(label, cls) {
    return `<span class="pill-int ${cls}">${esc(label)}</span>`;
  }

  function fmtAgo(iso) {
    if (!iso) return '—';
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return iso;
    const s = Math.max(1, Math.floor((Date.now() - t) / 1000));
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  }

  function enumChip(v) {
    return `<span class="pp-chip">${esc(v)}</span>`;
  }

  function typeBadge(a) {
    const req = a.required ? '<span class="pp-req" title="Required">req</span>' : '';
    const t = a.type ? `<span class="pp-type">${esc(a.type)}</span>` : '';
    return `${req}${t}`;
  }

  async function loadMeta() {
    try {
      const st = await api('/api/productpipeline/status');
      state.markets = st.marketplaces || [];
      state.regions = st.regions || [];
      state.requirements = st.requirements || [];
      return st;
    } catch (e) { toast(e.message, 'err'); return null; }
  }

  /* ------------------------------------------------------------ list view */
  async function renderList() {
    const root = $('#view-root');
    const st = await loadMeta();
    const hasKey = st ? st.has_key : false;

    root.innerHTML = `<div class="view">
      <div class="view-header"><div>
        <div class="view-title">Product Pipelines</div>
        <div class="view-sub">Turn Amazon's <code>getDefinitionsProductType</code> schema into a staged listing workflow — required attributes, flat-file columns, attribute guidelines, and catalog readiness.</div>
      </div></div>

      <div class="pp-panel">
        <div class="pp-config">
          <div class="keepa-config-head"><span class="codicon codicon-key"></span> SP-API credentials
            ${hasKey ? pill(`configured · ${st.auth_mode}`, 'pill-int-configured') : pill('not configured', 'pill-int-missing')}
          </div>
          <div class="pp-config-note">Live fetches use LWA (refresh_token + client_id + client_secret) or a direct access_token. Without credentials, fetches fall back to bundled sample definitions (labelled).</div>
          <div class="field-row">
            <label class="field"><span>Refresh token</span><input id="pp-refresh" type="password" placeholder="${hasKey ? st.refresh_token_masked + ' (saved)' : 'LWA refresh_token'}" autocomplete="off" /></label>
            <label class="field"><span>Client ID</span><input id="pp-client" type="password" placeholder="${hasKey ? st.client_id_masked + ' (saved)' : 'LWA client_id'}" autocomplete="off" /></label>
            <label class="field"><span>Client secret</span><input id="pp-secret" type="password" placeholder="LWA client_secret" autocomplete="off" /></label>
          </div>
          <div class="field-row">
            <label class="field"><span>Direct access token (optional)</span><input id="pp-token" type="password" placeholder="x-amz-access-token" autocomplete="off" /></label>
            <label class="field"><span>Region</span><select id="pp-region">${(state.regions || []).map((r) => `<option value="${esc(r.id)}" ${st && st.region === r.id ? 'selected' : ''}>${esc(r.id.toUpperCase())} — ${esc(r.host)}</option>`).join('')}</select></label>
          </div>
          <div class="settings-actions">
            <button class="btn-secondary" id="pp-save-key"><span class="codicon codicon-save"></span> Save credentials</button>
          </div>
        </div>

        <div class="pp-fetch">
          <div class="keepa-config-head"><span class="codicon codicon-cloud-download"></span> New pipeline from a product type</div>
          <div class="field-row">
            <label class="field" style="flex:1"><span>Product type</span><input id="pp-ptype" placeholder="LUGGAGE" /></label>
            <label class="field"><span>Marketplace</span><select id="pp-market">${(state.markets || []).map((m) => `<option value="${esc(m.id)}">${esc(m.code)} — ${esc(m.id)}</option>`).join('')}</select></label>
            <label class="field"><span>Locale</span><input id="pp-locale" value="en_US" style="width:5rem" /></label>
            <label class="field"><span>Requirements</span><select id="pp-req">${(state.requirements || ['LISTING']).map((r) => `<option ${r === 'LISTING' ? 'selected' : ''}>${esc(r)}</option>`).join('')}</select></label>
          </div>
          <div class="field-row">
            <label class="field" style="flex:1"><span>Pipeline name (optional)</span><input id="pp-name" placeholder="auto: LUGGAGE · US" /></label>
          </div>
          <div class="settings-actions">
            <button class="btn-primary" id="pp-fetch"><span class="codicon codicon-add"></span> Fetch &amp; build pipeline</button>
            <span class="muted" id="pp-fetch-hint" style="margin-left:0.25rem"></span>
          </div>
        </div>
      </div>

      <div class="view-title" style="margin-top:1.25rem">Pipelines</div>
      <div class="view-sub" style="margin-bottom:0.5rem">Saved product-type workflows. Open one to review attributes, generate flat files &amp; guidelines, and score the catalog.</div>
      <div id="pp-list" class="pp-list"><div class="folder-loading">Loading…</div></div>
    </div>`;

    $('#pp-save-key').addEventListener('click', async () => {
      const body = {};
      const r = $('#pp-refresh').value.trim();
      const c = $('#pp-client').value.trim();
      const s = $('#pp-secret').value.trim();
      const t = $('#pp-token').value.trim();
      if (r) body.refresh_token = r;
      if (c) body.client_id = c;
      if (s) body.client_secret = s;
      if (t) body.access_token = t;
      body.region = $('#pp-region').value;
      if (!r && !t && !c && !s) return toast('Enter credentials (refresh_token, or access_token)', 'warn');
      try {
        await api('/api/productpipeline/config', { method: 'POST', body });
        toast('SP-API credentials saved', 'ok');
        renderList();
      } catch (e) { toast(e.message, 'err'); }
    });

    $('#pp-fetch').addEventListener('click', async () => {
      const product_type = $('#pp-ptype').value.trim();
      if (!product_type) return toast('Enter a product type (e.g. LUGGAGE)', 'warn');
      const hint = $('#pp-fetch-hint');
      hint.textContent = 'fetching…';
      try {
        const d = await api('/api/productpipeline/fetch', {
          method: 'POST',
          body: {
            product_type,
            marketplace_ids: [$('#pp-market').value],
            locale: $('#pp-locale').value.trim() || 'en_US',
            requirements: $('#pp-req').value,
            name: $('#pp-name').value.trim(),
          },
        });
        toast(`Pipeline built (${d._fetched_from})`, 'ok');
        state.pipelineId = d.id;
        renderDetail(d.id);
      } catch (e) { toast(e.message, 'err'); }
      finally { hint.textContent = ''; }
    });

    try {
      const data = await api('/api/productpipeline/pipelines');
      const wrap = $('#pp-list');
      const items = data.pipelines || [];
      if (!items.length) {
        wrap.innerHTML = `<div class="empty-state">No pipelines yet — fetch a product type above to build your first one.</div>`;
        return;
      }
      wrap.innerHTML = items.map((p) => `
        <div class="pp-card" data-id="${p.id}">
          <div class="pp-card-head">
            <span class="codicon codicon-git-merge pp-card-icon"></span>
            <div style="flex:1;min-width:0">
              <div class="pp-card-name">${esc(p.name)}</div>
              <div class="pp-card-sub">${esc(p.product_type)} · ${esc(p.marketplace_id)} · ${esc(p.locale)} · ${esc(p.requirements)}</div>
            </div>
            ${pill(p.source, p.source === 'live' ? 'pill-int-configured' : 'pill-int-missing')}
            <button class="btn-secondary btn-sm pp-open" data-id="${p.id}"><span class="codicon codicon-chevron-right"></span> Open</button>
            <button class="btn-secondary btn-sm pp-del" data-id="${p.id}" title="Delete"><span class="codicon codicon-trash"></span></button>
          </div>
          <div class="pp-card-foot">Built ${fmtAgo(p.created_at)}</div>
        </div>`).join('');
      wrap.querySelectorAll('.pp-open').forEach((b) => b.addEventListener('click', () => renderDetail(Number(b.dataset.id))));
      wrap.querySelectorAll('.pp-del').forEach((b) => b.addEventListener('click', async () => {
        try {
          await api(`/api/productpipeline/pipelines/${b.dataset.id}`, { method: 'DELETE' });
          toast('Pipeline deleted', 'ok');
          renderList();
        } catch (e) { toast(e.message, 'err'); }
      }));
    } catch (e) { toast(e.message, 'err'); }
  }

  /* ------------------------------------------------------------ detail view */
  async function renderDetail(id) {
    const root = $('#view-root');
    state.pipelineId = id;
    let d;
    try { d = await api(`/api/productpipeline/pipelines/${id}`); }
    catch (e) { toast(e.message, 'err'); return renderList(); }

    const st = d.stages;
    const req = st.required_attributes || [];
    const attrs = st.attributes || [];
    const cols = st.flatfile_columns || [];
    const guides = st.guidelines || [];

    const groupNames = [...new Set(attrs.map((a) => a.group))];
    const attrTable = groupNames.map((g) => `
      <div class="pp-group">
        <div class="pp-group-title">${esc(g)}</div>
        <table class="data-table">
          <tr><th></th><th>Attribute</th><th>Type</th><th>Allowed values</th><th>Bounds</th><th>Description</th></tr>
          ${attrs.filter((a) => a.group === g).map((a) => `
            <tr>
              <td>${typeBadge(a)}</td>
              <td><b>${esc(a.name)}</b></td>
              <td>${esc(a.type || '—')}${a.format ? ` <span class="muted">(${esc(a.format)})</span>` : ''}</td>
              <td>${(a.enum || []).slice(0, 8).map(enumChip).join('') || '—'}</td>
              <td>${a.min_length != null || a.max_length != null ? `min ${a.min_length ?? '—'} / max ${a.max_length ?? '—'}` : (a.pattern ? `<code>${esc(a.pattern)}</code>` : '—')}</td>
              <td class="muted">${esc(a.description || '')}${a.example != null ? ` <span class="muted">e.g. ${esc(String(a.example))}</span>` : ''}</td>
            </tr>`).join('')}
        </table>
      </div>`).join('');

    root.innerHTML = `<div class="view">
      <div class="view-header"><div>
        <div style="display:flex;align-items:center;gap:0.5rem">
          <button class="btn-secondary btn-sm" id="pp-back"><span class="codicon codicon-arrow-left"></span> Back</button>
          <div class="view-title">${esc(d.name)}</div>
          ${pill(d.source, d.source === 'live' ? 'pill-int-configured' : 'pill-int-missing')}
        </div>
        <div class="view-sub">${esc(d.product_type)} · ${esc(d.marketplace_id)} · ${esc(d.locale)} · ${esc(d.requirements)} — ${attrs.length} attributes (${req.length} required)</div>
      </div></div>

      <div class="pp-stages">
        <div class="pp-stage"><div class="pp-stage-n">1</div><div>Required attributes<div class="muted">${req.length} required</div></div></div>
        <div class="pp-stage"><div class="pp-stage-n">2</div><div>Attribute table<div class="muted">${attrs.length} attributes</div></div></div>
        <div class="pp-stage"><div class="pp-stage-n">3</div><div>Flat-file columns<div class="muted">${cols.length} columns</div></div></div>
        <div class="pp-stage"><div class="pp-stage-n">4</div><div>Guidelines<div class="muted">${guides.length} rules</div></div></div>
        <div class="pp-stage"><div class="pp-stage-n">5</div><div>Catalog readiness<div class="muted">score vs required</div></div></div>
      </div>

      <div class="settings-actions" style="margin:0.75rem 0">
        <button class="btn-primary" id="pp-gen-both"><span class="codicon codicon-rocket"></span> Generate flat file + guidelines</button>
        <button class="btn-secondary" id="pp-gen-flatfile"><span class="codicon codicon-table"></span> Flat file only</button>
        <button class="btn-secondary" id="pp-gen-guidelines"><span class="codicon codicon-symbol-property"></span> Guidelines only</button>
        <button class="btn-secondary" id="pp-ready"><span class="codicon codicon-checklist"></span> Check catalog readiness</button>
        <span class="muted" id="pp-action-hint" style="margin-left:0.25rem"></span>
      </div>

      <div class="view-title" style="margin-top:1rem">Required attributes</div>
      <div class="pp-chips">${req.length ? req.map((r) => `<span class="pp-chip pp-chip-req">${esc(r)}</span>`).join('') : '<span class="muted">No required attributes in this schema.</span>'}</div>

      <div class="view-title" style="margin-top:1.25rem">Attribute table</div>
      ${attrTable || '<div class="empty-state">No attributes in this schema.</div>'}

      <div class="view-title" style="margin-top:1.25rem">Derived flat-file columns</div>
      <table class="data-table"><tr><th>Key</th><th>Label</th><th>Required</th><th>Allowed values</th><th>Example</th></tr>
        ${cols.map((c) => `<tr><td><code>${esc(c.key)}</code></td><td>${esc(c.label)}</td><td>${c.required ? '<span class="pp-req">req</span>' : '—'}</td><td>${(c.values || []).slice(0, 6).map(enumChip).join('') || '—'}</td><td class="muted">${c.example != null ? esc(String(c.example)) : '—'}</td></tr>`).join('')}
      </table>

      <div class="view-title" style="margin-top:1.25rem">Derived guidelines</div>
      <table class="data-table"><tr><th>Attribute</th><th>Rule</th><th>Value</th><th>Severity</th><th>Note</th></tr>
        ${guides.map((g) => `<tr><td><b>${esc(g.attribute)}</b></td><td><span class="pill-status">${esc(g.rule_type)}</span></td><td><code>${esc(g.rule_value || '')}</code></td><td>${esc(g.severity)}</td><td class="muted">${esc(g.note || '')}</td></tr>`).join('')}
      </table>

      <div id="pp-readiness" style="margin-top:1.25rem"></div>
    </div>`;

    $('#pp-back').addEventListener('click', () => { state.pipelineId = null; renderList(); });

    const hint = (txt) => { const h = $('#pp-action-hint'); if (h) h.textContent = txt; };

    $('#pp-gen-both').addEventListener('click', () => generate(id, 'both', hint));
    $('#pp-gen-flatfile').addEventListener('click', () => generate(id, 'flatfile', hint));
    $('#pp-gen-guidelines').addEventListener('click', () => generate(id, 'guidelines', hint));
    $('#pp-ready').addEventListener('click', () => renderReadiness(id));
  }

  async function generate(id, target, hint) {
    hint('generating…');
    try {
      const r = await api(`/api/productpipeline/pipelines/${id}/generate`, { method: 'POST', body: { target } });
      const parts = [];
      if (r.flatfile_template_id) parts.push(`flat-file template #${r.flatfile_template_id}`);
      if (r.guidelines_written) parts.push(`${r.guidelines_written} guideline(s)`);
      toast(`Generated ${parts.join(' + ') || 'nothing'}`, 'ok');
    } catch (e) { toast(e.message, 'err'); }
    finally { hint(''); }
  }

  async function renderReadiness(id) {
    const wrap = $('#pp-readiness');
    if (!wrap) return;
    wrap.innerHTML = `<div class="folder-loading">Scoring catalog…</div>`;
    try {
      const r = await api(`/api/productpipeline/pipelines/${id}/readiness`, { method: 'POST', body: {} });
      const rows = r.products || [];
      wrap.innerHTML = `<div class="view-title">Catalog readiness</div>
        <div class="view-sub">${r.ready_count} of ${r.catalog_count} catalog products satisfy all ${(r.required_attributes || []).length} required attributes.</div>
        ${rows.length ? `<table class="data-table"><tr><th>SKU</th><th>Name</th><th>Complete</th><th>Missing</th></tr>
          ${rows.map((p) => `<tr><td><code>${esc(p.sku)}</code></td><td>${esc(p.name)}</td><td>${p.complete ? '<span class="pill-status">ready</span>' : `<span class="pill-status pill-warn">${p.pct}%</span>`}</td><td>${p.missing.length ? p.missing.map((m) => `<span class="pp-chip pp-chip-req">${esc(m)}</span>`).join('') : '—'}</td></tr>`).join('')}
        </table>` : '<div class="empty-state">No catalog products to score.</div>'}`;
    } catch (e) { toast(e.message, 'err'); wrap.innerHTML = ''; }
  }

  /* ------------------------------------------------------------ export */
  return {
    render: function () {
      if (state.pipelineId && state.mode !== 'list') return renderDetail(state.pipelineId);
      return renderList();
    },
  };
})();

// Route the `productpipeline` nav view to this module.
try { VIEW_RENDERERS.productpipeline = () => window.ConductorProductPipeline.render(); } catch (e) { /* noop */ }

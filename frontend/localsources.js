/**
 * Conductor — Local Sources view.
 *
 * Designate local files/folders on this machine as data & context sources the
 * app can remember, list, browse, and read from. Loaded after app.js, so the
 * globals `api`, `esc`, `$`, `$$`, `toast`, `fmtNum` are available.
 *
 * Exposes `window.ConductorLocalSources.render()` for the nav dispatcher.
 */
'use strict';

window.ConductorLocalSources = (function () {
  const state = {
    sources: [],
    browsing: null, // { id, kind, path, sourceLabel, files, truncated }
  };

  /* ------------------------------------------------------------ utilities */
  function fmtSize(n) {
    const v = Number(n || 0);
    if (v < 1024) return v + ' B';
    if (v < 1024 * 1024) return (v / 1024).toFixed(1) + ' KB';
    if (v < 1024 * 1024 * 1024) return (v / 1024 / 1024).toFixed(1) + ' MB';
    return (v / 1024 / 1024 / 1024).toFixed(2) + ' GB';
  }

  function joinPath(base, name) {
    return base ? base + '/' + name : name;
  }

  function parentPath(p) {
    const i = p.lastIndexOf('/');
    return i < 0 ? '' : p.slice(0, i);
  }

  function injectStyle() {
    if (document.getElementById('ls-style')) return;
    const st = document.createElement('style');
    st.id = 'ls-style';
    st.textContent = `
      #ls-form input, #ls-form select {
        background: var(--input); border: 1px solid var(--sidebar-border);
        border-radius: var(--radius-sm, 4px); padding: 0.3125rem 0.5rem;
        font-size: 0.78125rem; color: var(--fg); outline: none;
        min-height: var(--control-h, 1.75rem);
      }
      #ls-form input:focus, #ls-form select:focus { border-color: var(--ring); }
      #ls-label { width: 12rem; }
      #ls-path { flex: 1; min-width: 16rem; font-family: var(--font-mono); font-size: 0.6875rem; }
      .ls-detail-card {
        max-width: 72rem; margin: 0.875rem auto 0;
        background: color-mix(in srgb, var(--card) 45%, transparent);
        border: 1px solid var(--sidebar-border); border-radius: var(--radius-sm, 4px);
        box-shadow: var(--elev-1); overflow: hidden;
      }
      .ls-detail-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
      .ls-detail-actions { display: flex; gap: 0.375rem; padding-right: 0.5rem; }
      .ls-crumb { cursor: pointer; color: var(--fg-strong); }
      .ls-crumb:hover { text-decoration: underline; }
      .ls-entry { cursor: pointer; }
      .ls-entry:hover td { background: color-mix(in srgb, var(--fg) 5%, transparent); }
      .ls-preview {
        margin: 0; padding: 0.75rem; max-height: 24rem; overflow: auto;
        font-family: var(--font-mono); font-size: 0.6875rem; line-height: 1.5;
        color: var(--fg); white-space: pre-wrap; word-break: break-word;
        background: var(--bg, color-mix(in srgb, var(--card) 30%, transparent));
        border-top: 1px solid var(--sidebar-border);
      }
    `;
    document.head.appendChild(st);
  }

  /* -------------------------------------------------------------- renderers */
  function drawSources() {
    const wrap = $('#ls-list');
    if (!wrap) return;
    if (!state.sources.length) {
      wrap.innerHTML = `<div class="empty-state"><div class="big"><span class="codicon codicon-folder-opened"></span></div>No local sources yet — point Conductor at a folder or file to use it as context.</div>`;
      return;
    }
    wrap.innerHTML = `<table class="data-table">
      <tr><th>Label</th><th>Path</th><th>Kind</th><th>Files</th><th>Status</th><th></th></tr>
      ${state.sources.map((s) => {
        const badge = s.exists
          ? `<span class="pill-int pill-int-configured">present</span>`
          : `<span class="pill-int pill-int-missing">missing</span>`;
        return `<tr data-id="${s.id}">
          <td><b>${esc(s.label)}</b></td>
          <td class="mono">${esc(s.path)}</td>
          <td><span class="pill-status">${esc(s.kind)}</span></td>
          <td>${fmtNum(s.count)}</td>
          <td>${badge}</td>
          <td style="white-space:nowrap">
            <button class="btn-secondary btn-sm ls-browse" data-id="${s.id}">Browse</button>
            <button class="btn-secondary btn-sm ls-remove" data-id="${s.id}">Remove</button>
          </td>
        </tr>`;
      }).join('')}
    </table>`;

    wrap.querySelectorAll('.ls-browse').forEach((b) => b.addEventListener('click', () => browse(b.dataset.id)));
    wrap.querySelectorAll('.ls-remove').forEach((b) => b.addEventListener('click', () => remove(b.dataset.id)));
  }

  function drawDetail(src) {
    const el = $('#ls-detail');
    if (!el) return;
    const b = state.browsing;
    if (!b || !src) { el.innerHTML = ''; return; }
    const crumbs = b.path ? b.path.split('/').filter(Boolean) : [];
    const breadcrumb =
      `<span class="ls-crumb" data-path="">${esc(b.sourceLabel)}</span>` +
      crumbs.map((c, i) =>
        `<span class="codicon codicon-chevron-right"></span><span class="ls-crumb" data-path="${esc(crumbs.slice(0, i + 1).join('/'))}">${esc(c)}</span>`
      ).join('');
    const up = (b.kind === 'folder' && b.path)
      ? `<button class="btn-secondary btn-sm ls-up">Up</button>` : '';
    let body;
    if (!b.files.length) {
      body = `<div class="empty-state">This ${b.kind} is empty.</div>`;
    } else {
      body = `<table class="data-table">
        <tr><th>Name</th><th>Size</th></tr>
        ${b.files.map((f) => {
          const icon = f.is_dir ? 'codicon-folder' : 'codicon-file';
          return `<tr class="ls-entry ${f.is_dir ? 'ls-dir' : 'ls-file'}" data-name="${esc(f.name)}" data-dir="${f.is_dir ? 1 : 0}">
            <td><span class="codicon ${icon}"></span> ${esc(f.name)}</td>
            <td class="mono">${f.is_dir ? '' : fmtSize(f.size)}</td>
          </tr>`;
        }).join('')}
      </table>`;
    }
    el.innerHTML = `<div class="ls-detail-card">
      <div class="ls-detail-head">
        <div class="folder-hint" style="border-top:0">${breadcrumb}</div>
        <div class="ls-detail-actions">${up}<button class="btn-secondary btn-sm ls-close">Close</button></div>
      </div>
      ${b.truncated ? `<div class="folder-hint">Showing first 200 entries.</div>` : ''}
      <div class="ls-detail-body">${body}</div>
    </div>`;

    el.querySelectorAll('.ls-crumb').forEach((c) => c.addEventListener('click', () => browse(b.id, c.dataset.path)));
    const upBtn = el.querySelector('.ls-up');
    if (upBtn) upBtn.addEventListener('click', () => browse(b.id, parentPath(b.path)));
    const closeBtn = el.querySelector('.ls-close');
    if (closeBtn) closeBtn.addEventListener('click', () => { state.browsing = null; drawDetail(src); });
    el.querySelectorAll('.ls-dir').forEach((r) => r.addEventListener('click', () => browse(b.id, joinPath(b.path, r.dataset.name))));
    el.querySelectorAll('.ls-file').forEach((r) => r.addEventListener('click', () => read(b.id, joinPath(b.path, r.dataset.name))));
  }

  /* ---------------------------------------------------------------- actions */
  async function loadSources() {
    const wrap = $('#ls-list');
    if (!wrap) return;
    try {
      state.sources = await api('/api/local-sources');
    } catch (e) {
      toast(e.message, 'err');
      state.sources = [];
    }
    drawSources();
  }

  async function browse(id, path) {
    const src = state.sources.find((x) => x.id === Number(id));
    if (!src) return;
    try {
      const res = await api(`/api/local-sources/${id}/browse?path=${encodeURIComponent(path || '')}`);
      state.browsing = {
        id: Number(id),
        kind: res.kind,
        path: res.path || '',
        sourceLabel: src.label,
        files: res.files || [],
        truncated: !!res.truncated,
      };
      drawDetail(src);
    } catch (e) { toast(e.message, 'err'); }
  }

  async function read(id, path) {
    const el = $('#ls-detail');
    if (!el) return;
    try {
      const res = await api(`/api/local-sources/${id}/read?path=${encodeURIComponent(path || '')}`);
      if (res.binary) {
        el.innerHTML = `<div class="ls-detail-card">
          <div class="ls-detail-head"><div class="folder-hint" style="border-top:0">${esc(res.name)}</div></div>
          <div class="empty-state">Binary file — ${fmtSize(res.size)}, can't preview as text.</div>
        </div>`;
        return;
      }
      el.innerHTML = `<div class="ls-detail-card">
        <div class="ls-detail-head">
          <div class="folder-hint" style="border-top:0">${esc(res.name)} · ${fmtSize(res.size)}${res.truncated ? ' · truncated at 200 KB' : ''}</div>
          <div class="ls-detail-actions"><button class="btn-secondary btn-sm ls-back">Back</button></div>
        </div>
        <pre class="ls-preview">${esc(res.text)}</pre>
      </div>`;
      const back = el.querySelector('.ls-back');
      if (back) back.addEventListener('click', () => {
        const src = state.sources.find((x) => x.id === state.browsing.id);
        drawDetail(src);
      });
    } catch (e) { toast(e.message, 'err'); }
  }

  async function addSource() {
    const label = $('#ls-label').value.trim();
    const path = $('#ls-path').value.trim();
    const kind = $('#ls-kind').value;
    if (!label) { toast('Label is required', 'err'); return; }
    if (!path) { toast('Path is required', 'err'); return; }
    try {
      const created = await api('/api/local-sources', { method: 'POST', body: { label, path, kind } });
      toast(`Added "${created.label}"`, 'ok');
      $('#ls-label').value = '';
      $('#ls-path').value = '';
      await loadSources();
    } catch (e) { toast(e.message, 'err'); }
  }

  async function remove(id) {
    const s = state.sources.find((x) => x.id === Number(id));
    if (!s || !confirm(`Remove local source "${s.label}"?`)) return;
    try {
      await api(`/api/local-sources/${id}`, { method: 'DELETE' });
      if (state.browsing && state.browsing.id === Number(id)) {
        state.browsing = null;
        const el = $('#ls-detail');
        if (el) el.innerHTML = '';
      }
      toast('Removed', 'ok');
      await loadSources();
    } catch (e) { toast(e.message, 'err'); }
  }

  /* ------------------------------------------------------------------ render */
  async function render() {
    const root = $('#view-root');
    if (!root) return;
    injectStyle();
    state.browsing = null;
    state.sources = [];
    root.innerHTML = `<div class="view">
      <div class="view-header">
        <div>
          <div class="view-title">Local Sources</div>
          <div class="view-sub">Designate files and folders on this machine as data and context sources the app can list, browse, and read.</div>
        </div>
      </div>
      <div class="view-toolbar" id="ls-form">
        <input id="ls-label" placeholder="Label (e.g. Product Sheets)" />
        <input id="ls-path" placeholder="C:/Users/.../some-folder" />
        <select id="ls-kind">
          <option value="folder">Folder</option>
          <option value="file">File</option>
        </select>
        <button class="btn-primary" id="ls-add"><span class="codicon codicon-add"></span> Add</button>
      </div>
      <div class="data-table-wrap" id="ls-list"><div class="folder-loading">Loading…</div></div>
      <div id="ls-detail"></div>
    </div>`;
    root.querySelector('#ls-add').addEventListener('click', addSource);
    root.querySelector('#ls-path').addEventListener('keydown', (e) => { if (e.key === 'Enter') addSource(); });
    root.querySelector('#ls-label').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#ls-path').focus(); });
    await loadSources();
  }

  return { render };
})();

/**
 * Conductor — Models view (HuggingFace browser + local model manager).
 *
 * Browse the HuggingFace Hub, open a model's full card (README + metadata +
 * GGUF files with a "will it run on this machine" verdict), then download,
 * run, and delete models fully local through the llama.cpp engine.
 *
 * Uses globals from app.js: $, $$, esc, api, toast, fmtNum, fmtBytes, fmtAgo,
 * fmtCount, md, el. Self-registers the `models` nav view.
 */
'use strict';

const modelsState = {
  query: '',
  sort: 'downloads',
  ggufOnly: true,
  results: [],
  selectedId: null,
  card: null,      // { model, readme, files, repo_id }
  tab: 'hub',      // 'hub' | 'library'
  sys: null,
  local: [],       // discovered local GGUF models
  llama: null,     // llama server status
  downloads: [],
};
let modelsPoll = null;

/* ------------------------------------------------------------- tiny helpers */
function mPill(text, cls) { return `<span class="pill-status ${cls || ''}">${esc(text)}</span>`; }

/* Convert an HF README (raw HTML + markdown) into plain markdown-ish text that
 * the app's `md()` renderer can handle safely. md() escapes everything first,
 * so stripping tags here is purely presentational, not a sanitization concern. */
function readmeToMarkdown(raw) {
  let s = String(raw || '');
  s = s.replace(/<script[\s\S]*?<\/script>/gi, '');
  s = s.replace(/<style[\s\S]*?<\/style>/gi, '');
  s = s.replace(/<img[^>]*alt="([^"]*)"[^>]*>/gi, '[$1]');
  s = s.replace(/<img[^>]*>/gi, '[image]');
  s = s.replace(/<br\s*\/?>/gi, '\n');
  s = s.replace(/<\/(p|div|h[1-6]|li|ul|ol|tr|table|section)>/gi, '\n');
  s = s.replace(/<[^>]+>/g, '');
  s = s.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
       .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&nbsp;/g, ' ');
  s = s.replace(/\n{3,}/g, '\n\n');
  return s;
}

function mFitBadge(fit) {
  if (!fit) return '';
  const cls = { ok: 'pill-int pill-int-configured', tight: 'pill-int pill-int-simulated', no: 'pill-int pill-int-missing', unknown: 'pill-status' }[fit.level] || 'pill-status';
  return `<span class="${cls}">${esc(fit.label)}</span>`;
}
function mTags(tags, max) {
  const t = (tags || []).slice(0, max || 6);
  return t.map((x) => mPill(x.replace(/^(license|base_model|region):/, ''), 'pill-status')).join(' ');
}

/* ------------------------------------------------------------- search */
async function modelsSearch() {
  const list = $('#hf-results');
  if (!list) return;
  list.innerHTML = '<div class="folder-loading">Searching Hugging Face…</div>';
  try {
    const q = new URLSearchParams({
      q: modelsState.query, sort: modelsState.sort,
      gguf: modelsState.ggufOnly ? 'true' : 'false', limit: '30',
    });
    const res = await api(`/api/hf/search?${q}`);
    modelsState.results = res.results || [];
    modelsRenderResults();
  } catch (e) {
    list.innerHTML = `<div class="folder-hint">Search failed: ${esc(e.message)}</div>`;
  }
}

function modelsRenderResults() {
  const list = $('#hf-results');
  if (!list) return;
  if (!modelsState.results.length) {
    list.innerHTML = '<div class="empty-state" style="padding:2rem 1rem">No models found. Try a different query.</div>';
    return;
  }
  list.innerHTML = modelsState.results.map((m) => {
    const active = m.id === modelsState.selectedId ? ' models-result-active' : '';
    const gated = m.gated ? '<span class="pill-int pill-int-simulated" title="Requires HF auth to download">gated</span>' : '';
    const gguf = m.gguf ? mPill('GGUF', 'pill-int pill-int-configured') : '';
    return `<button class="models-result${active}" data-id="${esc(m.id)}">
      <div class="models-result-head">
        <span class="models-result-author">${esc(m.author || '?')}</span>
        <span class="models-result-meta">${mPill(m.pipeline_tag || m.library_name || 'model', 'pill-status')} ${gguf} ${m.params ? mPill(m.params, 'pill-status') : ''} ${gated}</span>
      </div>
      <div class="models-result-name">${esc((m.id || '').split('/').pop() || m.id)}</div>
      <div class="models-result-foot">
        <span title="downloads"><span class="codicon codicon-cloud-download"></span> ${fmtCount(m.downloads)}</span>
        <span title="likes"><span class="codicon codicon-heart"></span> ${fmtCount(m.likes)}</span>
        ${m.license ? `<span class="models-result-lic">${esc(m.license)}</span>` : ''}
        <span class="models-result-ago">${m.lastModified ? fmtAgo(m.lastModified) : ''}</span>
      </div>
    </button>`;
  }).join('');
  list.querySelectorAll('.models-result').forEach((b) => b.addEventListener('click', () => modelsSelect(b.dataset.id)));
}

/* ------------------------------------------------------------- detail (model card) */
async function modelsSelect(id) {
  modelsState.selectedId = id;
  modelsRenderResults();
  const detail = $('#hf-detail');
  detail.innerHTML = '<div class="folder-loading">Loading model card…</div>';
  try {
    const res = await api(`/api/hf/model/${encodeURIComponent(id)}`);
    modelsState.card = res;
    modelsRenderCard();
  } catch (e) {
    detail.innerHTML = `<div class="folder-hint">Could not load model card: ${esc(e.message)}</div>`;
  }
}

function modelsRenderCard() {
  const detail = $('#hf-detail');
  const card = modelsState.card;
  if (!card) return;
  const m = card.model || {};
  const files = card.files || [];

  const fileRows = files.length
    ? files.map((f) => {
        const fit = f.fit || {};
        const needed = fit.needed ? `≈ ${(fit.needed / 1073741824).toFixed(1)} GB RAM` : '';
        const q = f.quant ? mPill(f.quant, 'pill-status') : '';
        const size = f.size ? `<span class="mono">${fmtBytes(f.size)}</span>` : '<span class="mono" style="opacity:.5">size n/a</span>';
        return `<div class="models-file">
          <div class="models-file-name mono">${esc(f.path)}</div>
          <div class="models-file-meta">${q} ${size} ${mFitBadge(fit)} ${needed ? `<span class="models-file-need">${esc(needed)}</span>` : ''}</div>
          <div class="models-file-actions">
            <button class="btn-secondary btn-sm" data-dl-repo="${esc(card.repo_id)}" data-dl-file="${esc(f.path)}"><span class="codicon codicon-cloud-download"></span> Download</button>
          </div>
        </div>`;
      }).join('')
    : '<div class="folder-hint">No GGUF files found in this repo — it may be a safetensors-only model (needs conversion).</div>';

  const tags = mTags(m.tags, 12);
  const metaBits = [
    m.params ? mPill(m.params, 'pill-status') : '',
    m.license ? mPill(m.license, 'pill-status') : '',
    m.pipeline_tag ? mPill(m.pipeline_tag, 'pill-status') : '',
    m.gated ? '<span class="pill-int pill-int-simulated">gated — needs HF token</span>' : '',
  ].filter(Boolean).join(' ');

  detail.innerHTML = `
    <div class="hf-card">
      <div class="hf-card-head">
        <div>
          <div class="hf-card-title">${esc((m.id || '').split('/').pop() || card.repo_id)}</div>
          <div class="hf-card-author mono">${esc(m.author ? m.author + ' / ' : '')}${esc(card.repo_id)}</div>
        </div>
        <a class="btn-secondary btn-sm" href="https://huggingface.co/${esc(card.repo_id)}" target="_blank" rel="noopener"><span class="codicon codicon-globe"></span> Open</a>
      </div>
      <div class="hf-card-stats">
        <span title="downloads"><span class="codicon codicon-cloud-download"></span> ${fmtCount(m.downloads)}</span>
        <span title="likes"><span class="codicon codicon-heart"></span> ${fmtCount(m.likes)}</span>
        <span title="updated">${m.lastModified ? 'updated ' + fmtAgo(m.lastModified) : ''}</span>
      </div>
      <div class="hf-card-tags">${metaBits}${tags ? '<span class="hf-tags-sep"></span>' + tags : ''}</div>

      <div class="pane-section-label">GGUF files (${files.length})</div>
      <div class="models-files">${fileRows}</div>

      <div class="pane-section-label">Model card</div>
      <div class="hf-readme">${card.readme ? md(readmeToMarkdown(card.readme)) : '<span class="folder-hint">No README for this model.</span>'}</div>
    </div>`;

  detail.querySelectorAll('[data-dl-repo]').forEach((b) => b.addEventListener('click', () => {
    modelsDownload(b.dataset.dlRepo, b.dataset.dlFile);
  }));
}

/* ------------------------------------------------------------- download */
async function modelsDownload(repoId, filename) {
  try {
    const res = await api('/api/hf/download', { method: 'POST', body: { repo_id: repoId, filename } });
    toast(`Downloading ${filename}…`, 'info');
    modelsStartPoll();
    await modelsDownloads();
  } catch (e) { toast(e.message, 'err'); }
}

async function modelsDownloads() {
  const box = $('#hf-downloads');
  if (!box) return;
  try {
    const res = await api('/api/hf/downloads');
    modelsState.downloads = res.downloads || [];
  } catch { modelsState.downloads = []; }
  const rows = modelsState.downloads.map((d) => {
    const pct = Math.round(d.progress || 0);
    const bar = `<div class="cdq-bar"><div class="cdq-bar-fill" style="width:${pct}%"></div></div>`;
    const statusCls = d.status === 'error' ? 'pill-int pill-int-missing' : d.status === 'done' ? 'pill-int pill-int-configured' : 'pill-status';
    const rate = d.rateBps ? ` · ${fmtBytes(d.rateBps)}/s` : '';
    const cancel = d.status === 'downloading' || d.status === 'queued' || d.status === 'cancelling'
      ? `<button class="nav-mini nav-mini-danger" data-cancel="${esc(d.id)}" title="Cancel">×</button>` : '';
    return `<div class="hf-download">
      <div class="hf-download-head">
        <span class="models-file-name mono" title="${esc(d.repo_id + '/' + d.filename)}">${esc(d.filename)}</span>
        <span class="${statusCls}">${esc(d.status)}</span>${cancel}
      </div>
      <div class="hf-download-meta mono">${fmtBytes(d.done || 0)} / ${fmtBytes(d.total || 0)}${rate}</div>
      ${bar}
      ${d.message && d.status === 'error' ? `<div class="hf-download-err">${esc(d.message)}</div>` : ''}
    </div>`;
  }).join('');
  box.innerHTML = rows || '<div class="folder-hint">Nothing downloading. Pick a GGUF file from a model card to download it.</div>';
  box.querySelectorAll('[data-cancel]').forEach((b) => b.addEventListener('click', async () => {
    await api(`/api/hf/downloads/${b.dataset.cancel}/cancel`, { method: 'POST' });
    toast('Download cancelled', 'info');
  }));
  // keep polling while anything is in flight
  if (modelsState.downloads.some((d) => d.status === 'downloading' || d.status === 'queued' || d.status === 'cancelling')) {
    modelsStartPoll();
  }
}

function modelsStartPoll() {
  if (modelsPoll) clearInterval(modelsPoll);
  modelsPoll = setInterval(() => {
    if (document.getElementById('hf-downloads')) modelsDownloads();
  }, 1200);
}

/* ------------------------------------------------------------- library (installed + running) */
async function modelsLibrary() {
  const box = $('#hf-library');
  if (!box) return;
  box.innerHTML = '<div class="folder-loading">Scanning local models…</div>';
  try {
    const [disc, llama] = await Promise.all([api('/api/llama/discover'), api('/api/llama/status')]);
    modelsState.local = disc.models || [];
    modelsState.llama = llama;
  } catch (e) {
    box.innerHTML = `<div class="folder-hint">Could not scan local models: ${esc(e.message)}</div>`;
    return;
  }
  const runningPath = modelsState.llama && modelsState.llama.modelPath;
  const srcLabel = (s) => {
    if (s.includes('conductor')) return 'conductor models/';
    if (s.includes('.ollama')) return 'Ollama';
    if (s.includes('lm-studio')) return 'LM Studio';
    if (s.includes('.lmstudio')) return 'LM Studio';
    if (s.includes('jan')) return 'Jan / Atomic Chat';
    return s.split(/[\\/]/).slice(-2).join('/');
  };
  const rows = modelsState.local.map((m) => {
    const running = runningPath && runningPath.toLowerCase() === (m.path || '').toLowerCase();
    const deletable = (m.path || '').toLowerCase().includes('conductor');
    return `<div class="models-file">
      <div class="models-file-name">${esc(m.name)} ${running ? '<span class="pill-int pill-int-configured">running</span>' : ''}</div>
      <div class="models-file-meta mono">${fmtBytes(m.sizeBytes)} · ${esc(srcLabel(m.sourceDir))} · ${esc(m.kind)}</div>
      <div class="models-file-actions">
        ${running
          ? `<button class="btn-secondary btn-sm" data-stop="1"><span class="codicon codicon-stop-circle"></span> Stop</button>`
          : `<button class="btn-primary btn-sm" data-run="${esc(m.path)}" data-name="${esc(m.name)}"><span class="codicon codicon-play"></span> Run</button>`}
        ${deletable ? `<button class="btn-secondary btn-sm" data-del="${esc(m.path)}" data-name="${esc(m.name)}"><span class="codicon codicon-trash"></span></button>` : ''}
      </div>
    </div>`;
  }).join('');
  box.innerHTML = rows || '<div class="folder-hint">No local GGUF models found. Download one from the Hub, or drop a .gguf into models/.</div>';
  box.querySelectorAll('[data-run]').forEach((b) => b.addEventListener('click', () => modelsRun(b.dataset.run, b.dataset.name)));
  box.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', () => modelsDelete(b.dataset.del, b.dataset.name)));
  box.querySelectorAll('[data-stop]').forEach((b) => b.addEventListener('click', modelsStop));
}

async function modelsRun(path, name) {
  try {
    const res = await api('/api/llama/start', { method: 'POST', body: { model: path, ctx: 4096 } });
    await api('/api/chat/config', { method: 'POST', body: { provider: 'llama', llama_model: path } });
    toast(`Running ${name} on port ${res.port}${res.reused ? ' (adopted)' : ''}`, 'ok');
  } catch (e) { toast(e.message, 'err'); }
  await modelsLibrary();
}

async function modelsStop() {
  try { await api('/api/llama/stop', { method: 'POST' }); toast('Local server stopped', 'ok'); }
  catch (e) { toast(e.message, 'err'); }
  await modelsLibrary();
}

async function modelsDelete(path, name) {
  if (!confirm(`Delete ${name}? This frees ${'the file'} from disk.`)) return;
  try {
    await api('/api/hf/delete', { method: 'POST', body: { path } });
    toast(`Deleted ${name}`, 'ok');
  } catch (e) { toast(e.message, 'err'); }
  await modelsLibrary();
}

/* ------------------------------------------------------------- system readout */
async function modelsSystem() {
  const el = $('#hf-system');
  if (!el) return;
  try {
    const s = await api('/api/hf/system');
    modelsState.sys = s;
    const ram = s.ram_total ? `${(s.ram_total / 1073741824).toFixed(0)} GB` : '?';
    const disk = s.disk_free ? `${(s.disk_free / 1073741824).toFixed(0)} GB` : '?';
    el.innerHTML = `<span title="Total RAM"><span class="codicon codicon-server-process"></span> ${ram} RAM</span>
      <span title="Free disk"><span class="codicon codicon-database"></span> ${disk} free</span>
      <span title="CPU threads"><span class="codicon codicon-cpu"></span> ${s.cpu_threads || '?'} threads</span>`;
  } catch { el.innerHTML = ''; }
}

/* ------------------------------------------------------------- entry */
window.ConductorModels = {
  render: async function () {
    const root = $('#view-root');
    root.innerHTML = `
      <div class="view">
        <div class="view-header"><div>
          <div class="view-title">Models</div>
          <div class="view-sub">Browse Hugging Face, open the full model card, and download / run / delete models entirely on your machine.</div>
        </div></div>
        <div class="view-toolbar">
          <div class="models-search">
            <input id="hf-q" type="text" placeholder="Search Hugging Face… (e.g. mistral 7b, llama, qwen)" value="${esc(modelsState.query)}" />
            <label class="toggle-mini" title="GGUF only"><input type="checkbox" id="hf-gguf" ${modelsState.ggufOnly ? 'checked' : ''} /><span></span></label>
            <span class="models-gguf-label">GGUF only</span>
            <select id="hf-sort">
              <option value="downloads" ${modelsState.sort === 'downloads' ? 'selected' : ''}>Most downloads</option>
              <option value="trendingScore" ${modelsState.sort === 'trendingScore' ? 'selected' : ''}>Trending</option>
              <option value="likes" ${modelsState.sort === 'likes' ? 'selected' : ''}>Most likes</option>
              <option value="lastModified" ${modelsState.sort === 'lastModified' ? 'selected' : ''}>Recently updated</option>
            </select>
            <button class="btn-primary" id="hf-search-btn"><span class="codicon codicon-search"></span> Search</button>
          </div>
          <div class="models-system" id="hf-system"></div>
        </div>

        <div class="models-layout">
          <div class="models-left">
            <div class="models-tabs">
              <button class="models-tab active" data-tab="hub"><span class="codicon codicon-globe"></span> Hub</button>
              <button class="models-tab" data-tab="library"><span class="codicon codicon-package"></span> Library</button>
            </div>
            <div class="models-left-scroll">
              <div id="models-hub">
                <div class="pane-section-label">Search results</div>
                <div id="hf-results" class="models-results"></div>
              </div>
              <div id="models-library" hidden>
                <div class="pane-section-label">Installed local models</div>
                <div id="hf-library"></div>
                <div class="pane-section-label">Downloads</div>
                <div id="hf-downloads"></div>
              </div>
            </div>
          </div>
          <div class="models-right">
            <div id="hf-detail">
              <div class="empty-state" style="padding:3rem 1rem">
                <div style="font-size:1.5rem;margin-bottom:0.4rem"><span class="codicon codicon-package"></span></div>
                <div>Select a model to see its full card.</div>
                <div class="view-sub" style="margin-top:0.3rem">Search the Hub on the left, then pick a GGUF file to download and run locally.</div>
              </div>
            </div>
          </div>
        </div>
      </div>`;

    // toolbar wiring
    root.querySelector('#hf-search-btn').addEventListener('click', () => {
      modelsState.query = root.querySelector('#hf-q').value.trim();
      modelsState.sort = root.querySelector('#hf-sort').value;
      modelsState.ggufOnly = root.querySelector('#hf-gguf').checked;
      modelsSearch();
    });
    root.querySelector('#hf-q').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') root.querySelector('#hf-search-btn').click();
    });
    root.querySelectorAll('.models-tab').forEach((t) => t.addEventListener('click', () => {
      modelsState.tab = t.dataset.tab;
      root.querySelectorAll('.models-tab').forEach((x) => x.classList.toggle('active', x === t));
      root.querySelector('#models-hub').hidden = modelsState.tab !== 'hub';
      root.querySelector('#models-library').hidden = modelsState.tab !== 'library';
      if (modelsState.tab === 'library') { modelsLibrary(); modelsDownloads(); }
    }));

    modelsSystem();
    await modelsSearch();
    await modelsLibrary();
    await modelsDownloads();
  }
};

// Route the `models` nav view to this module.
try { VIEW_RENDERERS.models = () => window.ConductorModels.render(); } catch (e) { /* noop */ }

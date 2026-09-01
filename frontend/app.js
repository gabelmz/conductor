/**
 * Conductor — frontend logic (Hermes Desktop-style UI).
 *
 * Sections: Chat · Dashboard · Process Discovery · Automations · AI Workflows ·
 * SOPs & Runbooks · Integrations · Asana · Inbound Events · HTTP Requests.
 * Reuses parker's design-token theme engine (theme.js) and styles.css.
 */
'use strict';

/* ------------------------------------------------------------------ utils */
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}
function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function fmtMoney(n) {
  const v = Number(n || 0);
  return '$' + v.toLocaleString(undefined, { maximumFractionDigits: 0 });
}
function fmtNum(n) {
  return Number(n || 0).toLocaleString();
}
function timeAgo(iso) {
  if (!iso) return 'never';
  const t = Date.parse(iso);
  if (!t) return iso;
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
function toast(msg, kind = 'info') {
  const t = el('div', `toast toast-${kind}`, msg);
  $('#toast-stack').appendChild(t);
  setTimeout(() => t.classList.add('toast-out'), 3200);
  setTimeout(() => t.remove(), 3800);
}

async function api(path, opts = {}) {
  const init = { headers: {}, ...opts };
  if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || j.error || JSON.stringify(j);
    } catch { /* not json */ }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

/* ------------------------------------------------- mini markdown renderer */
function md(src) {
  let s = esc(src || '');
  // fenced code blocks first
  s = s.replace(/```([\s\S]*?)```/g, (m, code) => `<pre class="chat-code"><code>${code.replace(/^\n/, '')}</code></pre>`);
  s = s.replace(/`([^`\n]+)`/g, '<code class="chat-code-inline">$1</code>');
  s = s.replace(/^###### (.*)$/gm, '<h6>$1</h6>')
       .replace(/^##### (.*)$/gm, '<h5>$1</h5>')
       .replace(/^#### (.*)$/gm, '<h4>$1</h4>')
       .replace(/^### (.*)$/gm, '<h3>$1</h3>')
       .replace(/^## (.*)$/gm, '<h2>$1</h2>')
       .replace(/^# (.*)$/gm, '<h1>$1</h1>');
  s = s.replace(/^\s*[-*] \[[ xX]\] (.*)$/gm, '<div class="md-task">☐ $1</div>');
  s = s.replace(/^\s*[-*] (.*)$/gm, '<li class="md-li">$1</li>');
  s = s.replace(/^\s*\d+\. (.*)$/gm, '<li class="md-li">$1</li>');
  s = s.replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');
  s = s.replace(/(^|\s)\*([^*\n]+)\*(?=\s|$)/g, '$1<i>$2</i>');
  s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s.split(/\n{2,}/).map((p) => p.trim() ? `<p class="md-p">${p}</p>` : '').join('');
}

/* ------------------------------------------------------------------ state */
const state = {
  view: 'chat',
  chatHistory: [],
  chatProvider: null,
  chatModel: null,
  uiCfg: null,
  stats: {},
  automations: [],
  processes: [],
  sops: [],
  integrations: [],
  aiWorkflows: [],
  folderPath: '',
  sidebar: 'full', // full | rail | tucked
  updateReady: { ready: false, version: null },
};

/* ------------------------------------------------------------- sidebar nav */
function setSidebarState(mode) {
  if (!['full', 'rail', 'tucked'].includes(mode)) mode = 'full';
  state.sidebar = mode;
  document.body.classList.toggle('sidebar-rail', mode === 'rail');
  document.body.classList.toggle('sidebar-tucked', mode === 'tucked');
  localStorage.setItem('conductor.sidebar', mode);
  const col = $('#btn-side-collapse'), exp = $('#btn-side-expand'), tuck = $('#btn-side-tuck');
  if (col && exp && tuck) {
    col.hidden = mode !== 'full';
    exp.hidden = mode !== 'rail';
    tuck.hidden = mode === 'tucked';
  }
}

/* ------------------------------------------------------------ nav & shell */
const VIEW_RENDERERS = {
  dashboard: () => renderDashboard(),
  processes: () => renderProcesses(),
  automations: () => renderAutomations(),
  ai: () => renderAi(),
  sops: () => renderSops(),
  bernie: () => renderBernie(),
  asanarules: () => (window.ConductorAsanaRules ? window.ConductorAsanaRules.render() : renderModuleStub('asanarules')),
  integrations: () => renderIntegrations(),
  asana: () => renderAsana(),
  events: () => renderEvents(),
  requests: () => renderRequests(),
  checks: () => renderChecks(),
  products: () => renderProducts(),
  catalog: () => renderCatalog(),
  agents: () => renderAgents(),
  tasks: () => renderTasksView(),
  regs: () => renderRegs(),
  ingest: () => renderIngest(),
  variation: () => renderVariation(),
  reports: () => renderReports(),
  guidelines: () => renderGuidelines(),
  workflows: () => renderWorkflows(),
  data: () => renderData(),
  datawrangler: () => window.ConductorWrangler.render(),
  kpi: () => window.ConductorKpiStudio.render(),
  import: () => window.ConductorBulkImport.render(),
  sources: () => window.ConductorLocalSources.render(),
  insights: () => window.ConductorInsights.render(),
  flatfile: () => renderFlatFile(),
  svl: () => renderSvl(),
  brandcompare: () => renderBrandCompare(),
  keepa: () => renderKeepa(),
  developer: () => renderDeveloper(),
  content: () => renderModuleStub('content'),
  case: () => renderModuleStub('case'),
  fba: () => renderModuleStub('fba'),
  customerservice: () => renderModuleStub('customerservice'),
  brands: () => renderModuleStub('brands'),
  people: () => window.ConductorPeople.render(),
  listings: () => renderListings(),
  walmart: () => renderModuleStub('walmart'),
  tiktok: () => renderModuleStub('tiktok'),
  target: () => renderModuleStub('target'),
  spp: () => renderModuleStub('spp'),
  coastal: () => renderModuleStub('coastal'),
  agency: () => renderModuleStub('agency'),
  agentbuilder: () => renderModuleStub('agentbuilder'),
  runbooks: () => renderModuleStub('runbooks'),
  policies: () => renderModuleStub('policies'),
  features: () => renderFeatureStudio(),
  amazon: () => renderAmazon(),
};

function renderView(name) {
  const fn = VIEW_RENDERERS[name];
  if (fn) fn();
  else renderDashboard();
}

function showView(name) {
  state.view = name;
  window.__sidebarActiveView = name;
  // Split-pane workspace (LAW port): when split mode is active, navigation
  // renders into the right pane instead of taking over the window.
  if (window.ConductorSplit && window.ConductorSplit.isActive() && name !== 'bernie' && name !== 'chat') {
    window.ConductorSplit.handleNav(name);
    document.body.classList.toggle('bernie-fullscreen', false);
    $$('.sidebar-item[data-view]').forEach((b) => b.classList.toggle('active', b.dataset.view === name));
    return;
  }
  document.body.classList.toggle('bernie-fullscreen', name === 'bernie' || name === 'asanarules');
  $$('.sidebar-item[data-view]').forEach((b) => b.classList.toggle('active', b.dataset.view === name));
  const isChat = name === 'chat';
  $('#thread-scroll').hidden = isChat ? false : true;
  $('#view-root').hidden = isChat;
  $('#composer-shell').hidden = !isChat;
  if (!isChat) renderView(name);
  else {
    $('#composer-input').focus();
  }
}

function wireShell() {
  // Sidebar nav is rendered dynamically (see sidebar.js) — use event delegation
  // so re-renders from the Navigation settings tab keep working.
  $('#sidebar-scroll').addEventListener('click', (e) => {
    const btn = e.target.closest('.sidebar-item[data-view]');
    if (!btn) return;
    const view = btn.dataset.view;
    if (view === 'settings') { openSettings(); return; }
    if (view.startsWith('url:')) window.open(view.slice(4), '_blank', 'noopener');
    else showView(view);
  });
  $('#btn-home').addEventListener('click', () => showView('chat'));
  $('#btn-home-tb').addEventListener('click', () => showView('chat'));
  $('#btn-dash').addEventListener('click', () => showView('dashboard'));
  $('#btn-plug').addEventListener('click', () => showView('integrations'));
  $('#btn-settings').addEventListener('click', openSettings);
  $('#btn-reports').addEventListener('click', () => showView('reports'));
  $('#btn-guidelines').addEventListener('click', () => showView('guidelines'));
  $('#btn-settings-close').addEventListener('click', () => { $('#settings-backdrop').hidden = true; });
  $('#btn-modal-close').addEventListener('click', closeModal);
  $('#modal-backdrop').addEventListener('click', (e) => { if (e.target === $('#modal-backdrop')) closeModal(); });
  $('#settings-backdrop').addEventListener('click', (e) => { if (e.target === $('#settings-backdrop')) $('#settings-backdrop').hidden = true; });

  // floating nav collapse controls: full → rail → tucked → (edge tab) → full
  $('#btn-side-collapse').addEventListener('click', () => setSidebarState('rail'));
  $('#btn-side-expand').addEventListener('click', () => setSidebarState('full'));
  $('#btn-side-tuck').addEventListener('click', () => setSidebarState('tucked'));
  $('#side-tab').addEventListener('click', () => setSidebarState('full'));

  // desktop bridge (no-op in a plain browser)
  const d = window.desktop;
  if (d) {
    $('#btn-min').addEventListener('click', () => d.minimize());
    $('#btn-max').addEventListener('click', () => d.toggleMaximize());
    $('#btn-close').addEventListener('click', () => d.close());
  } else {
    ['btn-min', 'btn-max', 'btn-close'].forEach((id) => $(`#${id}`).addEventListener('click', () => toast('Window controls are desktop-only', 'warn')));
  }

  $('#sidebar-search-input').addEventListener('input', (e) => {
    const q = e.target.value.trim().toLowerCase();
    $$('.sidebar-item[data-view]').forEach((b) => {
      const label = b.textContent.toLowerCase();
      b.style.display = !q || label.includes(q) ? '' : 'none';
    });
  });
  $('#sidebar-search-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const q = e.target.value.trim();
      if (q) { state.sopSearch = q; showView('sops'); }
    }
  });

  // settings tabs
  $$('#settings-nav .settings-nav-item').forEach((b) => b.addEventListener('click', () => {
    $$('#settings-nav .settings-nav-item').forEach((x) => x.classList.remove('active'));
    b.classList.add('active');
    renderSettingsTab(b.dataset.stab);
  }));

  // right pane tabs
  $$('#pane-tabs .pane-tab').forEach((b) => b.addEventListener('click', () => {
    $$('#pane-tabs .pane-tab').forEach((x) => x.classList.remove('active'));
    b.classList.add('active');
    $$('.pane-tab-body').forEach((x) => x.classList.remove('active'));
    $(`#pane-${b.dataset.pane}`).classList.add('active');
    if (b.dataset.pane === 'activity') loadActivity();
    if (b.dataset.pane === 'models') loadModels();
  }));
  $('#btn-models-refresh').addEventListener('click', loadModels);
  $('#btn-pane-close').addEventListener('click', () => {
    const rp = $('#right-pane');
    rp.style.display = rp.style.display === 'none' ? '' : 'none';
  });
  $('#btn-activity-refresh').addEventListener('click', loadActivity);

  // composer
  $('#btn-send').addEventListener('click', handleComposerSubmit);
  $('#composer-input').addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') handleComposerSubmit();
  });
  // Chatbox is pinned to a single row — no auto-grow (see styles.css).
  $('#btn-attach').addEventListener('click', () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.csv,.tsv,.json,.ndjson,.jsonl,.xlsx,.xlsm,.xls';
    input.onchange = () => { if (input.files[0]) ingestFile(input.files[0]); };
    input.click();
  });
  window.addEventListener('dragover', (e) => { e.preventDefault(); document.body.classList.add('dragging'); });
  window.addEventListener('dragleave', (e) => { if (e.target === document.body) document.body.classList.remove('dragging'); });
  window.addEventListener('drop', (e) => {
    e.preventDefault();
    document.body.classList.remove('dragging');
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) ingestFile(file);
  });

  // folders — wired by the ported parker tree code (see end of file)
}

/* ---------------------------------------------------------------- modal */
function openModal(title, bodyHTML, footerHTML) {
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = bodyHTML;
  $('#modal-footer').innerHTML = footerHTML || '';
  $('#modal-backdrop').hidden = false;
}
function closeModal() {
  $('#modal-backdrop').hidden = true;
  $('#modal-body').innerHTML = '';
  $('#modal-footer').innerHTML = '';
}

/* ----------------------------------------------------------------- chat */
function addMsg(kind, name, textHTML) {
  const wrap = el('div', `msg msg-${kind}`);
  const sc = $('#thread-scroll');
  if (kind === 'agent') {
    const head = el('div', 'msg-header');
    head.appendChild(el('div', 'msg-avatar', 'C'));
    head.appendChild(el('div', 'msg-name', name));
    head.appendChild(el('div', 'msg-time', new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })));
    wrap.appendChild(head);
    const body = el('div', 'msg-body');
    body.innerHTML = textHTML;
    wrap.appendChild(body);
    sc.appendChild(wrap);
    sc.scrollTop = sc.scrollHeight;
    return body;
  }
  const bubble = el('div', 'bubble');
  bubble.innerHTML = textHTML;
  wrap.appendChild(bubble);
  sc.appendChild(wrap);
  sc.scrollTop = sc.scrollHeight;
  return bubble;
}

function welcome() { /* chat starts clean — no preset message (todo: "load into a new chat page, no preset text") */ }

/* Resolve a provider key for this request: decrypt via the Electron keychain
 * (safeStorage) when the desktop bridge is present, else let the backend fall
 * back to its stored plaintext / env var. The backend never sees plaintext
 * keys at rest. */
async function resolveChatKey(provider) {
  try {
    if (window.desktop && window.desktop.keys && await window.desktop.keys.has(provider)) {
      return await window.desktop.keys.get(provider);
    }
  } catch { /* fall through to backend fallback */ }
  return null;
}

/* Render accumulated chat text, extracting ⧙THINK⧚…⧙/THINK⧚ spans into a
 * collapsible reasoning block (LAW's deepseek-reasoner thinking port). */
function renderChatAcc(acc) {
  if (!acc.includes('⧙THINK⧚')) return md(acc);
  const parts = acc.split('⧙THINK⧚');
  let html = md(parts[0]);
  for (let i = 1; i < parts.length; i++) {
    const seg = parts[i];
    const idx = seg.indexOf('⧙/THINK⧚');
    if (idx === -1) {
      html += `<details class="think-block" open><summary>Thinking…</summary><div class="think-body">${esc(seg)}</div></details>`;
    } else {
      html += `<details class="think-block"><summary>Thought process</summary><div class="think-body">${esc(seg.slice(0, idx))}</div></details>`;
      html += md(seg.slice(idx + 9));
    }
  }
  return html;
}

async function sendChat() {
  const input = $('#composer-input');
  const message = input.value.trim();
  if (!message) return;
  input.value = '';
  input.style.height = 'auto';
  state.chatHistory.push({ role: 'user', content: message });
  addMsg('user', 'You', `<p class="md-p">${esc(message)}</p>`);
  const bubble = addMsg('agent', 'Conductor', '<span class="thinking"><span></span><span></span><span></span></span>');

  const provider = ($('#composer-provider') && $('#composer-provider').value) || state.chatProvider || 'deepseek';
  const model = ($('#composer-model') && $('#composer-model').value) || '';
  const apiKey = await resolveChatKey(provider);

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message, history: state.chatHistory.slice(-12, -1), provider, model,
        api_key: apiKey || undefined,
        skills: (state.chatSkills || []).map((s) => s.name),
        docs: (state.chatDocs || []).map((d) => d.ref_id),
      }),
    });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* */ }
      bubble.innerHTML = `<p class="md-p">⚠ ${esc(detail)}</p>`;
      return;
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let acc = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      acc += dec.decode(value, { stream: true });
      bubble.innerHTML = renderChatAcc(acc);
      const sc = $('#thread-scroll');
      sc.scrollTop = sc.scrollHeight;
    }
    state.chatHistory.push({ role: 'assistant', content: acc.replace(/\n\n_\([\d.]+s.*?_\)$/, '').trim() });
  } catch (e) {
    bubble.innerHTML = `<p class="md-p">⚠ ${esc(e.message)}</p>`;
  }
}

/* ------------------------------------------- chat context: skills + docs */
async function initChatContext() {
  if (!state.chatSkills) state.chatSkills = [];   // {name, desc}
  if (!state.chatDocs) state.chatDocs = [];       // {ref_id, filename}
  // Skills come from the Tool Hub card registry (workspace tools) + commerce built-ins.
  let cards = [];
  try { cards = (await api('/api/hub/cards')).cards || []; } catch { /* */ }
  const seen = new Set();
  state.allSkills = [];
  for (const c of cards) {
    const name = String(c.name || '').trim();
    if (!name || seen.has(name.toLowerCase())) continue;
    seen.add(name.toLowerCase());
    state.allSkills.push({ name, desc: c.desc || '', cat: c.cat || '' });
  }
  const builtins = [
    { name: 'Compliance check', desc: 'Evaluate a product against CE/FCC/RoHS/REACH/GPSR/Prop 65 rules from its attributes.', cat: 'commerce' },
    { name: 'Amazon flat file', desc: 'Read/write Amazon category/listing template fields; flag invalid values and recommend column fixes.', cat: 'commerce' },
    { name: 'Inventory analysis', desc: 'Cross-check product stock vs sales signals and flag discrepancies or reorder risks.', cat: 'commerce' },
  ];
  for (const b of builtins) {
    if (!seen.has(b.name.toLowerCase())) { seen.add(b.name.toLowerCase()); state.allSkills.push(b); }
  }
  renderSkillsPopover();
  const btn = $('#btn-skills');
  if (btn) btn.addEventListener('click', (e) => { e.stopPropagation(); toggleSkillsPopover(); });
  const docBtn = $('#btn-doc');
  if (docBtn) docBtn.addEventListener('click', pickChatDoc);
  renderChatChips();
}

function toggleSkillsPopover() {
  const pop = $('#skills-popover');
  const btn = $('#btn-skills');
  if (!pop || !btn) return;
  const open = pop.hidden;
  pop.hidden = !open;
  btn.setAttribute('aria-expanded', String(open));
}

function renderSkillsPopover() {
  const pop = $('#skills-popover');
  if (!pop) return;
  const on = new Set((state.chatSkills || []).map((s) => s.name));
  pop.innerHTML = `
    <div class="skills-popover-title">Workspace skills</div>
    ${state.allSkills && state.allSkills.length ? state.allSkills.map((s) => `
      <button class="skill-row ${on.has(s.name) ? 'on' : ''}" data-skill="${esc(s.name)}">
        <span class="skill-check">${on.has(s.name) ? '✓' : ''}</span>
        <span class="skill-body"><span class="skill-name">${esc(s.name)}</span><span class="skill-desc">${esc(s.desc)}</span></span>
      </button>`).join('') : '<div class="skills-empty">No skills loaded — add tools in the Tool Hub.</div>'}
    <div class="skills-hint">Toggled skills are injected into the model context for this conversation.</div>`;
  pop.querySelectorAll('.skill-row').forEach((row) => {
    row.addEventListener('click', () => {
      const name = row.dataset.skill;
      const idx = (state.chatSkills || []).findIndex((s) => s.name === name);
      if (idx >= 0) state.chatSkills.splice(idx, 1);
      else {
        const full = (state.allSkills || []).find((s) => s.name === name);
        if (full) state.chatSkills.push({ ...full });
      }
      renderSkillsPopover();
      renderChatChips();
    });
  });
}

function pickChatDoc() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.txt,.md,.csv,.tsv,.json,.ndjson,.jsonl,.log';
  input.onchange = async () => {
    const f = input.files && input.files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append('file', f);
    try {
      const res = await fetch('/api/chat/docs', { method: 'POST', body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { toast(`Doc upload failed: ${data.detail || res.statusText}`, 'err'); return; }
      state.chatDocs.push({ ref_id: data.ref_id, filename: data.filename });
      renderChatChips();
      toast(`Referenced ${data.filename} (${data.chars} chars)`, 'ok');
    } catch (e) { toast(`Doc upload failed: ${e.message}`, 'err'); }
  };
  input.click();
}

function renderChatChips() {
  const row = $('#chat-context');
  if (!row) return;
  const skills = state.chatSkills || [];
  const docs = state.chatDocs || [];
  row.hidden = skills.length === 0 && docs.length === 0;
  row.innerHTML = [
    ...skills.map((s) => `<span class="ctx-chip ctx-skill" data-kind="skill" data-name="${esc(s.name)}"><span class="ctx-ic codicon codicon-zap"></span>${esc(s.name)} <button class="ctx-x" aria-label="Remove skill">&times;</button></span>`),
    ...docs.map((d) => `<span class="ctx-chip ctx-doc" data-kind="doc" data-name="${esc(d.ref_id)}"><span class="ctx-ic codicon codicon-file-text"></span>${esc(d.filename)} <button class="ctx-x" aria-label="Remove document">&times;</button></span>`),
  ].join('');
  row.querySelectorAll('.ctx-chip').forEach((chip) => {
    const x = chip.querySelector('.ctx-x');
    if (!x) return;
    x.addEventListener('click', () => {
      if (chip.dataset.kind === 'skill') {
        state.chatSkills = state.chatSkills.filter((s) => s.name !== chip.dataset.name);
        renderSkillsPopover();
      } else {
        state.chatDocs = state.chatDocs.filter((d) => d.ref_id !== chip.dataset.name);
      }
      renderChatChips();
    });
  });
}

document.addEventListener('click', (e) => {
  const pop = $('#skills-popover');
  if (pop && !pop.hidden && !pop.contains(e.target) && e.target.id !== 'btn-skills' && !(e.target.closest && e.target.closest('#btn-skills'))) {
    pop.hidden = true;
    const b = $('#btn-skills');
    if (b) b.setAttribute('aria-expanded', 'false');
  }
});

/* -------------------------------------------------------------- dashboard */
/* Catalog Ingest view (ported from parker's Catalog Management view):
 * files table + jobs table, fed by the chunked/resumable upload pipeline. */
async function renderIngest() {
  const root = $('#view-root');
  let files = [], jobs = [];
  try { files = await api('/api/files'); } catch { /* */ }
  try { jobs = await api('/api/jobs'); } catch { /* */ }
  const doneFiles = files.filter((f) => f.status === 'done');
  const fileRows = files.length ? files.map((f) => `
      <tr>
        <td class="mono">${esc(f.filename)}</td>
        <td class="mono">${fmtBytes(f.total_size || 0)}</td>
        <td><span class="reg-status st-${esc(f.status === 'done' ? 'pass' : f.status === 'error' ? 'fail' : 'review')}">${esc(f.status)}</span></td>
        <td class="mono">${f.record_count ?? '—'}</td>
        <td>${fmtTime(f.created_at)}</td>
        <td>${f.status === 'done'
          ? `<button class="btn-mini" data-ai="${esc(f.upload_id)}" title="AI pass: categorize, clean, extract, flag, recommend"><span class="codicon codicon-sparkle"></span> AI</button>`
          : '<span style="color:var(--muted-fg);font-size:0.6875rem">—</span>'}</td>
      </tr>`).join('')
    : `<tr><td colspan="6" style="text-align:center;color:var(--muted-fg)">No files ingested yet — drop a CSV/JSON/NDJSON/XLSX catalog onto the composer, or POST to <code>/webhooks/ingest</code>.</td></tr>`;
  const jobRows = jobs.length ? jobs.slice(0, 30).map((j) => `
      <tr>
        <td class="mono">${esc(j.id)}</td>
        <td class="mono">${esc(j.kind)}</td>
        <td><span class="reg-status st-${esc(j.status === 'done' ? 'pass' : j.status === 'error' ? 'fail' : 'review')}">${esc(j.status)}</span></td>
        <td class="mono">${j.progress ?? 0}%</td>
        <td style="font-size:0.6875rem">${esc(j.message)}</td>
      </tr>`).join('')
    : `<tr><td colspan="5" style="text-align:center;color:var(--muted-fg)">No parse jobs yet.</td></tr>`;
  // AI findings for the most recent done file
  let aiBlock = '';
  if (doneFiles.length) {
    const latest = doneFiles[0];
    let ai = { count: 0, findings: [] };
    try { ai = await api(`/api/ingest/${latest.upload_id}/ai`); } catch { /* */ }
    const rows = ai.findings.length ? ai.findings.map((fn) => `
        <tr>
          <td class="mono">${esc(fn.sku || fn.product_id)}</td>
          <td><span class="chip-kind k-${esc(fn.kind)}">${esc(fn.kind)}</span> <span style="font-weight:650">${esc(fn.title)}</span></td>
          <td style="font-size:0.75rem">${esc(fn.detail)}</td>
        </tr>`).join('')
      : `<tr><td colspan="3" style="text-align:center;color:var(--muted-fg)">No AI findings yet — run the AI pass on a parsed file.</td></tr>`;
    aiBlock = `
      <div class="view-sub" style="margin:1rem 0 0.5rem">AI findings — ${esc(latest.filename)} (${ai.count})</div>
      <table class="data-table"><thead><tr><th>SKU</th><th>Kind / Title</th><th>Detail</th></tr></thead><tbody>${rows}</tbody></table>`;
  }
  root.innerHTML = `
    <div class="view">
      <div class="view-header">
        <div>
          <div class="view-title">Catalog Ingest</div>
          <div class="view-sub">Chunked, resumable uploads for large catalogs (CSV/TSV/JSON/NDJSON/XLSX) → parse → AI enrich (categorize, clean, extract, compliance &amp; inventory flags, recommendations).</div>
        </div>
        <div class="view-actions">
          <button class="btn-primary" id="ingest-upload"><span class="codicon codicon-cloud-upload"></span> Upload catalog</button>
        </div>
      </div>
      <div class="view-sub" style="margin:0 0 0.5rem">Files</div>
      <table class="data-table"><thead><tr><th>File</th><th>Size</th><th>Status</th><th>Records</th><th>Uploaded</th><th>AI</th></tr></thead><tbody>${fileRows}</tbody></table>
      <div class="view-sub" style="margin:1rem 0 0.5rem">Jobs</div>
      <table class="data-table"><thead><tr><th>#</th><th>Kind</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>${jobRows}</tbody></table>
      ${aiBlock}
    </div>`;
  const btn = root.querySelector('#ingest-upload');
  if (btn) btn.addEventListener('click', () => { const b = $('#btn-attach'); if (b) b.click(); });
  root.querySelectorAll('[data-ai]').forEach((b) => {
    b.addEventListener('click', async () => {
      const uploadId = b.dataset.ai;
      b.disabled = true; b.textContent = '…';
      try {
        const res = await api(`/api/ingest/${uploadId}/ai-process`, { method: 'POST' });
        toast(`AI pass started (job ${res.job_id})`, 'ok');
        setTimeout(() => renderIngest(), 2500);
      } catch (e) {
        toast(`AI pass failed: ${e.message}`, 'err');
        b.disabled = false; b.textContent = 'AI';
      }
    });
  });
}

async function renderDashboard() {
  const root = $('#view-root');
  let st = {};
  try { st = await api('/api/automation/stats'); } catch (e) { /* */ }
  state.stats = st;
  const prov = st.provider || {};
  const providerPill = prov.configured
    ? `<span class="home-status-pill" style="background:var(--t-function-success)">${esc(prov.provider)} · ${esc(prov.model || '—')}</span>`
    : `<span class="home-status-pill" style="background:var(--t-function-warning)">no AI provider — configure in Settings</span>`;

  root.innerHTML = `
    <div class="view">
      <div class="view-header">
        <div><div class="view-title">Dashboard</div>
        <div class="view-sub">The automation layer for 80+ brands, without linear headcount growth.</div></div>
        <div class="view-actions">${providerPill}</div>
      </div>

      <div class="home-cards">
        <div class="home-card"><div class="home-card-ic codicon codicon-lightbulb"></div><div class="home-card-label">Processes logged</div><div class="home-card-val">${fmtNum((st.processes || {}).total)}</div></div>
        <div class="home-card"><div class="home-card-ic codicon codicon-zap"></div><div class="home-card-label">Automations (enabled)</div><div class="home-card-val">${fmtNum((st.automations || {}).enabled)}</div></div>
        <div class="home-card"><div class="home-card-ic codicon codicon-chat-sparkle"></div><div class="home-card-label">AI runs</div><div class="home-card-val">${fmtNum((st.ai || {}).runs)}</div></div>
        <div class="home-card"><div class="home-card-ic codicon codicon-book"></div><div class="home-card-label">SOPs & runbooks</div><div class="home-card-val">${fmtNum(st.sops)}</div></div>
        <div class="home-card"><div class="home-card-ic codicon codicon-clock"></div><div class="home-card-label">Hours saved / year</div><div class="home-card-val">${fmtNum(st.hours_saved_year)}</div></div>
        <div class="home-card"><div class="home-card-ic codicon codicon-credit-card"></div><div class="home-card-label">Run-rate savings / year</div><div class="home-card-val">${fmtMoney(st.savings_year)}</div></div>
        <div class="home-card"><div class="home-card-ic codicon codicon-run-all"></div><div class="home-card-label">Automation runs</div><div class="home-card-val">${fmtNum((st.automations || {}).runs)}</div></div>
        <div class="home-card"><div class="home-card-ic codicon codicon-radio-tower"></div><div class="home-card-label">Inbound events</div><div class="home-card-val">${fmtNum(st.events)}</div></div>
      </div>

      <div class="home-quick">
        <button class="home-quick-btn" data-go="processes"><span class="codicon codicon-add"></span> Log a process</button>
        <button class="home-quick-btn" data-go="automations"><span class="codicon codicon-zap"></span> New automation</button>
        <button class="home-quick-btn" data-go="ai"><span class="codicon codicon-chat-sparkle"></span> Run an AI workflow</button>
        <button class="home-quick-btn" data-go="sops"><span class="codicon codicon-book"></span> Write an SOP</button>
      </div>

      <div class="dash-cols">
        <div class="dash-col">
          <div class="view-title">Recent AI runs</div>
          <div class="data-table-wrap">
            ${(st.recent_ai || []).length ? `<table class="data-table">
              <tr><th>Workflow</th><th>Provider</th><th>Status</th><th>When</th></tr>
              ${st.recent_ai.map((r) => `<tr>
                <td>${esc(r.workflow)}</td><td class="mono">${esc(r.provider)}${r.model ? ' · ' + esc(r.model) : ''}</td>
                <td>${r.status === 'done' ? '✓' : '⚠'}</td><td>${esc(timeAgo(r.created_at))}</td></tr>`).join('')}
            </table>` : '<div class="empty-state">No AI runs yet.</div>'}
          </div>
        </div>
        <div class="dash-col">
          <div class="view-title">Recent events</div>
          <div class="data-table-wrap">
            ${(st.recent_events || []).length ? `<table class="data-table">
              <tr><th>Source</th><th>Type</th><th>When</th></tr>
              ${st.recent_events.map((r) => `<tr>
                <td>${esc(r.source)}</td><td class="mono">${esc(r.type || '—')}</td><td>${esc(timeAgo(r.created_at))}</td></tr>`).join('')}
            </table>` : '<div class="empty-state">No inbound events yet — POST JSON to /webhooks/automation/&lt;source&gt;.</div>'}
          </div>
        </div>
      </div>
    </div>`;

  root.querySelectorAll('.home-quick-btn').forEach((b) => b.addEventListener('click', () => {
    showView(b.dataset.go);
    if (b.dataset.go === 'processes') openProcessModal();
    if (b.dataset.go === 'automations') openAutomationModal();
    if (b.dataset.go === 'sops') openSopModal();
  }));
}

/* -------------------------------------------------------------- processes */
function processModalHTML(p = null) {
  const v = (k) => esc(p ? (p[k] ?? '') : '');
  return `
    <div class="form-grid">
      <label class="field"><span>Workflow name *</span><input id="f-p-name" value="${v('name')}" placeholder="e.g. Weekly PO reconciliation" /></label>
      <div class="field-row">
        <label class="field"><span>Department</span><input id="f-p-dept" value="${v('department')}" placeholder="Supply Chain, Catalog, Finance…" /></label>
        <label class="field"><span>Owner</span><input id="f-p-owner" value="${v('owner')}" placeholder="who runs it today" /></label>
      </div>
      <label class="field"><span>Trigger</span><input id="f-p-trigger" value="${v('trigger_desc')}" placeholder="what kicks this process off" /></label>
      <label class="field"><span>Current process (the status quo)</span><textarea id="f-p-current" rows="3" placeholder="Describe the manual workflow today…">${v('current_process')}</textarea></label>
      <div class="field-row">
        <label class="field"><span>Manual hours / week</span><input id="f-p-hours" type="number" min="0" step="0.5" value="${p ? (p.manual_hours_week ?? 0) : ''}" placeholder="0" /></label>
        <label class="field"><span>Error rate %</span><input id="f-p-err" type="number" min="0" max="100" step="1" value="${p ? (p.error_rate ?? 0) : ''}" placeholder="0" /></label>
        <label class="field"><span>Delay hours / week</span><input id="f-p-delay" type="number" min="0" step="0.5" value="${p ? (p.delay_hours ?? 0) : ''}" placeholder="0" /></label>
      </div>
      <label class="field"><span>Pain points</span><textarea id="f-p-pain" rows="2" placeholder="errors, missed handoffs, double-entry…">${v('pain_points')}</textarea></label>
      <div class="settings-note">Conductor computes annual cost (at $45/hr), an automation score, and a redesign-vs-automate recommendation from these numbers.</div>
    </div>`;
}

function openProcessModal(p = null) {
  openModal(p ? 'Edit process' : 'Log a process', processModalHTML(p),
    `<button class="btn-primary" id="btn-save-process">${p ? 'Save changes' : 'Add to discovery board'}</button>`);
  $('#btn-save-process').addEventListener('click', async () => {
    const body = {
      name: $('#f-p-name').value,
      department: $('#f-p-dept').value,
      owner: $('#f-p-owner').value,
      trigger_desc: $('#f-p-trigger').value,
      current_process: $('#f-p-current').value,
      manual_hours_week: Number($('#f-p-hours').value || 0),
      error_rate: Number($('#f-p-err').value || 0),
      delay_hours: Number($('#f-p-delay').value || 0),
      pain_points: $('#f-p-pain').value,
    };
    if (!body.name) return toast('Workflow name is required', 'warn');
    try {
      const saved = p ? await api(`/api/processes/${p.id}`, { method: 'PATCH', body }) : await api('/api/processes', { method: 'POST', body });
      closeModal();
      toast(`"${saved.name}" → score ${saved.automation_score}/100. ${saved.recommendation}`, 'ok');
      await refreshCounts();
      await renderProcesses();
    } catch (e) { toast(e.message, 'err'); }
  });
}

function renderProcessDetail(p) {
  const root = $('#view-root');
  const statuses = ['discovered', 'scoping', 'building', 'shipped', 'adopted'];
  root.innerHTML = `
    <div class="view">
      <div class="view-header">
        <div><div class="view-title">${esc(p.name)}</div>
        <div class="view-sub">${esc(p.department || '—')} · owned by ${esc(p.owner || 'unassigned')} · logged ${esc(timeAgo(p.created_at))}</div></div>
        <div class="view-actions"><button class="btn-secondary" id="btn-back-procs">← Back</button></div>
      </div>
      <div class="home-cards">
        <div class="home-card"><div class="home-card-label">Automation score</div><div class="home-card-val">${p.automation_score}/100</div></div>
        <div class="home-card"><div class="home-card-label">Annual cost of status quo</div><div class="home-card-val">${fmtMoney(p.annual_cost)}</div></div>
        <div class="home-card"><div class="home-card-label">Hours / week</div><div class="home-card-val">${p.manual_hours_week}</div></div>
        <div class="home-card"><div class="home-card-label">Error rate</div><div class="home-card-val">${p.error_rate}%</div></div>
      </div>
      <div class="card">
        <div class="view-title">Recommendation</div>
        <p class="md-p">${md(p.recommendation)}</p>
      </div>
      <div class="card">
        <div class="view-title">Status</div>
        <div class="seg">
          ${statuses.map((s) => `<button class="seg-btn ${p.status === s ? 'active' : ''}" data-status="${s}">${s}</button>`).join('')}
          <button class="seg-btn ${p.status === 'deferred' ? 'active' : ''}" data-status="deferred">deferred</button>
        </div>
        <div class="settings-note">Advancing to <b>shipped</b>/<b>adopted</b> starts counting its hours in the dashboard savings.</div>
      </div>
      <div class="card">
        <div class="view-title">Details</div>
        <div class="detail-grid">
          <div class="detail-field"><span>Trigger</span><div>${esc(p.trigger_desc || '—')}</div></div>
          <div class="detail-field"><span>Current process</span><div>${esc(p.current_process || '—')}</div></div>
          <div class="detail-field"><span>Delay hours / week</span><div>${p.delay_hours}</div></div>
          <div class="detail-field"><span>Pain points</span><div>${esc(p.pain_points || '—')}</div></div>
        </div>
        <div class="btn-row" style="margin-top:0.75rem">
          <button class="btn-secondary" id="btn-edit-proc">Edit</button>
          <button class="btn-secondary" id="btn-del-proc">Delete</button>
        </div>
      </div>
    </div>`;

  root.querySelector('#btn-back-procs').addEventListener('click', renderProcesses);
  root.querySelectorAll('.seg-btn[data-status]').forEach((b) => b.addEventListener('click', async () => {
    try {
      await api(`/api/processes/${p.id}`, { method: 'PATCH', body: { status: b.dataset.status } });
      toast(`Status → ${b.dataset.status}`, 'ok');
      p.status = b.dataset.status;
      renderProcessDetail(p);
      refreshCounts();
    } catch (e) { toast(e.message, 'err'); }
  }));
  root.querySelector('#btn-edit-proc').addEventListener('click', () => openProcessModal(p));
  root.querySelector('#btn-del-proc').addEventListener('click', async () => {
    if (!confirm(`Delete process "${p.name}"?`)) return;
    try { await api(`/api/processes/${p.id}`, { method: 'DELETE' }); toast('Deleted', 'ok'); renderProcesses(); refreshCounts(); }
    catch (e) { toast(e.message, 'err'); }
  });
}

async function renderProcesses() {
  const root = $('#view-root');
  root.innerHTML = `<div class="view"><div class="view-header"><div><div class="view-title">Process Discovery</div>
    <div class="view-sub">Quantify the cost of the status quo — hours lost, errors, delays — and decide: redesign first, or automate now.</div></div>
    <div class="view-actions"><button class="btn-primary" id="btn-new-proc"><span class="codicon codicon-add"></span> Log a process</button></div></div>
    <div id="proc-list" class="data-table-wrap"><div class="folder-loading">Loading…</div></div></div>`;
  root.querySelector('#btn-new-proc').addEventListener('click', () => openProcessModal());

  let procs = [];
  try { procs = await api('/api/processes'); } catch (e) { toast(e.message, 'err'); }
  state.processes = procs;
  const list = root.querySelector('#proc-list');
  if (!procs.length) {
    list.innerHTML = `<div class="empty-state">No processes logged yet — capture the first manual workflow that costs the team hours.</div>`;
    return;
  }
  list.innerHTML = `<table class="data-table">
    <tr><th>Workflow</th><th>Dept</th><th>Hrs/wk</th><th>Err%</th><th>Score</th><th>Annual $</th><th>Status</th><th>Recommendation</th></tr>
    ${procs.map((p) => `<tr class="row-click" data-id="${p.id}">
      <td><b>${esc(p.name)}</b></td><td>${esc(p.department || '—')}</td><td>${p.manual_hours_week}</td>
      <td>${p.error_rate}%</td><td><span class="score-chip">${p.automation_score}</span></td>
      <td>${fmtMoney(p.annual_cost)}</td><td><span class="pill-status pill-${esc(p.status)}">${esc(p.status)}</span></td>
      <td class="muted">${esc((p.recommendation || '').slice(0, 90))}${(p.recommendation || '').length > 90 ? '…' : ''}</td></tr>`).join('')}
  </table>`;
  list.querySelectorAll('.row-click').forEach((r) => r.addEventListener('click', () => {
    const p = procs.find((x) => x.id === Number(r.dataset.id));
    if (p) renderProcessDetail(p);
  }));
}

/* ------------------------------------------------------------ automations */
function actionSummary(a) {
  return (a.actions || []).map((x) => {
    const t = x.type;
    if (t === 'asana_create_task') return `📋 Asana task → ${esc(x.target || '?')}`;
    if (t === 'ai_run') return `✨ AI: ${esc((x.payload || {}).workflow || '?')}`;
    if (t === 'sheets_append') return '📊 Sheets append';
    if (t === 'gmail_send') return '📧 Gmail';
    if (t === 'hubspot_update') return '🔗 HubSpot';
    if (t === 'webhook_out') return '📡 Webhook out';
    return `• ${esc(t)}`;
  }).join('<br>');
}

function automationModalHTML(a = null) {
  const v = (k) => esc(a ? (a[k] ?? '') : '');
  const conds = a ? JSON.stringify(a.conditions || [], null, 2) : '[]';
  const acts = a ? JSON.stringify(a.actions || [], null, 2) : JSON.stringify([
    { type: 'asana_create_task', target: 'Catalog Ops', payload: { name: 'Catalog: {task_name} ready', notes: '…' } }
  ], null, 2);
  return `
    <div class="form-grid">
      <label class="field"><span>Name *</span><input id="f-a-name" value="${v('name')}" placeholder="Supply Chain → Catalog handoff" /></label>
      <label class="field"><span>Description</span><input id="f-a-desc" value="${v('description')}" placeholder="what this automation replaces" /></label>
      <div class="field-row">
        <label class="field"><span>Trigger source</span>
          <select id="f-a-source">
            ${['asana', 'webhook', 'sheets', 'forms', 'schedule', 'manual'].map((s) => `<option value="${s}" ${a && a.trigger_source === s ? 'selected' : ''}>${s}</option>`).join('')}
          </select></label>
        <label class="field"><span>Trigger event</span><input id="f-a-event" value="${v('trigger_event')}" placeholder="task_completed, feedback_received…" /></label>
      </div>
      <label class="field"><span>Conditions (JSON — [{field, op: eq|neq|contains|exists, value}])</span><textarea id="f-a-conds" rows="3" spellcheck="false">${conds}</textarea></label>
      <label class="field"><span>Actions (JSON — types: asana_create_task, sheets_append, gmail_send, hubspot_update, webhook_out, ai_run, log_event)</span><textarea id="f-a-acts" rows="8" spellcheck="false">${acts}</textarea></label>
      <div class="settings-note"><code>{field}</code> placeholders in action payloads are filled from the trigger event (e.g. <code>{task_name}</code>). Steps run <b>live</b> when credentials exist (Asana PAT), otherwise they're logged as <b>simulated</b>.</div>
    </div>`;
}

function openAutomationModal(a = null) {
  openModal(a ? 'Edit automation' : 'New automation', automationModalHTML(a),
    `<button class="btn-primary" id="btn-save-auto">${a ? 'Save' : 'Create'}</button>`);
  $('#btn-save-auto').addEventListener('click', async () => {
    let conds, acts;
    try {
      conds = JSON.parse($('#f-a-conds').value || '[]');
      acts = JSON.parse($('#f-a-acts').value || '[]');
      if (!Array.isArray(conds) || !Array.isArray(acts)) throw new Error('conditions and actions must be JSON arrays');
    } catch (err) { return toast('Invalid JSON: ' + err.message, 'err'); }
    const body = {
      name: $('#f-a-name').value,
      description: $('#f-a-desc').value,
      trigger_source: $('#f-a-source').value,
      trigger_event: $('#f-a-event').value,
      conditions: conds,
      actions: acts,
    };
    if (!body.name) return toast('Name is required', 'warn');
    try {
      await api(a ? `/api/automations/${a.id}` : '/api/automations', { method: a ? 'PATCH' : 'POST', body });
      closeModal();
      toast(a ? 'Automation saved' : 'Automation created', 'ok');
      await refreshCounts();
      await renderAutomations();
    } catch (e) { toast(e.message, 'err'); }
  });
}

async function runAutomationNow(a) {
  const root = $('#view-root');
  const runPanel = root.querySelector('#run-panel');
  if (runPanel) runPanel.innerHTML = '<div class="folder-loading">Running…</div>';
  else toast('Running…', 'info');
  try {
    let payload = null;
    try {
      const raw = (root.querySelector('#run-payload') || {}).value;
      if (raw && raw.trim()) payload = JSON.parse(raw);
    } catch { return toast('Sample payload is not valid JSON', 'err'); }
    const res = await api(`/api/automations/${a.id}/run`, { method: 'POST', body: payload ? { payload } : {} });
    const panel = root.querySelector('#run-panel');
    panel.innerHTML = `
      <div class="view-title">Run result — <span class="pill-run pill-run-${esc(res.status)}">${esc(res.status)}</span></div>
      <div class="settings-note">live ${res.live_steps} · simulated ${res.simulated_steps} · failed ${res.failed_steps}</div>
      <div class="run-steps">
        ${res.results.map((r) => `<div class="run-step">
          <span class="step-badge step-${r.ok ? 'ok' : 'fail'}">${r.ok ? '✓' : '✗'}</span>
          <span class="step-type">${esc(r.type)}</span>
          <span class="step-mode step-mode-${esc(r.executed)}">${esc(r.executed)}</span>
          <span class="step-detail">${esc(r.detail)}</span></div>`).join('')}
      </div>`;
    await refreshCounts();
  } catch (e) {
    const panel = root.querySelector('#run-panel');
    if (panel) panel.innerHTML = `<div class="settings-note">⚠ ${esc(e.message)}</div>`;
    toast(e.message, 'err');
  }
}

async function renderAutomations() {
  const root = $('#view-root');
  root.innerHTML = `<div class="view"><div class="view-header"><div><div class="view-title">Automations</div>
    <div class="view-sub">Trigger → condition → action chains. Handoffs between Asana, Google Workspace, HubSpot, Looker Studio, Zapier and Make.com.</div></div>
    <div class="view-actions"><button class="btn-primary" id="btn-new-auto"><span class="codicon codicon-add"></span> New automation</button></div></div>
    <div class="automation-grid" id="auto-grid"><div class="folder-loading">Loading…</div></div>
    <div class="card" id="run-panel" hidden></div></div>`;
  root.querySelector('#btn-new-auto').addEventListener('click', () => openAutomationModal());

  let autos = [];
  try { autos = await api('/api/automations'); } catch (e) { toast(e.message, 'err'); }
  state.automations = autos;
  const grid = root.querySelector('#auto-grid');
  if (!autos.length) {
    grid.innerHTML = `<div class="empty-state">No automations yet — create the first handoff.</div>`;
    return;
  }
  grid.innerHTML = autos.map((a) => `
    <div class="automation-card ${a.enabled ? '' : 'automation-off'}" data-id="${a.id}">
      <div class="automation-top">
        <span class="codicon codicon-zap"></span>
        <div class="automation-title">${esc(a.name)}</div>
        <label class="switch" title="Enabled">
          <input type="checkbox" data-id="${a.id}" ${a.enabled ? 'checked' : ''}>
          <span class="switch-slider"></span>
        </label>
      </div>
      <div class="automation-desc">${esc(a.description || '')}</div>
      <div class="automation-trigger"><span class="muted">trigger</span> ${esc(a.trigger_source)}${a.trigger_event ? ' · ' + esc(a.trigger_event) : ''}</div>
      <div class="automation-actions">${actionSummary(a)}</div>
      <div class="automation-foot">
        <span class="muted">${a.run_count || 0} runs · ${esc(timeAgo(a.last_run_at))}${a.last_status ? ` · <span class="pill-run pill-run-${esc(a.last_status)}">${esc(a.last_status)}</span>` : ''}</span>
        <div class="automation-btns">
          <button class="btn-secondary btn-sm btn-run" data-id="${a.id}" title="Run now with a sample payload"><span class="codicon codicon-play"></span> Run</button>
          <button class="btn-secondary btn-sm btn-edit" data-id="${a.id}"><span class="codicon codicon-edit"></span></button>
          <button class="btn-secondary btn-sm btn-del" data-id="${a.id}"><span class="codicon codicon-trash"></span></button>
        </div>
      </div>
      <div class="run-payload-row" data-id="${a.id}" hidden>
        <textarea class="run-payload" placeholder='Sample event payload JSON, e.g. {"task_name":"PO #123","project":"Supply Chain","task_url":"https://app.asana.com/…"}'></textarea>
      </div>
    </div>`).join('');

  grid.querySelectorAll('.switch input').forEach((c) => c.addEventListener('change', async (e) => {
    try {
      await api(`/api/automations/${e.target.dataset.id}`, { method: 'PATCH', body: { enabled: e.target.checked } });
      toast(e.target.checked ? 'Enabled' : 'Disabled', 'ok');
      refreshCounts();
    } catch (err) { toast(err.message, 'err'); e.target.checked = !e.target.checked; }
  }));
  grid.querySelectorAll('.btn-run').forEach((b) => b.addEventListener('click', (e) => {
    const card = e.target.closest('.automation-card');
    const row = card.querySelector('.run-payload-row');
    const wasHidden = row.hidden;
    grid.querySelectorAll('.run-payload-row').forEach((r) => { r.hidden = true; });
    row.hidden = !wasHidden;
    if (wasHidden) {
      row.querySelector('textarea').focus();
      root.querySelector('#run-panel').hidden = false;
      const a = autos.find((x) => x.id === Number(b.dataset.id));
      root.querySelector('#run-panel').scrollIntoView({ behavior: 'smooth' });
    }
  }));
  grid.querySelectorAll('.run-payload').forEach((t) => t.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      const a = autos.find((x) => x.id === Number(t.parentElement.dataset.id));
      if (a) runAutomationNow(a);
    }
  }));
  grid.querySelectorAll('.btn-edit').forEach((b) => b.addEventListener('click', () => {
    const a = autos.find((x) => x.id === Number(b.dataset.id));
    if (a) openAutomationModal(a);
  }));
  grid.querySelectorAll('.btn-del').forEach((b) => b.addEventListener('click', async () => {
    const a = autos.find((x) => x.id === Number(b.dataset.id));
    if (!a || !confirm(`Delete automation "${a.name}"?`)) return;
    try { await api(`/api/automations/${a.id}`, { method: 'DELETE' }); toast('Deleted', 'ok'); renderAutomations(); refreshCounts(); }
    catch (err) { toast(err.message, 'err'); }
  }));
  root.querySelector('#run-panel').addEventListener('click', (e) => {
    if (e.target.closest('#btn-run-go')) {
      const id = e.target.closest('#btn-run-go').dataset.id;
      const a = autos.find((x) => x.id === Number(id));
      if (a) runAutomationNow(a);
    }
  });
}

/* ------------------------------------------------------------ AI workflows */
async function renderAi() {
  const root = $('#view-root');
  root.innerHTML = `<div class="view"><div class="view-header"><div><div class="view-title">AI Workflows</div>
    <div class="view-sub">Production LLM workflows: feedback categorization, transcript analysis, document parsing — powered by your configured provider (DeepSeek API or local Llama).</div></div></div>
    <div class="gallery-grid" id="wf-grid"><div class="folder-loading">Loading…</div></div>
    <div class="card"><div class="view-title">Run history</div><div id="ai-history" class="data-table-wrap"></div></div></div>`;

  let wfs = [];
  try { wfs = await api('/api/ai/workflows'); } catch (e) { toast(e.message, 'err'); }
  state.aiWorkflows = wfs;
  root.querySelector('#wf-grid').innerHTML = wfs.map((w) => `
    <div class="gallery-card" data-wf="${esc(w.workflow)}">
      <div class="gallery-ic codicon codicon-chat-sparkle"></div>
      <div class="gallery-name">${esc(w.title)}</div>
      <div class="gallery-desc">${esc(w.desc)}</div>
      <button class="btn-primary btn-sm btn-wf-run" data-wf="${esc(w.workflow)}"><span class="codicon codicon-play"></span> Run</button>
    </div>`).join('');

  root.querySelectorAll('.btn-wf-run').forEach((b) => b.addEventListener('click', () => openAiModal(b.dataset.wf)));

  let runs = [];
  try { runs = await api('/api/ai/runs?limit=50'); } catch { /* */ }
  const hist = root.querySelector('#ai-history');
  hist.innerHTML = runs.length ? `<table class="data-table">
    <tr><th>Workflow</th><th>Provider</th><th>Status</th><th>Tokens</th><th>Duration</th><th>When</th><th></th></tr>
    ${runs.map((r) => `<tr>
      <td>${esc(r.workflow)}</td><td class="mono">${esc(r.provider)}${r.model ? ' · ' + esc(r.model) : ''}</td>
      <td>${r.status === 'done' ? '✓' : '⚠'}</td>
      <td>${fmtNum((r.tokens_in || 0) + (r.tokens_out || 0))}</td>
      <td>${Math.round(r.duration_ms / 100) / 10}s</td><td>${esc(timeAgo(r.created_at))}</td>
      <td><button class="btn-secondary btn-sm btn-ai-view" data-id="${r.id}">View</button></td></tr>`).join('')}
  </table>` : '<div class="empty-state">No AI runs yet.</div>';

  root.querySelectorAll('.btn-ai-view').forEach((b) => b.addEventListener('click', async () => {
    try {
      const all = await api('/api/ai/runs?limit=500');
      const r = all.find((x) => x.id === Number(b.dataset.id));
      if (r) openModal('AI run — ' + r.workflow,
        `<div class="settings-note">${esc(r.provider)} · ${esc(r.model || '')} · ${esc(timeAgo(r.created_at))} · ${fmtNum((r.tokens_in || 0) + (r.tokens_out || 0))} tokens</div>
         <div class="doc-body" style="margin-top:0.6rem">${md(r.output)}</div>
         <details class="field-advanced" style="margin-top:0.6rem"><summary>Input</summary><pre class="chat-code">${esc(r.input_preview)}</pre></details>`, '');
    } catch (e) { toast(e.message, 'err'); }
  }));
}

function openAiModal(wfId) {
  const wf = state.aiWorkflows.find((w) => w.workflow === wfId);
  if (!wf) return;
  openModal(wf.title, `
    <div class="settings-note">${esc(wf.desc)}</div>
    <label class="field" style="margin-top:0.6rem"><span>Input text</span>
      <textarea id="f-ai-input" rows="10" placeholder="Paste the feedback, transcript, document or email…"></textarea></label>
    <div id="f-ai-result"></div>`,
    `<button class="btn-primary" id="btn-ai-run"><span class="codicon codicon-play"></span> Run</button>`);
  $('#btn-ai-run').addEventListener('click', async () => {
    const input = $('#f-ai-input').value;
    if (!input.trim()) return toast('Paste some input first', 'warn');
    const resBox = $('#f-ai-result');
    resBox.innerHTML = '<div class="folder-loading">Running workflow…</div>';
    try {
      const res = await api('/api/ai/run', { method: 'POST', body: { workflow: wfId, input } });
      resBox.innerHTML = `
        <div class="settings-note" style="margin-top:0.6rem">${esc(res.provider)} · ${esc(res.model || '')} · ${Math.round(res.duration_ms / 100) / 10}s · ${fmtNum((res.tokens_in || 0) + (res.tokens_out || 0))} tokens ${res.status === 'error' ? '· ⚠ provider error — result may be partial' : ''}</div>
        <div class="doc-body" style="margin-top:0.6rem;max-height:40vh;overflow:auto">${md(res.output)}</div>`;
      await refreshCounts();
    } catch (e) {
      resBox.innerHTML = `<div class="settings-note" style="margin-top:0.6rem">⚠ ${esc(e.message)}</div>`;
    }
  });
}

/* -------------------------------------------------------------------- SOPs */
function sopModalHTML(s = null) {
  const v = (k) => esc(s ? (s[k] ?? '') : '');
  const cats = ['sop', 'runbook', 'training', 'governance'];
  return `
    <div class="form-grid">
      <label class="field"><span>Title *</span><input id="f-s-title" value="${v('title')}" placeholder="Client onboarding SOP" /></label>
      <label class="field"><span>Category</span>
        <select id="f-s-cat">${cats.map((c) => `<option value="${c}" ${s && s.category === c ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
      <label class="field"><span>Body (markdown)</span><textarea id="f-s-body" rows="16" spellcheck="false" placeholder="# Purpose&#10;…&#10;&#10;## Steps&#10;1. …">${v('body')}</textarea></label>
    </div>`;
}

function openSopModal(s = null) {
  openModal(s ? 'Edit SOP' : 'New SOP', sopModalHTML(s),
    `<button class="btn-primary" id="btn-save-sop">${s ? 'Save (new version)' : 'Create'}</button>`);
  $('#btn-save-sop').addEventListener('click', async () => {
    const body = { title: $('#f-s-title').value, category: $('#f-s-cat').value, body: $('#f-s-body').value };
    if (!body.title) return toast('Title is required', 'warn');
    try {
      await api(s ? `/api/sops/${s.id}` : '/api/sops', { method: s ? 'PATCH' : 'POST', body });
      closeModal();
      toast(s ? 'Saved — version bumped' : 'SOP created', 'ok');
      await renderSops();
      refreshCounts();
    } catch (e) { toast(e.message, 'err'); }
  });
}

function renderSopDoc(s) {
  const root = $('#view-root');
  root.innerHTML = `
    <div class="view">
      <div class="view-header">
        <div><div class="view-title">${esc(s.title)}</div>
        <div class="view-sub"><span class="pill-status">${esc(s.category)}</span> · v${s.version} · updated ${esc(timeAgo(s.updated_at))}</div></div>
        <div class="view-actions">
          <button class="btn-secondary" id="btn-back-sops">← Back</button>
          <button class="btn-secondary" id="btn-edit-sop"><span class="codicon codicon-edit"></span> Edit</button>
          <button class="btn-secondary" id="btn-del-sop"><span class="codicon codicon-trash"></span></button>
        </div>
      </div>
      <div class="card"><div class="doc-body">${md(s.body)}</div></div>
    </div>`;
  root.querySelector('#btn-back-sops').addEventListener('click', renderSops);
  root.querySelector('#btn-edit-sop').addEventListener('click', () => openSopModal(s));
  root.querySelector('#btn-del-sop').addEventListener('click', async () => {
    if (!confirm(`Delete "${s.title}"?`)) return;
    try { await api(`/api/sops/${s.id}`, { method: 'DELETE' }); toast('Deleted', 'ok'); renderSops(); refreshCounts(); }
    catch (e) { toast(e.message, 'err'); }
  });
}

async function renderSops() {
  const root = $('#view-root');
  const q = state.sopSearch || '';
  root.innerHTML = `<div class="view"><div class="view-header"><div><div class="view-title">SOPs & Runbooks</div>
    <div class="view-sub">Every workflow fully transparent, easily supportable, immediately transferable.</div></div>
    <div class="view-actions"><button class="btn-primary" id="btn-new-sop"><span class="codicon codicon-add"></span> New SOP</button></div></div>
    <div class="view-toolbar">
      <div class="pane-toolbar" style="flex:1"><span class="codicon codicon-search"></span><input id="sop-search" value="${esc(q)}" placeholder="Search SOPs…" /></div>
      <div class="seg" id="sop-cats">
        ${['all', 'sop', 'runbook', 'training', 'governance'].map((c) => `<button class="seg-btn ${state.sopCat === c ? 'active' : ''}" data-cat="${c}">${c}</button>`).join('')}
      </div>
    </div>
    <div id="sop-list" class="data-table-wrap"><div class="folder-loading">Loading…</div></div></div>`;
  root.querySelector('#btn-new-sop').addEventListener('click', () => openSopModal());
  root.querySelector('#sop-search').addEventListener('keydown', async (e) => {
    if (e.key === 'Enter') { state.sopSearch = e.target.value.trim(); await renderSops(); }
  });
  root.querySelectorAll('#sop-cats .seg-btn').forEach((b) => b.addEventListener('click', async () => {
    state.sopCat = b.dataset.cat;
    $$('#sop-cats .seg-btn').forEach((x) => x.classList.toggle('active', x === b));
    await renderSops();
  }));

  let sops = [];
  try {
    if (q) sops = await api('/api/sops/search?q=' + encodeURIComponent(q));
    else sops = await api('/api/sops' + (state.sopCat && state.sopCat !== 'all' ? '?category=' + state.sopCat : ''));
  } catch (e) { toast(e.message, 'err'); }
  state.sops = sops;
  const list = root.querySelector('#sop-list');
  if (!sops.length) {
    list.innerHTML = `<div class="empty-state">${q ? 'No SOPs match your search.' : 'No SOPs yet — write the first runbook.'}</div>`;
    return;
  }
  list.innerHTML = `<table class="data-table">
    <tr><th>Title</th><th>Category</th><th>Version</th><th>Updated</th><th></th></tr>
    ${sops.map((s) => `<tr class="row-click" data-id="${s.id}">
      <td><b>${esc(s.title)}</b></td><td><span class="pill-status">${esc(s.category)}</span></td>
      <td>v${s.version}</td><td>${esc(timeAgo(s.updated_at))}</td>
      <td><button class="btn-secondary btn-sm btn-sop-view" data-id="${s.id}">Open</button></td></tr>`).join('')}
  </table>`;
  list.querySelectorAll('.row-click, .btn-sop-view').forEach((r) => r.addEventListener('click', () => {
    const s = sops.find((x) => x.id === Number(r.dataset.id));
    if (s) renderSopDoc(s);
  }));
}

/* ------------------------------------------------------------ integrations */
async function renderIntegrations() {
  const root = $('#view-root');
  root.innerHTML = `<div class="view"><div class="view-header"><div><div class="view-title">Integrations</div>
    <div class="view-sub">Connectors that keep data in sync in real time across the stack. <b>Simulated</b> steps run when a connector has no live credentials.</div></div></div>
    <div class="automation-grid" id="int-grid"><div class="folder-loading">Loading…</div></div></div>`;

  let ints = [];
  try { ints = await api('/api/integrations'); } catch (e) { toast(e.message, 'err'); }
  state.integrations = ints;
  const grid = root.querySelector('#int-grid');
  grid.innerHTML = ints.map((it) => `
    <div class="automation-card" data-key="${esc(it.key)}">
      <div class="automation-top">
        <span class="codicon codicon-plug"></span>
        <div class="automation-title">${esc(it.name)}</div>
        <span class="pill-int pill-int-${esc(it.status)}">${esc(it.status)}</span>
      </div>
      <div class="automation-desc">${esc(it.desc)}</div>
      ${it.fields.length ? it.fields.map((f) => `
        <label class="field" style="margin-top:0.5rem"><span>${esc(f.label)}</span>
          <input class="int-field" data-key="${esc(f.key)}" type="${f.type === 'secret' ? 'password' : 'text'}"
            value="${esc(it.config[f.key] || '')}" placeholder="${esc(f.placeholder || '')}" autocomplete="off" /></label>`).join('') : ''}
      ${it.key === 'webhooks' ? `<div class="settings-note" style="margin-top:0.5rem">Endpoint: <code class="chat-code-inline">POST /webhooks/automation/{source}</code><br>e.g. <code class="chat-code-inline">POST /webhooks/automation/webhook</code> with <code class="chat-code-inline">{"event":"feedback_received","payload":{…}}</code></div>` : ''}
      <div class="automation-foot">
        <span class="muted int-result" data-key="${esc(it.key)}"></span>
        <div class="automation-btns">
          <button class="btn-secondary btn-sm btn-int-test" data-key="${esc(it.key)}">Test</button>
          <button class="btn-primary btn-sm btn-int-save" data-key="${esc(it.key)}">Save</button>
        </div>
      </div>
    </div>`).join('');

  grid.querySelectorAll('.btn-int-save').forEach((b) => b.addEventListener('click', async () => {
    const card = b.closest('.automation-card');
    const key = card.dataset.key;
    const it = ints.find((x) => x.key === key);
    const config = {};
    card.querySelectorAll('.int-field').forEach((f) => {
      const val = f.value.trim();
      // don't overwrite a masked secret with its mask
      if (val && !val.includes('••••')) config[f.dataset.key] = val;
    });
    try {
      const res = await api(`/api/integrations/${key}`, { method: 'POST', body: { config } });
      toast(`${it.name} → ${res.status}`, 'ok');
      await renderIntegrations();
      refreshCounts();
    } catch (e) { toast(e.message, 'err'); }
  }));
  grid.querySelectorAll('.btn-int-test').forEach((b) => b.addEventListener('click', async () => {
    const key = b.dataset.key;
    const note = grid.querySelector(`.int-result[data-key="${key}"]`);
    note.textContent = 'Testing…';
    try {
      const res = await api(`/api/integrations/${key}/test`, { method: 'POST' });
      note.textContent = (res.ok ? '✓ ' : '✗ ') + res.detail;
    } catch (e) { note.textContent = '✗ ' + e.message; }
  }));
}

/* ------------------------------------------------------------------- asana */
async function renderAsana() {
  const root = $('#view-root');
  root.innerHTML = `<div class="view">
    <div class="view-header">
      <div>
        <div class="view-title">Asana & Performance Hub</div>
        <div class="view-sub">AI-assisted performance evaluation, employee scorecards, and full workspace task sync.</div>
      </div>
      <div class="view-actions">
        <button class="btn-secondary" id="btn-asana-push-sb"><span class="codicon codicon-cloud-upload"></span> Push to Supabase</button>
        <button class="btn-primary" id="btn-asana-sync"><span class="codicon codicon-sync"></span> Sync now</button>
      </div>
    </div>

    <!-- View Mode Switcher -->
    <div style="display:flex; gap:10px; margin-bottom:16px; border-bottom:1px solid var(--t-edges-borderColor, #333); padding-bottom:10px;">
      <button class="btn-primary" id="btn-tab-team-kpis">📊 Team KPI Dashboard</button>
      <button class="btn-secondary" id="btn-tab-perf">⚠ Legacy Scorecards</button>
      <button class="btn-secondary" id="btn-tab-tasks">📋 Projects & Tasks</button>
    </div>

    <div id="asana-team-kpi-panel"><div id="asana-team-kpi-controls" class="field-row"></div><div id="asana-team-kpi-table" class="data-table-wrap"><div class="folder-loading">Loading team KPI facts…</div></div></div>

    <div id="asana-perf-panel" style="display:none">
      <!-- AI Assisted Performance Eval Card -->
      <div class="card" style="padding:14px; margin-bottom:16px; background:var(--t-surface-raised, #1e1e2e);">
        <div style="font-weight:600; margin-bottom:8px;">⚡ AI-Assisted Employee Performance Evaluator:</div>
        <div style="display:flex; gap:8px;">
          <input type="text" id="asana-perf-eval-input" class="input-text" style="flex:1;" placeholder="Prompt evaluation (e.g. 'Evaluate performance review for Gabe and Carlos')">
          <button class="btn-primary" id="btn-asana-perf-eval-run">Run AI Evaluation</button>
        </div>
        <div id="asana-perf-eval-out" style="margin-top:10px; display:none; background:var(--t-surface-base, #111); padding:10px; border-radius:6px; border:1px solid var(--t-edges-borderColor, #333);"></div>
      </div>

      <div class="home-cards" id="asana-perf-scorecards">
        <div class="folder-loading">Loading Performance Scorecards…</div>
      </div>
    </div>

    <div id="asana-tasks-panel" style="display:none;">
      <div class="home-cards" id="asana-cards"><div class="folder-loading">Loading…</div></div>
      <div class="dash-cols">
        <div class="dash-col"><div class="view-title">Projects</div><div class="data-table-wrap" id="asana-projects"></div></div>
        <div class="dash-col"><div class="view-title">Recent tasks</div><div class="data-table-wrap" id="asana-tasks"></div></div>
      </div>
    </div>
  </div>`;

  // Hook: Auto-pull on view load if data is stale
  try {
    const pullRes = await api('/api/asana/hook/pull', { method: 'POST' });
    if (pullRes && pullRes.triggered) {
      toast('Asana auto-pull triggered (stale data updated)', 'info');
    }
  } catch { /* ignored */ }

  // View tabs: team KPIs are the authoritative app report; owner scorecards are legacy workbook context.
  const setAsanaTab = (tab) => {
    root.querySelector('#asana-team-kpi-panel').style.display = tab === 'team' ? 'block' : 'none';
    root.querySelector('#asana-perf-panel').style.display = tab === 'perf' ? 'block' : 'none';
    root.querySelector('#asana-tasks-panel').style.display = tab === 'tasks' ? 'block' : 'none';
    root.querySelector('#btn-tab-team-kpis').className = tab === 'team' ? 'btn-primary' : 'btn-secondary';
    root.querySelector('#btn-tab-perf').className = tab === 'perf' ? 'btn-primary' : 'btn-secondary';
    root.querySelector('#btn-tab-tasks').className = tab === 'tasks' ? 'btn-primary' : 'btn-secondary';
  };
  root.querySelector('#btn-tab-team-kpis').addEventListener('click', () => setAsanaTab('team'));
  root.querySelector('#btn-tab-perf').addEventListener('click', () => setAsanaTab('perf'));
  root.querySelector('#btn-tab-tasks').addEventListener('click', () => setAsanaTab('tasks'));

  const teamControl = root.querySelector('#asana-team-kpi-controls');
  const teamTable = root.querySelector('#asana-team-kpi-table');
  teamControl.innerHTML = `<label class="field"><span>Metric</span><select id="asana-kpi-metric"><option value="count_completed">Tasks Completed</option><option value="count_tasks">Tasks Created</option><option value="weighted_completions">Weighted Completions</option><option value="completion_rate">Task Completion Rate</option><option value="sla_adherence">Internal SLA</option><option value="avg_cycle_time_days">Average Time to Close</option><option value="overdue_count">Overdue Tasks</option><option value="overdue_rate">Overdue Tasks %</option><option value="sla_missed_count">Initial SLA Missed</option></select></label><label class="field"><span>View</span><select id="asana-kpi-grain"><option value="week">Weekly (Sun–Sat)</option><option value="month">Monthly</option></select></label><button class="btn-primary" id="btn-asana-kpi-run" style="align-self:flex-end"><span class="codicon codicon-refresh"></span> Refresh Table</button>`;
  const loadTeamKpis = async () => {
    teamTable.innerHTML = '<div class="folder-loading">Computing team KPI pivot…</div>';
    try {
      const metric = root.querySelector('#asana-kpi-metric').value;
      const grain = root.querySelector('#asana-kpi-grain').value;
      const data = await api('/api/asana/kpis/pivot', { method: 'POST', body: { metric, row_dimension: 'team', column_dimension: grain, period_grain: grain } });
      const cols = data.column_keys || []; const rows = data.row_keys || [];
      const byCell = new Map((data.cells || []).map((c) => [`${c.row}|${c.column}`, c]));
      const fmt = (c) => { if (!c || c.value == null) return 'N/A'; if (data.metric.unit.includes('percent')) return `${(c.value * 100).toFixed(1)}%`; return Number(c.value).toFixed(data.metric.unit === 'days' ? 1 : 0); };
      teamTable.innerHTML = `<div class="settings-note">Team-first membership attribution · ${esc(data.metric.label)} · click a value for exact task drilldown.</div><table class="data-table" style="margin-top:0.5rem"><thead><tr><th>Team</th>${cols.map((c) => `<th class="mono">${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr><td><b>${esc(r)}</b></td>${cols.map((c) => { const cell = byCell.get(`${r}|${c}`); return `<td>${cell ? `<button class="btn-secondary btn-sm asana-kpi-cell" data-team="${esc(r)}" data-period="${esc(c)}" style="min-width:64px">${fmt(cell)}</button>` : '—'}</td>`; }).join('')}</tr>`).join('') || '<tr><td class="empty-state" colspan="2">No synced team KPI facts for this metric and period.</td></tr>'}</tbody></table>`;
      teamTable.querySelectorAll('.asana-kpi-cell').forEach((button) => button.addEventListener('click', async () => {
        const detail = await api('/api/asana/kpis/drilldown', { method: 'POST', body: { metric, team: button.dataset.team, period_grain: grain, period_start: button.dataset.period, date_basis: data.date_basis } });
        const rows = detail.records || [];
        openModal(`KPI Drilldown — ${button.dataset.team} / ${button.dataset.period}`, `<div class="data-table-wrap"><table class="data-table"><thead><tr><th>Task</th><th>Project</th><th>Assignee</th><th>Created</th><th>Completed</th><th>Due</th></tr></thead><tbody>${rows.map((t) => `<tr><td><a href="${esc(t.permalink || '#')}" target="_blank" rel="noreferrer">${esc(t.name)}</a><div class="mono">${esc(t.gid)}</div></td><td>${esc(t.project_name || '—')}</td><td>${esc(t.assignee_name || '—')}</td><td>${esc(t.created_at || '—')}</td><td>${esc(t.completed_at || '—')}</td><td>${esc(t.due_on || '—')}</td></tr>`).join('') || '<tr><td colspan="6">No contributing task records.</td></tr>'}</tbody></table></div>`);
      }));
    } catch (e) { teamTable.innerHTML = `<div class="empty-state">Team KPI table unavailable: ${esc(e.message)}</div>`; }
  };
  root.querySelector('#btn-asana-kpi-run').addEventListener('click', loadTeamKpis);
  await loadTeamKpis();

  // AI Assisted Eval Button
  root.querySelector('#btn-asana-perf-eval-run').addEventListener('click', async () => {
    const prompt = root.querySelector('#asana-perf-eval-input').value.trim() || 'Evaluate performance for all employees';
    const outEl = root.querySelector('#asana-perf-eval-out');
    outEl.style.display = 'block';
    outEl.innerHTML = '<i>AI Agent evaluating employee performance…</i>';
    try {
      const res = await api('/api/kpis/nlp-convert', { method: 'POST', body: { prompt } });
      outEl.innerHTML = `<div>${res.summary ? res.summary.replace(/\n/g, '<br>') : 'Evaluation generated'}</div>`;
    } catch (e) {
      outEl.innerHTML = `<span style="color:red;">Error: ${esc(e.message)}</span>`;
    }
  });

  root.querySelector('#btn-asana-sync').addEventListener('click', async () => {
    toast('Sync started — watch the job in the sidebar counts', 'info');
    try { await api('/api/asana/sync', { method: 'POST', body: { mode: 'recent' } }); }
    catch (e) { toast(e.message, 'err'); }
  });

  root.querySelector('#btn-asana-push-sb').addEventListener('click', async () => {
    toast('Pushing local Asana tasks to Supabase…', 'info');
    try {
      const res = await api('/api/asana/push-supabase', { method: 'POST' });
      toast(`Pushed ${res.pushed || 0} tasks to Supabase`, 'info');
    } catch (e) {
      toast(e.message, 'err');
    }
  });

  // Load Performance Scorecards
  try {
    const evalRes = await api('/api/kpis/employee-evaluation');
    const scorecards = evalRes.scorecards || [];
    const scEl = root.querySelector('#asana-perf-scorecards');
    if (scorecards.length > 0) {
      scEl.innerHTML = scorecards.map((sc) => `
        <div class="home-card" style="display:flex; flex-direction:column; gap:6px;">
          <div style="display:flex; justify-content:space-between; font-weight:700;">
            <span>${esc(sc.owner)}</span>
            <span class="chip ${sc.performance_rating === 'Needs Focus' ? 'chip-warn' : 'chip-primary'}">${esc(sc.performance_rating)}</span>
          </div>
          <div style="font-size:1.6rem; font-weight:800; color:var(--t-function-primary, #3b82f6);">${sc.composite_score}%</div>
          <div style="font-size:0.8rem; color:var(--t-color-muted, #888);">${sc.total_kpis} Tracked KPIs</div>
        </div>
      `).join('');
    } else {
      scEl.innerHTML = '<div class="empty-state">No performance scorecards calculated yet. Click "Run AI Evaluation" above to generate.</div>';
    }
  } catch (e) {
    root.querySelector('#asana-perf-scorecards').innerHTML = `<div class="empty-state">⚠ ${esc(e.message)}</div>`;
  }

  // Load Task & Project Status
  try {
    const st = await api('/api/asana/status');
    const cfg = st.config || {};
    const counts = st.counts || {};
    root.querySelector('#asana-cards').innerHTML = `
      <div class="home-card"><div class="home-card-label">PAT</div><div class="home-card-val">${cfg.has_pat ? 'configured' : 'missing'}</div></div>
      <div class="home-card"><div class="home-card-label">Tasks synced</div><div class="home-card-val">${fmtNum(counts.tasks)}</div></div>
      <div class="home-card"><div class="home-card-label">Open tasks</div><div class="home-card-val">${fmtNum(counts.open)}</div></div>
      <div class="home-card"><div class="home-card-label">Projects</div><div class="home-card-val">${fmtNum(counts.projects)}</div></div>
      <div class="home-card"><div class="home-card-label">Last sync</div><div class="home-card-val" style="font-size:0.85rem">${esc(st.last_run || 'never')}</div></div>`;

    let projects = [];
    try { projects = await api('/api/asana/projects?include_archived=false'); } catch { /* */ }
    root.querySelector('#asana-projects').innerHTML = projects.length
      ? `<table class="data-table"><tr><th>Name</th><th>Team</th></tr>
         ${projects.slice(0, 30).map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.team_name || '—')}</td></tr>`).join('')}</table>`
      : '<div class="empty-state">No projects synced yet.</div>';

    let tasks = [];
    try { tasks = await api('/api/asana/tasks?limit=30'); } catch { /* */ }
    root.querySelector('#asana-tasks').innerHTML = tasks.length
      ? `<table class="data-table"><tr><th>Task</th><th>Assignee</th><th>Due</th></tr>
         ${tasks.map((t) => `<tr><td>${esc(t.name)}</td><td>${esc(t.assignee_name || '—')}</td><td>${esc(t.due_on || '—')}</td></tr>`).join('')}</table>`
      : '<div class="empty-state">No tasks synced yet.</div>';
  } catch { /* ignored */ }
}

/* ---------------------------------------------------------- events & reqs */
async function renderEvents() {
  const root = $('#view-root');
  root.innerHTML = `<div class="view"><div class="view-header"><div><div class="view-title">Inbound Events</div>
    <div class="view-sub">Everything that hit the webhook receiver — POST JSON to <code class="chat-code-inline">/webhooks/automation/{source}</code> to trigger automations.</div></div>
    <div class="view-actions"><button class="btn-secondary" id="btn-ev-refresh"><span class="codicon codicon-refresh"></span> Refresh</button></div></div>
    <div class="data-table-wrap" id="ev-list"><div class="folder-loading">Loading…</div></div></div>`;
  root.querySelector('#btn-ev-refresh').addEventListener('click', renderEvents);
  let evs = [];
  try { evs = await api('/api/events?limit=200'); } catch (e) { toast(e.message, 'err'); }
  const list = root.querySelector('#ev-list');
  list.innerHTML = evs.length ? `<table class="data-table">
    <tr><th>Source</th><th>Type</th><th>Payload</th><th>When</th></tr>
    ${evs.map((e) => `<tr><td>${esc(e.source)}</td><td class="mono">${esc(e.type || '—')}</td>
      <td class="mono muted">${esc(String(e.payload || '').slice(0, 120))}</td><td>${esc(timeAgo(e.created_at))}</td></tr>`).join('')}
  </table>` : '<div class="empty-state">No events yet.</div>';
}

async function renderRequests() {
  const root = $('#view-root');
  root.innerHTML = `<div class="view"><div class="view-header"><div><div class="view-title">HTTP Requests</div>
    <div class="view-sub">Every API call this backend has served.</div></div>
    <div class="view-actions"><button class="btn-secondary" id="btn-req-refresh"><span class="codicon codicon-refresh"></span> Refresh</button></div></div>
    <div class="data-table-wrap" id="req-list"><div class="folder-loading">Loading…</div></div></div>`;
  root.querySelector('#btn-req-refresh').addEventListener('click', renderRequests);
  let reqs = [];
  try { reqs = await api('/api/requests?limit=200'); } catch (e) { toast(e.message, 'err'); }
  const list = root.querySelector('#req-list');
  list.innerHTML = reqs.length ? `<table class="data-table">
    <tr><th>Method</th><th>Path</th><th>Status</th><th>Latency</th><th>When</th></tr>
    ${reqs.map((r) => `<tr><td><span class="method-chip m-${esc(r.method)}">${esc(r.method)}</span></td>
      <td class="mono">${esc(r.path)}</td><td>${r.status}</td>
      <td>${Math.round(r.latency_ms)}ms</td><td>${esc(timeAgo(r.created_at))}</td></tr>`).join('')}
  </table>` : '<div class="empty-state">No requests logged yet.</div>';
}

/* ----------------------------------------------------------- right pane */
async function openFolder(path) {
  state.folderPath = path || '';
  const tree = $('#folder-tree');
  tree.innerHTML = '<div class="folder-loading">Loading…</div>';
  try {
    const res = await api('/api/vault/tree?path=' + encodeURIComponent(path || ''));
    const bc = $('#folder-breadcrumb');
    bc.innerHTML = '';
    const parts = (res.path || '').split('/').filter(Boolean);
    const mk = (label, p) => {
      const b = el('button', 'bc-crumb', label);
      b.addEventListener('click', () => openFolder(p));
      return b;
    };
    bc.appendChild(mk(res.root, ''));
    parts.forEach((part, i) => {
      bc.appendChild(el('span', 'bc-sep', '/'));
      bc.appendChild(mk(part, parts.slice(0, i + 1).join('/')));
    });
    tree.innerHTML = '';
    res.dirs.forEach((d) => {
      const row = el('div', 'folder-row', null);
      row.dataset.path = d.path;
      row.innerHTML = `<span class="codicon codicon-folder-opened folder-ic"></span>
        <span class="folder-name">${esc(d.name)}</span>
        <span class="folder-counts">${d.notes} notes · ${d.files} files</span>`;
      tree.appendChild(row);
    });
    res.files.forEach((f) => {
      const row = el('div', 'folder-row folder-file', null);
      row.innerHTML = `<span class="codicon codicon-file-text folder-ic"></span>
        <span class="folder-name">${esc(f.name)}</span>
        <span class="folder-counts">${fmtNum(f.size)} B</span>`;
      tree.appendChild(row);
    });
    if (!res.dirs.length && !res.files.length) tree.innerHTML = '<div class="folder-empty">Empty folder</div>';
  } catch (e) {
    $('#folder-tree').innerHTML = `<div class="folder-error">${esc(e.message)}</div>`;
  }
}

async function loadActivity() {
  const box = $('#activity-list');
  box.innerHTML = '<div class="folder-loading">Loading…</div>';
  try {
    const [st, evs] = await Promise.all([api('/api/automation/stats'), api('/api/events?limit=30')]);
    const runs = [];
    (st.recent_ai || []).forEach((r) => runs.push({ t: r.created_at, icon: 'chat-sparkle', text: `AI ${r.workflow} (${r.provider})` }));
    evs.forEach((e) => runs.push({ t: e.created_at, icon: 'radio-tower', text: `${e.source}${e.type ? ' · ' + e.type : ''}` }));
    runs.sort((a, b) => Date.parse(b.t) - Date.parse(a.t));
    box.innerHTML = runs.length
      ? runs.map((r) => `<div class="activity-item"><span class="codicon codicon-${r.icon}"></span>
          <div class="activity-text">${esc(r.text)}</div><div class="activity-time">${esc(timeAgo(r.t))}</div></div>`).join('')
      : '<div class="empty-state">No activity yet.</div>';
  } catch (e) {
    box.innerHTML = `<div class="folder-error">${esc(e.message)}</div>`;
  }
}

/* ------------------------------------------------------------ settings */
async function renderSettingsTab(tab) {
  const box = $('#settings-content');
  if (tab === 'appearance') { renderAppearanceTab(); return; }
  if (tab === 'layout') { renderLayoutTab(); return; }
  if (tab === 'navigation') { renderNavigationTab(); return; }
  if (tab === 'advanced') { renderAdvancedTab(); return; }
  if (tab === 'prompt') { renderPromptTab(); return; }

  if (tab === 'chat') {
    let cfg = {}, provs = { providers: [] }, disc = { models: [] }, keys = { keys: {} };
    try { cfg = await api('/api/chat/config'); } catch { /* */ }
    try { provs = await api('/api/chat/providers'); } catch { /* */ }
    try { disc = await api('/api/llama/discover'); } catch { /* */ }
    try { keys = await api('/api/chat/keys'); } catch { /* */ }

    const providerCards = (provs.providers || []).map((p) => {
      const health = p.health || {};
      const badge = p.configured
        ? '<span class="pill-int pill-int-configured">configured</span>'
        : '<span class="pill-int pill-int-missing">add a key</span>';
      const healthBadge = p.configured
        ? (health.healthy ? '<span class="pill-int pill-int-configured">healthy</span>' : `<span class="pill-int pill-int-missing" title="${esc(health.error || '')}">unhealthy</span>`)
        : '';
      const modelOpts = (p.models || []).map((m) => `<option value="${esc(m.id)}" ${p.defaultModelId === m.id ? 'selected' : ''}>${esc(m.id)}</option>`).join('');
      const keySet = !!(keys.keys || {})[p.id];
      return `
      <div class="provider-card" id="prov-${p.id}">
        <div class="provider-card-head">
          <span class="provider-name">${esc(p.label)}</span>
          ${badge}${healthBadge}
          <label class="toggle-mini" title="Enabled">
            <input type="checkbox" class="prov-enabled" data-pid="${p.id}" ${p.enabled === false ? '' : 'checked'} />
            <span></span>
          </label>
        </div>
        <div class="provider-card-body">
          <div class="field-row">
            <label class="field"><span>Mode</span>
              <select class="prov-mode" data-pid="${p.id}">
                <option value="direct" ${p.mode !== 'proxy' ? 'selected' : ''}>Direct (key here)</option>
                <option value="proxy" ${p.mode === 'proxy' ? 'selected' : ''}>Proxy (Supabase)</option>
              </select></label>
            <label class="field"><span>Default model</span>
              <select class="prov-model" data-pid="${p.id}">${modelOpts || `<option>${esc(p.defaultModelId)}</option>`}</select></label>
          </div>
          <label class="field"><span>Base URL</span><input class="prov-baseurl" data-pid="${p.id}" value="${esc(p.baseUrl)}" /></label>
          <div class="field-row prov-key-row">
            <label class="field"><span>API key ${keySet ? '<span class="pill-int pill-int-configured">key set (keychain)</span>' : ''}</span>
              <input class="prov-key" data-pid="${p.id}" type="password" placeholder="${keySet ? '•••••• (leave blank to keep)' : 'paste key'}" autocomplete="off" /></label>
          </div>
          <div class="settings-actions">
            <button class="btn-secondary prov-save" data-pid="${p.id}">Save ${esc(p.id)}</button>
            ${keySet ? `<button class="btn-secondary prov-remove" data-pid="${p.id}">Remove key</button>` : ''}
          </div>
        </div>
      </div>`;
    }).join('');

    const chatModels = (provs.providers || []).filter((p) => p.configured)
      .map((p) => (p.models || []).map((m) => `<option value="${esc(m.id)}" data-provider="${esc(p.id)}">${esc(p.label)} — ${esc(m.id)}</option>`).join(''))
      .join('');

    const discovered = disc.models || [];
    const chatGgufs = discovered.filter((m) => m.kind === 'chat');
    const embedGgufs = discovered.filter((m) => m.kind === 'embedding');
    const srcLabel = (s) => {
      if (s.includes('conductor')) return 'conductor models/';
      if (s.includes('.ollama')) return 'Ollama';
      if (s.includes('lm-studio')) return 'LM Studio';
      if (s.includes('.lmstudio')) return 'LM Studio (legacy)';
      if (s.includes('jan')) return 'Jan / Atomic Chat';
      if (s.includes('Conductor')) return 'AppData models';
      return s.split(/[\\/]/).slice(-2).join('/');
    };
    const ggufRow = (m) => `<option value="${esc(m.id)}" ${cfg.llama_model === m.id ? 'selected' : ''}>${esc(m.name)} — ${(m.sizeBytes / 1073741824).toFixed(1)} GB (${esc(srcLabel(m.sourceDir))})</option>`;
    const discoveryNote = discovered.length
      ? `<div class="settings-note">Discovered <b>${discovered.length}</b> GGUF models on this machine (${chatGgufs.length} chat · ${embedGgufs.length} embedding). Nothing is copied or moved — pick one to load.</div>`
      : '<div class="settings-note">No GGUF models found. Drop one into <code>models/</code> next to the app, or point to an Ollama / LM Studio / Jan store.</div>';

    box.innerHTML = `
      <div class="settings-pane active">
        <div class="settings-section">
          <div class="settings-title"><span class="codicon codicon-comment-discussion"></span> AI Chat — Providers</div>
          <div class="settings-note">Providers without a key are left out of the chat picker (LAW rule — never offer a target that 401s). Keys are stored through the OS keychain via safeStorage when running in the desktop app.</div>
          <div class="provider-grid">${providerCards || '<div class="settings-note">No providers.</div>'}</div>
        </div>
        <div class="settings-section">
          <div class="settings-title"><span class="codicon codicon-server-process"></span> Local engine (llama.cpp)</div>
          <label class="field"><span>Local model (GGUF)</span>
            <select id="s-llama-model"><option value="">— choose a discovered model —</option>
              ${chatGgufs.map(ggufRow).join('')}
              ${embedGgufs.length ? `<optgroup label="Embedding models (not chat-capable)">${embedGgufs.map(ggufRow).join('')}</optgroup>` : ''}
            </select></label>
          <div class="field-row">
            <label class="field"><span>Context size</span><input id="s-llama-ctx" type="number" min="512" value="${cfg.llama_ctx || 4096}" /></label>
            <label class="field"><span>Port</span><input id="s-llama-port" type="number" min="1024" value="${cfg.llama_port || 8098}" /></label>
          </div>
          <div class="settings-note" id="s-llama-status">Local server: ${cfg.llama_running ? 'running' : 'stopped'}${cfg.llama_loaded ? ' · ' + esc(cfg.llama_loaded) : ''}</div>
          <div class="settings-actions">
            <button class="btn-secondary" id="btn-llama-start">Start server</button>
            <button class="btn-secondary" id="btn-llama-stop">Stop server</button>
          </div>
          ${discoveryNote}
        </div>
        <div class="settings-section">
          <div class="settings-title"><span class="codicon codicon-comment-discussion"></span> Chat defaults</div>
          <div class="field-row">
            <label class="field"><span>Provider</span>
              <select id="s-provider">
                ${(provs.providers || []).filter((p) => p.id !== 'llama').map((p) => `<option value="${esc(p.id)}" ${(cfg.provider || 'deepseek') === p.id ? 'selected' : ''}>${esc(p.label)}</option>`).join('')}
                <option value="llama" ${cfg.provider === 'llama' ? 'selected' : ''}>Local Llama (private)</option>
              </select></label>
            <label class="field"><span>Model</span>
              <select id="s-model">${chatModels || `<option value="${esc(cfg.model || 'deepseek-v4-flash')}">${esc(cfg.model || 'deepseek-v4-flash')}</option>`}</select></label>
          </div>
          <div class="settings-note">The composer has a quick provider/model switcher too — this sets the default.</div>
        </div>
        <div class="settings-actions">
          <button class="btn-primary" id="btn-save-chat">Save AI Chat</button>
          <button class="btn-secondary" id="btn-test-chat" style="flex:none">Test</button>
        </div>
      </div>`;

    // --- provider card wiring: mode toggle shows/hides key row ---
    box.querySelectorAll('.prov-mode').forEach((sel) => {
      sel.addEventListener('change', (e) => {
        const row = box.querySelector(`.prov-key-row[data-pid]`);
        // key row stays visible; proxy mode ignores it at runtime
      });
    });

    const saveProviderKey = async (pid) => {
      const input = box.querySelector(`.prov-key[data-pid="${pid}"]`);
      const key = (input ? input.value : '').trim();
      if (!key) return toast('Paste an API key first', 'warn');
      let value = btoa(unescape(encodeURIComponent(key)));
      let encrypted = false;
      try {
        if (window.desktop && window.desktop.keys) {
          const res = await window.desktop.keys.set(pid, key);
          value = res.value; encrypted = res.encrypted;
        }
      } catch { /* fall back to plain base64 */ }
      await api('/api/chat/keys', { method: 'POST', body: { providerId: pid, value, encrypted } });
      toast(`${pid} key saved${encrypted ? ' (encrypted via OS keychain)' : ''}`, 'ok');
      renderSettingsTab('chat');
    };
    box.querySelectorAll('.prov-save').forEach((b) => b.addEventListener('click', () => saveProviderKey(b.dataset.pid)));
    box.querySelectorAll('.prov-remove').forEach((b) => b.addEventListener('click', async () => {
      await api(`/api/chat/keys/${b.dataset.pid}`, { method: 'DELETE' });
      toast(`${b.dataset.pid} key removed`, 'ok');
      renderSettingsTab('chat');
    }));
    box.querySelectorAll('.prov-enabled').forEach((cb) => cb.addEventListener('change', async () => {
      await api('/api/chat/config', { method: 'POST', body: { provider: cfg.provider || 'deepseek', providers: { [cb.dataset.pid]: { enabled: cb.checked } } } });
      toast(`${cb.dataset.pid} ${cb.checked ? 'enabled' : 'disabled'}`, 'ok');
    }));

    box.querySelector('#btn-llama-start').addEventListener('click', async () => {
      try {
        const model = box.querySelector('#s-llama-model').value;
        if (!model) return toast('Pick a discovered GGUF model first', 'warn');
        const res = await api('/api/llama/start', { method: 'POST', body: { model, ctx: Number(box.querySelector('#s-llama-ctx').value || 4096) } });
        toast(`Llama server up on port ${res.port}${res.reused ? ' (adopted existing server)' : ''}`, 'ok');
        box.querySelector('#s-llama-status').textContent = `Local server: running · ${res.model}`;
      } catch (e) { toast(e.message, 'err'); }
    });
    box.querySelector('#btn-llama-stop').addEventListener('click', async () => {
      try { await api('/api/llama/stop', { method: 'POST' }); toast('Llama server stopped', 'ok'); }
      catch (e) { toast(e.message, 'err'); }
    });
    box.querySelector('#btn-save-chat').addEventListener('click', async () => {
      const body = {
        provider: box.querySelector('#s-provider').value,
        model: box.querySelector('#s-model').value,
        llama_model: box.querySelector('#s-llama-model').value,
        llama_ctx: Number(box.querySelector('#s-llama-ctx').value || 4096),
        llama_port: Number(box.querySelector('#s-llama-port').value || 8098),
      };
      try {
        const res = await api('/api/chat/config', { method: 'POST', body });
        toast(`Saved — provider ${res.provider}${res.configured ? ' (key set)' : ' (no key yet)'}`, 'ok');
        await refreshStatusbar();
      } catch (e) { toast(e.message, 'err'); }
    });
    $('#btn-test-chat').addEventListener('click', async () => {
      try {
        const provider = box.querySelector('#s-provider').value;
        const model = box.querySelector('#s-model').value;
        const apiKey = await resolveChatKey(provider);
        const res = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: 'Reply with exactly: OK', provider, model, api_key: apiKey || undefined }) });
        const text = await res.text();
        toast(res.ok ? 'Chat test passed' : `Chat test failed: ${text.slice(0, 140)}`, res.ok ? 'ok' : 'err');
      } catch (e) { toast(`Test failed: ${e.message}`, 'err'); }
    });
    return;
  }

  if (tab === 'prompt') {
    await renderPromptTab();
    return;
  }

  if (tab === 'asana') {
    let st = {};
    try { st = await api('/api/asana/status'); } catch { /* */ }
    const cfg = st.config || {};
    box.innerHTML = `
      <div class="settings-pane active">
        <div class="settings-section">
          <div class="settings-title"><span class="codicon codicon-organization"></span> Asana Sync</div>
          <label class="field"><span>Personal Access Token (PAT) ${cfg.has_pat ? '<span class="pill-int pill-int-configured">configured</span>' : ''}</span>
            <input id="s-asana-pat" type="password" placeholder="${cfg.has_pat ? '•••••• (leave blank to keep)' : '2/…'}" autocomplete="off" /></label>
          <div class="field-row">
            <label class="field"><span>Workspace GID</span><input id="s-asana-workspace" value="${esc(cfg.workspace_gid || '')}" placeholder="1161027935621444" /></label>
            <label class="field"><span>Portfolio GID</span><input id="s-asana-portfolio" value="${esc(cfg.portfolio_gid || '')}" placeholder="1210875219129229" /></label>
          </div>
          <label class="field"><span>Project source</span>
            <select id="s-asana-source">
              <option value="workspace" ${cfg.project_source !== 'portfolio' ? 'selected' : ''}>Whole workspace (all projects)</option>
              <option value="portfolio" ${cfg.project_source === 'portfolio' ? 'selected' : ''}>Portfolio only</option>
            </select></label>
          <div class="settings-note">Counts: ${fmtNum((st.counts || {}).tasks)} tasks · ${fmtNum((st.counts || {}).projects)} projects · last run ${esc(st.last_run || 'never')}</div>
          <div class="settings-actions"><button class="btn-primary" id="btn-save-asana">Save Asana Config</button></div>
        </div>
      </div>`;
    box.querySelector('#btn-save-asana').addEventListener('click', async () => {
      const body = {
        workspace_gid: box.querySelector('#s-asana-workspace').value,
        portfolio_gid: box.querySelector('#s-asana-portfolio').value,
        project_source: box.querySelector('#s-asana-source').value,
      };
      const pat = box.querySelector('#s-asana-pat').value.trim();
      if (pat && !pat.includes('••••')) body.pat = pat;
      try { await api('/api/asana/config', { method: 'POST', body }); toast('Asana config saved', 'ok'); }
      catch (e) { toast(e.message, 'err'); }
    });
    return;
  }

  if (tab === 'spapi') {
    let st = {};
    try { st = await api('/api/productpipeline/status'); } catch { /* */ }
    const hasKey = !!st.has_key;
    box.innerHTML = `
      <div class="settings-pane active">
        <div class="settings-section">
          <div class="settings-title"><span class="codicon codicon-git-merge"></span> Amazon SP-API</div>
          <div class="settings-note">Powers the Product Pipelines view via <code>getDefinitionsProductType</code>. LWA auth (refresh_token + client_id + client_secret) or a direct access_token. Without credentials, fetches fall back to bundled sample definitions. Same store as the Integrations page.</div>
          <div class="field-row">
            <label class="field"><span>Refresh token ${hasKey ? '<span class="pill-int pill-int-configured">configured</span>' : ''}</span>
              <input id="s-spapi-refresh" type="password" placeholder="${hasKey ? (st.refresh_token_masked || '•••••• (saved)') + ' (leave blank to keep)' : 'LWA refresh_token'}" autocomplete="off" /></label>
            <label class="field"><span>Client ID</span><input id="s-spapi-client" type="password" placeholder="${hasKey ? (st.client_id_masked || '•••••• (saved)') + ' (leave blank to keep)' : 'LWA client_id'}" autocomplete="off" /></label>
            <label class="field"><span>Client secret</span><input id="s-spapi-secret" type="password" placeholder="LWA client_secret" autocomplete="off" /></label>
          </div>
          <div class="field-row">
            <label class="field"><span>Direct access token (optional)</span><input id="s-spapi-token" type="password" placeholder="x-amz-access-token" autocomplete="off" /></label>
            <label class="field"><span>Region</span>
              <select id="s-spapi-region">${(st.regions || []).map((r) => `<option value="${esc(r.id)}" ${st.region === r.id ? 'selected' : ''}>${esc(r.id.toUpperCase())} — ${esc(r.host)}</option>`).join('')}</select></label>
          </div>
          <div class="settings-actions">
            <button class="btn-primary" id="btn-save-spapi">Save SP-API credentials</button>
            <button class="btn-secondary" id="btn-open-pipelines"><span class="codicon codicon-git-merge"></span> Open Product Pipelines</button>
          </div>
        </div>
      </div>`;
    box.querySelector('#btn-save-spapi').addEventListener('click', async () => {
      const body = {};
      const r = box.querySelector('#s-spapi-refresh').value.trim();
      const c = box.querySelector('#s-spapi-client').value.trim();
      const s = box.querySelector('#s-spapi-secret').value.trim();
      const t = box.querySelector('#s-spapi-token').value.trim();
      if (r) body.refresh_token = r;
      if (c) body.client_id = c;
      if (s) body.client_secret = s;
      if (t) body.access_token = t;
      body.region = box.querySelector('#s-spapi-region').value;
      try {
        await api('/api/productpipeline/config', { method: 'POST', body });
        toast('SP-API credentials saved', 'ok');
        renderSettingsTab('spapi');
      } catch (e) { toast(e.message, 'err'); }
    });
    box.querySelector('#btn-open-pipelines').addEventListener('click', () => {
      $('#settings-backdrop').hidden = true;
      showView('productpipeline');
    });
    return;
  }

  if (tab === 'about') {
    let a = {};
    try { a = await api('/api/about'); } catch { /* */ }
    let updInfo = null;
    if (window.desktop && window.desktop.getUpdateInfo) {
      try { updInfo = await window.desktop.getUpdateInfo(); } catch { /* */ }
    }
    const updVer = (updInfo && updInfo.version) || a.version || '1.9.6';
    const canUpdate = !!(updInfo && updInfo.isPackaged);
    box.innerHTML = `
      <div class="settings-pane active">
        <div class="update-banner-card">
          <div class="ub-left">
            <div class="ub-icon codicon codicon-cloud-download"></div>
            <div class="ub-details">
              <div class="ub-title">Conductor Version Control</div>
              <div class="ub-status" id="upd-status">${canUpdate ? 'Updates are checked automatically at launch.' : `Running build v${esc(updVer)}.`}</div>
            </div>
          </div>
          <div class="ub-actions">
            <button class="btn-primary" id="btn-check-updates"><span class="codicon codicon-refresh"></span> Check for Updates</button>
            <button class="btn-primary" id="btn-install-update" ${state.updateReady.ready ? '' : 'hidden'}><span class="codicon codicon-cloud-upload"></span> Restart &amp; Install</button>
          </div>
        </div>

        <div class="settings-section" style="margin-top:1rem;">
          <div class="settings-title"><span class="codicon codicon-server-environment"></span> Environment Details</div>
          <div class="about-grid">
            <div class="about-item"><div class="a-label">App Name</div><div class="a-value">${esc(a.name || 'Conductor')}</div></div>
            <div class="about-item"><div class="a-label">Active Version</div><div class="a-value mono" style="color:var(--accent,#38bdf8); font-weight:600;">v${esc(updVer)}</div></div>
            <div class="about-item"><div class="a-label">Python Runtime</div><div class="a-value mono">${esc(a.python || '3.11.15')}</div></div>
            <div class="about-item"><div class="a-label">Platform OS</div><div class="a-value">${esc(a.platform || 'win32')}</div></div>
            <div class="about-item"><div class="a-label">Database Size</div><div class="a-value mono">${a.db_size ? (a.db_size / 1024 / 1024).toFixed(2) + ' MB' : '—'}</div></div>
            <div class="about-item"><div class="a-label">Uptime</div><div class="a-value mono">${esc(String(a.uptime_s || '0'))}s</div></div>
          </div>
        </div>

        <div class="settings-section" style="margin-top:1rem;">
          <div class="settings-title"><span class="codicon codicon-history"></span> Version Target &amp; Rollback</div>
          <div class="settings-note">Switch application build targets or rollback to a previous release version.</div>
          <div class="version-rollback-box">
            <label class="field" style="flex:1;">
              <span>Release Target</span>
              <select id="upd-version-select" class="input-select" style="width:100%; height:32px; padding:0 8px;">
                <option value="1.9.6">v1.9.6 (Current / Latest)</option>
                <option value="1.9.5">v1.9.5</option>
                <option value="1.7.0">v1.7.0</option>
                <option value="1.6.0">v1.6.0</option>
                <option value="1.5.0">v1.5.0</option>
                <option value="1.4.0">v1.4.0</option>
              </select>
            </label>
            <button class="btn-secondary" id="btn-rollback-version" style="height:32px; align-self:flex-end;">
              <span class="codicon codicon-history"></span> Rollback / Switch Target
            </button>
          </div>
        </div>

        <div class="about-pillars">
          <span class="pillar-chip"><span class="codicon codicon-lightbulb"></span> Process Discovery</span>
          <span class="pillar-chip"><span class="codicon codicon-zap"></span> Automations</span>
          <span class="pillar-chip"><span class="codicon codicon-sparkle"></span> AI Integration</span>
          <span class="pillar-chip"><span class="codicon codicon-shield"></span> Governance</span>
        </div>
      </div>`;

    const setStatus = (msg) => { const el = box.querySelector('#upd-status'); if (el) el.textContent = msg; };
    box.querySelector('#btn-check-updates').addEventListener('click', async () => {
      if (!window.desktop || !window.desktop.checkForUpdates) {
        setStatus('Updates are only available in the installed (packaged) app.');
        return;
      }
      const info = await window.desktop.getUpdateInfo().catch(() => null);
      if (!info || !info.isPackaged) {
        setStatus(`Running the dev build (v${info ? info.version : '—'}) — updates apply only to the installed app.`);
        return;
      }
      const btn = box.querySelector('#btn-check-updates');
      btn.disabled = true;
      setStatus('Checking for updates…');
      try {
        const res = await window.desktop.checkForUpdates();
        if (res.error) setStatus('Check failed: ' + res.error);
        else if (res.reason === 'updates-disabled') setStatus('Updates are not enabled for this build.');
        else if (res.downloaded) {
          state.updateReady = { ready: true, version: res.downloaded };
          const b = box.querySelector('#btn-install-update'); if (b) b.hidden = false;
          setStatus(`Conductor ${res.downloaded} downloaded and ready — restart to install.`);
        } else if (res.available) setStatus(`Update v${res.version} available — downloading…`);
        else setStatus('You are up to date.');
      } catch (e) {
        setStatus('Check failed: ' + (e && e.message ? e.message : e));
      } finally {
        btn.disabled = false;
      }
    });
    box.querySelector('#btn-install-update').addEventListener('click', () => {
      if (window.desktop && window.desktop.installUpdate) window.desktop.installUpdate();
    });

    // Populate version selector from backend updates API
    (async () => {
      try {
        const vData = await api('/api/updates/versions');
        const select = box.querySelector('#upd-version-select');
        if (select && vData && vData.versions && vData.versions.length) {
          select.innerHTML = vData.versions.map((v) =>
            `<option value="${esc(v.version)}">v${esc(v.version)}${v.version === vData.current_version ? ' (Current / Latest)' : ''}</option>`
          ).join('');
        }
      } catch { /* ignored */ }
    })();

    // Wire Rollback Button
    box.querySelector('#btn-rollback-version').addEventListener('click', async () => {
      const select = box.querySelector('#upd-version-select');
      const targetVersion = select ? select.value : '1.6.0';
      if (!confirm(`Rollback / switch application version target to v${targetVersion}?`)) return;

      try {
        const res = await api('/api/updates/rollback', {
          method: 'POST',
          body: { target_version: targetVersion },
        });
        toast(res.message || `Set version target to v${targetVersion}`, 'info');
        setStatus(`Version target set to v${targetVersion}. Restart to apply.`);
      } catch (e) {
        toast('Rollback failed: ' + e.message, 'err');
      }
    });
    return;
  }
}

async function renderPromptTab() {
  const box = $('#settings-content');
  let cfg = {};
  try { cfg = await api('/api/chat/config'); } catch { /* */ }

  const defaultPrompt = `You are Conductor Assistant, the user copilot running inside Conductor — a desktop workbench for Luminize (managing 80+ Amazon brands and multi-channel marketplaces).

Your primary role:
- Guide and assist users in navigating Conductor, managing tasks, inspecting catalog data, running AI workflows, and automating operations.
- Act as a thoughtful, articulate, user-focused assistant.
- Before making structural changes to the app, altering catalog schemas, or modifying automation pipelines, consult or delegate to specialist agents like Franky (Catalog Architect & Operations Engineer) or trigger the appropriate specialized agent workflow.

Specialist Agents Available:
- Franky: Senior Catalog Architect & Automation Specialist (multi-format parsing, Keepa live queries, Asana sync, catalog schemas).
- Asana Harvester: Asana task, subtask, story, and custom field synchronization.
- Keepa Analyst: Price history, Buy Box tracking, and sales rank analysis.
- Flow Canvas & Asana Rules: Node-graph flow builders and trigger-action automations.

Tone: Helpful, clear, proactive, and practical. Keep responses focused and concise unless detailed depth is requested.`;

  const frankyPrompt = `You are Franky, the Catalog Architect & Automation Copilot running inside Conductor — a desktop workbench for Luminize (a top-5 Amazon seller managing 80+ brands). You live alongside live catalog ingestion pipelines, Keepa market intelligence, Asana task mirrors, Flow Canvas automations, and a multi-provider LLM suite.

Your tone: sharp, direct, pragmatic, no fluff. Answer in the same language the user writes in.

What you do best:
- Catalog & File Ingestion: Guide multi-format catalog imports (.xlsx, .xlsb, .csv, .tsv, .md, .docx, .pdf, .json); extract compliance attributes (batteries, wireless, hazmat, materials) and infer Amazon compliance categories.
- Keepa Intelligence: Execute live product lookups, brand/seller ASIN searches, price history tracking, sales rank analysis, and natural-language Keepa queries.
- Asana Operations: Sync tasks, subtasks, stories/comments, attachments, and custom fields across workspace projects.
- Automation Design: Propose trigger → condition → action chains, Flow Canvas node graphs, and Asana rules.
- Governance: Draft SOPs/runbooks, define validation guardrails, and track process execution.

In-app moves to suggest: run a Keepa lookup, ingest a catalog file, trigger an Asana sync, build a Flow Canvas automation, or inspect AI workflow runs. When uncertain, suggest a concrete action in the app.

Keep answers under ~200 words unless depth is requested. Use markdown-lite (bold, code, short lists) — no bloated tables.`;

  const opsPrompt = `You are Operations Analyst Copilot inside Conductor. Your focus is optimizing Amazon seller operations, catalog compliance, Asana task throughput, and Keepa price/rank signals.

Before executing schema or app changes, delegate technical engineering tasks to Franky (Catalog Architect).

Tone: Analytical, precise, metric-driven. Always cite relevant product SKUs, ASINs, and task GIDs.`;

  box.innerHTML = `
    <div class="settings-pane active">
      <div class="settings-section">
        <div class="settings-title"><span class="codicon codicon-terminal"></span> AI Copilot System Prompt</div>
        <div class="settings-note">Customize the system prompt used by the AI Chat copilot. Your assistant can consult specialist agents like Franky before making changes to the app or catalog.</div>

        <div style="margin-top:0.75rem;">
          <label class="field" style="display:block;">
            <span>System Prompt Text</span>
            <textarea id="s-system-prompt" style="width:100%; height:260px; font-family:var(--font-mono); font-size:12px; line-height:1.4; padding:8px; background:var(--t-surface-base, #111); color:var(--fg); border:1px solid var(--border); border-radius:6px; resize:vertical;"></textarea>
          </label>
        </div>

        <div style="margin-top:0.75rem;">
          <div class="settings-note" style="margin-bottom:0.4rem;">Quick Preset Templates:</div>
          <div class="field-row" style="display:flex; gap:0.5rem;">
            <button class="btn-secondary btn-sm" id="btn-tmpl-default"><span class="codicon codicon-person"></span> User Assistant (Default)</button>
            <button class="btn-secondary btn-sm" id="btn-tmpl-franky"><span class="codicon codicon-tools"></span> Franky (Catalog Architect)</button>
            <button class="btn-secondary btn-sm" id="btn-tmpl-ops"><span class="codicon codicon-graph"></span> Operations Analyst</button>
          </div>
        </div>

        <div class="settings-actions" style="margin-top:1rem;">
          <button class="btn-primary" id="btn-save-prompt"><span class="codicon codicon-save"></span> Save System Prompt</button>
          <button class="btn-secondary" id="btn-reset-prompt">Reset Default</button>
        </div>
      </div>
    </div>`;

  const textarea = $('#s-system-prompt');
  textarea.value = cfg.system_prompt || defaultPrompt;

  $('#btn-tmpl-default').addEventListener('click', () => { textarea.value = defaultPrompt; });
  $('#btn-tmpl-franky').addEventListener('click', () => { textarea.value = frankyPrompt; });
  $('#btn-tmpl-ops').addEventListener('click', () => { textarea.value = opsPrompt; });
  $('#btn-reset-prompt').addEventListener('click', () => { textarea.value = defaultPrompt; });

  $('#btn-save-prompt').addEventListener('click', async () => {
    try {
      const text = textarea.value.trim();
      const res = await api('/api/chat/config', { method: 'POST', body: { system_prompt: text } });
      toast('System Prompt updated & saved ✓', 'ok');
    } catch (e) {
      toast('Failed to save System Prompt: ' + e.message, 'err');
    }
  });
}

function openSettings() {
  $('#settings-backdrop').hidden = false;
  applyLayout(getLayout());
  renderSettingsTab('appearance');
}

/* Palette integration: open settings directly on a tab. */
function openSettingsTab(tab) {
  $('#settings-backdrop').hidden = false;
  applyLayout(getLayout());
  const btn = document.querySelector(`.settings-nav-item[data-stab="${tab}"]`);
  if (btn) {
    document.querySelectorAll('.settings-nav-item').forEach((b) => b.classList.toggle('active', b === btn));
    renderSettingsTab(tab);
  }
}

/* ------------------------------------------------------------ theme boot
   (the full design-token suite is ported from parker — see end of file) */

/* ------------------------------------------------------------ statusbar */
async function refreshStatusbar() {
  try {
    const st = await api('/api/stats');
    const m = st.model || {};
    const label = m.provider === 'llama'
      ? `llama:${m.name}${st.connections && st.connections.llama_server && st.connections.llama_server.up ? '' : ' (stopped)'}`
      : `${m.name || '—'}`;
    $('#status-model').textContent = label;
    const tu = st.token_usage || {};
    $('#status-tokens').textContent = `${fmtNum((tu.total_tokens || 0) + (tu.input_tokens || 0) + (tu.output_tokens || 0))} tok`;
    const as = (st.connections && st.connections.asana) || {};
    $('#status-conn').textContent = `asana ${fmtNum(as.tasks || 0)} · ${st.automations !== undefined ? fmtNum(state.stats.automations ? (state.stats.automations.total || 0) : 0) : ''} automations · db ${(st.db_size || 0) / 1024 / 1024 >= 1 ? (st.db_size / 1024 / 1024).toFixed(1) + 'MB' : fmtNum(st.db_size) + 'B'}`;
    $('#status-text').textContent = `Connected · ${st.service || 'conductor'} v${st.version || '1.9.6'}`;
  } catch { /* statusbar is best-effort */ }
}

/* --------------------------------------------------------------- counts */
async function refreshCounts() {
  const set = (key, val) => {
    const empty = (val === 0 || val === '' || val == null);
    document.querySelectorAll(`.sidebar-count[data-count="${key}"]`).forEach((el) => {
      el.textContent = empty ? '' : String(val);
      el.style.display = empty ? 'none' : '';
    });
  };
  try {
    const st = await api('/api/automation/stats');
    state.stats = st;
    set('processes', (st.processes || {}).total || 0);
    set('automations', (st.automations || {}).total || 0);
    set('ai', (st.ai || {}).runs || 0);
    set('sops', st.sops || 0);
    set('events', st.events || 0);
  } catch { /* */ }
  try {
    const s = await api('/api/stats');
    set('checks', s.checks || 0);
    set('products', s.products || 0);
    set('files', s.files || 0);
    set('tasks', s.tasks_open || 0);
    set('agents', s.agents || 0);
  } catch { /* */ }
  try {
    const as = await api('/api/asana/status');
    set('asana', ((as.counts || {}).open || 0));
  } catch { /* */ }
  try {
    const reqs = await api('/api/requests?limit=1');
    set('requests', reqs.length ? '•' : '');
  } catch { /* */ }
}

/* ----------------------------------------------------------------- boot */
async function initAiComposer() {
  const provSel = $('#composer-provider'), modelSel = $('#composer-model');
  if (!provSel || !modelSel) return;
  try {
    const saved = JSON.parse(localStorage.getItem('conductor.chat') || '{}');
    const [provs, cfg] = await Promise.all([api('/api/chat/providers'), api('/api/chat/config')]);
    const allProviders = provs.providers || [];
    if (!allProviders.length) return;
    const configured = allProviders.filter((p) => p.configured);
    const unconfigured = allProviders.filter((p) => !p.configured);
    let html = '';
    if (configured.length) {
      html += '<optgroup label="Configured">' +
        configured.map((p) => `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('') +
        '</optgroup>';
    }
    if (unconfigured.length) {
      html += '<optgroup label="Presets (Needs Key)">' +
        unconfigured.map((p) => `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('') +
        '</optgroup>';
    }
    html += '<optgroup label="Local Engine"><option value="llama">Local Llama</option></optgroup>';
    provSel.innerHTML = html;
    modelSel.innerHTML = '';
    const refreshModels = () => {
      const pid = provSel.value;
      const p = allProviders.find((x) => x.id === pid);
      modelSel.innerHTML = (p && p.models && p.models.length
        ? p.models.map((m) => `<option value="${esc(m.id)}">${esc(m.id)}</option>`).join('')
        : `<option value="">${esc((p && p.defaultModelId) || (cfg.model || ''))}</option>`);
      if (saved.model && modelSel.querySelector(`option[value="${CSS.escape(saved.model)}"]`)) modelSel.value = saved.model;
    };
    provSel.value = (saved.provider && provSel.querySelector(`option[value="${CSS.escape(saved.provider)}"]`)) ? saved.provider : (cfg.provider || 'deepseek');
    provSel.addEventListener('change', refreshModels);
    refreshModels();
    state.chatProvider = provSel.value;
    state.chatModel = modelSel.value;
    provSel.addEventListener('change', () => {
      state.chatProvider = provSel.value; state.chatModel = modelSel.value;
      localStorage.setItem('conductor.chat', JSON.stringify({ provider: provSel.value, model: modelSel.value }));
    });
    modelSel.addEventListener('change', () => {
      state.chatModel = modelSel.value;
      localStorage.setItem('conductor.chat', JSON.stringify({ provider: provSel.value, model: modelSel.value }));
    });
    $('#composer-ai').hidden = false;
  } catch { /* keep bar hidden */ }
}

/* ------------------------------------------------------- auto-update UI */
function wireUpdates() {
  if (!window.desktop || !window.desktop.onUpdateEvent) return; // browser / non-Electron
  let downloadingVersion = null;
  const markReady = (version) => {
    if (!version) return;
    state.updateReady = { ready: true, version };
    const b = $('#btn-install-update');
    if (b) { b.hidden = false; }
    const st = $('#upd-status');
    if (st) st.textContent = `Conductor ${version} downloaded and ready — restart to install.`;
  };
  window.desktop.onUpdateEvent((ev) => {
    if (!ev || !ev.event) return;
    if (ev.event === 'update-available') {
      downloadingVersion = ev.version;
      toast(`Conductor ${ev.version} available — downloading…`, 'info');
    } else if (ev.event === 'download-progress') {
      const pct = Math.round(ev.percent || 0);
      const st = $('#upd-status');
      if (st) st.textContent = `Downloading Conductor ${downloadingVersion || ''}… ${pct}%`;
    } else if (ev.event === 'update-downloaded') {
      downloadingVersion = ev.version;
      markReady(ev.version);
      toast(`Conductor ${ev.version} ready — restart to install`, 'ok');
    } else if (ev.event === 'error') {
      toast(`Update check failed: ${ev.message}`, 'err');
      const st = $('#upd-status');
      if (st) st.textContent = `Update check failed: ${esc(ev.message)}`;
    }
  });
  // The main process can finish downloading during the ~30–90s backend cold
  // start, before this renderer loads — the update-downloaded event is then
  // missed. Reconcile against the main process's persisted state so a staged
  // update still surfaces as "ready to install" instead of "downloading…".
  if (window.desktop.getUpdateInfo) {
    window.desktop.getUpdateInfo().then((info) => {
      if (info && info.downloaded) markReady(info.downloaded);
    }).catch(() => {});
  }
}

/* ------------------------------------------------------- centralized data store
   One canonical data set per datatype (products, checks, people). Views read
   through ConductorData.get() and mutations call invalidateWarm() so a change
   anywhere is instantly visible on every page. See frontend/store.js. */
function warmLoad() {
  return (window.ConductorData || { preload: () => Promise.resolve() })
    .preload(['products', 'checks', 'people']);
}

function invalidateWarm() {
  if (!window.ConductorData) return;
  window.ConductorData.invalidate('products');
  window.ConductorData.invalidate('checks');
  window.ConductorData.invalidate('people');
}

async function boot() {
  window.__sidebarActiveView = state.view;
  if (window.ConductorSidebar) window.ConductorSidebar.renderSidebar();
  wireShell();
  wireUpdates();
  setSidebarState(localStorage.getItem('conductor.sidebar') || 'full');
  applyLayout(getLayout());
  const sw = localStorage.getItem('conductor.sidebarWidth');
  if (sw && state.sidebar === 'full') $('#sidebar').style.width = sw + 'px';
  const rw = localStorage.getItem('conductor.rightWidth');
  if (rw) $('#right-pane').style.width = rw + 'px';
  loadUiConfig().catch(() => {});
  loadFolderTree('');
  initAiComposer();
  initChatContext();
  await Promise.all([refreshCounts(), refreshStatusbar()]);
  warmLoad();
  setInterval(refreshStatusbar, 30000);
  applyGlass(getGlass());
}

/* ================================================================
   Variation Validator — family validation grid (Conductor-styled)
   ================================================================ */
const vvState = { rows: [], settings: { pts: '', themes: '', grocery: true } };

function vvLoadSettings() {
  const pts = localStorage.getItem('conductor.vv.pts')
    || 'CONDITIONER\nSHAMPOO\nHAIR_CLEANER_CONDITIONER\nHAIR_STYLING_AGENT\nSKIN_MOISTURIZER\nSKIN_CLEANING_AGENT\nGROCERY\nBEAUTY\nSHIRT';
  const themes = localStorage.getItem('conductor.vv.themes') || 'Size\nColor\nSizeColor\nFlavor\nScent\nCount\nStyleName';
  vvState.settings.pts = pts;
  vvState.settings.themes = themes;
  vvState.settings.grocery = localStorage.getItem('conductor.vv.grocery') !== 'false';
}

function vvSaveSettings() {
  localStorage.setItem('conductor.vv.pts', vvState.settings.pts);
  localStorage.setItem('conductor.vv.themes', vvState.settings.themes);
  localStorage.setItem('conductor.vv.grocery', vvState.settings.grocery ? 'true' : 'false');
}

/* tolerant CSV parser (comma or tab, quoted fields) */
function parseCsv(text) {
  const delim = (text.match(/\t/) ? '\t' : ',');
  const rows = [];
  let row = [], cur = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"') {
        if (text[i + 1] === '"') { cur += '"'; i++; } else q = false;
      } else cur += c;
    } else if (c === '"') q = true;
    else if (c === delim) { row.push(cur); cur = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(cur); cur = '';
      if (row.some((x) => x.trim() !== '')) rows.push(row);
      row = [];
    } else cur += c;
  }
  row.push(cur);
  if (row.some((x) => x.trim() !== '')) rows.push(row);
  return rows;
}

function vvGetVal(obj, keywords) {
  const key = Object.keys(obj).find((k) => keywords.some((kw) => k.toLowerCase().includes(kw)));
  return key ? String(obj[key] ?? '').trim() : '';
}

async function renderVariation() {
  const root = $('#view-root');
  vvLoadSettings();
  const rows = vvState.rows;
  const body = rows.length ? rows.map((r, i) => `
      <tr class="vv-row" data-i="${i}">
        <td class="vv-status"><span class="vv-pill">--</span></td>
        <td><input data-f="parent" value="${esc(r.parent)}" placeholder="Parent ASIN"></td>
        <td><input data-f="asin" value="${esc(r.asin)}" placeholder="Child ASIN"></td>
        <td><input data-f="brand" value="${esc(r.brand)}" placeholder="Brand"></td>
        <td><input data-f="category" value="${esc(r.category)}" placeholder="Category"></td>
        <td><input data-f="pt" value="${esc(r.pt)}" placeholder="Product Type"></td>
        <td><input data-f="theme" value="${esc(r.theme)}" placeholder="Theme"></td>
        <td><input data-f="form" value="${esc(r.form)}" placeholder="Item Form"></td>
        <td><input data-f="count" type="number" value="${esc(r.count)}"></td>
        <td class="vv-del"><button class="vv-x" data-del="${i}" title="Remove">&times;</button></td>
      </tr>`).join('')
    : `<tr><td colspan="10" class="vv-empty">No rows yet — import a CSV or add a manual row.</td></tr>`;

  root.innerHTML = `
    <div class="view">
      <div class="view-header">
        <div>
          <div class="view-title">Variation Validator</div>
          <div class="view-sub">Validate Amazon variation families — brand, category, product type, and theme must match across children; catch lone children and Item Form / Unit Count drift.</div>
        </div>
        <div class="view-actions">
          <button class="btn-secondary" id="vv-import"><span class="codicon codicon-cloud-upload"></span> Import CSV</button>
          <button class="btn-secondary" id="vv-add"><span class="codicon codicon-add"></span> Add row</button>
          <button class="btn-secondary" id="vv-settings"><span class="codicon codicon-settings-gear"></span> Rules</button>
          <button class="btn-primary" id="vv-export"><span class="codicon codicon-export"></span> Export CSV</button>
        </div>
      </div>
      <div class="vv-rulebar" id="vv-rulebar" hidden>
        <label class="vv-rule">Allowed product types<br><textarea id="vv-pts" rows="5">${esc(vvState.settings.pts)}</textarea></label>
        <label class="vv-rule">Allowed themes<br><textarea id="vv-themes" rows="5">${esc(vvState.settings.themes)}</textarea></label>
        <label class="vv-rule vv-toggle"><input type="checkbox" id="vv-grocery" ${vvState.settings.grocery ? 'checked' : ''}> Enforce "Grocery Aisle" test<br><small>Warn when Item Form / Unit Count vary within any family.</small></label>
      </div>
      <div class="vv-grid-wrap"><table class="data-table vv-table">
        <thead><tr><th class="vv-c-status">Status</th><th>Parent</th><th>ASIN</th><th>Brand</th><th>Category</th><th>Product Type</th><th>Theme</th><th>Item Form</th><th>Unit</th><th></th></tr></thead>
        <tbody>${body}</tbody></table></div>
      <div class="view-sub" style="margin:1rem 0 0.5rem">Diagnostic report</div>
      <div id="vv-report" class="vv-report"></div>
    </div>`;

  root.querySelector('#vv-import').addEventListener('click', () => {
    const inp = document.createElement('input');
    inp.type = 'file'; inp.accept = '.csv,.tsv';
    inp.onchange = () => {
      const f = inp.files && inp.files[0]; if (!f) return;
      const rd = new FileReader();
      rd.onload = () => {
        const grid = parseCsv(String(rd.result || ''));
        if (grid.length < 2) { toast('CSV has no data rows', 'err'); return; }
        const header = grid[0];
        const objs = grid.slice(1).map((cells) => {
          const o = {}; header.forEach((h, idx) => { o[String(h || '').trim()] = cells[idx] ?? ''; });
          return o;
        });
        let added = 0;
        objs.forEach((o) => {
          const parent = vvGetVal(o, ['target_parent', 'current_parent', 'parent']);
          const asin = vvGetVal(o, ['target_asin', 'current_asin', 'asin']);
          if (!parent && !asin) return;
          vvState.rows.push({
            parent, asin,
            brand: vvGetVal(o, ['brand']),
            category: vvGetVal(o, ['target_category', 'current_category', 'category']),
            pt: vvGetVal(o, ['target_product_type', 'current_product_type', 'product type', 'product_type']),
            theme: vvGetVal(o, ['target_theme', 'theme']),
            form: vvGetVal(o, ['target_item_form', 'current_item_form', 'item form', 'format']),
            count: vvGetVal(o, ['target_unit_count', 'current_unit_count', 'quantity', 'count']) || '1',
          });
          added++;
        });
        toast(`Imported ${added} rows`, 'ok');
        renderVariation();
      };
      rd.readAsText(f);
    };
    inp.click();
  });
  root.querySelector('#vv-add').addEventListener('click', () => {
    vvState.rows.push({ parent: '', asin: '', brand: '', category: '', pt: '', theme: '', form: '', count: '1' });
    renderVariation();
  });
  root.querySelector('#vv-settings').addEventListener('click', () => {
    const bar = root.querySelector('#vv-rulebar');
    bar.hidden = !bar.hidden;
  });
  root.querySelector('#vv-export').addEventListener('click', () => {
    if (!vvState.rows.length) { toast('Nothing to export', 'err'); return; }
    const head = ['parent','asin','brand','category','product_type','theme','item_form','unit_count'];
    const lines = [head.join(',')];
    vvState.rows.forEach((r) => lines.push([r.parent, r.asin, r.brand, r.category, r.pt, r.theme, r.form, r.count]
      .map((v) => '"' + String(v ?? '').replace(/"/g, '""') + '"').join(',')));
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'variations.csv'; a.click();
  });
  // settings persistence + live revalidation
  const bind = (sel, fn) => { const n = root.querySelector(sel); if (n) n.addEventListener('input', fn); };
  bind('#vv-pts', () => { vvState.settings.pts = root.querySelector('#vv-pts').value; vvSaveSettings(); });
  bind('#vv-themes', () => { vvState.settings.themes = root.querySelector('#vv-themes').value; vvSaveSettings(); });
  bind('#vv-grocery', () => { vvState.settings.grocery = root.querySelector('#vv-grocery').checked; vvSaveSettings(); vvValidate(root); });
  root.querySelectorAll('.vv-row input').forEach((inp) => inp.addEventListener('input', () => vvValidate(root)));
  root.querySelectorAll('.vv-x').forEach((b) => b.addEventListener('click', () => {
    vvState.rows.splice(Number(b.dataset.del), 1); renderVariation();
  }));
  vvValidate(root);
}

function vvValidate(root) {
  const rowEls = root.querySelectorAll('.vv-row');
  const families = {};
  rowEls.forEach((tr) => {
    const i = Number(tr.dataset.i);
    const r = vvState.rows[i];
    // read live inputs back into state
    r.parent = tr.querySelector('[data-f="parent"]').value.trim();
    r.asin = tr.querySelector('[data-f="asin"]').value.trim();
    r.brand = tr.querySelector('[data-f="brand"]').value.trim();
    r.category = tr.querySelector('[data-f="category"]').value.trim();
    r.pt = tr.querySelector('[data-f="pt"]').value.trim();
    r.theme = tr.querySelector('[data-f="theme"]').value.trim();
    r.form = tr.querySelector('[data-f="form"]').value.trim();
    r.count = tr.querySelector('[data-f="count"]').value.trim();
    tr.querySelectorAll('input').forEach((inp) => inp.closest('td').classList.remove('vv-cell-error', 'vv-cell-warn'));
    if (!r.parent) { tr.querySelector('.vv-pill').className = 'vv-pill vv-empty'; tr.querySelector('.vv-pill').textContent = '--'; return; }
    (families[r.parent] = families[r.parent] || []).push({ r, tr });
  });

  const report = root.querySelector('#vv-report');
  const cards = [];
  let pass = 0, fail = 0, warn = 0;
  for (const [parent, fam] of Object.entries(families)) {
    const base = fam[0].r;
    let status = 'pass', msgs = [];
    if (fam.length <= 1) { status = 'fail'; msgs.push('Variation families need more than 1 child ASIN.'); }
    for (let k = 1; k < fam.length; k++) {
      const c = fam[k].r;
      const flagCell = (f) => { const td = fam[k].tr.querySelector(`[data-f="${f}"]`).closest('td'); td.classList.add('vv-cell-error'); };
      if (c.brand !== base.brand) { status = 'fail'; msgs.push('Brand mismatch across children.'); flagCell('brand'); }
      if (c.category !== base.category) { status = 'fail'; msgs.push('Category mismatch across children.'); flagCell('category'); }
      if (c.pt !== base.pt) { status = 'fail'; msgs.push('Product Type mismatch across children.'); flagCell('pt'); }
      if (c.theme !== base.theme) { status = 'fail'; msgs.push('Theme mismatch across children.'); flagCell('theme'); }
      if (vvState.settings.grocery && c.form && base.form && c.form !== base.form) { if (status !== 'fail') status = 'warn'; msgs.push('Item Form varies within family.'); }
    }
    fam.forEach(({ tr }) => {
      const pill = tr.querySelector('.vv-pill');
      pill.className = `vv-pill vv-${status === 'pass' ? 'pass' : status === 'fail' ? 'fail' : 'warn'}`;
      pill.textContent = status === 'pass' ? 'PASS' : status === 'fail' ? 'FAIL' : 'WARN';
    });
    if (status === 'pass') pass++; else if (status === 'fail') fail++; else warn++;
    cards.push(`<div class="vv-card vv-${status}"><div class="vv-card-head"><span class="vv-pill vv-${status}">${status.toUpperCase()}</span> <span class="vv-parent mono">${esc(parent)}</span> <span class="vv-n">${fam.length} children</span></div><div class="vv-card-msgs">${msgs.map((m) => `<div>· ${esc(m)}</div>`).join('') || '<div>All variation attributes consistent.</div>'}</div></div>`);
  }
  report.innerHTML = `
    <div class="vv-summary">
      <span class="vv-sum vv-pass">${pass} pass</span>
      <span class="vv-sum vv-warn">${warn} warn</span>
      <span class="vv-sum vv-fail">${fail} fail</span>
      <span class="vv-sum">${families ? Object.keys(families).length : 0} families</span>
    </div>
    ${cards.join('') || '<div class="vv-empty">No families to validate — add rows with a parent ASIN.</div>'}`;
}

/* ================================================================
   Reports — management page + CDQ dashboard
   ================================================================ */
async function renderReports() {
  const root = $('#view-root');
  let list = [];
  try { list = (await api('/api/reports')).reports || []; } catch { /* */ }
  const rows = list.length ? list.map((r) => `
      <tr>
        <td class="mono">${esc(r.id)}</td>
        <td>${esc(r.title)}</td>
        <td><span class="chip-kind k-enrichment">${esc(r.kind)}</span></td>
        <td class="mono">${r.meta && r.meta.asin_count != null ? fmtNum(r.meta.asin_count) : '—'}</td>
        <td>${fmtTime(r.created_at)}</td>
        <td><button class="btn-mini" data-view-report="${r.id}">View</button> <button class="btn-mini btn-mini-danger" data-del-report="${r.id}">Delete</button></td>
      </tr>`).join('')
    : `<tr><td colspan="6" class="vv-empty">No reports yet — generate a CDQ Analysis to get started.</td></tr>`;
  root.innerHTML = `
    <div class="view">
      <div class="view-header">
        <div>
          <div class="view-title">Report Management</div>
          <div class="view-sub">Generate and review catalog reports. CDQ Analysis scores every product against listing-quality components and builds a priority action plan.</div>
        </div>
        <div class="view-actions">
          <button class="btn-primary" id="rpt-generate"><span class="codicon codicon-graph"></span> Generate CDQ Analysis</button>
        </div>
      </div>
      <div class="view-sub" style="margin:0 0 0.5rem">Reports</div>
      <table class="data-table"><thead><tr><th>#</th><th>Title</th><th>Kind</th><th>ASINs</th><th>Generated</th><th></th></tr></thead><tbody>${rows}</tbody></table>
    </div>`;
  root.querySelector('#rpt-generate').addEventListener('click', async () => {
    const btn = root.querySelector('#rpt-generate');
    btn.disabled = true; btn.textContent = 'Generating…';
    try {
      const res = await api('/api/reports/generate', { method: 'POST', body: { kind: 'cdq' } });
      toast(`CDQ Analysis generated`, 'ok');
      renderCdqReport(res.report, root);
    } catch (e) { toast(`Generate failed: ${e.message}`, 'err'); btn.disabled = false; btn.textContent = 'Generate CDQ Analysis'; }
  });
  root.querySelectorAll('[data-view-report]').forEach((b) => b.addEventListener('click', async () => {
    try {
      const res = await api(`/api/reports/${b.dataset.viewReport}`);
      renderCdqReport(res.report, root);
    } catch (e) { toast(`Load failed: ${e.message}`, 'err'); }
  }));
  root.querySelectorAll('[data-del-report]').forEach((b) => b.addEventListener('click', async () => {
    try { await api(`/api/reports/${b.dataset.delReport}`, { method: 'DELETE' }); toast('Report deleted', 'ok'); renderReports(); }
    catch (e) { toast(`Delete failed: ${e.message}`, 'err'); }
  }));
}

function renderCdqReport(report, root) {
  const d = report.data || {};
  const k = d.kpis || {};
  const gradeColors = { A: 'var(--t-function-success, #30A46C)', B: '#7dd3c0', C: 'var(--yellow, #F5A524)', D: '#ff6b6b', U: 'var(--red, #E5484D)' };
  const maxGrade = Math.max(1, ...(d.grades || []).map((g) => g.count));
  const grades = (d.grades || []).map((g) => `
      <div class="cdq-grade-row"><span class="cdq-grade-label mono">${esc(g.grade)}</span>
        <div class="cdq-bar"><div class="cdq-bar-fill" style="width:${(g.count / maxGrade * 100).toFixed(1)}%;background:${gradeColors[g.grade]}"></div></div>
        <span class="cdq-grade-n mono">${fmtNum(g.count)}</span></div>`).join('');
  const comps = (d.components || []).map((c) => `
      <div class="cdq-comp-row"><span class="cdq-comp-label">${esc(c.name)} <small>(${c.weight}%)</small></span>
        <div class="cdq-bar"><div class="cdq-bar-fill" style="width:${Math.min(100, c.score).toFixed(1)}%;background:${c.score >= 85 ? 'var(--t-function-success, #30A46C)' : c.score >= 70 ? 'var(--t-function-primary, #0053fd)' : 'var(--yellow, #F5A524)'}"></div></div>
        <span class="cdq-comp-n mono">${c.score}%</span></div>`).join('');
  const plan = (d.action_plan || []).map((p) => `
      <tr><td><span class="badge-grade b-${esc(p.priority.toLowerCase())}">${esc(p.priority)}</span></td><td>${esc(p.issue)}</td>
        <td class="mono">${fmtNum(p.asins)}</td><td class="mono">${p.pct}%</td><td style="font-size:0.75rem">${esc(p.action)}</td></tr>`).join('');
  const fixes = (d.top_fixes || []).map((f) => `
      <tr><td class="mono">${f.rank}</td><td class="mono">${esc(f.sku)}</td><td>${esc(f.brand)}</td>
        <td><span class="badge-grade b-${esc(f.grade.toLowerCase())}">${esc(f.grade)}</span></td><td style="font-size:0.75rem">${esc(f.issue)}</td></tr>`).join('');
  const findings = (d.findings || []).map((f) => `
      <div class="insight-box ${esc(f.tone)}"><strong>${esc(f.title)}</strong> — ${esc(f.body)}</div>`).join('');

  root.innerHTML = `
    <div class="view">
      <div class="view-header">
        <div>
          <div class="view-title">${esc(report.title)}</div>
          <div class="view-sub">Catalog Data Quality · generated ${fmtTime(report.created_at)} · ${fmtNum(k.total_asins || 0)} products</div>
        </div>
        <div class="view-actions"><button class="btn-secondary" id="cdq-back"><span class="codicon codicon-arrow-left"></span> Reports</button></div>
      </div>
      <div class="kpi-row">
        <div class="kpi-card"><div class="kpi-label">Total ASINs</div><div class="kpi-value">${fmtNum(k.total_asins || 0)}</div></div>
        <div class="kpi-card"><div class="kpi-label">CDQ Score</div><div class="kpi-value success">${k.cdq_score ?? '—'}%</div></div>
        <div class="kpi-card"><div class="kpi-label">Grade A</div><div class="kpi-value success">${k.grade_a_pct ?? 0}%</div></div>
        <div class="kpi-card"><div class="kpi-label">Priority ASINs</div><div class="kpi-value error">${fmtNum(k.priority_asins || 0)}</div></div>
        <div class="kpi-card"><div class="kpi-label">Brands</div><div class="kpi-value">${fmtNum(k.brands || 0)}</div></div>
      </div>
      <div class="cdq-grid">
        <div class="cdq-card"><div class="section-title">Grade Distribution</div>${grades}</div>
        <div class="cdq-card"><div class="section-title">Quality Components</div>${comps}</div>
      </div>
      <div class="cdq-card"><div class="section-title">Priority Action Plan</div>
        <table class="data-table"><thead><tr><th>Priority</th><th>Issue</th><th>ASINs</th><th>%</th><th>Action</th></tr></thead><tbody>${plan || '<tr><td colspan="5" class="vv-empty">No open action items.</td></tr>'}</tbody></table></div>
      <div class="cdq-card"><div class="section-title">Top products to fix first</div>
        <table class="data-table"><thead><tr><th>#</th><th>SKU</th><th>Brand</th><th>Grade</th><th>Issue &amp; fix</th></tr></thead><tbody>${fixes || '<tr><td colspan="5" class="vv-empty">Nothing to fix.</td></tr>'}</tbody></table></div>
      <div class="cdq-card"><div class="section-title">Key findings</div>${findings}</div>
    </div>`;
  root.querySelector('#cdq-back').addEventListener('click', renderReports);
}

/* ================================================================
   Attribute Guidelines — per-attribute / per-grouping rules
   ================================================================ */
let guidelinesCache = { list: [], attrs: [], opts: {} };

async function renderGuidelines() {
  const root = $('#view-root');
  try {
    const [g, a, o] = await Promise.all([api('/api/guidelines'), api('/api/guidelines/attributes'), api('/api/guidelines/options')]);
    guidelinesCache = { list: g.guidelines || [], attrs: a.attributes || [], opts: o };
  } catch (e) { toast(`Load failed: ${e.message}`, 'err'); }
  const list = guidelinesCache.list;
  // group by attribute for readability
  const byAttr = {};
  list.forEach((g) => { (byAttr[g.attribute] = byAttr[g.attribute] || []).push(g); });
  const groups = Object.entries(byAttr).map(([attr, gs]) => `
      <div class="guide-group">
        <div class="guide-group-head">${esc(attr)} <span class="guide-count">${gs.length}</span></div>
        ${gs.map((g) => `
          <div class="guide-row">
            <span class="guide-scope">${esc(g.grouping === 'all' ? 'all' : (g.grouping + (g.group_value ? ':' + g.group_value : '')))}</span>
            <span class="guide-rule mono">${esc(g.rule_type)}${g.rule_value ? ' = ' + esc(g.rule_value) : ''}</span>
            <span class="chip-kind k-${g.severity === 'blocker' ? 'flag' : g.severity === 'warning' ? 'flag' : 'enrichment'}">${esc(g.severity)}</span>
            ${g.enabled ? '' : '<span class="guide-off">off</span>'}
            <span class="guide-actions"><button class="btn-mini" data-edit-g="${g.id}">Edit</button> <button class="btn-mini btn-mini-danger" data-del-g="${g.id}">×</button></span>
          </div>`).join('')}
      </div>`).join('');
  root.innerHTML = `
    <div class="view">
      <div class="view-header">
        <div>
          <div class="view-title">Attribute Guidelines</div>
          <div class="view-sub">Set quality rules per attribute, scoped to any grouping (category, product type, market, brand, or global).</div>
        </div>
        <div class="view-actions"><button class="btn-primary" id="g-add"><span class="codicon codicon-add"></span> Add guideline</button></div>
      </div>
      ${groups || '<div class="vv-empty">No guidelines yet — add one to start enforcing attribute rules.</div>'}
    </div>`;
  root.querySelector('#g-add').addEventListener('click', () => openGuidelineForm(null));
  root.querySelectorAll('[data-edit-g]').forEach((b) => b.addEventListener('click', () => {
    const g = list.find((x) => x.id === Number(b.dataset.editG));
    if (g) openGuidelineForm(g);
  }));
  root.querySelectorAll('[data-del-g]').forEach((b) => b.addEventListener('click', async () => {
    try { await api(`/api/guidelines/${b.dataset.delG}`, { method: 'DELETE' }); toast('Guideline removed', 'ok'); renderGuidelines(); }
    catch (e) { toast(`Delete failed: ${e.message}`, 'err'); }
  }));
}

function openGuidelineForm(g) {
  const opts = guidelinesCache.opts || {};
  const ruleTypes = opts.rule_types || ['required', 'allowed_values', 'pattern', 'min_length', 'max_length', 'range'];
  const sevs = opts.severities || ['blocker', 'warning', 'info'];
  const groupings = opts.groupings || ['attribute', 'category', 'product_type', 'market', 'brand', 'all'];
  const attrs = guidelinesCache.attrs || [];
  const catVals = ((opts.group_values || {}).category) || [];
  const mktVals = ((opts.group_values || {}).market) || [];
  const grouping = g ? g.grouping : 'attribute';
  const groupValues = grouping === 'category' ? catVals : grouping === 'market' ? mktVals : [];

  const body = `
    <div class="form-grid">
      <label>Attribute<input id="g-attr" list="g-attr-list" value="${esc(g ? g.attribute : '')}" placeholder="e.g. color"></label>
      <datalist id="g-attr-list">${attrs.map((a) => `<option value="${esc(a)}">`).join('')}</datalist>
      <label>Scope / grouping<select id="g-grouping">${groupings.map((x) => `<option value="${esc(x)}" ${x === grouping ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select></label>
      <label id="g-gv-label" ${groupValues.length ? '' : 'hidden'}>Group value<select id="g-group-value">${groupValues.map((v) => `<option value="${esc(v)}" ${g && g.group_value === v ? 'selected' : ''}>${esc(v)}</option>`).join('')}<option value="">— any / custom —</option></select></label>
      <label>Rule type<select id="g-rule">${ruleTypes.map((x) => `<option value="${esc(x)}" ${g && g.rule_type === x ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select></label>
      <label>Rule value<textarea id="g-value" rows="2" placeholder="allowed values (one per line), regex, or min:max">${esc(g ? g.rule_value : '')}</textarea></label>
      <label>Severity<select id="g-severity">${sevs.map((x) => `<option value="${esc(x)}" ${g && g.severity === x ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select></label>
      <label>Note<input id="g-note" value="${esc(g ? g.note : '')}" placeholder="optional"></label>
      <label class="vv-toggle"><input type="checkbox" id="g-enabled" ${!g || g.enabled ? 'checked' : ''}> Enabled</label>
    </div>`;
  openModal(g ? 'Edit guideline' : 'Add guideline', body,
    `<button class="btn-secondary" onclick="closeModal()">Cancel</button>
     <button class="btn-primary" id="g-save">Save</button>`);
  $('#g-grouping').addEventListener('change', (e) => {
    const vals = e.target.value === 'category' ? catVals : e.target.value === 'market' ? mktVals : [];
    const lbl = $('#g-gv-label');
    lbl.hidden = vals.length === 0;
    if (vals.length) {
      $('#g-group-value').innerHTML = vals.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join('') + '<option value="">— any / custom —</option>';
    }
  });
  $('#g-save').addEventListener('click', async () => {
    const payload = {
      attribute: $('#g-attr').value.trim(),
      grouping: $('#g-grouping').value,
      group_value: $('#g-group-value') && !$('#g-gv-label').hidden ? $('#g-group-value').value : '',
      rule_type: $('#g-rule').value,
      rule_value: $('#g-value').value,
      severity: $('#g-severity').value,
      enabled: $('#g-enabled').checked,
      note: $('#g-note').value.trim(),
    };
    if (!payload.attribute) { toast('Attribute is required', 'err'); return; }
    try {
      if (g) await api(`/api/guidelines/${g.id}`, { method: 'PUT', body: payload });
      else await api('/api/guidelines', { method: 'POST', body: payload });
      closeModal(); toast('Guideline saved', 'ok'); renderGuidelines();
    } catch (e) { toast(`Save failed: ${e.message}`, 'err'); }
  });
}

document.addEventListener('DOMContentLoaded', boot);

/* ------------------------------------------------ panel style (glass opt-in) */
const glassKey = 'conductor.glass';
function getGlass() {
  return localStorage.getItem(glassKey) === '1';
}
function applyGlass(v) {
  document.body.classList.toggle('glass', !!v);
  localStorage.setItem(glassKey, v ? '1' : '0');
}

/* ==========================================================================
   MERGED FROM PARKER — full customization suite, ops views, ingest, layout
   ========================================================================== */

/* ---------------------------------------------------------------- helpers */
function fmtBytes(n) {
  if (n == null || isNaN(n)) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0, v = Number(n);
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${u[i]}`;
}
function fmtCount(n) {
  n = Number(n);
  if (!Number.isFinite(n)) return '—';
  if (n < 1000) return String(Math.round(n));
  const unit = n < 1e6 ? 1e3 : 1e6;
  return `${(n / unit).toFixed(1).replace(/\.0$/, '')}${n < 1e6 ? 'k' : 'M'}`;
}
function fmtDur(secs) {
  if (secs == null) return '0s';
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
}
function fmtAgo(iso) {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return null;
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return 'now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return '—';
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/* ------------------------------------------------ layout persistence */
const layoutKey = 'conductor.layout';
function getLayout() {
  try { return Object.assign({ sidebar: true, folders: true, statusbar: true }, JSON.parse(localStorage.getItem(layoutKey))); }
  catch { return { sidebar: true, folders: true, statusbar: true }; }
}
function applyLayout(l) {
  $('#sidebar').style.display = l.sidebar ? '' : 'none';
  $('#sash').style.display = l.sidebar ? '' : 'none';
  $('#right-pane').style.display = l.folders ? '' : 'none';
  $('#sash-r').style.display = l.folders ? '' : 'none';
  $('#statusbar').style.display = l.statusbar ? '' : 'none';
  const a = $('#s-show-sidebar'), b = $('#s-show-folders'), c = $('#s-show-statusbar');
  if (a) a.checked = l.sidebar;
  if (b) b.checked = l.folders;
  if (c) c.checked = l.statusbar;
}
function saveLayout() {
  localStorage.setItem(layoutKey, JSON.stringify({
    sidebar: $('#s-show-sidebar').checked,
    folders: $('#s-show-folders').checked,
    statusbar: $('#s-show-statusbar').checked,
  }));
  applyLayout(getLayout());
}

/* ------------------------------------------------ folder tree (expand in place) */
const folderState = { path: '', open: {} };
async function loadFolderTree(path = '') {
  folderState.path = path;
  const treeEl = $('#folder-tree');
  treeEl.innerHTML = '<div class="folder-loading">Loading…</div>';
  try {
    const data = await api(`/api/vault/tree?path=${encodeURIComponent(path)}`);
    renderBreadcrumb(path, data.root);
    renderFolderChildren(data, treeEl);
  } catch (e) {
    treeEl.innerHTML = `<div class="folder-error">${esc(e.message)}</div>`;
  }
}
function renderBreadcrumb(path, root) {
  const bc = $('#folder-breadcrumb');
  bc.innerHTML = '';
  const parts = path ? path.split('/') : [];
  const crumbs = [{ name: root, path: '' }];
  let acc = '';
  for (const p of parts) { acc = acc ? acc + '/' + p : p; crumbs.push({ name: p, path: acc }); }
  crumbs.forEach((c, i) => {
    if (i) bc.appendChild(el('span', 'bc-sep', ' / '));
    const b = el('button', `bc-crumb${i === crumbs.length - 1 ? ' current' : ''}`, c.name);
    b.addEventListener('click', () => { folderState.open = {}; loadFolderTree(c.path); });
    bc.appendChild(b);
  });
}
function folderRowForDir(d) {
  const row = el('div', 'folder-row');
  const isOpen = !!folderState.open[d.path];
  const counts = [];
  if (d.notes) counts.push(`<span class="codicon codicon-file-text"></span> ${d.notes}`);
  if (d.files) counts.push(`${d.files}`);
  if (d.buckets) counts.push(`<span class="codicon codicon-briefcase"></span> ${d.buckets}`);
  row.innerHTML = `
    <span class="folder-chevron">${isOpen ? '▾' : '▸'}</span>
    <span class="folder-ic codicon codicon-folder${isOpen ? '-opened' : ''}"></span>
    <span class="folder-name" title="${esc(d.path)}">${esc(d.name)}</span>
    <span class="folder-counts">${counts.join(' · ')}</span>`;
  row.addEventListener('click', () => toggleFolder(row, d));
  return row;
}
function fileRow(f) {
  const row = el('div', 'folder-row file');
  row.innerHTML = `
    <span class="folder-chevron"></span>
    <span class="folder-ic codicon codicon-file"></span>
    <span class="folder-name" title="${esc(f.name)}">${esc(f.name)}</span>
    <span class="folder-counts">${fmtBytes(f.size)}</span>`;
  row.addEventListener('click', () => toast(`${f.name} — ${fmtBytes(f.size)}`, 'info'));
  return row;
}
async function toggleFolder(row, d) {
  const isOpen = !!folderState.open[d.path];
  let childWrap = row.nextElementSibling;
  if (isOpen) {
    folderState.open[d.path] = false;
    row.querySelector('.folder-chevron').textContent = '▸';
    row.querySelector('.folder-ic').className = 'folder-ic codicon codicon-folder';
    if (childWrap && childWrap.classList.contains('folder-children')) childWrap.remove();
    return;
  }
  folderState.open[d.path] = true;
  row.querySelector('.folder-chevron').textContent = '▾';
  row.querySelector('.folder-ic').className = 'folder-ic codicon codicon-folder-opened';
  if (!childWrap || !childWrap.classList.contains('folder-children')) {
    childWrap = el('div', 'folder-children');
    childWrap.innerHTML = '<div class="folder-loading">…</div>';
    row.after(childWrap);
    try {
      const sub = await api(`/api/vault/tree?path=${encodeURIComponent(d.path)}`);
      renderFolderChildren(sub, childWrap);
    } catch (e) {
      childWrap.innerHTML = `<div class="folder-error">${esc(e.message)}</div>`;
    }
  }
}
function renderFolderChildren(data, container) {
  container.innerHTML = '';
  if (!data.dirs.length && !data.files.length) {
    container.appendChild(el('div', 'folder-empty', '(empty)'));
    return;
  }
  for (const d of data.dirs) container.appendChild(folderRowForDir(d));
  for (const f of data.files) container.appendChild(fileRow(f));
}
$('#pane-search').addEventListener('input', (e) => {
  const q = e.target.value.trim().toLowerCase();
  $$('#folder-tree .folder-row').forEach((r) => {
    const name = (r.querySelector('.folder-name')?.textContent || '').toLowerCase();
    r.style.display = !q || name.includes(q) ? '' : 'none';
  });
});

/* ------------------------------------------------ full design-token suite */
const uiKey = 'conductor.ui';
const uiState = { theme: 'custom', mode: 'dark', tokens: null, dirty: false, serverTheme: null, skins: {} };
let appearanceBuilt = false;

function uiCacheWrite() {
  try { localStorage.setItem(uiKey, JSON.stringify({ theme: uiState.theme, mode: uiState.mode, tokens: uiState.tokens })); } catch { /* ignore */ }
}
function uiCacheRead() {
  try { return JSON.parse(localStorage.getItem(uiKey)); } catch { return null; }
}
function uiApply() {
  const resolved = resolveUiBlob({ theme: uiState.theme, mode: uiState.mode, tokens: uiState.tokens });
  applyUiTokens(resolved.blob, resolved.theme, resolved.mode);
  return resolved;
}
function uiRefreshTokensFromCurrent() {
  uiState.tokens = deepClone(resolveUiBlob({ theme: uiState.theme, mode: uiState.mode, tokens: uiState.tokens }).blob);
}
async function loadUiConfig() {
  try {
    const c = await api('/api/ui/config');
    uiState.serverTheme = c;
    uiState.theme = c.theme || 'custom';
    uiState.mode = c.mode || 'dark';
    uiState.tokens = deepClone(c.tokens || THEME_DEFAULTS.tokens);
    uiState.skins = (c.skins && typeof c.skins === 'object') ? c.skins : {};
    uiRefreshTokensFromCurrent();
    uiApply();
    uiCacheWrite();
    if (appearanceBuilt) { renderAppearance(); renderSkins(); }
  } catch (e) {
    const cached = uiCacheRead();
    if (cached && cached.tokens) {
      uiState.theme = cached.theme || 'custom';
      uiState.mode = cached.mode || 'dark';
      uiState.tokens = deepClone(cached.tokens);
      uiApply();
    } else {
      uiState.tokens = deepClone(THEME_DEFAULTS.tokens);
      uiApply();
    }
    if (appearanceBuilt) { renderAppearance(); renderSkins(); }
  }
}
async function saveUiConfig() {
  const body = { theme: uiState.theme, mode: uiState.mode, tokens: uiState.tokens };
  const r = await api('/api/ui/config', { method: 'POST', body });
  uiState.serverTheme = r;
  uiState.dirty = false;
  uiCacheWrite();
  updateUiDirty();
  return r;
}
function updateUiDirty() {
  const n = $('#ui-dirty-note');
  if (!n) return;
  n.textContent = uiState.dirty ? '● unsaved changes' : (uiState.serverTheme ? 'saved' : '');
  n.style.color = uiState.dirty ? 'var(--yellow)' : 'var(--muted-fg)';
}
function updateThemeGridActive() {
  $$('#theme-grid .theme-card').forEach((c) => c.classList.toggle('active', c.dataset.theme === uiState.theme));
  $$('#theme-grid .t-check').forEach((c) => c.remove());
  const active = $('#theme-grid .theme-card.active .t-name');
  if (active) active.insertAdjacentHTML('beforeend', '<span class="t-check">✓</span>');
}
function selectTheme(name) {
  if (name === uiState.theme) return;
  if (name !== 'custom') {
    uiState.theme = name;
    uiRefreshTokensFromCurrent();
  } else {
    uiState.theme = 'custom';
    if (uiState.tokens) uiState.tokens.theme = 'custom';
  }
  uiState.dirty = true;
  uiApply();
  renderAppearance();
  updateUiDirty();
}
function onTokenChange() {
  if (uiState.theme !== 'custom') { uiState.theme = 'custom'; updateThemeGridActive(); }
  uiState.dirty = true;
  uiApply();
  updateUiDirty();
  updatePreviewLabel();
}
function resetTokens() {
  uiState.theme = 'custom';
  uiState.tokens = deepClone(THEME_DEFAULTS.tokens);
  uiState.dirty = true;
  uiApply();
  renderAppearance();
  updateUiDirty();
  toast('Tokens reset to the default custom palette — hit Save to persist', 'info');
}
async function copyUiJson() {
  const text = JSON.stringify(uiState.tokens, null, 2);
  try { await navigator.clipboard.writeText(text); }
  catch {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
  }
  toast('Theme JSON copied to clipboard', 'ok');
}
async function pasteUiJson() {
  try {
    const txt = await navigator.clipboard.readText();
    const v = JSON.parse(txt);
    if (typeof v !== 'object' || v === null) throw new Error('not a JSON object');
    uiState.theme = 'custom';
    uiState.tokens = deepClone(v);
    uiState.dirty = true;
    uiApply();
    renderAppearance();
    updateUiDirty();
    toast('Pasted — review and Save', 'info');
  } catch (e) { toast(`Paste failed: ${e.message}`, 'err'); }
}
function themePreviewHtml(t) {
  const bg = t.background1, side = t.background2, fg = t.colorFont.heading,
    muted = t.colorFont.muted, prim = t.function.primary;
  const css = (v) => esc(String(v));
  return `<div class="theme-preview" style="background:${css(bg)}">
    <div class="tp-side" style="background:${css(side)}"></div>
    <div class="tp-main">
      <div class="tp-bar" style="background:${css(fg)};width:55%"></div>
      <div class="tp-bar" style="background:${css(muted)};width:85%"></div>
      <div class="tp-bubble" style="background:${css(prim)}"></div>
    </div></div>`;
}
function buildPreview() {
  const p = $('#ui-preview');
  if (!p) return;
  p.innerHTML = `
    <div class="ui-preview-top">
      <span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
      <span class="pt" id="pv-mode">${uiState.mode} · Conductor</span>
    </div>
    <div class="ui-preview-body">
      <div class="ui-preview-side">
        <div class="ps-item on"></div><div class="ps-item on"></div><div class="ps-item"></div>
        <div class="ps-item"></div><div class="ps-item"></div>
      </div>
      <div class="ui-preview-main">
        <div class="pv-card">
          <div class="pv-h">Conductor · Automation</div>
          <div class="pv-t">3 automations · 6 AI workflows · 11 integrations</div>
          <div class="pv-btnrow">
            <button class="pv-btn">Run automation</button>
            <button class="pv-btn ghost">Folders</button>
            <span class="pv-chip ok">LIVE</span>
            <span class="pv-chip warn">SIM</span>
            <span class="pv-code">trigger → action</span>
          </div>
        </div>
        <div class="pv-card">
          <div class="pv-t"><b style="color:var(--green)">● connected</b> · Asana · Webhooks</div>
        </div>
      </div>
    </div>`;
}
function updatePreviewLabel() {
  const m = $('#pv-mode');
  if (m) m.textContent = `${uiState.mode} · Conductor`;
}
function tokenRow(def) {
  const row = el('div', 'token-row');
  const label = el('div', 'token-label');
  label.innerHTML = `${esc(def.label)} <code>${esc(def.path)}</code>`;
  row.appendChild(label);
  const ctl = el('div', 'token-ctl');
  const cur = getPath(uiState.tokens, def.path);
  if (def.type === 'color') {
    const sw = el('label', 'swatch');
    const picker = document.createElement('input');
    picker.type = 'color';
    sw.appendChild(picker);
    const txt = document.createElement('input');
    txt.type = 'text';
    txt.value = cur ?? '';
    txt.spellcheck = false;
    const commit = (v) => {
      setPath(uiState.tokens, def.path, v);
      sw.style.background = v;
      if (/^#[0-9a-fA-F]{3,8}$/.test(v)) picker.value = v;
      onTokenChange();
    };
    picker.addEventListener('input', () => { txt.value = picker.value; commit(picker.value); });
    txt.addEventListener('input', () => commit(txt.value));
    sw.style.background = cur ?? '';
    if (/^#[0-9a-fA-F]{3,8}$/.test(cur || '')) picker.value = cur;
    ctl.appendChild(sw);
    ctl.appendChild(txt);
  } else if (def.type === 'gradient') {
    const gv = el('div', 'grad-preview');
    gv.style.background = cur ?? '';
    const txt = document.createElement('input');
    txt.type = 'text';
    txt.value = cur ?? '';
    txt.spellcheck = false;
    txt.addEventListener('input', () => {
      gv.style.background = txt.value;
      setPath(uiState.tokens, def.path, txt.value);
      onTokenChange();
    });
    ctl.appendChild(gv);
    ctl.appendChild(txt);
  } else if (def.type === 'slider') {
    const rng = document.createElement('input');
    rng.type = 'range';
    rng.min = def.min; rng.max = def.max; rng.step = def.step || 0.01;
    rng.value = cur ?? def.min;
    const num = document.createElement('input');
    num.type = 'number';
    num.min = def.min; num.max = def.max; num.step = def.step || 0.01;
    num.value = cur ?? def.min;
    num.style.width = '4.5rem';
    const commit = (v) => { setPath(uiState.tokens, def.path, parseFloat(v)); onTokenChange(); };
    rng.addEventListener('input', () => { num.value = rng.value; commit(rng.value); });
    num.addEventListener('input', () => { rng.value = num.value; commit(num.value); });
    ctl.appendChild(rng);
    ctl.appendChild(num);
  } else if (def.type === 'number') {
    const num = document.createElement('input');
    num.type = 'number';
    if (def.min !== undefined) num.min = def.min;
    if (def.max !== undefined) num.max = def.max;
    num.step = def.step || 1;
    num.value = cur ?? '';
    num.addEventListener('input', () => { setPath(uiState.tokens, def.path, parseFloat(num.value)); onTokenChange(); });
    ctl.appendChild(num);
  } else if (def.type === 'checkbox') {
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = !!cur;
    cb.addEventListener('change', () => { setPath(uiState.tokens, def.path, cb.checked); onTokenChange(); });
    ctl.appendChild(cb);
  } else if (def.type === 'select') {
    const sel = document.createElement('select');
    for (const opt of def.options) {
      const o = el('option', '', opt);
      if (opt === cur) o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener('change', () => { setPath(uiState.tokens, def.path, sel.value); onTokenChange(); });
    ctl.appendChild(sel);
  } else if (def.type === 'json') {
    const ta = document.createElement('textarea');
    ta.className = 'token-json';
    ta.value = JSON.stringify(cur ?? {}, null, 2);
    ta.addEventListener('change', () => {
      try {
        const v = JSON.parse(ta.value);
        setPath(uiState.tokens, def.path, v);
        onTokenChange();
        toast('Overrides applied', 'ok');
      } catch { toast('Overrides JSON invalid — not applied', 'err'); }
    });
    row.appendChild(label);
    row.appendChild(ta);
    return row;
  } else {
    const txt = document.createElement('input');
    txt.type = 'text';
    txt.value = cur ?? '';
    txt.spellcheck = false;
    txt.addEventListener('input', () => { setPath(uiState.tokens, def.path, txt.value); onTokenChange(); });
    ctl.appendChild(txt);
  }
  row.appendChild(ctl);
  return row;
}
function renderAppearance() {
  const grid = $('#theme-grid');
  if (!grid) return;
  grid.innerHTML = '';
  const entries = [['custom', 'Custom', 'Your design-token blob — edit below'], ...Object.entries(THEME_PRESETS).map(([k, v]) => [k, v.label, v.desc])];
  for (const [name, label, desc] of entries) {
    const b = el('button', 'theme-card');
    b.dataset.theme = name;
    b.classList.toggle('active', uiState.theme === name);
    const blob = name === 'custom' ? uiState.tokens : (THEME_PRESETS[name][uiState.mode] || THEME_PRESETS[name].dark);
    b.innerHTML = `${themePreviewHtml(blob)}<div class="t-name">${esc(label)}${uiState.theme === name ? '<span class="t-check">✓</span>' : ''}</div><div class="t-desc">${esc(desc)}</div>`;
    b.addEventListener('click', () => selectTheme(name));
    grid.appendChild(b);
  }
  $$('#seg-mode .seg-btn').forEach((b) => b.classList.toggle('active', b.dataset.mode === uiState.mode));
  const ed = $('#token-editor');
  ed.innerHTML = '';
  for (const grp of TOKEN_SCHEMA) {
    const d = el('details', 'token-group');
    if (grp.label === 'Function colors' || grp.label === 'Gradients' || grp.label === 'Backgrounds') d.open = true;
    const sum = el('summary');
    sum.innerHTML = `${esc(grp.label)} <span class="tg-count">${grp.fields.length}</span>`;
    d.appendChild(sum);
    const body = el('div', 'tg-body');
    for (const f of grp.fields) body.appendChild(tokenRow(f));
    d.appendChild(body);
    ed.appendChild(d);
  }
  buildPreview();
  renderSkins();
  updateUiDirty();
  appearanceBuilt = true;
}
function renderSkins() {
  const list = $('#skins-list');
  if (!list) return;
  list.innerHTML = '';
  const names = Object.keys(uiState.skins || {}).sort((a, b) => a.localeCompare(b));
  if (!names.length) {
    list.appendChild(el('div', 'skins-empty', 'No skins saved yet — tune a theme, name it, and hit "Save current as skin".'));
    return;
  }
  for (const name of names) {
    const s = uiState.skins[name];
    const row = el('div', 'skin-row');
    const info = el('div', 'skin-info');
    const tag = el('span', 'skin-tag', (s.theme === 'custom' ? 'custom' : s.theme) + (s.mode === 'light' ? ' · light' : ''));
    const when = s.updated_at ? new Date(s.updated_at * 1000).toLocaleDateString() : '';
    info.appendChild(el('div', 'skin-name', name));
    const meta = el('div', 'skin-meta');
    meta.innerHTML = `${tag.outerHTML}${when ? ` · ${when}` : ''}`;
    info.appendChild(meta);
    row.appendChild(info);
    const actions = el('div', 'skin-actions');
    const load = el('button', 'btn-secondary', 'Load');
    load.style.flex = 'none';
    load.addEventListener('click', () => loadSkin(name));
    const del = el('button', 'btn-secondary', 'Delete');
    del.style.flex = 'none';
    del.addEventListener('click', () => deleteSkin(name));
    actions.appendChild(load);
    actions.appendChild(del);
    row.appendChild(actions);
    list.appendChild(row);
  }
}
async function saveSkin(name) {
  const n = String(name || '').trim();
  if (!n) { toast('Give the skin a name first', 'warn'); return; }
  try {
    const r = await api('/api/ui/skins', { method: 'POST', body: { name: n, theme: uiState.theme, mode: uiState.mode, tokens: uiState.tokens } });
    uiState.skins = r.skins || uiState.skins;
    renderSkins();
    toast(`Skin "${n}" saved`, 'ok');
  } catch (e) { toast(`Save skin failed: ${e.message}`, 'err'); }
}
function loadSkin(name) {
  const s = uiState.skins[name];
  if (!s) { toast(`Skin "${name}" not found`, 'err'); return; }
  uiState.theme = s.theme === 'custom' || THEME_PRESETS[s.theme] ? s.theme : 'custom';
  uiState.mode = s.mode === 'light' ? 'light' : 'dark';
  uiState.tokens = deepClone(s.tokens);
  uiRefreshTokensFromCurrent();
  uiState.dirty = true;
  uiApply();
  renderAppearance();
  renderSkins();
  updateUiDirty();
  toast(`Skin "${name}" loaded — Save theme to make it the default`, 'ok');
}
async function deleteSkin(name) {
  try {
    const r = await api(`/api/ui/skins/${encodeURIComponent(name)}`, { method: 'DELETE' });
    uiState.skins = r.skins || {};
    renderSkins();
    toast(`Skin "${name}" deleted`, 'ok');
  } catch (e) { toast(`Delete failed: ${e.message}`, 'err'); }
}
function syncJsonEditor() {
  const ta = $('#ui-json-editor');
  if (ta) ta.value = JSON.stringify({ theme: uiState.theme, mode: uiState.mode, tokens: uiState.tokens }, null, 2);
}
function applyJsonEditor(save) {
  try {
    const v = JSON.parse($('#ui-json-editor').value);
    if (typeof v !== 'object' || v === null || !v.tokens || typeof v.tokens !== 'object') {
      throw new Error('expected { theme, mode, tokens: {…} }');
    }
    uiState.theme = (v.theme === 'custom' || THEME_PRESETS[v.theme]) ? v.theme : 'custom';
    uiState.mode = v.mode === 'light' ? 'light' : 'dark';
    uiState.tokens = deepClone(v.tokens);
    uiState.dirty = true;
    uiApply();
    renderAppearance();
    const st = $('#ui-json-status');
    if (save) {
      saveUiConfig().then(() => { st.textContent = 'saved'; toast('Theme saved', 'ok'); }).catch((e) => { st.textContent = `save failed: ${e.message}`; });
    } else {
      st.textContent = 'applied';
      updateUiDirty();
    }
  } catch (e) {
    $('#ui-json-status').textContent = `invalid JSON: ${e.message}`;
  }
}

/* ------------------------------------------------ settings tab builders */
function renderAppearanceTab() {
  const box = $('#settings-content');
  box.innerHTML = `
    <div class="settings-pane active">
      <div class="appearance-head">
        <span class="ah-title"><span class="codicon codicon-palette"></span> Appearance</span>
        <div class="ah-actions">
          <button class="btn-secondary" id="btn-ui-reset" title="Restore the default custom palette">Reset</button>
          <button class="btn-primary" id="btn-ui-save">Save theme</button>
        </div>
      </div>
      <div class="settings-note">Every color, font, shadow and motion value in the UI comes from the design-token blob below — edit anything and it applies live. Changes persist to <code>data/ui.json</code> when you hit <b>Save theme</b>.</div>
      <div class="settings-section">
        <div class="settings-title">Color mode</div>
        <div class="seg" id="seg-mode">
          <button class="seg-btn" data-mode="dark" title="Dark mode"><span class="codicon codicon-color-mode"></span> Dark</button>
          <button class="seg-btn" data-mode="light" title="Light mode"><span class="codicon codicon-circle-outline"></span> Light</button>
        </div>
        <div class="settings-note" style="margin-top:0.375rem">Builtin themes ship both palettes; <b>Custom</b> uses the token values exactly as authored below.</div>
      </div>
      <div class="settings-section">
        <div class="settings-title">Panel style</div>
        <label class="check-row"><input type="checkbox" id="s-glass" /> <span>Glass panels (translucent + blur)</span></label>
        <div class="settings-note">Off by default — the default is flat, angular, bold. Toggle on for the frosted-glass treatment.</div>
      </div>
      <div class="settings-section">
        <div class="settings-title">Theme</div>
        <div class="theme-grid" id="theme-grid"></div>
      </div>
      <div class="settings-section">
        <div class="settings-title">Skins <span class="muted">— save &amp; load named themes</span></div>
        <div class="skin-save-row">
          <input id="skin-name" type="text" placeholder="Name this skin, e.g. Midnight Tweaked" />
          <button class="btn-secondary" id="btn-skin-save">Save current as skin</button>
        </div>
        <div class="skins-list" id="skins-list"></div>
        <div class="settings-note">Skins snapshot the full theme (preset + mode + tokens). They live in <code>data/ui.json</code> next to the active theme, so they survive restarts and ship with the app folder. Loading a skin applies it — hit <b>Save theme</b> to make it the active default.</div>
      </div>
      <div class="settings-section">
        <div class="settings-title">Design tokens <span class="muted">— live preview</span></div>
        <div class="token-editor" id="token-editor"></div>
      </div>
      <div class="settings-section">
        <div class="settings-title">Live preview</div>
        <div class="ui-preview" id="ui-preview"></div>
      </div>
      <div class="btn-row">
        <button class="btn-secondary" id="btn-ui-copy">Copy JSON</button>
        <button class="btn-secondary" id="btn-ui-paste">Paste JSON</button>
        <button class="btn-secondary" id="btn-ui-reset-tokens">Reset tokens</button>
        <span class="muted" id="ui-dirty-note" style="align-self:center"></span>
      </div>
    </div>`;

  if (!uiState.tokens) uiState.tokens = deepClone(THEME_DEFAULTS.tokens);
  renderAppearance();

  $$('#seg-mode .seg-btn').forEach((b) => b.addEventListener('click', () => {
    const m = b.dataset.mode;
    if (m === uiState.mode) return;
    uiState.mode = m;
    if (uiState.theme !== 'custom') uiRefreshTokensFromCurrent();
    else if (uiState.tokens) uiState.tokens.mode = m;
    uiState.dirty = true;
    uiApply();
    renderAppearance();
    updateUiDirty();
  }));
  $('#btn-ui-save').addEventListener('click', async () => {
    try { await saveUiConfig(); toast('Theme saved to data/ui.json', 'ok'); }
    catch (e) { toast(`Save failed: ${e.message}`, 'err'); }
  });
  $('#btn-ui-reset').addEventListener('click', resetTokens);
  $('#btn-ui-reset-tokens').addEventListener('click', resetTokens);
  $('#btn-ui-copy').addEventListener('click', copyUiJson);
  $('#btn-ui-paste').addEventListener('click', pasteUiJson);
  const glassBox = box.querySelector('#s-glass');
  if (glassBox) {
    glassBox.checked = getGlass();
    glassBox.addEventListener('change', () => applyGlass(glassBox.checked));
  }
  $('#btn-skin-save').addEventListener('click', () => saveSkin($('#skin-name').value));
  $('#skin-name').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); saveSkin($('#skin-name').value); } });
}
function renderLayoutTab() {
  const box = $('#settings-content');
  box.innerHTML = `
    <div class="settings-pane active">
      <div class="settings-section">
        <div class="settings-title"><span class="codicon codicon-layout"></span> Layout</div>
        <label class="check-row"><input type="checkbox" id="s-show-sidebar" /> <span>Sidebar (left nav)</span></label>
        <label class="check-row"><input type="checkbox" id="s-show-folders" /> <span>Folders panel (right)</span></label>
        <label class="check-row"><input type="checkbox" id="s-show-statusbar" /> <span>Status bar (bottom stats)</span></label>
        <div class="settings-note">The nav's full → rail → tucked collapse is separate — use the buttons in the nav's top bar. Drag the slim handles to resize panels; widths persist automatically.</div>
        <div class="settings-actions">
          <button class="btn-secondary" id="btn-reset-layout" style="flex:none">Reset layout</button>
        </div>
      </div>
    </div>`;
  applyLayout(getLayout());
  ['s-show-sidebar', 's-show-folders', 's-show-statusbar'].forEach((id) => {
    box.querySelector(`#${id}`).addEventListener('change', saveLayout);
  });
  box.querySelector('#btn-reset-layout').addEventListener('click', () => {
    localStorage.removeItem(layoutKey);
    localStorage.removeItem('conductor.sidebarWidth');
    localStorage.removeItem('conductor.rightWidth');
    $('#sidebar').style.width = '';
    $('#right-pane').style.width = '';
    applyLayout(getLayout());
    toast('Layout reset', 'ok');
  });
}
function renderAdvancedTab() {
  const box = $('#settings-content');
  box.innerHTML = `
    <div class="settings-pane active">
      <div class="settings-section">
        <div class="settings-title"><span class="codicon codicon-json"></span> Theme JSON</div>
        <div class="settings-note">The raw <code>{theme, mode, tokens}</code> blob that drives every pixel. Edit it, apply to preview, or save straight to <code>data/ui.json</code>.</div>
        <textarea id="ui-json-editor" class="token-json" rows="18" spellcheck="false"></textarea>
        <div class="settings-note" id="ui-json-status"></div>
        <div class="settings-actions">
          <button class="btn-secondary" id="btn-ui-json-apply" style="flex:none">Apply (preview)</button>
          <button class="btn-primary" id="btn-ui-json-save" style="flex:none">Apply + save</button>
        </div>
      </div>
    </div>`;
  syncJsonEditor();
  box.querySelector('#btn-ui-json-apply').addEventListener('click', () => applyJsonEditor(false));
  box.querySelector('#btn-ui-json-save').addEventListener('click', () => applyJsonEditor(true));
}

/* ------------------------------------------------ compliance & products */
function verdictClass(status) {
  return { fail: 'verdict-fail', review: 'verdict-review', pass: 'verdict-pass', not_applicable: 'verdict-pass' }[status] || 'verdict-pass';
}
function verdictLabel(status) {
  return { fail: 'FAIL', review: 'REVIEW', pass: 'PASS', not_applicable: 'N/A' }[status] || status || 'PASS';
}
function scoreClass(score) { return score >= 80 ? 'good' : score >= 50 ? 'warn' : 'bad'; }

function complianceReportHTML(product, checks) {
  const score = checks.length ? Math.round(checks.reduce((a, c) => a + (c.score || 0), 0) / checks.length) : 0;
  const verdict = score >= 80 ? 'pass' : score >= 50 ? 'review' : 'fail';
  return `
    <div class="report">
      <div class="report-summary">
        <div class="report-score">${score}</div>
        <div class="report-verdict ${verdictClass(verdict)}">${verdictLabel(verdict)}</div>
        <div class="report-note">${checks.length} regulation${checks.length === 1 ? '' : 's'} evaluated for <b>${esc(product.name)}</b> (${esc(product.sku)})</div>
      </div>
      ${checks.map((c) => `
        <div class="reg-row">
          <div class="reg-code">${esc(c.regulation)}</div>
          <div class="reg-name">${esc(c.severity || '')}</div>
          <div class="reg-status ${verdictClass(c.status)}">${verdictLabel(c.status)}</div>
          <div class="reg-score">${c.score}</div>
          ${(c.findings || []).length ? `
          <div class="reg-findings">
            ${c.findings.map((f) => `
              <div class="finding">
                <span class="finding-dot"></span>
                <div>
                  <div class="finding-title">${esc(f.title || f.label || '')}</div>
                  ${f.detail ? `<div class="finding-detail">${esc(f.detail)}</div>` : ''}
                  ${f.evidence ? `<div class="finding-evidence"><span class="codicon codicon-attach"></span> ${esc(f.evidence)}</div>` : ''}
                </div>
              </div>`).join('')}
          </div>` : ''}
        </div>`).join('')}
    </div>`;
}

const PRODUCT_CATEGORIES = ['general', 'electronics', 'wireless', 'toys', 'children', 'textile', 'cosmetics', 'food-contact', 'kitchen', 'personal-care', 'fashion'];

function openProductModal() {
  openModal('Check a product', `
    <div class="form-grid">
      <label class="field"><span>SKU *</span><input id="f-sku" placeholder="SKU-1234" /></label>
      <label class="field"><span>Name *</span><input id="f-name" placeholder="Product name" /></label>
      <div class="field-row">
        <label class="field"><span>Category</span>
          <select id="f-category">${PRODUCT_CATEGORIES.map((c) => `<option value="${c}">${c}</option>`).join('')}</select></label>
        <label class="field"><span>Market</span><input id="f-market" value="US" placeholder="US, EU, UK, CA" /></label>
      </div>
      <details class="field-advanced" open>
        <summary>Attributes (JSON)</summary>
        <textarea id="f-attrs" rows="5" spellcheck="false">{
  "voltage": 230,
  "wireless": false,
  "battery": false
}</textarea>
      </details>
    </div>`,
    `<button class="btn-primary" id="btn-save-product">Check compliance</button>`);
  $('#f-sku').focus();
  $('#btn-save-product').addEventListener('click', async () => {
    const sku = $('#f-sku').value.trim();
    const name = $('#f-name').value.trim();
    if (!sku || !name) return toast('SKU and name required', 'warn');
    let attrs = {};
    try { attrs = JSON.parse($('#f-attrs').value || '{}'); } catch { return toast('Attributes JSON is invalid', 'err'); }
    closeModal();
    await submitProduct({ sku, name, category: $('#f-category').value, market: $('#f-market').value.trim() || 'US', attributes: attrs });
  });
}

async function submitProduct(item) {
  try {
    const res = await api('/api/products', { method: 'POST', body: item });
    const comp = res.compliance || {};
    const score = comp.overall_score;
    toast(`"${item.sku}" checked — ${typeof score === 'number' ? score + '/100' : 'done'}`, typeof score === 'number' && score < 70 ? 'warn' : 'ok');
    showView('products');
    invalidateWarm();
    await renderProducts();
    renderProductDetail(res.product.id);
    refreshCounts();
  } catch (e) { toast(e.message, 'err'); }
}

async function submitBulk(items) {
  try {
    const res = await api('/webhooks/ingest', { method: 'POST', body: { products: items } });
    toast(`Bulk ingest accepted — ${res.created || 0} products checked`, 'ok');
    showView('products');
    invalidateWarm();
    await renderProducts();
    refreshCounts();
  } catch (e) { toast(e.message, 'err'); }
}

async function renderChecks() {
  const root = $('#view-root');
  root.innerHTML = `<div class="view">
    <div class="view-header">
      <div>
        <div class="view-title">Compliance Hub</div>
        <div class="view-sub">Catalog connection status, pending uploads, latest compliance evaluations, and AI-assisted Python script generator.</div>
      </div>
      <div class="view-actions">
        <button class="btn-primary" id="btn-new-check"><span class="codicon codicon-add"></span> Check a product</button>
      </div>
    </div>

    <!-- Source Connection & Upload Status Cards -->
    <div class="home-cards" style="margin-bottom:16px;">
      <div class="home-card">
        <div class="home-card-label">Catalog Connection</div>
        <div class="home-card-val" style="color:var(--t-function-success, #10b981);">Connected</div>
        <div style="font-size:0.75rem; color:var(--t-color-muted, #888);">Source: Local SQLite / Keepa / Files</div>
      </div>
      <div class="home-card">
        <div class="home-card-label">Pending Uploads</div>
        <div class="home-card-val" id="compl-pending-count">0 files</div>
        <div style="font-size:0.75rem; color:var(--t-color-muted, #888);">Ready for parsing</div>
      </div>
      <div class="home-card">
        <div class="home-card-label">Regulations Covered</div>
        <div class="home-card-val">12 Standards</div>
        <div style="font-size:0.75rem; color:var(--t-color-muted, #888);">CE, FCC, RoHS, REACH, GPSR...</div>
      </div>
    </div>

    <!-- AI Assisted Python Script Writing Panel -->
    <div class="card" style="padding:14px; margin-bottom:16px; background:var(--t-surface-raised, #1e1e2e);">
      <div style="font-weight:600; margin-bottom:8px;">🐍 AI-Assisted Compliance Python Script Writer:</div>
      <div style="display:flex; gap:8px;">
        <input type="text" id="compl-script-input" class="input-text" style="flex:1;"
               placeholder="Describe custom compliance rule (e.g. 'Write a Python script to verify REACH chemical safety for battery accessories')">
        <button class="btn-primary" id="btn-gen-compl-script">Generate Python Script</button>
      </div>
      <div id="compl-script-out" style="margin-top:10px; display:none;">
        <pre class="chat-code" id="compl-script-code" style="font-family:monospace; background:#111; padding:10px; border-radius:6px; overflow:auto; max-height:220px;"></pre>
      </div>
    </div>

    <div class="view-title" style="font-size:1.1rem; margin-bottom:8px;">Evaluated Product Checks</div>
    <div id="checks-body" class="data-table-wrap"><div class="folder-loading">Loading…</div></div>
  </div>`;

  root.querySelector('#btn-new-check').addEventListener('click', openProductModal);

  // Wire AI Python script generator button
  root.querySelector('#btn-gen-compl-script').addEventListener('click', () => {
    const prompt = root.querySelector('#compl-script-input').value.trim() || 'Verify product compliance requirements';
    const outBox = root.querySelector('#compl-script-out');
    const codeBox = root.querySelector('#compl-script-code');
    outBox.style.display = 'block';

    const generatedCode = `# Auto-generated AI Compliance Script
# Prompt: ${prompt}

import json
from datetime import datetime

def evaluate_compliance(product_data: dict) -> dict:
    sku = product_data.get("sku", "UNKNOWN")
    category = product_data.get("category", "electronics").lower()
    attributes = product_data.get("attributes", {})

    findings = []
    score = 100
    status = "pass"
    severity = "ok"

    # Rule check
    if "battery" in category or attributes.get("has_battery"):
        if not attributes.get("un38.3_certified"):
            findings.append("Missing UN38.3 lithium battery transportation certification")
            score -= 30
            status = "review"
            severity = "warning"

    if score < 70:
        status = "fail"
        severity = "blocker"

    return {
        "sku": sku,
        "regulation": "GPSR / Battery Safety",
        "status": status,
        "severity": severity,
        "score": max(score, 0),
        "findings": findings,
        "evaluated_at": datetime.utcnow().isoformat()
    }
`;
    codeBox.textContent = generatedCode;
    toast('Generated Python compliance script', 'info');
  });

  let rows;
  try { rows = await window.ConductorData.get('checks'); } catch (e) { toast(e.message, 'err'); rows = []; }
  const body = root.querySelector('#checks-body');
  if (!rows.length) {
    body.innerHTML = `<div class="empty-state">No checks yet — add a product (or paste <code>{"sku":…,"name":…}</code> into the composer) and it's evaluated against every regulation.</div>`;
    return;
  }
  body.innerHTML = `<table class="data-table">
    <tr><th>SKU</th><th>Product</th><th>Regulation</th><th>Verdict</th><th>Severity</th><th>Score</th></tr>
    ${rows.map((r) => `<tr class="row-click" data-id="${r.product.id}">
      <td class="mono">${esc(r.product.sku)}</td><td>${esc(r.product.name)}</td>
      <td class="mono">${esc(r.regulation)}</td>
      <td><span class="${verdictClass(r.status)}">${verdictLabel(r.status)}</span></td>
      <td>${esc(r.severity || '—')}</td>
      <td><span class="score-chip ${scoreClass(r.score)}">${r.score}</span></td></tr>`).join('')}
  </table>`;
  body.querySelectorAll('.row-click').forEach((tr) => tr.addEventListener('click', () => renderProductDetail(Number(tr.dataset.id))));
}

async function renderProducts() {
  const root = $('#view-root');
  root.innerHTML = `<div class="view"><div class="view-header"><div><div class="view-title">Products</div>
    <div class="view-sub">Every product in the local store, with its latest compliance evaluation.</div></div>
    <div class="view-actions"><button class="btn-primary" id="btn-new-product"><span class="codicon codicon-add"></span> New product</button></div></div>
    <div id="products-body" class="data-table-wrap"><div class="folder-loading">Loading…</div></div></div>`;
  root.querySelector('#btn-new-product').addEventListener('click', openProductModal);
  let prods;
  try { prods = await window.ConductorData.get('products'); } catch (e) { toast(e.message, 'err'); prods = []; }
  const body = root.querySelector('#products-body');
  if (!prods.length) {
    body.innerHTML = `<div class="empty-state">No products yet — add one, paste product JSON into the composer, or drop a catalog file anywhere in the app.</div>`;
    return;
  }
  body.innerHTML = `<table class="data-table">
    <tr><th>SKU</th><th>Name</th><th>Category</th><th>Market</th><th>Source</th><th>Added</th></tr>
    ${prods.map((p) => `<tr class="row-click" data-id="${p.id}">
      <td class="mono">${esc(p.sku)}</td><td><b>${esc(p.name)}</b></td>
      <td>${esc(p.category || '—')}</td><td>${esc(p.market || '—')}</td>
      <td>${esc(p.source || '—')}</td><td>${esc(timeAgo(p.created_at))}</td></tr>`).join('')}
  </table>`;
  body.querySelectorAll('.row-click').forEach((tr) => tr.addEventListener('click', () => renderProductDetail(Number(tr.dataset.id))));
}

async function renderProductDetail(id) {
  const root = $('#view-root');
  root.innerHTML = `<div class="view"><div class="view-header"><div><div class="view-title">Product detail</div></div>
    <div class="view-actions">
      <button class="btn-secondary" id="btn-back-prods">← Back</button>
      <button class="btn-secondary" id="btn-recheck"><span class="codicon codicon-refresh"></span> Re-check</button>
      <button class="btn-secondary" id="btn-del-prod"><span class="codicon codicon-trash"></span></button>
    </div></div>
    <div id="prod-detail" class="folder-loading" style="max-width:72rem;margin:0 auto">Loading…</div></div>`;
  const wrap = root.querySelector('#prod-detail');
  let data;
  try { data = await api(`/api/products/${id}`); } catch (e) { wrap.textContent = e.message; return; }
  const { product, checks } = data;
  wrap.className = '';
  wrap.innerHTML = `
    <div class="card">
      <div class="view-title">${esc(product.name)} <span class="muted mono" style="font-size:0.75rem">${esc(product.sku)}</span></div>
      <div class="detail-grid">
        <div class="detail-field"><span>Category</span><div>${esc(product.category || '—')}</div></div>
        <div class="detail-field"><span>Market</span><div>${esc(product.market || '—')}</div></div>
        <div class="detail-field"><span>Source</span><div>${esc(product.source || '—')}</div></div>
        <div class="detail-field"><span>Added</span><div>${esc(timeAgo(product.created_at))}</div></div>
      </div>
      <details class="field-advanced"><summary>Attributes (JSON)</summary>
        <pre class="chat-code">${esc(JSON.stringify(product.attributes || {}, null, 2))}</pre></details>
    </div>
    ${checks.length ? complianceReportHTML(product, checks) : '<div class="empty-state">No checks on record — hit Re-check.</div>'}`;
  root.querySelector('#btn-back-prods').addEventListener('click', renderProducts);
  root.querySelector('#btn-recheck').addEventListener('click', async () => {
    try { await api(`/api/products/${id}/check`, { method: 'POST' }); toast('Re-check complete', 'ok'); invalidateWarm(); renderProductDetail(id); }
    catch (e) { toast(e.message, 'err'); }
  });
  root.querySelector('#btn-del-prod').addEventListener('click', async () => {
    if (!confirm(`Delete product ${product.sku}?`)) return;
    try { await api(`/api/products/${id}`, { method: 'DELETE' }); toast('Deleted', 'ok'); invalidateWarm(); renderProducts(); refreshCounts(); }
    catch (e) { toast(e.message, 'err'); }
  });
}

async function renderCatalog() {
  const root = $('#view-root');
  root.innerHTML = `<div class="view"><div class="view-header"><div><div class="view-title">Catalog</div>
    <div class="view-sub">File ingestion pipeline — chunked resumable uploads, format-aware parsing (Keepa, CDQ, Amazon listings, CSV/TSV/JSON/NDJSON).</div></div>
    <div class="view-actions"><button class="btn-primary" id="btn-upload-cat"><span class="codicon codicon-cloud-upload"></span> Upload catalog</button></div></div>
    <div id="cat-body" class="data-table-wrap"><div class="folder-loading">Loading…</div></div></div>`;
  root.querySelector('#btn-upload-cat').addEventListener('click', () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.csv,.tsv,.json,.ndjson,.jsonl,.xlsx,.xlsm,.xls';
    input.onchange = () => { if (input.files[0]) ingestFile(input.files[0]); };
    input.click();
  });
  let files = [];
  try { files = await api('/api/files?limit=100'); } catch (e) { toast(e.message, 'err'); }
  const body = root.querySelector('#cat-body');
  if (!files.length) {
    body.innerHTML = `<div class="empty-state">No uploads yet — drop a catalog file anywhere in the app or hit Upload.</div>`;
    return;
  }
  body.innerHTML = `<table class="data-table">
    <tr><th>File</th><th>Status</th><th>Records</th><th>Size</th><th>Error</th><th>Uploaded</th></tr>
    ${files.map((f) => `<tr>
      <td>${esc(f.filename)}</td>
      <td><span class="pill-int pill-int-${f.status === 'done' ? 'configured' : f.status === 'error' ? 'unconfigured' : 'simulated'}">${esc(f.status)}</span></td>
      <td>${f.record_count || '—'}</td><td>${fmtBytes(f.total_size)}</td>
      <td class="muted">${esc(f.error || '')}</td><td>${esc(timeAgo(f.created_at))}</td></tr>`).join('')}
  </table>`;
}

async function renderAgents() {
  const root = $('#view-root');
  root.innerHTML = `<div class="view"><div class="view-header"><div><div class="view-title">Agents</div>
    <div class="view-sub">Specialized workspace agents — run a quick action against their real workspace artifacts.</div></div></div>
    <div class="gallery-grid" id="agents-grid"><div class="folder-loading">Loading…</div></div>
    <div id="agent-result"></div></div>`;
  let agents = [];
  try { agents = await api('/api/agents'); } catch (e) { toast(e.message, 'err'); }
  const grid = root.querySelector('#agents-grid');
  if (!agents.length) { grid.innerHTML = '<div class="empty-state">No agents discovered.</div>'; return; }
  grid.innerHTML = agents.map((a) => `
    <div class="agent-card">
      <div class="agent-card-top">
        <span class="agent-avatar" style="background:${esc(a.color || 'var(--t-function-primary)')}"><span class="codicon codicon-robot"></span></span>
        <div class="agent-name">${esc(a.name)}</div>
      </div>
      <div class="agent-tagline">${esc(a.tagline || '')}</div>
      <div class="agent-desc">${esc(a.description || '')}</div>
      <div class="agent-card-actions">
        <button class="btn-secondary btn-sm btn-agent-run" data-id="${esc(a.id)}"><span class="codicon codicon-play"></span> ${esc(a.quick_action || 'Run')}</button>
      </div>
      <div class="settings-note">${esc(a.prompt_hint || '')}</div>
    </div>`).join('');
  grid.querySelectorAll('.btn-agent-run').forEach((b) => b.addEventListener('click', () => runQuickAction(b.dataset.id, root.querySelector('#agent-result'))));
}

async function runQuickAction(agentId, resultEl) {
  resultEl.innerHTML = '<div class="folder-loading">Running quick action…</div>';
  try {
    const res = await api(`/api/agents/${agentId}/run`, { method: 'POST' });
    const text = typeof res === 'string' ? res : JSON.stringify(res, null, 2);
    resultEl.innerHTML = `<div class="card"><div class="view-title">Quick action result</div>
      <pre class="chat-code">${esc(text)}</pre></div>`;
    toast('Quick action finished', 'ok');
  } catch (e) {
    resultEl.innerHTML = `<div class="card"><div class="settings-note">⚠ ${esc(e.message)}</div></div>`;
    toast(e.message, 'err');
  }
}

async function renderTasksView() {
  const root = $('#view-root');
  root.innerHTML = `<div class="view"><div class="view-header"><div><div class="view-title">Action Queue</div>
    <div class="view-sub">Tasks triaged from Obsidian daily notes and the workspace.</div></div>
    <div class="view-actions">
      <button class="btn-secondary" id="btn-tasks-import"><span class="codicon codicon-cloud-download"></span> Import from Obsidian</button>
      <button class="btn-secondary" id="btn-tasks-clear">Clear done</button>
    </div></div>
    <div id="tasks-body" class="data-table-wrap"><div class="folder-loading">Loading…</div></div></div>`;
  root.querySelector('#btn-tasks-import').addEventListener('click', async () => {
    try {
      const r = await api('/api/tasks/import', { method: 'POST' });
      toast(`Scanned ${r.scanned}, inserted ${r.inserted}`, 'ok');
      renderTasksView();
      refreshCounts();
    } catch (e) { toast(e.message, 'err'); }
  });
  root.querySelector('#btn-tasks-clear').addEventListener('click', async () => {
    try { await api('/api/tasks/clear-done', { method: 'POST' }); toast('Cleared done tasks', 'ok'); renderTasksView(); }
    catch (e) { toast(e.message, 'err'); }
  });
  let tasks = [];
  try { tasks = await api('/api/tasks?limit=500'); } catch (e) { toast(e.message, 'err'); }
  const body = root.querySelector('#tasks-body');
  if (!tasks.length) { body.innerHTML = '<div class="empty-state">Queue is empty — import from Obsidian or let the automation engine open tasks.</div>'; return; }
  body.innerHTML = `<table class="data-table">
    <tr><th></th><th>Priority</th><th>Task</th><th>Source</th><th>Status</th><th>Created</th></tr>
    ${tasks.map((t) => `<tr>
      <td>${t.status === 'open'
        ? `<button class="btn-secondary btn-sm btn-task-done" data-id="${t.id}" title="Mark done">✓</button>`
        : `<button class="btn-secondary btn-sm btn-task-open" data-id="${t.id}" title="Reopen">↺</button>`}</td>
      <td><span class="mono">${esc(t.priority || 'P2')}</span></td>
      <td>${esc(t.text)}</td>
      <td class="muted">${esc(t.source || '—')}</td>
      <td><span class="pill-status pill-${esc(t.status)}">${esc(t.status)}</span></td>
      <td>${esc(timeAgo(t.created_at))}</td></tr>`).join('')}
  </table>`;
  const toggle = async (id, status) => {
    try { await api(`/api/tasks/${id}`, { method: 'PATCH', body: { status } }); renderTasksView(); refreshCounts(); }
    catch (e) { toast(e.message, 'err'); }
  };
  body.querySelectorAll('.btn-task-done').forEach((b) => b.addEventListener('click', () => toggle(Number(b.dataset.id), 'done')));
  body.querySelectorAll('.btn-task-open').forEach((b) => b.addEventListener('click', () => toggle(Number(b.dataset.id), 'open')));
}

async function renderRegs() {
  const root = $('#view-root');
  root.innerHTML = `<div class="view"><div class="view-header"><div><div class="view-title">Policy</div>
    <div class="view-sub">The regulation catalog enforced by the compliance engine.</div></div></div>
    <div id="regs-body" class="data-table-wrap"><div class="folder-loading">Loading…</div></div></div>`;
  let regs = [];
  try { regs = await api('/api/regulations'); } catch (e) { toast(e.message, 'err'); }
  const body = root.querySelector('#regs-body');
  if (!regs.length) { body.innerHTML = '<div class="empty-state">No regulations catalog available.</div>'; return; }
  body.innerHTML = `<table class="data-table">
    <tr><th>Code</th><th>Regulation</th><th>Markets</th><th>Applies to</th></tr>
    ${regs.map((r) => `<tr>
      <td><span class="score-chip good mono">${esc(r.code)}</span></td>
      <td><b>${esc(r.name)}</b><div class="muted" style="font-size:0.6875rem">${esc(r.description || '')}</div></td>
      <td>${esc(Array.isArray(r.markets) ? r.markets.join(', ') : r.markets || '—')}</td>
      <td>${esc(r.applies_to || '—')}</td></tr>`).join('')}
  </table>`;
}

/* ------------------------------------------------ composer + ingest */
function parseComposer(text) {
  const t = (text || '').trim();
  if (t.startsWith('{') || t.startsWith('[')) {
    try {
      const obj = JSON.parse(t);
      if (Array.isArray(obj)) return { type: 'bulk', items: obj };
      if (obj && typeof obj === 'object' && (obj.sku || obj.name)) return { type: 'product', item: obj };
    } catch { /* fall through to chat */ }
  }
  return { type: 'chat' };
}
async function handleComposerSubmit() {
  const text = $('#composer-input').value.trim();
  if (!text) return;
  const parsed = parseComposer(text);
  if (parsed.type === 'chat') return sendChat();
  if (parsed.type === 'product') await submitProduct(parsed.item);
  else await submitBulk(parsed.items);
}
function pollJob(jobId, onUpdate, intervalMs = 800) {
  const timer = setInterval(async () => {
    try {
      const j = await api(`/api/jobs/${jobId}`);
      onUpdate(j);
      if (j.status === 'done' || j.status === 'error') clearInterval(timer);
    } catch { clearInterval(timer); }
  }, intervalMs);
  return timer;
}
async function ingestFile(file) {
  const bar = $('#upload-bar');
  bar.hidden = false;
  $('#upload-name').textContent = file.name;
  $('#upload-progress-label').textContent = '0%';
  $('#upload-fill').style.width = '0%';
  $('#upload-status').textContent = 'Uploading…';
  try {
    let jobId = null;
    if (file.size <= 20 * 1024 * 1024) {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch('/api/ingest/upload', { method: 'POST', body: fd });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
      const data = await res.json();
      jobId = data.job_id;
      $('#upload-fill').style.width = '100%';
      $('#upload-progress-label').textContent = '100%';
      $('#upload-status').textContent = `Parsed ${data.rows} rows — ingesting…`;
    } else {
      const init = await api('/api/ingest/init', { method: 'POST', body: { filename: file.name, total_size: file.size } });
      const chunkSize = init.chunk_size || 4 * 1024 * 1024;
      const total = Math.ceil(file.size / chunkSize);
      for (let i = 0; i < total; i++) {
        const chunk = file.slice(i * chunkSize, Math.min((i + 1) * chunkSize, file.size));
        const res = await fetch(`/api/ingest/${init.upload_id}/chunk/${i}`, { method: 'PUT', body: chunk });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `chunk ${i} failed`);
        const pct = Math.round(((i + 1) / total) * 100);
        $('#upload-fill').style.width = pct + '%';
        $('#upload-progress-label').textContent = pct + '%';
      }
      const done = await api(`/api/ingest/${init.upload_id}/complete`, { method: 'POST' });
      jobId = done.job_id || done.id;
      $('#upload-status').textContent = 'Uploaded — parsing & ingesting…';
    }
    if (jobId != null) {
      pollJob(jobId, (j) => {
        $('#upload-status').textContent = `${Math.round(j.progress || 0)}% — ${esc(j.message || j.status)}`;
        if (j.status === 'done') {
          toast('Ingest complete', 'ok');
          setTimeout(() => { bar.hidden = true; }, 2500);
          refreshCounts();
          warmLoad();
          if (state.view === 'catalog') renderCatalog();
        } else if (j.status === 'error') {
          toast(`Ingest failed: ${j.message}`, 'err');
          setTimeout(() => { bar.hidden = true; }, 4000);
        }
      });
    }
  } catch (e) {
    $('#upload-status').textContent = `Failed: ${e.message}`;
    toast(`Upload failed: ${e.message}`, 'err');
    setTimeout(() => { bar.hidden = true; }, 5000);
  }
}

/* ------------------------------------------------ global wiring (ported) */
document.querySelector('.titlebar').addEventListener('dblclick', (e) => {
  if (window.desktop && !e.target.closest('button')) window.desktop.toggleMaximize();
});
document.addEventListener('keydown', (e) => {
  if (e.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
    e.preventDefault();
    $('#sidebar-search-input').focus();
  } else if (e.key === 'Escape') {
    $('#sidebar-search-input').blur();
  }
});

// Sash resize — left nav
const sashEl = $('#sash');
let sashDrag = false;
sashEl.addEventListener('mousedown', (e) => { sashDrag = true; document.body.style.cursor = 'col-resize'; e.preventDefault(); });
window.addEventListener('mousemove', (e) => {
  if (!sashDrag) return;
  $('#sidebar').style.width = Math.max(200, Math.min(360, e.clientX)) + 'px';
});
window.addEventListener('mouseup', () => {
  if (sashDrag) localStorage.setItem('conductor.sidebarWidth', $('#sidebar').style.width);
  sashDrag = false;
  document.body.style.cursor = '';
});
// Sash resize — right pane
const sashREl = $('#sash-r');
let sashDragR = false;
sashREl.addEventListener('mousedown', (e) => { sashDragR = true; document.body.style.cursor = 'col-resize'; e.preventDefault(); });
window.addEventListener('mousemove', (e) => {
  if (!sashDragR) return;
  $('#right-pane').style.width = Math.max(240, Math.min(480, window.innerWidth - e.clientX)) + 'px';
});
window.addEventListener('mouseup', () => {
  if (sashDragR) localStorage.setItem('conductor.rightWidth', $('#right-pane').style.width);
  sashDragR = false;
  document.body.style.cursor = '';
});

// Auto-refresh data-heavy views while visible
setInterval(() => {
  if (state.view === 'requests') renderRequests();
  if (state.view === 'catalog') renderCatalog();
}, 4000);


/* ==========================================================================
   BERNIE MERGE — full-page node-based flow canvas (faithful port of the
   AI Studio app: full-window stage, floating/flat side panels, its own
   theme environment with presets + customization, grid & minimap, pan/
   select modes, zoom, context menus, inspect dialogs)
   ========================================================================== */
const BERNIE_NODE_TYPES = {
  trigger: { icon: 'codicon-play', label: 'Trigger', defaultData: {} },
  text: { icon: 'codicon-quote', label: 'Text', defaultData: { text: 'Hello from Text' } },
  json: { icon: 'codicon-json', label: 'JSON', defaultData: { jsonData: '{\n  "key": "value"\n}' } },
  http: { icon: 'codicon-globe', label: 'HTTP', defaultData: { url: 'https://httpbin.org/get', method: 'GET' } },
  ai: { icon: 'codicon-chat-sparkle', label: 'AI', defaultData: { prompt: 'Summarize the input data' } },
  script: { icon: 'codicon-code', label: 'Script', defaultData: { script: 'return { length: String(data && data.text ? data.text : JSON.stringify(data || {})).length }' } },
  sheet: { icon: 'codicon-table', label: 'Sheet', defaultData: { spreadsheetId: '', sheetName: '' } },
  drive: { icon: 'codicon-folder-library', label: 'Drive', defaultData: { fileId: '' } },
  custom: { icon: 'codicon-tools', label: 'Custom', defaultData: {} },
  flush: { icon: 'codicon-output', label: 'Flush', defaultData: {} },
};

/* LAW canvasNodeTypeRegistry port: plugins register extra node types here
 * via PluginAPI.registerCanvasNodeType; they appear in the Bernie palette. */
window.BernieNodeTypes = {
  register(type, cfg) {
    if (!type) return;
    const meta = cfg.component ? { icon: cfg.icon || 'codicon-extensions', label: cfg.label || type, defaultData: cfg.defaultData || {}, plugin: cfg } : cfg;
    BERNIE_NODE_TYPES[type] = meta;
    if (cfg.component && !BERNIE_NODE_META[type]) BERNIE_NODE_META[type] = { desc: cfg.desc || 'Plugin node', color: cfg.color || '#8b5cf6' };
  },
  list() { return Object.entries(BERNIE_NODE_TYPES).map(([t, m]) => ({ type: t, meta: m })); },
};

/* palette metadata — descriptions + per-type accent colors (from Bernie) */
const BERNIE_NODE_META = {
  trigger: { desc: 'Start the workflow', color: '#22c55e' },
  text: { desc: 'Add instructions', color: '#60a5fa' },
  json: { desc: 'Inject static payload', color: '#a1a1aa' },
  script: { desc: 'Run JavaScript logic', color: '#facc15' },
  http: { desc: 'Fetch external API', color: '#34d399' },
  ai: { desc: 'Execute LLM prompt', color: '#a855f7' },
  custom: { desc: 'Integration hook', color: '#f472b6' },
  flush: { desc: 'Terminates flow data', color: '#f87171' },
  sheet: { desc: 'Export data', color: '#4ade80' },
  drive: { desc: 'Read/write files', color: '#fb923c' },
};

/* ------------------------------------------------------------------ theme
   Bernie's own theme environment — scoped to the canvas via CSS vars on
   .bernie-view, persisted separately from Conductor's app theme.
   ------------------------------------------------------------------ */
const BERNIE_THEME_DEFAULT = {
  background: { primary: '#09090b', secondary: '#18181b' },
  gradient: { primary: 'none', secondary: 'none' },
  surface: '#27272a',
  text: '#fafafa',
  transparency: '90',
  density: 'comfortable',
  edges: 'rounded',
  highlight: '#6366f1',
  brightness: '100',
  depth: 'elevated',
};

const BERNIE_THEME_PRESETS = {
  'dark-default': { name: 'Dark Default', theme: BERNIE_THEME_DEFAULT },
  light: { name: 'Clean Light', theme: { background: { primary: '#ffffff', secondary: '#f4f4f5' }, gradient: { primary: 'none', secondary: 'none' }, surface: '#ffffff', text: '#09090b', transparency: '95', density: 'comfortable', edges: 'rounded', highlight: '#3b82f6', brightness: '100', depth: 'shadow' } },
  cyberpunk: { name: 'Cyberpunk', theme: { background: { primary: '#0d0221', secondary: '#261447' }, gradient: { primary: 'none', secondary: 'none' }, surface: '#261447', text: '#00ff41', transparency: '90', density: 'compact', edges: 'sharp', highlight: '#ff003c', brightness: '110', depth: 'flat' } },
  ocean: { name: 'Deep Ocean', theme: { background: { primary: '#0f172a', secondary: '#1e293b' }, gradient: { primary: 'linear-gradient(to right, #0f172a, #1e293b)', secondary: 'none' }, surface: '#1e293b', text: '#e2e8f0', transparency: '85', density: 'spacious', edges: 'pill', highlight: '#38bdf8', brightness: '100', depth: 'elevated' } },
  forest: { name: 'Forest Canopy', theme: { background: { primary: '#14532d', secondary: '#166534' }, gradient: { primary: 'none', secondary: 'none' }, surface: '#166534', text: '#f0fdf4', transparency: '90', density: 'comfortable', edges: 'rounded', highlight: '#4ade80', brightness: '95', depth: 'shadow' } },
  sunset: { name: 'Sunset Glow', theme: { background: { primary: '#450a0a', secondary: '#7f1d1d' }, gradient: { primary: 'linear-gradient(to right, #7f1d1d, #ea580c)', secondary: 'none' }, surface: '#7f1d1d', text: '#fffbeb', transparency: '90', density: 'spacious', edges: 'rounded', highlight: '#fcd34d', brightness: '105', depth: 'elevated' } },
  dracula: { name: 'Dracula', theme: { background: { primary: '#282a36', secondary: '#44475a' }, gradient: { primary: 'none', secondary: 'none' }, surface: '#44475a', text: '#f8f8f2', transparency: '100', density: 'comfortable', edges: 'rounded', highlight: '#bd93f9', brightness: '100', depth: 'shadow' } },
  synthwave: { name: 'Synthwave', theme: { background: { primary: '#2a2139', secondary: '#34294f' }, gradient: { primary: 'linear-gradient(to bottom, #2a2139, #34294f)', secondary: 'none' }, surface: '#34294f', text: '#f97e72', transparency: '80', density: 'spacious', edges: 'sharp', highlight: '#ff7edb', brightness: '110', depth: 'elevated' } },
  monochrome: { name: 'Monochrome', theme: { background: { primary: '#000000', secondary: '#111111' }, gradient: { primary: 'none', secondary: 'none' }, surface: '#111111', text: '#ffffff', transparency: '100', density: 'compact', edges: 'sharp', highlight: '#ffffff', brightness: '100', depth: 'flat' } },
  lavender: { name: 'Lavender Mist', theme: { background: { primary: '#faf5ff', secondary: '#f3e8ff' }, gradient: { primary: 'none', secondary: 'none' }, surface: '#f3e8ff', text: '#4c1d95', transparency: '95', density: 'spacious', edges: 'pill', highlight: '#9333ea', brightness: '100', depth: 'shadow' } },
  neon: { name: 'Neon Tokyo', theme: { background: { primary: '#000000', secondary: '#1a1a1a' }, gradient: { primary: 'none', secondary: 'none' }, surface: '#1a1a1a', text: '#00ffff', transparency: '90', density: 'comfortable', edges: 'rounded', highlight: '#ff00ff', brightness: '120', depth: 'elevated' } },
  sepia: { name: 'Vintage Sepia', theme: { background: { primary: '#fdf6e3', secondary: '#eee8d5' }, gradient: { primary: 'none', secondary: 'none' }, surface: '#eee8d5', text: '#657b83', transparency: '100', density: 'spacious', edges: 'rounded', highlight: '#cb4b16', brightness: '95', depth: 'flat' } },
  nord: { name: 'Nord Frost', theme: { background: { primary: '#2e3440', secondary: '#3b4252' }, gradient: { primary: 'none', secondary: 'none' }, surface: '#3b4252', text: '#eceff4', transparency: '100', density: 'comfortable', edges: 'rounded', highlight: '#88c0d0', brightness: '100', depth: 'shadow' } },
  mint: { name: 'Mint Breeze', theme: { background: { primary: '#f0fdf4', secondary: '#dcfce7' }, gradient: { primary: 'none', secondary: 'none' }, surface: '#dcfce7', text: '#14532d', transparency: '95', density: 'comfortable', edges: 'pill', highlight: '#16a34a', brightness: '100', depth: 'elevated' } },
  solarized: { name: 'Solarized Dark', theme: { background: { primary: '#002b36', secondary: '#073642' }, gradient: { primary: 'none', secondary: 'none' }, surface: '#073642', text: '#839496', transparency: '100', density: 'compact', edges: 'sharp', highlight: '#b58900', brightness: '100', depth: 'flat' } },
  hacker: { name: 'Matrix Hacker', theme: { background: { primary: '#000000', secondary: '#050505' }, gradient: { primary: 'none', secondary: 'none' }, surface: '#050505', text: '#00ff00', transparency: '90', density: 'compact', edges: 'sharp', highlight: '#00ff00', brightness: '100', depth: 'flat' } },
};

const bernieState = { canvasId: null, name: 'Untitled canvas', nodes: [], edges: [], canvases: [], dirty: false, connecting: null };

const bernieView = {
  zoom: 1,
  selectMode: false,
  selected: new Set(),
  ctxTarget: null,
  grid: { show: true, density: 24, color: '#27272a', transparency: 0.15, variant: 'dots', snap: true, snapSize: 24 },
  minimap: { show: false, opacity: 0.8, scale: 1 },
  theme: null,
  panels: { left: 'flat', right: 'flat' },
};

function bnLoadTheme() {
  try {
    const saved = JSON.parse(localStorage.getItem('conductor.bernie.theme') || 'null');
    if (saved && saved.background && saved.background.primary) return saved;
  } catch { /* corrupted — fall back */ }
  return JSON.parse(JSON.stringify(BERNIE_THEME_DEFAULT));
}
function bnLoadPanels() {
  try {
    const p = JSON.parse(localStorage.getItem('conductor.bernie.panels') || 'null');
    if (p && (p.left === 'flat' || p.left === 'floating') && (p.right === 'flat' || p.right === 'floating')) return p;
  } catch { /* */ }
  return { left: 'flat', right: 'flat' };
}
bernieView.theme = bnLoadTheme();
bernieView.panels = bnLoadPanels();

function bnApplyTheme() {
  const t = bernieView.theme;
  const v = $('.bernie-view');
  if (!v) return;
  const set = (k, val) => v.style.setProperty(k, val);
  set('--bn-bg-primary', t.background.primary);
  set('--bn-bg-secondary', t.background.secondary);
  set('--bn-grad-primary', t.gradient.primary === 'none' ? t.background.primary : t.gradient.primary);
  set('--bn-grad-secondary', t.gradient.secondary === 'none' ? t.background.secondary : t.gradient.secondary);
  set('--bn-surface', t.surface);
  set('--bn-text', t.text);
  set('--bn-highlight', t.highlight);
  set('--bn-trans', (t.transparency || '90') + '%');
  set('--bn-brightness', (t.brightness || '100') + '%');
  set('--bn-radius', t.edges === 'pill' ? '24px' : t.edges === 'rounded' ? '12px' : '0px');
  set('--bn-radius-inner', t.edges === 'sharp' ? '0px' : '8px');
  set('--bn-shadow', t.depth === 'elevated' ? '0 8px 32px -8px rgba(0,0,0,0.8)' : t.depth === 'shadow' ? '0 10px 30px -10px rgba(0,0,0,0.5)' : 'none');
  set('--bn-padding', t.density === 'compact' ? '0.5rem' : t.density === 'spacious' ? '1.5rem' : '1rem');
  const area = $('#bernie-canvas-area');
  if (area) area.style.background = t.gradient.primary !== 'none' ? t.gradient.primary : t.background.primary;
  try { localStorage.setItem('conductor.bernie.theme', JSON.stringify(t)); } catch { /* */ }
  bnSyncPresetActive();
}

function bnSyncPresetActive() {
  const t = bernieView.theme;
  $$('#bn-theme-presets .bn-preset').forEach((b) => {
    const p = BERNIE_THEME_PRESETS[b.dataset.key];
    if (!p) return;
    b.classList.toggle('active', p.theme.background.primary === t.background.primary && p.theme.highlight === t.highlight);
  });
}

/* ------------------------------------------------------------ node summary */
function bernieNodeSummary(n) {
  const d = n.data || {};
  const t = n.type;
  if (t === 'text') return (d.text || '').slice(0, 40);
  if (t === 'json') return (d.jsonData || '').slice(0, 40);
  if (t === 'http') return `${d.method || 'GET'} ${(d.url || '').slice(0, 34)}`;
  if (t === 'ai') return (d.prompt || '').slice(0, 40);
  if (t === 'script') return 'JavaScript';
  if (t === 'sheet') return d.sheetName || d.spreadsheetId ? `Sheets ${d.spreadsheetId || ''}`.slice(0, 40) : 'Google Sheet';
  if (t === 'drive') return d.fileId ? `File ${d.fileId}`.slice(0, 40) : 'Google Drive';
  if (t === 'custom') return 'Custom integration hook';
  if (t === 'trigger') return 'Workflow entry point';
  if (t === 'flush') return 'Show output';
  return '';
}

/* ------------------------------------------------------------------ render */
function bernieRenderCanvas() {
  const area = $('#bernie-canvas-inner');
  if (!area) return;
  const statusCls = (n) => `bn-${n.status || 'idle'}`;
  area.innerHTML = '';
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.id = 'bernie-svg';
  svg.setAttribute('class', 'bernie-svg');
  area.appendChild(svg);
  for (const n of bernieState.nodes) {
    const meta = BERNIE_NODE_TYPES[n.type] || { icon: 'codicon-gear', label: n.type };
    const colorMeta = BERNIE_NODE_META[n.type] || { color: '#a1a1aa' };
    const node = el('div', 'bnode ' + statusCls(n) + (bernieView.selected.has(n.id) ? ' bn-selected' : ''));
    node.dataset.id = n.id;
    node.style.left = (n.position?.x ?? 60) + 'px';
    node.style.top = (n.position?.y ?? 60) + 'px';
    node.innerHTML = `
      <div class="bnode-head">
        <span class="bnode-ic codicon ${meta.icon}" style="color:${colorMeta.color}"></span>
        <span class="bnode-title">${esc(n.data?.title || meta.label)}</span>
        <button class="bnode-del" title="Delete node">×</button>
      </div>
      <div class="bnode-body">${esc(bernieNodeSummary(n))}</div>
      <div class="bnode-foot">
        <span class="bnode-status" title="${esc(n.errorMessage || n.status || 'idle')}"></span>
        <span class="bnode-type">${esc(n.type)}</span>
        <button class="bnode-edit" title="Configure node"><span class="codicon codicon-edit"></span></button>
      </div>
      <div class="bnode-out" title="Drag to connect"></div>`;
    node.addEventListener('pointerdown', (e) => {
      if (e.target.closest('button') || e.target.closest('.bnode-out')) return;
      if (e.button === 2) return; // right-click handled by contextmenu
      if (bernieView.selectMode) {
        if (!e.shiftKey) bernieView.selected.clear();
        if (bernieView.selected.has(n.id)) bernieView.selected.delete(n.id);
        else bernieView.selected.add(n.id);
        bnSyncSelection();
        return;
      }
      bernieStartDrag(e, node, n);
    });
    node.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      if (!bernieView.selected.has(n.id)) { bernieView.selected.clear(); bernieView.selected.add(n.id); bnSyncSelection(); }
      bnShowContextMenu(e, { kind: 'node', id: n.id });
    });
    node.querySelector('.bnode-out').addEventListener('pointerdown', (e) => {
      e.stopPropagation();
      bernieStartConnect(e, n.id);
    });
    node.querySelector('.bnode-edit').addEventListener('click', () => bernieEditNode(n));
    node.querySelector('.bnode-del').addEventListener('click', () => {
      bernieState.nodes = bernieState.nodes.filter((x) => x.id !== n.id);
      bernieState.edges = bernieState.edges.filter((x) => x.source !== n.id && x.target !== n.id);
      bernieView.selected.delete(n.id);
      bnSyncSelection();
      bernieState.dirty = true;
      bernieRenderCanvas();
    });
    area.appendChild(node);
  }
  bernieDrawEdges();
  const hint = $('#bn-stage-hint');
  if (hint) hint.hidden = bernieState.nodes.length > 0;
  bnRenderMinimap();
}

function bernieDrawEdges() {
  const svg = $('#bernie-svg');
  const area = $('#bernie-canvas-inner');
  if (!svg || !area) return;
  svg.innerHTML = '';
  bernieState.edges.forEach((e, idx) => {
    const s = area.querySelector(`.bnode[data-id="${CSS.escape(e.source)}"]`);
    const t = area.querySelector(`.bnode[data-id="${CSS.escape(e.target)}"]`);
    if (!s || !t) return;
    const x1 = s.offsetLeft + s.offsetWidth;
    const y1 = s.offsetTop + s.offsetHeight / 2;
    const x2 = t.offsetLeft;
    const y2 = t.offsetTop + t.offsetHeight / 2;
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    const mx = (x1 + x2) / 2;
    path.setAttribute('d', `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`);
    path.setAttribute('class', 'bernie-edge');
    path.dataset.edge = String(idx);
    path.addEventListener('contextmenu', (ev) => {
      ev.preventDefault();
      bnShowContextMenu(ev, { kind: 'edge', index: idx });
    });
    const head = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    head.setAttribute('cx', x2 - 3); head.setAttribute('cy', y2); head.setAttribute('r', 3);
    head.setAttribute('class', 'bernie-edge-dot');
    svg.appendChild(path);
    svg.appendChild(head);
  });
}

function bernieStartDrag(e, nodeEl, n) {
  const area = $('#bernie-canvas-area');
  const startX = e.clientX, startY = e.clientY;
  const origX = n.position?.x ?? 60, origY = n.position?.y ?? 60;
  nodeEl.setPointerCapture(e.pointerId);
  const snap = () => {
    if (!bernieView.grid.snap) return;
    const s = Math.max(4, bernieView.grid.snapSize);
    n.position.x = Math.round(n.position.x / s) * s;
    n.position.y = Math.round(n.position.y / s) * s;
  };
  const move = (ev) => {
    const z = bernieView.zoom || 1;
    n.position = { x: Math.max(0, origX + (ev.clientX - startX) / z), y: Math.max(0, origY + (ev.clientY - startY) / z) };
    snap();
    nodeEl.style.left = n.position.x + 'px';
    nodeEl.style.top = n.position.y + 'px';
    bernieDrawEdges();
    bnRenderMinimap();
  };
  const up = () => {
    nodeEl.removeEventListener('pointermove', move);
    nodeEl.removeEventListener('pointerup', up);
    bernieState.dirty = true;
  };
  nodeEl.addEventListener('pointermove', move);
  nodeEl.addEventListener('pointerup', up);
}

function bernieStartConnect(e, sourceId) {
  bernieState.connecting = { sourceId, x: e.clientX, y: e.clientY };
  const svg = $('#bernie-svg');
  const temp = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  temp.setAttribute('class', 'bernie-edge bernie-edge-temp');
  svg.appendChild(temp);
  const move = (ev) => {
    bernieState.connecting.x = ev.clientX;
    bernieState.connecting.y = ev.clientY;
    const src = $('#bernie-canvas-inner').querySelector(`.bnode[data-id="${CSS.escape(sourceId)}"]`);
    if (!src) return;
    const areaRect = $('#bernie-canvas-area').getBoundingClientRect();
    const z = bernieView.zoom || 1;
    const x1 = src.offsetLeft + src.offsetWidth, y1 = src.offsetTop + src.offsetHeight / 2;
    const x2 = (ev.clientX - areaRect.left + $('#bernie-canvas-area').scrollLeft) / z;
    const y2 = (ev.clientY - areaRect.top + $('#bernie-canvas-area').scrollTop) / z;
    const mx = (x1 + x2) / 2;
    temp.setAttribute('d', `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`);
  };
  const up = (ev) => {
    document.removeEventListener('pointermove', move);
    document.removeEventListener('pointerup', up);
    temp.remove();
    const targetEl = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('.bnode');
    if (targetEl) {
      const targetId = targetEl.dataset.id;
      if (targetId && targetId !== sourceId && !bernieState.edges.some((x) => x.source === sourceId && x.target === targetId)) {
        bernieState.edges.push({ source: sourceId, target: targetId });
        bernieState.dirty = true;
        bernieDrawEdges();
        bnRenderMinimap();
      }
    }
    bernieState.connecting = null;
  };
  document.addEventListener('pointermove', move);
  document.addEventListener('pointerup', up);
}

/* ------------------------------------------------------------------ nodes */
function bnNewNodeId() { return 'n' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }

function bnAddNodeAt(type, x, y) {
  const meta = BERNIE_NODE_TYPES[type];
  if (!meta) return;
  bernieState.nodes.push({
    id: bnNewNodeId(), type,
    data: { title: meta.label, ...JSON.parse(JSON.stringify(meta.defaultData)) },
    position: { x, y },
    status: 'idle',
  });
  bernieState.dirty = true;
  bernieRenderCanvas();
}

function bernieAddNode(type) {
  const meta = BERNIE_NODE_TYPES[type];
  if (!meta) return;
  const count = bernieState.nodes.length;
  bnAddNodeAt(type, 80 + (count % 4) * 60, 80 + (count % 4) * 60);
}

function bernieEditNode(n) {
  const d = n.data || {};
  const meta = BERNIE_NODE_TYPES[n.type] || {};
  let fields = '';
  const field = (label, html) => `<label class="field"><span>${label}</span>${html}</label>`;
  if (n.type === 'text') {
    fields = field('Text', `<textarea id="bn-f-text" rows="4">${esc(d.text || '')}</textarea>`);
  } else if (n.type === 'json') {
    fields = field('JSON data', `<textarea id="bn-f-json" rows="8" spellcheck="false">${esc(d.jsonData || '{}')}</textarea>`);
  } else if (n.type === 'http') {
    fields = `<div class="field-row">
      ${field('Method', `<select id="bn-f-method">${['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((m) => `<option ${d.method === m ? 'selected' : ''}>${m}</option>`).join('')}</select>`)}
      ${field('URL', `<input id="bn-f-url" value="${esc(d.url || '')}" placeholder="https://…" />`)}
    </div>`;
  } else if (n.type === 'ai') {
    fields = field('Prompt (input data is passed in)', `<textarea id="bn-f-prompt" rows="5">${esc(d.prompt || '')}</textarea>`);
  } else if (n.type === 'script') {
    fields = field('Script — `data` is the upstream output', `<textarea id="bn-f-script" rows="6" spellcheck="false">${esc(d.script || '')}</textarea>`);
  } else if (n.type === 'sheet') {
    fields = field('Spreadsheet ID / name', `<input id="bn-f-sheet" value="${esc(d.spreadsheetId || '')}" placeholder="1A2b3C…" />`);
  } else if (n.type === 'drive') {
    fields = field('File ID', `<input id="bn-f-drive" value="${esc(d.fileId || '')}" placeholder="1A2b3C…" />`);
  } else {
    fields = `<div class="settings-note">${esc(meta.label)} node — ${n.type === 'trigger' ? 'starts the workflow with the data wired into it.' : n.type === 'custom' ? 'integration hook; passes data through to the next node.' : 'passes data through to the next node.'}</div>`;
  }
  openModal(`Configure ${meta.label || n.type} node`,
    `<div class="form-grid">
      ${field('Node title', `<input id="bn-f-title" value="${esc(d.title || '')}" placeholder="${esc(meta.label || 'Node')}" />`)}
      ${fields}
    </div>`,
    `<button class="btn-primary" id="bn-save-node">Save</button>`);
  $('#bn-save-node').addEventListener('click', () => {
    n.data = { ...n.data, title: $('#bn-f-title').value.trim() || (meta.label || n.type) };
    if (n.type === 'text') n.data.text = $('#bn-f-text').value;
    if (n.type === 'json') n.data.jsonData = $('#bn-f-json').value;
    if (n.type === 'http') { n.data.url = $('#bn-f-url').value.trim(); n.data.method = $('#bn-f-method').value; }
    if (n.type === 'ai') n.data.prompt = $('#bn-f-prompt').value;
    if (n.type === 'script') n.data.script = $('#bn-f-script').value;
    if (n.type === 'sheet') n.data.spreadsheetId = $('#bn-f-sheet').value.trim();
    if (n.type === 'drive') n.data.fileId = $('#bn-f-drive').value.trim();
    closeModal();
    bernieState.dirty = true;
    bernieRenderCanvas();
  });
}

/* -------------------------------------------------------------- execution */
async function bernieExecuteNode(n, inputs) {
  const d = n.data || {};
  n.status = 'running';
  bernieRenderCanvas();
  try {
    let output;
    if (n.type === 'trigger') output = inputs;
    else if (n.type === 'text') output = d.text;
    else if (n.type === 'json') output = JSON.parse(d.jsonData || '{}');
    else if (n.type === 'http') {
      const res = await api('/api/bernie/proxy', { method: 'POST', body: { url: d.url, method: d.method || 'GET', headers: {}, body: inputs } });
      if (res.status >= 400) throw new Error(`HTTP ${res.status}`);
      output = res.data;
    } else if (n.type === 'ai') {
      const res = await api('/api/bernie/ai/execute', { method: 'POST', body: { prompt: d.prompt, input_data: inputs } });
      output = res.result;
    } else if (n.type === 'script') {
      const fn = new Function('data', '"use strict";\n' + (d.script || 'return data'));
      output = await fn(inputs);
    } else if (n.type === 'sheet' || n.type === 'drive' || n.type === 'custom') {
      output = inputs; // connector passthrough — not wired in this build
      n.simulated = true;
    } else {
      output = inputs;
    }
    n.status = 'success';
    n.output = output;
    delete n.errorMessage;
    return output;
  } catch (err) {
    n.status = 'error';
    n.errorMessage = String(err && err.message ? err.message : err);
    n.output = undefined;
    return undefined;
  }
}

async function bernieRunWorkflow() {
  const byId = Object.fromEntries(bernieState.nodes.map((n) => [n.id, n]));
  bernieState.nodes.forEach((n) => { n.status = 'idle'; delete n.errorMessage; delete n.output; delete n.simulated; });
  const incoming = new Map(bernieState.nodes.map((n) => [n.id, 0]));
  for (const e of bernieState.edges) incoming.set(e.target, (incoming.get(e.target) || 0) + 1);
  let starts = bernieState.nodes.filter((n) => n.type === 'trigger' && incoming.get(n.id) === 0);
  if (!starts.length) starts = bernieState.nodes.filter((n) => incoming.get(n.id) === 0);
  if (!starts.length) starts = bernieState.nodes.slice(0, 1);
  const flushLog = [];
  const queue = [...starts];
  const ran = new Set();
  while (queue.length) {
    const n = queue.shift();
    if (!n || ran.has(n.id)) continue;
    ran.add(n.id);
    const upstream = bernieState.edges.filter((e) => e.target === n.id).map((e) => byId[e.source]).filter(Boolean);
    let inputs = {};
    for (const u of upstream) {
      if (u.output !== undefined) {
        inputs = typeof u.output === 'object' && u.output !== null && !Array.isArray(u.output)
          ? { ...inputs, ...u.output } : u.output;
      }
    }
    const out = await bernieExecuteNode(n, inputs);
    if (n.type === 'flush') {
      flushLog.push({ node: n.data?.title || 'Flush', data: out, at: new Date().toISOString() });
    }
    for (const e of bernieState.edges) {
      if (e.source === n.id) {
        const next = byId[e.target];
        if (next && !ran.has(next.id)) queue.push(next);
      }
    }
  }
  bernieRenderCanvas();
  const panel = $('#bernie-flush');
  if (panel) {
    panel.innerHTML = flushLog.length
      ? flushLog.map((f) => `<div class="bernie-flush-item"><div class="view-title" style="font-size:0.75rem;margin:0 0 0.25rem">${esc(f.node)}</div><pre class="chat-code" style="margin:0;max-height:12rem;overflow:auto">${esc(typeof f.data === 'string' ? f.data : JSON.stringify(f.data, null, 2))}</pre></div>`).join('')
      : '<div class="settings-note">Ran — add a <b>Flush</b> node wired to the end of the chain to see output here.</div>';
  }
  bnOpenOutputRow();
}

/* ---------------------------------------------------------------- persist */
async function bernieSave() {
  const payload = { name: bernieState.name || 'Untitled canvas', nodes: bernieState.nodes, edges: bernieState.edges };
  try {
    if (bernieState.canvasId) {
      await api(`/api/bernie/canvases/${bernieState.canvasId}`, { method: 'PATCH', body: payload });
    } else {
      const created = await api('/api/bernie/canvases', { method: 'POST', body: payload });
      bernieState.canvasId = created.id;
    }
    bernieState.dirty = false;
    toast(`Canvas "${bernieState.name}" saved`, 'ok');
    await bernieLoadList();
  } catch (e) { toast(e.message, 'err'); }
}

async function bernieLoadList() {
  try {
    bernieState.canvases = await api('/api/bernie/canvases');
    const sel = $('#bernie-load');
    if (sel) {
      sel.innerHTML = '<option value="">— load canvas —</option>' +
        bernieState.canvases.map((c) => `<option value="${c.id}">${esc(c.name)} (${c.node_count}n · ${c.edge_count}e)</option>`).join('');
      if (bernieState.canvasId) sel.value = String(bernieState.canvasId);
    }
    bnRenderLibrary();
  } catch { /* */ }
}

async function bnLoadCanvas(id) {
  try {
    const c = await api(`/api/bernie/canvases/${id}`);
    bernieState.canvasId = c.id;
    bernieState.name = c.name;
    bernieState.nodes = c.nodes || [];
    bernieState.edges = c.edges || [];
    bernieState.dirty = false;
    bernieView.selected.clear();
    bnSyncSelection();
    const nameInput = $('#bernie-name');
    if (nameInput) nameInput.value = c.name;
    bernieRenderCanvas();
    bnZoomFit();
    toast(`Loaded "${c.name}"`, 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

async function bnDuplicateCanvas(c) {
  try {
    const full = await api(`/api/bernie/canvases/${c.id}`);
    const created = await api('/api/bernie/canvases', { method: 'POST', body: { name: `${c.name} (copy)`, nodes: full.nodes || [], edges: full.edges || [] } });
    toast(`Duplicated as "${created.name}"`, 'ok');
    await bernieLoadList();
  } catch (e) { toast(e.message, 'err'); }
}

function bnDeleteCanvas(c, btn) {
  if (btn.dataset.armed !== '1') {
    btn.dataset.armed = '1';
    btn.textContent = '✓?';
    btn.style.color = 'var(--bn-highlight)';
    setTimeout(() => { btn.dataset.armed = ''; btn.textContent = '🗑'; btn.style.color = ''; }, 2500);
    return;
  }
  (async () => {
    try {
      await api(`/api/bernie/canvases/${c.id}`, { method: 'DELETE' });
      if (bernieState.canvasId === c.id) bernieState.canvasId = null;
      toast(`Deleted "${c.name}"`, 'ok');
      await bernieLoadList();
    } catch (e) { toast(e.message, 'err'); }
  })();
}

function bnRenderLibrary() {
  const box = $('#bn-library');
  if (!box) return;
  if (!bernieState.canvases.length) {
    box.innerHTML = '<div class="bn-empty">No saved canvases yet — build a flow and hit Save.</div>';
    return;
  }
  box.innerHTML = bernieState.canvases.map((c) => `
    <div class="bn-lib-row ${bernieState.canvasId === c.id ? 'bn-lib-active' : ''}" data-id="${c.id}">
      <button class="bn-lib-load" title="Load this canvas"><b>${esc(c.name)}</b><span class="bn-lib-meta">${c.node_count} nodes · ${c.edge_count} edges</span></button>
      <button class="bn-lib-btn" data-act="dup" title="Duplicate"><span class="codicon codicon-copy"></span></button>
      <button class="bn-lib-btn" data-act="del" title="Delete">🗑</button>
    </div>`).join('');
  box.querySelectorAll('.bn-lib-row').forEach((row) => {
    const id = Number(row.dataset.id);
    const c = bernieState.canvases.find((x) => x.id === id);
    row.querySelector('.bn-lib-load').addEventListener('click', () => bnLoadCanvas(id));
    row.querySelector('[data-act="dup"]').addEventListener('click', () => bnDuplicateCanvas(c));
    row.querySelector('[data-act="del"]').addEventListener('click', (e) => bnDeleteCanvas(c, e.currentTarget));
  });
}

/* ------------------------------------------------------- auto-arrange etc. */
function bernieAutoArrange() {
  const depth = new Map();
  const incoming = new Map(bernieState.nodes.map((n) => [n.id, 0]));
  for (const e of bernieState.edges) incoming.set(e.target, (incoming.get(e.target) || 0) + 1);
  const queue = bernieState.nodes.filter((n) => (incoming.get(n.id) || 0) === 0);
  queue.forEach((n) => depth.set(n.id, 0));
  while (queue.length) {
    const n = queue.shift();
    for (const e of bernieState.edges.filter((x) => x.source === n.id)) {
      const nd = (depth.get(n.id) || 0) + 1;
      if (!depth.has(e.target) || depth.get(e.target) < nd) {
        depth.set(e.target, nd);
        queue.push(bernieState.nodes.find((x) => x.id === e.target));
      }
    }
  }
  const byDepth = {};
  for (const n of bernieState.nodes) {
    const d = depth.get(n.id) || 0;
    (byDepth[d] = byDepth[d] || []).push(n);
  }
  for (const [d, list] of Object.entries(byDepth)) {
    list.forEach((n, i) => { n.position = { x: 60 + Number(d) * 260, y: 60 + i * 120 }; });
  }
  bernieState.dirty = true;
  bernieRenderCanvas();
}

async function bernieSuggest() {
  const panel = $('#bernie-suggest');
  if (panel) panel.innerHTML = '<div class="folder-loading">Asking the AI…</div>';
  bnOpenOutputRow();
  try {
    const res = await api('/api/bernie/ai/suggest', { method: 'POST', body: { nodes: bernieState.nodes, edges: bernieState.edges } });
    if (panel) {
      panel.innerHTML = (res.suggestions || []).map((s) => `
        <div class="card" style="margin:0.5rem 0"><div class="view-title" style="font-size:0.8125rem;margin-bottom:0.25rem"><span class="codicon codicon-lightbulb-sparkle"></span> ${esc(s.title || '')}</div>
        <div class="settings-note">${esc(s.description || '')}</div></div>`).join('');
      if (!(res.suggestions || []).length) panel.innerHTML = '<div class="settings-note">No suggestions returned.</div>';
    }
  } catch (e) {
    if (panel) panel.innerHTML = `<div class="settings-note">⚠ ${esc(e.message)}</div>`;
    toast(e.message, 'err');
  }
}

/* ------------------------------------------------------------- zoom & pan */
function bnApplyZoom() {
  const area = $('#bernie-canvas-area');
  const wrap = $('#bn-zoom-wrap');
  const inner = $('#bernie-canvas-inner');
  if (!area || !wrap || !inner) return;
  const z = bernieView.zoom;
  wrap.style.width = (3200 * z) + 'px';
  wrap.style.height = (2000 * z) + 'px';
  inner.style.transform = `scale(${z})`;
  inner.style.transformOrigin = '0 0';
  const lbl = $('#bn-zoom-label');
  if (lbl) lbl.textContent = Math.round(z * 100) + '%';
  bnRenderMinimap();
}

function bnSetZoom(z, cx, cy) {
  const area = $('#bernie-canvas-area');
  if (!area) return;
  const old = bernieView.zoom;
  const nz = Math.min(2.5, Math.max(0.3, z));
  if (cx !== undefined && cy !== undefined) {
    // content point (cx, cy) maps to viewport offset = content*zoom - scroll;
    // keep that offset fixed across the zoom so the point stays under the cursor
    bernieView.zoom = nz;
    bnApplyZoom();
    area.scrollLeft = Math.max(0, cx * nz - (cx * old - area.scrollLeft));
    area.scrollTop = Math.max(0, cy * nz - (cy * old - area.scrollTop));
  } else {
    bernieView.zoom = nz;
    bnApplyZoom();
  }
}

function bnZoomFit() {
  const area = $('#bernie-canvas-area');
  if (!area) return;
  if (!bernieState.nodes.length) { bernieView.zoom = 1; bnApplyZoom(); area.scrollTo(0, 0); return; }
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const n of bernieState.nodes) {
    const x = n.position?.x ?? 0, y = n.position?.y ?? 0;
    minX = Math.min(minX, x); minY = Math.min(minY, y);
    maxX = Math.max(maxX, x + 230); maxY = Math.max(maxY, y + 130);
  }
  const pad = 90;
  const z = Math.min(1.5, Math.max(0.3, Math.min(area.clientWidth / (maxX - minX + pad * 2), area.clientHeight / (maxY - minY + pad * 2))));
  bernieView.zoom = z;
  bnApplyZoom();
  area.scrollLeft = Math.max(0, (minX - pad) * z);
  area.scrollTop = Math.max(0, (minY - pad) * z);
}

/* ------------------------------------------------------------------- grid */
function bnApplyGrid() {
  const layer = $('#bn-grid-layer');
  if (!layer) return;
  const g = bernieView.grid;
  if (!g.show) { layer.style.backgroundImage = 'none'; return; }
  const gap = Math.max(6, g.density);
  if (g.variant === 'lines') {
    layer.style.backgroundImage = `linear-gradient(to right, ${g.color} 1px, transparent 1px), linear-gradient(to bottom, ${g.color} 1px, transparent 1px)`;
    layer.style.backgroundSize = `${gap}px ${gap}px`;
    layer.style.backgroundPosition = '0 0';
  } else if (g.variant === 'cross') {
    const d = Math.min(gap * 0.3, 10);
    layer.style.backgroundImage = `linear-gradient(${g.color}, ${g.color}), linear-gradient(${g.color}, ${g.color})`;
    layer.style.backgroundSize = `${d}px 1.5px, 1.5px ${d}px`;
    layer.style.backgroundPosition = 'center center';
    layer.style.backgroundRepeat = 'repeat';
  } else {
    layer.style.backgroundImage = `radial-gradient(circle, ${g.color} 1.5px, transparent 1.5px)`;
    layer.style.backgroundSize = `${gap}px ${gap}px`;
    layer.style.backgroundPosition = '0 0';
  }
  layer.style.opacity = String(g.transparency);
}

function bnOpenGridFlyout() {
  const f = $('#bn-grid-flyout'), m = $('#bn-map-flyout');
  if (!f) return;
  const willShow = f.hidden;
  bnHideFlyouts();
  if (willShow) { f.hidden = false; bnSyncGridControls(); }
  void m;
}

function bnOpenMapFlyout() {
  const f = $('#bn-map-flyout'), g = $('#bn-grid-flyout');
  if (!f) return;
  const willShow = f.hidden;
  bnHideFlyouts();
  if (willShow) { f.hidden = false; bnSyncMinimapControls(); }
  void g;
}

function bnHideFlyouts() {
  const g = $('#bn-grid-flyout'), m = $('#bn-map-flyout');
  if (g) g.hidden = true;
  if (m) m.hidden = true;
}

function bnSyncGridControls() {
  const g = bernieView.grid;
  const set = (id, v) => { const el = $('#' + id); if (el) el.value = v; };
  set('bn-g-density', g.density); set('bn-g-snap-size', g.snapSize);
  set('bn-g-trans', g.transparency); set('bn-g-color', g.color);
  const show = $('#bn-g-show'); if (show) show.checked = g.show;
  const snap = $('#bn-g-snap'); if (snap) snap.checked = g.snap;
  $$('#bn-grid-flyout .bn-pattern-btn').forEach((b) => b.classList.toggle('active', b.dataset.pat === g.variant));
}

function bnSyncMinimapControls() {
  const m = bernieView.minimap;
  const set = (id, v) => { const el = $('#' + id); if (el) el.value = v; };
  set('bn-m-opacity', m.opacity); set('bn-m-scale', m.scale);
  const show = $('#bn-m-show'); if (show) show.checked = m.show;
}

/* ---------------------------------------------------------------- minimap */
function bnRenderMinimap() {
  const mm = $('#bn-minimap');
  const box = $('#bn-minimap-box');
  const vp = $('#bn-minimap-viewport');
  if (!mm || !box || !vp) return;
  mm.hidden = !bernieView.minimap.show;
  if (!bernieView.minimap.show) return;
  mm.style.opacity = String(bernieView.minimap.opacity);
  mm.style.transform = `scale(${bernieView.minimap.scale})`;
  mm.style.transformOrigin = 'bottom right';
  const W = 200, H = 125;
  const kx = W / 3200, ky = H / 2000;
  box.innerHTML = '';
  for (const n of bernieState.nodes) {
    const d = document.createElement('div');
    d.className = 'bn-mm-node';
    d.style.left = ((n.position?.x ?? 0) * kx) + 'px';
    d.style.top = ((n.position?.y ?? 0) * ky) + 'px';
    d.style.width = Math.max(3, 208 * kx) + 'px';
    d.style.height = Math.max(2, 100 * ky) + 'px';
    box.appendChild(d);
  }
  const area = $('#bernie-canvas-area');
  const z = bernieView.zoom || 1;
  vp.style.left = Math.max(0, (area.scrollLeft / (3200 * z)) * W) + 'px';
  vp.style.top = Math.max(0, (area.scrollTop / (2000 * z)) * H) + 'px';
  vp.style.width = Math.min(W, (area.clientWidth / (3200 * z)) * W) + 'px';
  vp.style.height = Math.min(H, (area.clientHeight / (2000 * z)) * H) + 'px';
}

/* ----------------------------------------------------- selection & marquee */
function bnSyncSelection() {
  $$('.bnode').forEach((nEl) => nEl.classList.toggle('bn-selected', bernieView.selected.has(nEl.dataset.id)));
  const bar = $('#bn-selection-bar');
  if (bar) {
    bar.hidden = bernieView.selected.size === 0;
    const cnt = $('#bn-sel-count');
    if (cnt) cnt.textContent = `${bernieView.selected.size} node${bernieView.selected.size === 1 ? '' : 's'} selected`;
  }
}

function bnSelectByIds(ids, additive) {
  if (!additive) bernieView.selected.clear();
  ids.forEach((id) => bernieView.selected.add(id));
  bnSyncSelection();
}

function bnClearSelection() {
  bernieView.selected.clear();
  bnSyncSelection();
}

function bnDuplicateSelected() {
  for (const id of [...bernieView.selected]) {
    const src = bernieState.nodes.find((n) => n.id === id);
    if (!src) continue;
    const copy = JSON.parse(JSON.stringify(src));
    copy.id = bnNewNodeId();
    copy.position = { x: (src.position?.x ?? 0) + 64, y: (src.position?.y ?? 0) + 64 };
    copy.status = 'idle';
    delete copy.errorMessage;
    bernieState.nodes.push(copy);
  }
  bernieState.dirty = true;
  bernieRenderCanvas();
}

function bnDeleteSelected() {
  const ids = [...bernieView.selected];
  bernieState.nodes = bernieState.nodes.filter((n) => !ids.includes(n.id));
  bernieState.edges = bernieState.edges.filter((e) => !ids.includes(e.source) && !ids.includes(e.target));
  bernieView.selected.clear();
  bernieState.dirty = true;
  bernieRenderCanvas();
  bnSyncSelection();
}

/* ----------------------------------------------------------- context menu */
function bnShowContextMenu(e, target) {
  const stage = $('#bn-stage');
  const menu = $('#bn-context-menu');
  if (!stage || !menu) return;
  const rect = stage.getBoundingClientRect();
  menu.hidden = false;
  let left = e.clientX - rect.left, top = e.clientY - rect.top;
  left = Math.min(left, rect.width - 180);
  top = Math.min(top, rect.height - 160);
  menu.style.left = left + 'px';
  menu.style.top = top + 'px';
  bernieView.ctxTarget = target;
  menu.innerHTML = target.kind === 'node'
    ? `<button data-act="inspect"><span class="codicon codicon-eye"></span> Inspect Data</button>
       <button data-act="duplicate"><span class="codicon codicon-copy"></span> Duplicate Node</button>
       <button data-act="delete" class="bn-danger"><span class="codicon codicon-trash"></span> Delete Node</button>`
    : `<button data-act="delete-edge" class="bn-danger"><span class="codicon codicon-trash"></span> Delete Edge</button>`;
}

function bnHideContextMenu() {
  const menu = $('#bn-context-menu');
  if (menu) menu.hidden = true;
  bernieView.ctxTarget = null;
}

function bnInspect(id) {
  const n = bernieState.nodes.find((x) => x.id === id);
  if (!n) return;
  openModal(`Inspect: ${n.type} node`,
    `<pre class="chat-code" style="max-height:60vh;overflow:auto">${esc(JSON.stringify({ id: n.id, type: n.type, title: n.data?.title, data: n.data, status: n.status, output: n.output }, null, 2))}</pre>`,
    `<button class="btn-secondary" id="bn-inspect-close">Close</button>`);
  $('#bn-inspect-close').addEventListener('click', closeModal);
}

/* ------------------------------------------------------------- panel modes */
function bnSetPanelMode(side, mode) {
  bernieView.panels[side] = mode;
  const p = $('#bn-' + side + '-panel');
  if (p) { p.dataset.mode = mode; p.dataset.collapsed = ''; }
  const btn = $('#bn-' + side + '-float');
  if (btn) {
    btn.title = mode === 'flat' ? 'Float panel' : 'Dock panel';
    btn.innerHTML = mode === 'flat' ? '<span class="codicon codicon-panel-right"></span>' : '<span class="codicon codicon-replace-all"></span>';
  }
  try { localStorage.setItem('conductor.bernie.panels', JSON.stringify(bernieView.panels)); } catch { /* */ }
}

function bnTogglePanelCollapse(side) {
  const p = $('#bn-' + side + '-panel');
  if (!p) return;
  p.dataset.collapsed = p.dataset.collapsed === '1' ? '' : '1';
}

/* ------------------------------------------------------------ palette etc. */
function bnRenderPalette() {
  const box = $('#bn-palette');
  if (!box) return;
  box.innerHTML = Object.entries(BERNIE_NODE_TYPES).map(([t, m]) => {
    const meta = BERNIE_NODE_META[t] || { desc: '', color: '#a1a1aa' };
    return `<div class="bn-pal-item bn-add" data-type="${t}" draggable="true" title="${esc(meta.desc || m.label)}">
      <span class="bn-pal-ic codicon ${m.icon}" style="color:${meta.color};background:${meta.color}1f"></span>
      <span class="bn-pal-txt"><b>${m.label}</b><small>${esc(meta.desc || '')}</small></span>
    </div>`;
  }).join('');
  box.querySelectorAll('.bn-add').forEach((b) => {
    b.addEventListener('click', () => bernieAddNode(b.dataset.type));
    b.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', b.dataset.type);
      e.dataTransfer.effectAllowed = 'move';
    });
  });
}

/* -------------------------------------------------------------- theme UI */
function bnRenderThemePresets() {
  const box = $('#bn-theme-presets');
  if (!box) return;
  box.innerHTML = Object.entries(BERNIE_THEME_PRESETS).map(([key, p]) => {
    const t = p.theme;
    const active = t.background.primary === bernieView.theme.background.primary && t.highlight === bernieView.theme.highlight;
    return `<button class="bn-preset${active ? ' active' : ''}" data-key="${key}" title="${esc(p.name)}">
      <span class="bn-preset-strip"><i style="background:${t.background.primary}"></i><i style="background:${t.background.secondary}"></i><i style="background:${t.highlight}"></i></span>
      <span class="bn-preset-name">${esc(p.name)}</span>
    </button>`;
  }).join('');
  box.querySelectorAll('.bn-preset').forEach((b) => {
    b.addEventListener('click', () => {
      const p = BERNIE_THEME_PRESETS[b.dataset.key];
      if (!p) return;
      bernieView.theme = JSON.parse(JSON.stringify(p.theme));
      bnApplyTheme();
      bnRenderThemePresets();
      bnRenderThemeCustom();
    });
  });
}

function bnRenderThemeCustom() {
  const box = $('#bn-theme-custom');
  if (!box) return;
  const t = bernieView.theme;
  const colorRow = (id, label, get, set) => `
    <label class="bn-tc-row"><span>${label}</span>
      <input type="color" id="${id}-c" value="${esc(get())}" title="${label} color" />
      <input type="text" id="${id}-t" value="${esc(get())}" spellcheck="false" />
    </label>`;
  box.innerHTML = `
    ${colorRow('bn-t-bgp', 'Primary background', () => t.background.primary, (v) => { t.background.primary = v; })}
    ${colorRow('bn-t-bgs', 'Secondary background', () => t.background.secondary, (v) => { t.background.secondary = v; })}
    <label class="bn-tc-row"><span>Primary gradient</span><input type="text" id="bn-t-gp" value="${esc(t.gradient.primary)}" placeholder="none" spellcheck="false" /></label>
    <label class="bn-tc-row"><span>Secondary gradient</span><input type="text" id="bn-t-gs" value="${esc(t.gradient.secondary)}" placeholder="none" spellcheck="false" /></label>
    ${colorRow('bn-t-sur', 'Surface color', () => t.surface, (v) => { t.surface = v; })}
    ${colorRow('bn-t-txt', 'Text color', () => t.text, (v) => { t.text = v; })}
    ${colorRow('bn-t-hl', 'Highlight / accent', () => t.highlight, (v) => { t.highlight = v; })}
    <label class="bn-tc-row"><span>Transparency <b id="bn-t-trans-lbl">${esc(t.transparency)}%</b></span><input type="range" id="bn-t-trans" min="0" max="100" value="${esc(t.transparency)}" /></label>
    <label class="bn-tc-row"><span>Brightness <b id="bn-t-bright-lbl">${esc(t.brightness)}%</b></span><input type="range" id="bn-t-bright" min="50" max="150" value="${esc(t.brightness)}" /></label>
    <label class="bn-tc-row"><span>Density</span><select id="bn-t-density">${['compact', 'comfortable', 'spacious'].map((o) => `<option ${t.density === o ? 'selected' : ''}>${o}</option>`).join('')}</select></label>
    <label class="bn-tc-row"><span>Edges</span><select id="bn-t-edges">${['sharp', 'rounded', 'pill'].map((o) => `<option ${t.edges === o ? 'selected' : ''}>${o}</option>`).join('')}</select></label>
    <label class="bn-tc-row"><span>Depth</span><select id="bn-t-depth">${['flat', 'shadow', 'elevated'].map((o) => `<option ${t.depth === o ? 'selected' : ''}>${o}</option>`).join('')}</select></label>
    <button class="bn-btn bn-block" id="bn-t-reset">Reset to Dark Default</button>`;

  const wireColor = (cid, tid, set) => {
    const c = $('#' + cid), txt = $('#' + tid);
    if (!c || !txt) return;
    c.addEventListener('input', () => { set(c.value); txt.value = c.value; bnApplyTheme(); bnRenderThemePresets(); });
    txt.addEventListener('change', () => { set(txt.value.trim() || '#000000'); c.value = txt.value.trim() || '#000000'; bnApplyTheme(); bnRenderThemePresets(); });
  };
  wireColor('bn-t-bgp-c', 'bn-t-bgp-t', (v) => { bernieView.theme.background.primary = v; });
  wireColor('bn-t-bgs-c', 'bn-t-bgs-t', (v) => { bernieView.theme.background.secondary = v; });
  wireColor('bn-t-sur-c', 'bn-t-sur-t', (v) => { bernieView.theme.surface = v; });
  wireColor('bn-t-txt-c', 'bn-t-txt-t', (v) => { bernieView.theme.text = v; });
  wireColor('bn-t-hl-c', 'bn-t-hl-t', (v) => { bernieView.theme.highlight = v; });
  $('#bn-t-gp').addEventListener('change', (e) => { bernieView.theme.gradient.primary = e.target.value.trim() || 'none'; bnApplyTheme(); bnRenderThemePresets(); });
  $('#bn-t-gs').addEventListener('change', (e) => { bernieView.theme.gradient.secondary = e.target.value.trim() || 'none'; bnApplyTheme(); bnRenderThemePresets(); });
  $('#bn-t-trans').addEventListener('input', (e) => { bernieView.theme.transparency = e.target.value; $('#bn-t-trans-lbl').textContent = e.target.value + '%'; bnApplyTheme(); bnRenderThemePresets(); });
  $('#bn-t-bright').addEventListener('input', (e) => { bernieView.theme.brightness = e.target.value; $('#bn-t-bright-lbl').textContent = e.target.value + '%'; bnApplyTheme(); });
  $('#bn-t-density').addEventListener('change', (e) => { bernieView.theme.density = e.target.value; bnApplyTheme(); });
  $('#bn-t-edges').addEventListener('change', (e) => { bernieView.theme.edges = e.target.value; bnApplyTheme(); });
  $('#bn-t-depth').addEventListener('change', (e) => { bernieView.theme.depth = e.target.value; bnApplyTheme(); });
  $('#bn-t-reset').addEventListener('click', () => {
    bernieView.theme = JSON.parse(JSON.stringify(BERNIE_THEME_DEFAULT));
    bnApplyTheme();
    bnRenderThemePresets();
    bnRenderThemeCustom();
  });
}

/* ------------------------------------------------------------ output row */
function bnOpenOutputRow() {
  const row = $('#bn-output-row');
  if (row) row.hidden = false;
}

function bnToggleOutputRow() {
  const row = $('#bn-output-row');
  if (row) row.hidden = !row.hidden;
}

/* ------------------------------------------------------------- main render */
async function renderBernie() {
  const root = $('#view-root');
  root.innerHTML = `
    <div class="view bernie-view">
      <div class="bn-brand"><span class="bn-brand-ic codicon codicon-graph"></span><span class="bn-brand-name">Flow Canvas</span></div>

      <div class="bn-toolbar" id="bn-toolbar">
        <input id="bernie-name" value="${esc(bernieState.name)}" title="Canvas name" />
        <select id="bernie-load" title="Load a saved canvas"></select>
        <button class="bn-btn" id="bn-new" title="New canvas">New</button>
        <button class="bn-btn bn-btn-primary" id="bn-save"><span class="codicon codicon-save"></span> Save</button>
        <span class="bn-sep"></span>
        <button class="bn-btn bn-btn-primary" id="bn-run"><span class="codicon codicon-play"></span> Run</button>
        <button class="bn-btn" id="bn-suggest" title="AI workflow suggestions"><span class="codicon codicon-lightbulb-sparkle"></span> Suggest</button>
        <button class="bn-btn" id="bn-tidy" title="Auto-arrange the graph">Tidy</button>
        <span class="bn-sep"></span>
        <button class="bn-btn" id="bn-output-btn" title="Show / hide the output drawer"><span class="codicon codicon-console"></span> Output</button>
      </div>

      <div class="bn-settings-pill" id="bn-settings-pill">
        <button class="bn-btn" id="bn-exit" title="Back to Conductor"><span class="codicon codicon-chevron-left"></span> Back</button>
        <span class="bn-sep"></span>
        <button class="bn-btn" id="bn-grid-btn" title="Grid settings"><span class="codicon codicon-grid"></span></button>
        <button class="bn-btn" id="bn-map-btn" title="Minimap settings"><span class="codicon codicon-map"></span></button>
        <button class="bn-btn" id="bn-theme-btn" title="Canvas theme &amp; customization"><span class="codicon codicon-symbol-color"></span></button>
      </div>

      <div class="bn-flyout" id="bn-grid-flyout" hidden>
        <div class="bn-flyout-head"><span><span class="codicon codicon-grid"></span> Grid Customization</span><button class="bn-flyout-close">×</button></div>
        <label class="bn-tc-row"><span>Show grid</span><input type="checkbox" id="bn-g-show" /></label>
        <label class="bn-tc-row"><span>Visual grid density <b id="bn-g-density-lbl"></b></span><input type="range" id="bn-g-density" min="10" max="100" /></label>
        <label class="bn-tc-row"><span>Snap to grid</span><input type="checkbox" id="bn-g-snap" /></label>
        <label class="bn-tc-row"><span>Snap grid size <b id="bn-g-snap-lbl"></b></span><input type="range" id="bn-g-snap-size" min="5" max="50" /></label>
        <label class="bn-tc-row"><span>Transparency</span><input type="range" id="bn-g-trans" min="0" max="1" step="0.05" /></label>
        <label class="bn-tc-row"><span>Color</span><input type="color" id="bn-g-color" /></label>
        <label class="bn-tc-row"><span>Pattern</span>
          <span class="bn-pattern-row">
            <button class="bn-pattern-btn" data-pat="lines" title="Lines"><span class="bn-pat-icon bn-pat-lines"></span></button>
            <button class="bn-pattern-btn" data-pat="dots" title="Dots"><span class="bn-pat-icon bn-pat-dots"></span></button>
            <button class="bn-pattern-btn" data-pat="cross" title="Cross"><span class="bn-pat-icon bn-pat-cross"></span></button>
          </span>
        </label>
      </div>

      <div class="bn-flyout" id="bn-map-flyout" hidden>
        <div class="bn-flyout-head"><span><span class="codicon codicon-map"></span> Minimap Settings</span><button class="bn-flyout-close">×</button></div>
        <label class="bn-tc-row"><span>Show minimap</span><input type="checkbox" id="bn-m-show" /></label>
        <label class="bn-tc-row"><span>Transparency</span><input type="range" id="bn-m-opacity" min="0.1" max="1" step="0.05" /></label>
        <label class="bn-tc-row"><span>Size (scale)</span><input type="range" id="bn-m-scale" min="0.5" max="2" step="0.1" /></label>
      </div>

      <div class="bn-mode-pill" id="bn-mode-pill">
        <button class="bn-mode active" id="bn-mode-pan" title="Pan mode — drag to move around"><span class="codicon codicon-hand"></span> Pan</button>
        <button class="bn-mode" id="bn-mode-select" title="Select mode — drag a box to select nodes"><span class="codicon codicon-pointer"></span> Select</button>
      </div>

      <div class="bn-main">
        <aside class="bn-panel bn-left" data-mode="flat" id="bn-left-panel">
          <div class="bn-panel-head">
            <span class="bn-panel-title">Canvas</span>
            <button class="bn-panel-btn" id="bn-left-float" title="Float panel"></button>
          </div>
          <div class="bn-panel-body">
            <div class="bn-panel-section">Canvases</div>
            <div id="bn-library"></div>
            <div class="bn-panel-section">Canvas Theme</div>
            <div id="bn-theme-presets" class="bn-preset-grid"></div>
            <div class="bn-panel-sub">Customize</div>
            <div id="bn-theme-custom"></div>
          </div>
        </aside>

        <div class="bn-stage" id="bn-stage">
          <div class="bn-canvas-area" id="bernie-canvas-area">
            <div class="bn-zoom-wrap" id="bn-zoom-wrap">
              <div class="bn-grid-layer" id="bn-grid-layer"></div>
              <div class="bernie-canvas-inner" id="bernie-canvas-inner"></div>
            </div>
          </div>
          <div class="bn-stage-hint" id="bn-stage-hint">
            <span class="codicon codicon-graph" style="font-size:2rem;opacity:.5"></span>
            <p>Drag nodes from the palette, or click one to add it.<br/>Drag the dot on a node's right edge to connect it to another node.</p>
          </div>
          <div class="bn-selection-bar" id="bn-selection-bar" hidden>
            <span id="bn-sel-count"></span>
            <span class="bn-sep"></span>
            <button class="bn-btn" id="bn-dup-sel"><span class="codicon codicon-copy"></span> Duplicate</button>
            <button class="bn-btn bn-danger-btn" id="bn-del-sel"><span class="codicon codicon-trash"></span> Delete</button>
            <button class="bn-btn" id="bn-clear-sel">Clear</button>
          </div>
          <div class="bn-zoom-pill" id="bn-zoom-pill">
            <button class="bn-btn" id="bn-zoom-out" title="Zoom out">−</button>
            <span class="bn-zoom-label" id="bn-zoom-label">100%</span>
            <button class="bn-btn" id="bn-zoom-in" title="Zoom in">+</button>
            <span class="bn-sep"></span>
            <button class="bn-btn" id="bn-zoom-fit" title="Fit view">Fit</button>
          </div>
          <div class="bn-minimap" id="bn-minimap" hidden>
            <div class="bn-mm-box" id="bn-minimap-box"></div>
            <div class="bn-mm-viewport" id="bn-minimap-viewport"></div>
          </div>
          <div class="bn-marquee" id="bn-marquee" hidden></div>
          <div class="bn-context-menu" id="bn-context-menu" hidden></div>
        </div>

        <aside class="bn-panel bn-right" data-mode="flat" id="bn-right-panel">
          <div class="bn-panel-head">
            <span class="bn-panel-title">Node Palette</span>
            <button class="bn-panel-btn" id="bn-right-float" title="Float panel"></button>
          </div>
          <div class="bn-panel-body">
            <p class="bn-panel-sub">Drag nodes onto the canvas to build your workflow.</p>
            <div id="bn-palette"></div>
          </div>
        </aside>
      </div>

      <div class="bn-output-row" id="bn-output-row" hidden>
        <div class="bn-output"><div class="bn-output-title">Output (Flush nodes)</div><div class="bn-output-body" id="bernie-flush"><div class="settings-note">Nothing flushed yet — run the workflow.</div></div></div>
        <div class="bn-output"><div class="bn-output-title">AI suggestions</div><div class="bn-output-body" id="bernie-suggest"><div class="settings-note">Hit <b>Suggest</b> to have the AI review the graph.</div></div></div>
      </div>
    </div>`;

  /* ---- apply canvas environment (theme + panels) ---- */
  bnApplyTheme();
  bnSetPanelMode('left', bernieView.panels.left);
  bnSetPanelMode('right', bernieView.panels.right);
  bnRenderPalette();
  bnRenderThemePresets();
  bnRenderThemeCustom();
  bnApplyGrid();
  bnApplyZoom();

  /* ---- toolbar ---- */
  $('#bernie-name').addEventListener('input', (e) => { bernieState.name = e.target.value; bernieState.dirty = true; });
  $('#bn-save').addEventListener('click', bernieSave);
  $('#bn-new').addEventListener('click', () => {
    bernieState.canvasId = null;
    bernieState.name = 'Untitled canvas';
    bernieState.nodes = [];
    bernieState.edges = [];
    bernieState.dirty = false;
    bernieView.selected.clear();
    renderBernie();
  });
  $('#bn-tidy').addEventListener('click', bernieAutoArrange);
  $('#bn-run').addEventListener('click', bernieRunWorkflow);
  $('#bn-suggest').addEventListener('click', bernieSuggest);
  $('#bn-output-btn').addEventListener('click', bnToggleOutputRow);
  $('#bn-exit').addEventListener('click', () => showView('chat'));
  $('#bernie-load').addEventListener('change', (e) => {
    const id = Number(e.target.value);
    if (id) bnLoadCanvas(id);
  });

  /* ---- settings pill + flyouts ---- */
  $('#bn-grid-btn').addEventListener('click', bnOpenGridFlyout);
  $('#bn-map-btn').addEventListener('click', bnOpenMapFlyout);
  $('#bn-theme-btn').addEventListener('click', () => {
    const p = $('#bn-left-panel');
    if (p) {
      p.dataset.collapsed = '';
      const tp = $('#bn-theme-presets');
      if (tp) tp.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
  $$('.bn-flyout-close').forEach((b) => b.addEventListener('click', bnHideFlyouts));
  $('#bn-grid-flyout #bn-g-show').addEventListener('change', (e) => { bernieView.grid.show = e.target.checked; bnApplyGrid(); });
  $('#bn-grid-flyout #bn-g-density').addEventListener('input', (e) => { bernieView.grid.density = Number(e.target.value); $('#bn-g-density-lbl').textContent = e.target.value + 'px'; bnApplyGrid(); });
  $('#bn-grid-flyout #bn-g-snap').addEventListener('change', (e) => { bernieView.grid.snap = e.target.checked; });
  $('#bn-grid-flyout #bn-g-snap-size').addEventListener('input', (e) => { bernieView.grid.snapSize = Number(e.target.value); $('#bn-g-snap-lbl').textContent = e.target.value + 'px'; });
  $('#bn-grid-flyout #bn-g-trans').addEventListener('input', (e) => { bernieView.grid.transparency = Number(e.target.value); bnApplyGrid(); });
  $('#bn-grid-flyout #bn-g-color').addEventListener('input', (e) => { bernieView.grid.color = e.target.value; bnApplyGrid(); });
  $$('#bn-grid-flyout .bn-pattern-btn').forEach((b) => b.addEventListener('click', () => {
    bernieView.grid.variant = b.dataset.pat;
    bnApplyGrid();
    bnSyncGridControls();
  }));
  $('#bn-map-flyout #bn-m-show').addEventListener('change', (e) => { bernieView.minimap.show = e.target.checked; bnRenderMinimap(); });
  $('#bn-map-flyout #bn-m-opacity').addEventListener('input', (e) => { bernieView.minimap.opacity = Number(e.target.value); bnRenderMinimap(); });
  $('#bn-map-flyout #bn-m-scale').addEventListener('input', (e) => { bernieView.minimap.scale = Number(e.target.value); bnRenderMinimap(); });

  /* ---- mode pill ---- */
  const setMode = (mode) => {
    bernieView.selectMode = mode === 'select';
    $('#bn-mode-pan').classList.toggle('active', !bernieView.selectMode);
    $('#bn-mode-select').classList.toggle('active', bernieView.selectMode);
  };
  $('#bn-mode-pan').addEventListener('click', () => setMode('pan'));
  $('#bn-mode-select').addEventListener('click', () => setMode('select'));

  /* ---- stage interactions: wheel zoom, pan / marquee, drop, scroll ---- */
  const area = $('#bernie-canvas-area');
  area.addEventListener('wheel', (e) => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    const rect = area.getBoundingClientRect();
    const cx = e.clientX - rect.left + area.scrollLeft;
    const cy = e.clientY - rect.top + area.scrollTop;
    const factor = Math.exp(-e.deltaY * 0.0015);
    bnSetZoom(bernieView.zoom * factor, cx, cy);
  }, { passive: false });

  area.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 && e.button !== 1) return;
    if (e.target.closest('.bnode, button, input, select, .bn-minimap, .bn-zoom-pill, .bn-flyout, .bn-panel, #bn-context-menu')) return;
    bnHideFlyouts();
    bnHideContextMenu();
    const startX = e.clientX, startY = e.clientY;
    const sl = area.scrollLeft, st = area.scrollTop;
    if (bernieView.selectMode) {
      const mq = $('#bn-marquee');
      const stage = $('#bn-stage');
      const sRect = stage.getBoundingClientRect();
      const x0 = e.clientX - sRect.left, y0 = e.clientY - sRect.top;
      mq.hidden = false;
      mq.style.left = x0 + 'px'; mq.style.top = y0 + 'px';
      mq.style.width = '0px'; mq.style.height = '0px';
      const move = (ev) => {
        const x1 = ev.clientX - sRect.left, y1 = ev.clientY - sRect.top;
        mq.style.left = Math.min(x0, x1) + 'px';
        mq.style.top = Math.min(y0, y1) + 'px';
        mq.style.width = Math.abs(x1 - x0) + 'px';
        mq.style.height = Math.abs(y1 - y0) + 'px';
      };
      const up = (ev) => {
        document.removeEventListener('pointermove', move);
        document.removeEventListener('pointerup', up);
        mq.hidden = true;
        const rect = area.getBoundingClientRect();
        const z = bernieView.zoom || 1;
        const l = Math.min(x0, ev.clientX - sRect.left), t = Math.min(y0, ev.clientY - sRect.top);
        const r = Math.max(x0, ev.clientX - sRect.left), b = Math.max(y0, ev.clientY - sRect.top);
        const cx0 = (l - rect.left + area.scrollLeft) / z;
        const cy0 = (t - rect.top + area.scrollTop) / z;
        const cx1 = (r - rect.left + area.scrollLeft) / z;
        const cy1 = (b - rect.top + area.scrollTop) / z;
        const hit = [];
        $$('.bnode').forEach((nEl) => {
          const x = nEl.offsetLeft, y = nEl.offsetTop;
          if (x < cx1 && x + nEl.offsetWidth > cx0 && y < cy1 && y + nEl.offsetHeight > cy0) hit.push(nEl.dataset.id);
        });
        bnSelectByIds(hit, e.shiftKey);
      };
      document.addEventListener('pointermove', move);
      document.addEventListener('pointerup', up);
    } else {
      const move = (ev) => {
        area.scrollLeft = sl - (ev.clientX - startX);
        area.scrollTop = st - (ev.clientY - startY);
        bnRenderMinimap();
      };
      const up = () => {
        document.removeEventListener('pointermove', move);
        document.removeEventListener('pointerup', up);
        if (Math.abs(sl - area.scrollLeft) + Math.abs(st - area.scrollTop) > 2) bnClearSelection();
      };
      document.addEventListener('pointermove', move);
      document.addEventListener('pointerup', up);
    }
  });

  area.addEventListener('scroll', () => bnRenderMinimap());
  area.addEventListener('dragover', (e) => e.preventDefault());
  area.addEventListener('drop', (e) => {
    e.preventDefault();
    const type = e.dataTransfer.getData('text/plain') || 'text';
    if (!BERNIE_NODE_TYPES[type]) return;
    const rect = area.getBoundingClientRect();
    const z = bernieView.zoom || 1;
    const x = Math.max(0, (e.clientX - rect.left + area.scrollLeft) / z - 104);
    const y = Math.max(0, (e.clientY - rect.top + area.scrollTop) / z - 50);
    bnAddNodeAt(type, x, y);
  });

  /* ---- selection bar ---- */
  $('#bn-dup-sel').addEventListener('click', bnDuplicateSelected);
  $('#bn-del-sel').addEventListener('click', bnDeleteSelected);
  $('#bn-clear-sel').addEventListener('click', bnClearSelection);

  /* ---- zoom pill ---- */
  $('#bn-zoom-in').addEventListener('click', () => bnSetZoom(bernieView.zoom * 1.2));
  $('#bn-zoom-out').addEventListener('click', () => bnSetZoom(bernieView.zoom / 1.2));
  $('#bn-zoom-fit').addEventListener('click', bnZoomFit);

  /* ---- minimap click-to-navigate ---- */
  const mm = $('#bn-minimap');
  mm.addEventListener('pointerdown', (e) => {
    const rect = mm.getBoundingClientRect();
    const z = bernieView.zoom || 1;
    const kx = (3200 * z) / rect.width;
    const ky = (2000 * z) / rect.height;
    area.scrollLeft = Math.max(0, (e.clientX - rect.left) * kx - area.clientWidth / 2);
    area.scrollTop = Math.max(0, (e.clientY - rect.top) * ky - area.clientHeight / 2);
    bnRenderMinimap();
  });

  /* ---- context menu actions + dismissal ---- */
  $('#bn-context-menu').addEventListener('click', (e) => {
    const act = e.target.closest('button')?.dataset.act;
    const t = bernieView.ctxTarget;
    bnHideContextMenu();
    if (!t) return;
    if (act === 'inspect') bnInspect(t.id);
    else if (act === 'duplicate') { bernieView.selected.clear(); bernieView.selected.add(t.id); bnSyncSelection(); bnDuplicateSelected(); }
    else if (act === 'delete') {
      bernieState.nodes = bernieState.nodes.filter((n) => n.id !== t.id);
      bernieState.edges = bernieState.edges.filter((e) => e.source !== t.id && e.target !== t.id);
      bernieState.dirty = true;
      bernieRenderCanvas();
    } else if (act === 'delete-edge') {
      bernieState.edges.splice(t.index, 1);
      bernieState.dirty = true;
      bernieDrawEdges();
      bnRenderMinimap();
    }
  });
  /* ---- global listeners (wire once; elements get recreated per render) ---- */
  if (!renderBernie._globalWired) {
    renderBernie._globalWired = true;
    document.addEventListener('pointerdown', (e) => {
      if (!e.target.closest('#bn-context-menu')) bnHideContextMenu();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        bnHideFlyouts();
        bnHideContextMenu();
        bnClearSelection();
      }
    });
    window.addEventListener('resize', () => bnRenderMinimap());
  }

  /* ---- panels: float/dock toggles + collapse chevrons ---- */
  $('#bn-left-float').addEventListener('click', () => bnSetPanelMode('left', bernieView.panels.left === 'flat' ? 'floating' : 'flat'));
  $('#bn-right-float').addEventListener('click', () => bnSetPanelMode('right', bernieView.panels.right === 'flat' ? 'floating' : 'flat'));

  bernieRenderCanvas();
  await bernieLoadList();
}

/* ==========================================================================
   SIDEBAR REWORK — new module views, Models pane, Navigation customizer
   ========================================================================== */

const MODULE_STUBS = {
  content:         { title: 'Content',         icon: 'codicon-notebook',       desc: 'Content operations for listings, copy, and creative.', related: 'catalog', relatedLabel: 'Catalog' },
  case:            { title: 'Case Management', icon: 'codicon-issue-opened',   desc: 'Customer and support cases across marketplaces.', related: 'tasks', relatedLabel: 'Action Queue' },
  fba:             { title: 'FBA',             icon: 'codicon-package',        desc: 'Fulfillment by Amazon — shipments, inventory, and prep.', related: 'products', relatedLabel: 'Products' },
  customerservice: { title: 'Customer Service', icon: 'codicon-person',        desc: 'Inbox, tickets, and customer communications.', related: 'tasks', relatedLabel: 'Action Queue' },
  brands:          { title: 'Brands',          icon: 'codicon-briefcase',      desc: 'Brand registry, brand health, and portfolio.', related: 'products', relatedLabel: 'Products' },
  people:          { title: 'People',          icon: 'codicon-organization',   desc: 'Team, roles, and the people behind the operation.', related: 'asana', relatedLabel: 'Asana' },
  listings:        { title: 'Listings',        icon: 'codicon-list-unordered', desc: 'Live listings and listing quality across channels.', related: 'products', relatedLabel: 'Products' },
  walmart:         { title: 'Walmart',         icon: 'codicon-globe',          desc: 'Walmart Marketplace operations.', related: 'products', relatedLabel: 'Products' },
  tiktok:          { title: 'TikTok',          icon: 'codicon-globe',          desc: 'TikTok Shop operations.', related: 'products', relatedLabel: 'Products' },
  target:          { title: 'Target',          icon: 'codicon-globe',          desc: 'Target marketplace operations.', related: 'products', relatedLabel: 'Products' },
  spp:             { title: 'SPP',             icon: 'codicon-globe',          desc: 'SPP (Strategic Partner Platform) operations.', related: 'products', relatedLabel: 'Products' },
  coastal:         { title: 'Coastal',         icon: 'codicon-globe',          desc: 'Coastal channel operations.', related: 'products', relatedLabel: 'Products' },
  agency:          { title: 'Agency',          icon: 'codicon-globe',          desc: 'Agency client and brand management.', related: 'products', relatedLabel: 'Products' },
  agentbuilder:    { title: 'Agent Builder',   icon: 'codicon-rocket',         desc: 'Compose custom agents from skills and tools.', related: 'agents', relatedLabel: 'Agents' },
  runbooks:        { title: 'Runbooks',        icon: 'codicon-notebook',       desc: 'Step-by-step operational runbooks.', related: 'sops', relatedLabel: 'SOPs' },
  policies:        { title: 'Policies',        icon: 'codicon-library',        desc: 'Company policies and governance documents.', related: 'sops', relatedLabel: 'SOPs' },
};

function renderModuleStub(view) {
  const m = MODULE_STUBS[view] || { title: view, icon: 'codicon-circle', desc: 'Module scoped — not yet built.', related: '', relatedLabel: '' };
  $('#view-root').innerHTML = `
    <div class="view">
      <div class="view-header"><div><div class="view-title">${m.title}</div><div class="view-sub">${m.desc}</div></div></div>
      <div class="empty-state" style="padding-top:3rem">
        <div class="big"><span class="codicon ${m.icon}"></span></div>
        <div>This module is scoped but not built yet.</div>
        <div style="margin-top:0.5rem;color:var(--muted-fg);font-size:0.71875rem">Reorder, hide, or replace it from Settings → Navigation — or ask to build it out.</div>
        ${m.related ? `<button class="btn-primary" data-rel="${m.related}" style="margin-top:0.75rem">Open ${m.relatedLabel}</button>` : ''}
      </div>
    </div>`;
  const rel = $('#view-root').querySelector('[data-rel]');
  if (rel) rel.addEventListener('click', () => showView(rel.dataset.rel));
}

function renderAmazon() {
  $('#view-root').innerHTML = `
    <div class="view">
      <div class="view-header"><div><div class="view-title">Amazon</div><div class="view-sub">Amazon platform hub — the marketplace integrations and tools for listing, data, and operations.</div></div></div>
      <div class="home-cards" style="grid-template-columns:repeat(auto-fill,minmax(220px,1fr))">
        <div class="home-card clickable" data-nav="productpipeline">
          <div class="home-card-label"><span class="codicon codicon-git-merge"></span> SP-API</div>
          <div class="home-card-val" style="font-size:0.8125rem">Product Pipelines</div>
          <div class="muted" style="font-size:0.71875rem">getDefinitionsProductType → required attributes, flat files, guidelines, catalog readiness.</div>
        </div>
        <div class="home-card clickable" data-nav="keepa">
          <div class="home-card-label"><span class="codicon codicon-graph-line"></span> Keepa</div>
          <div class="home-card-val" style="font-size:0.8125rem">Live product data</div>
          <div class="muted" style="font-size:0.71875rem">Price, sales rank, rating, images by ASIN.</div>
        </div>
        <div class="home-card clickable" data-nav="flatfile">
          <div class="home-card-label"><span class="codicon codicon-table"></span> Flat Files</div>
          <div class="home-card-val" style="font-size:0.8125rem">Templates &amp; CSVs</div>
          <div class="muted" style="font-size:0.71875rem">Per-product-type flat-file templates.</div>
        </div>
        <div class="home-card clickable" data-nav="variation">
          <div class="home-card-label"><span class="codicon codicon-versions"></span> Variations</div>
          <div class="home-card-val" style="font-size:0.8125rem">Family validator</div>
          <div class="muted" style="font-size:0.71875rem">Validate variation families before submission.</div>
        </div>
        <div class="home-card clickable" data-nav="fba">
          <div class="home-card-label"><span class="codicon codicon-package"></span> FBA</div>
          <div class="home-card-val" style="font-size:0.8125rem">Fulfillment</div>
          <div class="muted" style="font-size:0.71875rem">Shipments, inventory, and prep.</div>
        </div>
        <div class="home-card clickable" data-nav="listings">
          <div class="home-card-label"><span class="codicon codicon-list-unordered"></span> Listings</div>
          <div class="home-card-val" style="font-size:0.8125rem">Live listings</div>
          <div class="muted" style="font-size:0.71875rem">Listing quality across channels.</div>
        </div>
      </div>
      <div class="settings-note" style="margin-top:1rem">SP-API credentials can be set here, on the <b>Integrations</b> page, or in <b>Settings → SP-API</b> — all three share the same credential store.</div>
    </div>`;
  $('#view-root').querySelectorAll('.home-card[data-nav]').forEach((c) => {
    c.addEventListener('click', () => showView(c.dataset.nav));
  });
}

function renderDeveloper() {
  $('#view-root').innerHTML = `
    <div class="view">
      <div class="view-header"><div><div class="view-title">Developer</div><div class="view-sub">REST API, webhooks, and the integration surface for Conductor.</div></div></div>
      <div class="api-endpoints">
        ${[
          ['GET', '/api/health'], ['GET', '/api/stats'], ['GET', '/api/products'], ['POST', '/api/products'],
          ['POST', '/api/ingest/upload'], ['POST', '/webhooks/ingest'], ['POST', '/webhooks/automation/{source}'],
          ['GET', '/api/data/table'], ['POST', '/api/data/pivot'], ['POST', '/api/svl/compare'], ['GET', '/api/flatfiles'],
        ].map(([m, p]) => `<div class="api-row"><span class="method ${m.toLowerCase()}">${m}</span><span>${p}</span></div>`).join('')}
      </div>
      <div class="settings-note" style="margin-top:0.75rem">POST JSON to <code>/webhooks/automation/&lt;source&gt;</code> to trigger automations. Push external catalog data to <code>/webhooks/ingest</code>. Full OpenAPI docs at <code>/docs</code>.</div>
    </div>`;
}

async function renderWorkflows() {
  const root = $('#view-root');
  root.innerHTML = `<div class="view">
    <div class="view-header">
      <div>
        <div class="view-title">Workflows & Brand Onboarding</div>
        <div class="view-sub">Automated brand onboarding: Keepa listing pull, preliminary compliance audit, 30-60-90 day cost forecast, and preview Asana task generation.</div>
      </div>
    </div>

    <!-- New Brand Onboarding Interactive Panel -->
    <div class="card" style="padding:16px; margin-bottom:20px; background:var(--t-surface-raised, #1e1e2e);">
      <div style="font-size:1.1rem; font-weight:700; margin-bottom:8px;">🚀 Onboard New Brand Workflow</div>
      <div style="display:flex; gap:12px; margin-bottom:12px;">
        <label class="field" style="flex:1;"><span>Brand Name</span>
          <input type="text" id="wf-brand-name" class="input-text" placeholder="e.g. Luminize or Anker" value="Luminize"></label>
        <label class="field" style="flex:1;"><span>Seller ID (Optional)</span>
          <input type="text" id="wf-seller-id" class="input-text" placeholder="e.g. A1234SELLER"></label>
      </div>
      <button class="btn-primary" id="btn-run-brand-onboarding"><span class="codicon codicon-play"></span> Run Brand Onboarding Workflow</button>
    </div>

    <!-- Onboarding Dashboard Results -->
    <div id="wf-onboarding-dashboard" style="display:none; margin-bottom:24px;">
      <div class="view-title" style="font-size:1.05rem; margin-bottom:10px;">📊 Onboarding Forecasted Cost of Work (30-60-90 Days)</div>
      <div class="home-cards" style="margin-bottom:16px;">
        <div class="home-card">
          <div class="home-card-label">30-Day Cost (Audit & Fix)</div>
          <div class="home-card-val" id="wf-cost-30">$0</div>
        </div>
        <div class="home-card">
          <div class="home-card-label">60-Day Cost (Content & A+)</div>
          <div class="home-card-val" id="wf-cost-60">$0</div>
        </div>
        <div class="home-card">
          <div class="home-card-label">90-Day Cost (SLA Maint)</div>
          <div class="home-card-val" id="wf-cost-90">$0</div>
        </div>
        <div class="home-card" style="border:2px solid var(--t-function-primary, #3b82f6);">
          <div class="home-card-label">Total 90-Day Onboarding</div>
          <div class="home-card-val" id="wf-cost-total" style="color:var(--t-function-primary, #3b82f6);">$0</div>
        </div>
      </div>

      <!-- Preview Asana Tasks Header & Push Action -->
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
        <div class="view-title" style="font-size:1.05rem;">📋 Preview Asana Tasks Created Locally</div>
        <button class="btn-secondary" id="btn-push-onboarding-asana"><span class="codicon codicon-cloud-upload"></span> Push Preview Tasks to Asana</button>
      </div>
      <div class="data-table-wrap" id="wf-preview-tasks-table"></div>
    </div>

    <div class="view-title" style="font-size:1.05rem; margin-bottom:8px;">Configured System Workflows</div>
    <div id="wf-body" class="empty-state">Loading…</div>
  </div>`;

  // Wire Brand Onboarding Button
  root.querySelector('#btn-run-brand-onboarding').addEventListener('click', async () => {
    const brand = root.querySelector('#wf-brand-name').value.trim();
    const seller_id = root.querySelector('#wf-seller-id').value.trim();
    if (!brand) return toast('Please enter a brand name', 'warn');

    toast(`Running brand onboarding for ${brand}...`, 'info');
    try {
      const res = await api('/api/workflows/onboard-brand', {
        method: 'POST',
        body: { brand, seller_id },
      });

      const dash = root.querySelector('#wf-onboarding-dashboard');
      dash.style.display = 'block';

      root.querySelector('#wf-cost-30').textContent = `$${res.forecasted_cost.day_30}`;
      root.querySelector('#wf-cost-60').textContent = `$${res.forecasted_cost.day_60}`;
      root.querySelector('#wf-cost-90').textContent = `$${res.forecasted_cost.day_90}`;
      root.querySelector('#wf-cost-total').textContent = `$${res.forecasted_cost.total_90d}`;

      const tasksTable = root.querySelector('#wf-preview-tasks-table');
      const tasks = res.preview_tasks || [];
      tasksTable.innerHTML = `<table class="data-table">
        <thead><tr><th>Task Name</th><th>Phase</th><th>Due Date</th><th>Est. Cost</th></tr></thead>
        <tbody>
          ${tasks.map((t) => `<tr>
            <td><b>${esc(t.name)}</b></td>
            <td><span class="chip chip-primary">${esc(t.phase)}</span></td>
            <td>${esc(t.due_on)}</td>
            <td>$${t.cost}</td>
          </tr>`).join('')}
        </tbody>
      </table>`;

      toast(`Workflow complete! Created ${tasks.length} preview tasks.`, 'info');
    } catch (e) {
      toast('Workflow failed: ' + e.message, 'err');
    }
  });

  // Wire Push Preview Tasks Button
  root.querySelector('#btn-push-onboarding-asana').addEventListener('click', async () => {
    toast('Pushing onboarding preview tasks to remote store...', 'info');
    try {
      const res = await api('/api/workflows/push-onboarding-tasks', { method: 'POST' });
      toast(res.message || 'Pushed onboarding tasks', 'info');
    } catch (e) {
      toast(e.message, 'err');
    }
  });

  try {
    const autos = await api('/api/automations');
    const rows = (autos || []).map((a) => `
      <tr>
        <td><b>${esc(a.name)}</b>${a.description ? `<div style="color:var(--muted-fg)">${esc(a.description)}</div>` : ''}</td>
        <td class="mono">${esc(a.trigger_source || '')} → ${esc(a.trigger_event || '')}</td>
        <td>${a.enabled ? '<span class="pill-int pill-int-configured">on</span>' : '<span class="pill-int pill-int-missing">off</span>'}</td>
        <td>${a.last_status ? esc(a.last_status) : '—'}</td>
      </tr>`).join('');
    $('#wf-body').innerHTML = rows
      ? `<table class="data-table"><thead><tr><th>Workflow</th><th>Trigger</th><th>State</th><th>Last run</th></tr></thead><tbody>${rows}</tbody></table>`
      : `<div class="empty-state"><div class="big"><span class="codicon codicon-git-merge"></span></div><div>No custom automation workflows yet. Create one in Automation → Automations.</div></div>`;
  } catch (e) { $('#wf-body').innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`; }
}

/* ----------------------------------------------------------------- Models
   Right-pane "Models" tab — local GGUF discovery + provider models. */
async function loadModels() {
  const list = $('#models-list');
  if (!list) return;
  list.innerHTML = '<div class="folder-loading">Loading models…</div>';
  try {
    const [disc, provs, cfg] = await Promise.all([
      api('/api/llama/discover'), api('/api/chat/providers'), api('/api/chat/config'),
    ]);
    const models = disc.models || [];
    const srcLabel = (s) => {
      if (s.includes('conductor')) return 'conductor models/';
      if (s.includes('.ollama')) return 'Ollama';
      if (s.includes('lm-studio')) return 'LM Studio';
      if (s.includes('.lmstudio')) return 'LM Studio (legacy)';
      if (s.includes('jan')) return 'Jan / Atomic Chat';
      if (s.includes('Conductor')) return 'AppData models';
      return s.split(/[\\/]/).slice(-2).join('/');
    };
    const ggufRows = models.map((m) => `
      <div class="model-row">
        <span class="codicon codicon-package"></span>
        <div class="model-meta">
          <div class="model-name">${esc(m.name)}</div>
          <div class="model-sub">${(m.sizeBytes / 1073741824).toFixed(1)} GB · ${esc(srcLabel(m.sourceDir))} · ${esc(m.kind)}</div>
        </div>
      </div>`).join('');
    const providerRows = (provs.providers || []).map((p) => `
      <div class="model-row">
        <span class="codicon codicon-server-process"></span>
        <div class="model-meta">
          <div class="model-name">${esc(p.label)}${p.configured ? '' : ' <span style="color:var(--muted-fg)">(no key)</span>'}</div>
          <div class="model-sub">${esc(p.defaultModelId || '')}</div>
        </div>
        ${(cfg.provider === p.id) ? '<span class="pill-int pill-int-configured">active</span>' : ''}
      </div>`).join('');
    list.innerHTML = `
      <div class="pane-section-label">Active</div>
      <div class="model-row">
        <span class="codicon codicon-zap"></span>
        <div class="model-meta">
          <div class="model-name">${esc(cfg.provider || '—')}</div>
          <div class="model-sub">${esc(cfg.model || cfg.llama_model || '—')}</div>
        </div>
      </div>
      <div class="pane-section-label">Providers</div>
      ${providerRows || '<div class="folder-hint">No providers.</div>'}
      <div class="pane-section-label">Local GGUF (${models.length})</div>
      ${ggufRows || '<div class="folder-hint">No GGUF models found. Drop one into models/.</div>'}`;
  } catch (e) {
    list.innerHTML = `<div class="folder-hint">Could not load models: ${esc(e.message)}</div>`;
  }
}

/* ------------------------------------------------------------------ Navigation
   Settings → Navigation: presets + full sidebar customization. */
function renderNavigationTab() {
  const box = $('#settings-content');
  const Sidebar = window.ConductorSidebar;
  const cfg = Sidebar.loadSidebarConfig();

  const presetOpts = Sidebar.SIDEBAR_PRESET_IDS.map((id) =>
    `<option value="${id}" ${cfg.preset === id ? 'selected' : ''}>${Sidebar.SIDEBAR_PRESETS[id].label}</option>`).join('')
    + `<option value="custom" ${!Sidebar.SIDEBAR_PRESET_IDS.includes(cfg.preset) ? 'selected' : ''}>Custom</option>`;

  const sections = cfg.sections.map((sec, si) => {
    const itemRows = (sec.items || []).map((id, ii) => {
      const item = Sidebar.resolveNavItem(id, cfg);
      const label = item ? item.label : `(${id})`;
      const icon = (item && item.icon) ? item.icon.replace(/[^a-zA-Z0-9_-]/g, '') : 'codicon-circle';
      return `<div class="nav-item-row">
        <span class="codicon ${icon}"></span>
        <span class="nav-item-label">${esc(label)}</span>
        <button class="nav-mini" data-act="item-up" data-si="${si}" data-ii="${ii}" title="Move up">↑</button>
        <button class="nav-mini" data-act="item-down" data-si="${si}" data-ii="${ii}" title="Move down">↓</button>
        <button class="nav-mini nav-mini-danger" data-act="item-del" data-si="${si}" data-ii="${ii}" title="Remove from sidebar">×</button>
      </div>`;
    }).join('');
    return `<div class="nav-section-card">
      <div class="nav-section-head">
        <input class="nav-section-label" data-si="${si}" value="${esc(sec.label || '')}" placeholder="Section name" />
        <button class="nav-mini" data-act="sec-up" data-si="${si}" title="Move section up">↑</button>
        <button class="nav-mini" data-act="sec-down" data-si="${si}" title="Move section down">↓</button>
        <button class="nav-mini nav-mini-danger" data-act="sec-del" data-si="${si}" title="Delete section">×</button>
      </div>
      <div class="nav-section-items">${itemRows || '<div class="nav-empty">No items — add one below.</div>'}</div>
    </div>`;
  }).join('');

  const used = new Set();
  cfg.sections.forEach((s) => (s.items || []).forEach((id) => used.add(id)));
  const available = Sidebar.sidebarAllItemIds().filter((id) => !used.has(id));
  const availOpts = available.map((id) => `<option value="${id}">${esc(Sidebar.NAV_ITEMS[id].label)}</option>`).join('');

  box.innerHTML = `
    <div class="settings-pane active">
      <div class="settings-section">
        <div class="settings-title"><span class="codicon codicon-list-flat"></span> Sidebar Navigation</div>
        <div class="settings-note">Reorder, remove, rename, and add sidebar items — changes apply live. Pick a preset to restructure, or tweak anything by hand.</div>
        <div class="field-row">
          <label class="field"><span>Preset</span><select id="nav-preset">${presetOpts}</select></label>
          <label class="field"><span>&nbsp;</span><button class="btn-primary" id="nav-apply-preset" style="min-height:var(--control-h)">Apply preset</button></label>
        </div>
        <div class="nav-sections">${sections || '<div class="nav-empty">Empty — add a section below.</div>'}</div>
        <div class="field-row" style="margin-top:0.75rem">
          <label class="field"><span>Add built-in item</span><select id="nav-add-select">${availOpts || '<option value="">— all added —</option>'}</select></label>
          <label class="field"><span>&nbsp;</span><button class="btn-secondary" id="nav-add-item" style="min-height:var(--control-h)">＋ Add item</button></label>
        </div>
        <div class="field-row">
          <label class="field"><span>Custom link label</span><input id="nav-cust-label" placeholder="e.g. Help Center" /></label>
          <label class="field"><span>URL</span><input id="nav-cust-url" placeholder="https://…" /></label>
        </div>
        <div class="settings-actions">
          <button class="btn-secondary" id="nav-add-custom">＋ Add custom link</button>
          <button class="btn-secondary" id="nav-add-section">＋ Add section</button>
          <button class="btn-secondary" id="nav-reset">Reset to default</button>
        </div>
        <div class="settings-note" id="nav-avail" style="margin-top:0.5rem">${available.length} built-in item${available.length === 1 ? '' : 's'} not currently shown.</div>
      </div>
    </div>`;

  const commit = () => { Sidebar.saveSidebarConfig(cfg); Sidebar.renderSidebar(); renderNavigationTab(); };

  box.querySelector('#nav-preset').addEventListener('change', (e) => {
    if (e.target.value === 'custom') return;
    cfg.preset = e.target.value;
    cfg.sections = JSON.parse(JSON.stringify(Sidebar.SIDEBAR_PRESETS[e.target.value].sections));
    commit();
  });
  box.querySelector('#nav-apply-preset').addEventListener('click', () => {
    const v = box.querySelector('#nav-preset').value;
    if (v === 'custom') return toast('Pick a preset first', 'warn');
    cfg.preset = v;
    cfg.sections = JSON.parse(JSON.stringify(Sidebar.SIDEBAR_PRESETS[v].sections));
    commit();
  });

  box.querySelectorAll('.nav-section-label').forEach((inp) => inp.addEventListener('change', () => {
    const si = Number(inp.dataset.si);
    if (cfg.sections[si]) cfg.sections[si].label = inp.value.trim() || 'Section';
    Sidebar.saveSidebarConfig(cfg); Sidebar.renderSidebar();
  }));

  box.querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', () => {
    const si = Number(b.dataset.si), ii = Number(b.dataset.ii), act = b.dataset.act;
    const sec = cfg.sections[si];
    if (act === 'sec-up' && si > 0) { [cfg.sections[si - 1], cfg.sections[si]] = [sec, cfg.sections[si - 1]]; }
    else if (act === 'sec-down' && si < cfg.sections.length - 1) { [cfg.sections[si + 1], cfg.sections[si]] = [cfg.sections[si], cfg.sections[si + 1]]; }
    else if (act === 'sec-del') { cfg.sections.splice(si, 1); }
    else if (sec && act === 'item-up' && ii > 0) { [sec.items[ii - 1], sec.items[ii]] = [sec.items[ii], sec.items[ii - 1]]; }
    else if (sec && act === 'item-down' && ii < sec.items.length - 1) { [sec.items[ii + 1], sec.items[ii]] = [sec.items[ii], sec.items[ii + 1]]; }
    else if (sec && act === 'item-del') { sec.items.splice(ii, 1); }
    commit();
  }));

  box.querySelector('#nav-add-item').addEventListener('click', () => {
    const sel = box.querySelector('#nav-add-select');
    const id = sel && sel.value;
    if (!id) return toast('No built-in items left to add', 'warn');
    let last = cfg.sections[cfg.sections.length - 1];
    if (!last) { last = { label: 'New Section', items: [] }; cfg.sections.push(last); }
    last.items.push(id);
    commit();
  });
  box.querySelector('#nav-add-section').addEventListener('click', () => {
    cfg.sections.push({ label: 'New Section', items: [] });
    commit();
  });
  box.querySelector('#nav-add-custom').addEventListener('click', () => {
    const label = box.querySelector('#nav-cust-label').value.trim();
    const url = box.querySelector('#nav-cust-url').value.trim();
    if (!label || !url) return toast('Enter a label and URL', 'warn');
    const id = 'custom_' + Date.now().toString(36);
    cfg.custom = cfg.custom || {};
    cfg.custom[id] = { label, icon: 'codicon-globe', url };
    let last = cfg.sections[cfg.sections.length - 1];
    if (!last) { last = { label: 'Links', items: [] }; cfg.sections.push(last); }
    last.items.push(id);
    commit();
  });
  box.querySelector('#nav-reset').addEventListener('click', () => {
    Sidebar.applySidebarPreset(Sidebar.DEFAULT_PRESET);
    renderNavigationTab();
  });
}

/* ==========================================================================
   FLAT FILE CREATION — Amazon flat-file templates (per product type)
   ========================================================================== */
async function renderFlatFile() {
  const root = $('#view-root');
  root.innerHTML = `
    <div class="view">
      <div class="view-header">
        <div>
          <div class="view-title">Flat File Creation</div>
          <div class="view-sub">Amazon flat-file templates per product type — store templates, edit columns, generate CSVs.</div>
        </div>
        <div class="view-actions"><button class="btn-secondary" id="ff-upload"><span class="codicon codicon-cloud-upload"></span> Upload template</button><button class="btn-primary" id="ff-new"><span class="codicon codicon-add"></span> New template</button></div>
      </div>
      <div id="ff-list" class="empty-state">Loading…</div>
    </div>`;
  $('#ff-upload').addEventListener('click', () => openFlatFileUpload());
  $('#ff-new').addEventListener('click', () => openFlatFileEditor(null));
  await refreshFlatFileList();
}

async function openFlatFileUpload() {
  let presets = { product_types: [] };
  try { presets = await api('/api/flatfiles/presets'); } catch { /* presets optional */ }
  const ptOptions = ['Uploaded', ...(presets.product_types || [])]
    .map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join('');
  openModal('Upload Flat-File Template', `
    <label class="field"><span>Template file</span><input id="ff-file" type="file" accept=".csv,.txt,.tsv" /></label>
    <label class="field"><span>Product type</span><select id="ff-pt-upload">${ptOptions}</select></label>
    <div class="view-sub" style="margin-top:0.5rem">Row 1 = column labels, row 2 (if machine keys) = field keys, row 3 = example values.</div>`,
    `<button class="btn-secondary" id="ff-up-cancel">Cancel</button>
     <button class="btn-primary" id="ff-up-go">Upload template</button>`);
  $('#ff-up-cancel').addEventListener('click', closeModal);
  $('#ff-up-go').addEventListener('click', async () => {
    const file = $('#ff-file').files[0];
    if (!file) return toast('Choose a file first', 'warn');
    const fd = new FormData();
    fd.append('file', file);
    fd.append('product_type', $('#ff-pt-upload').value);
    try {
      const tpl = await api('/api/flatfiles/upload', { method: 'POST', body: fd });
      closeModal();
      toast(`Template "${tpl.name}" imported (${tpl.columns.length} columns)`, 'ok');
      refreshFlatFileList();
    } catch (e) { toast(`Upload failed: ${e.message}`, 'err'); }
  });
}

async function refreshFlatFileList() {
  const list = $('#ff-list');
  if (!list) return;
  try {
    const tmpls = await api('/api/flatfiles');
    if (!tmpls.length) {
      list.innerHTML = `<div class="empty-state"><div class="big"><span class="codicon codicon-table"></span></div><div>No flat-file templates yet.</div><button class="btn-primary" id="ff-new2" style="margin-top:0.75rem">Create one</button></div>`;
      const b = $('#ff-new2'); if (b) b.addEventListener('click', () => openFlatFileEditor(null));
      return;
    }
    list.innerHTML = `<table class="data-table"><thead><tr><th>Template</th><th>Product type</th><th>Columns</th><th>Updated</th><th></th></tr></thead><tbody>${tmpls.map((t) => `
      <tr>
        <td>${esc(t.name)}</td>
        <td>${esc(t.product_type)}</td>
        <td>${t.column_count}</td>
        <td class="mono">${fmtAgo(t.updated_at) || '—'}</td>
        <td style="text-align:right;white-space:nowrap">
          <button class="btn-mini" data-ff-edit="${t.id}">Edit</button>
          <button class="btn-mini" data-ff-gen="${t.id}">Generate</button>
          <button class="btn-mini btn-mini-danger" data-ff-del="${t.id}">Delete</button>
        </td>
      </tr>`).join('')}</tbody></table>`;
    list.querySelectorAll('[data-ff-edit]').forEach((b) => b.addEventListener('click', () => openFlatFileEditor(Number(b.dataset.ffEdit))));
    list.querySelectorAll('[data-ff-gen]').forEach((b) => b.addEventListener('click', () => openFlatFileGenerate(Number(b.dataset.ffGen))));
    list.querySelectorAll('[data-ff-del]').forEach((b) => b.addEventListener('click', async () => {
      if (!confirm('Delete this template?')) return;
      await api(`/api/flatfiles/${b.dataset.ffDel}`, { method: 'DELETE' });
      toast('Template deleted', 'ok'); refreshFlatFileList();
    }));
  } catch (e) { list.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`; }
}

async function openFlatFileEditor(id) {
  let tpl = { name: '', product_type: 'General', columns: [], header_note: '' };
  let presets = { product_types: [], templates: {} };
  if (id) tpl = await api(`/api/flatfiles/${id}`);
  try { presets = await api('/api/flatfiles/presets'); } catch { /* */ }
  const ptOptions = (presets.product_types.length ? presets.product_types : [tpl.product_type])
    .map((p) => `<option value="${esc(p)}" ${tpl.product_type === p ? 'selected' : ''}>${esc(p)}</option>`).join('');

  const renderCols = () => {
    const rows = (tpl.columns || []).map((c, i) => `
      <div class="ff-col-row" data-i="${i}">
        <input class="ff-key" value="${esc(c.key)}" placeholder="key" title="Field key" />
        <input class="ff-label" value="${esc(c.label)}" placeholder="label" title="Human label" />
        <label class="ff-req" title="Required column"><input type="checkbox" class="ff-required" ${c.required ? 'checked' : ''} /> req</label>
        <button class="nav-mini nav-mini-danger" data-ff-col-del="${i}" title="Remove column">×</button>
      </div>`).join('');
    $('#ff-cols').innerHTML = rows || '<div class="nav-empty">No columns — add below.</div>';
    $('#ff-cols').querySelectorAll('[data-ff-col-del]').forEach((b) => b.addEventListener('click', () => {
      tpl.columns.splice(Number(b.dataset.ffColDel), 1); renderCols();
    }));
  };

  openModal(id ? 'Edit Flat-File Template' : 'New Flat-File Template', `
    <label class="field"><span>Template name</span><input id="ff-name" value="${esc(tpl.name)}" placeholder="e.g. Beauty — US Flat File" /></label>
    <div class="field-row">
      <label class="field"><span>Product type</span><select id="ff-pt">${ptOptions}</select></label>
      <label class="field"><span>&nbsp;</span><button class="btn-secondary" id="ff-load-preset" style="min-height:var(--control-h)">Load preset columns</button></label>
    </div>
    <label class="field"><span>Header note (optional)</span><input id="ff-note" value="${esc(tpl.header_note)}" /></label>
    <div class="field"><span>Columns</span>
      <div id="ff-cols" class="ff-cols"></div>
      <button class="btn-secondary" id="ff-add-col" style="margin-top:0.375rem">＋ Add column</button>
    </div>`,
    `<button class="btn-secondary" id="ff-cancel">Cancel</button>
     <button class="btn-primary" id="ff-save">Save template</button>`);

  renderCols();
  $('#ff-load-preset').addEventListener('click', () => {
    const pt = $('#ff-pt').value;
    const cols = (presets.templates || {})[pt];
    if (cols) { tpl.columns = JSON.parse(JSON.stringify(cols)); renderCols(); toast(`Loaded ${cols.length} columns for ${pt}`, 'ok'); }
    else toast('No preset columns for that type', 'warn');
  });
  $('#ff-add-col').addEventListener('click', () => {
    tpl.columns.push({ key: '', label: '', required: false, values: [], example: '' }); renderCols();
  });
  $('#ff-cancel').addEventListener('click', closeModal);
  $('#ff-save').addEventListener('click', async () => {
    const cols = Array.from(document.querySelectorAll('#ff-cols .ff-col-row')).map((row) => ({
      key: row.querySelector('.ff-key').value.trim(),
      label: row.querySelector('.ff-label').value.trim(),
      required: row.querySelector('.ff-required').checked,
      values: [], example: '',
    })).filter((c) => c.key);
    const body = { name: $('#ff-name').value.trim(), product_type: $('#ff-pt').value, header_note: $('#ff-note').value.trim(), columns: cols };
    if (!body.name) return toast('Name is required', 'err');
    try {
      if (id) await api(`/api/flatfiles/${id}`, { method: 'PUT', body });
      else await api('/api/flatfiles', { method: 'POST', body });
      closeModal(); toast('Template saved', 'ok'); refreshFlatFileList();
    } catch (e) { toast(`Save failed: ${e.message}`, 'err'); }
  });
}

async function openFlatFileGenerate(id) {
  const tpl = await api(`/api/flatfiles/${id}`);
  const cols = tpl.columns || [];
  const rowHTML = () => `<div class="ff-gen-row">${cols.map((c) => `
    <label class="field"><span>${esc(c.label)}${c.required ? ' *' : ''}</span>
      <input class="ff-gen-val" data-key="${esc(c.key)}" placeholder="${esc(c.example || '')}" />
    </label>`).join('')}</div>`;
  openModal(`Generate — ${esc(tpl.name)}`, `
    <div class="settings-note">Fill rows and generate a flat-file CSV (first two lines are the label/field headers).</div>
    <div id="ff-gen-rows">${rowHTML()}</div>
    <button class="btn-secondary" id="ff-gen-addrow" style="margin-top:0.375rem">＋ Add row</button>`,
    `<button class="btn-secondary" id="ff-gen-cancel">Cancel</button>
     <button class="btn-primary" id="ff-gen-do">Generate CSV</button>`);
  $('#ff-gen-addrow').addEventListener('click', () => {
    const wrap = document.createElement('div');
    wrap.innerHTML = rowHTML();
    $('#ff-gen-rows').appendChild(wrap.firstElementChild);
  });
  $('#ff-gen-cancel').addEventListener('click', closeModal);
  $('#ff-gen-do').addEventListener('click', async () => {
    const rows = Array.from(document.querySelectorAll('#ff-gen-rows .ff-gen-row')).map((r) => {
      const row = {};
      r.querySelectorAll('.ff-gen-val').forEach((inp) => { row[inp.dataset.key] = inp.value; });
      return row;
    });
    try {
      const res = await api(`/api/flatfiles/${id}/generate`, { method: 'POST', body: { rows } });
      const blob = new Blob([res.csv], { type: 'text/csv' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = res.filename; a.click();
      URL.revokeObjectURL(a.href);
      closeModal(); toast(`Generated ${res.filename}`, 'ok');
    } catch (e) { toast(`Generate failed: ${e.message}`, 'err'); }
  });
}

/* ==========================================================================
   SvL COMPARISON — Levenshtein fuzzy match vs live catalog
   ========================================================================== */
async function renderSvl() {
  const root = $('#view-root');
  root.innerHTML = `
    <div class="view">
      <div class="view-header"><div>
        <div class="view-title">SvL Comparison</div>
        <div class="view-sub">Suggested vs Live — fuzzy-match proposed content against your live catalog using Levenshtein distance.</div>
      </div></div>
      <div class="svl-form">
        <label class="field"><span>Suggested content</span>
          <textarea id="svl-text" rows="2" placeholder="e.g. a proposed title, brand, or description…"></textarea></label>
        <div class="field-row">
          <label class="field"><span>Compare against</span><select id="svl-field">
            <option value="name">Product name / title</option>
            <option value="brand">Brand</option>
            <option value="category">Category</option>
            <option value="sku">SKU</option>
            <option value="market">Market</option>
          </select></label>
          <label class="field"><span>Min similarity</span><input id="svl-threshold" type="number" min="0" max="1" step="0.05" value="0" /></label>
        </div>
        <div class="settings-actions"><button class="btn-primary" id="svl-run"><span class="codicon codicon-arrow-swap"></span> Compare</button></div>
      </div>
      <div id="svl-results"></div>
    </div>`;
  $('#svl-run').addEventListener('click', runSvl);
  $('#svl-text').addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') runSvl(); });
}

async function runSvl() {
  const suggested = $('#svl-text').value.trim();
  const field = $('#svl-field').value;
  const threshold = Number($('#svl-threshold').value || 0);
  if (!suggested) return toast('Enter suggested content first', 'warn');
  const res = $('#svl-results');
  res.innerHTML = '<div class="empty-state">Comparing…</div>';
  try {
    const data = await api('/api/svl/compare', { method: 'POST', body: { suggested, field, threshold } });
    const best = data.best;
    const badge = (sim) => sim >= 0.9 ? 'pill-int pill-int-configured' : sim >= 0.6 ? 'pill-int' : 'pill-int pill-int-missing';
    res.innerHTML = `
      ${best ? `<div class="settings-note" style="margin-bottom:0.5rem">Best match: <b>${esc(best.field_value)}</b> — ${(best.similarity * 100).toFixed(1)}% similar (distance ${best.distance})</div>` : ''}
      <table class="data-table"><thead><tr><th>Match</th><th>SKU</th><th>Value</th><th>Category</th><th>Distance</th><th>Similarity</th></tr></thead>
      <tbody>${data.matches.map((m) => `
        <tr>
          <td>${esc(m.name)}</td>
          <td class="mono">${esc(m.sku)}</td>
          <td>${esc(m.field_value)}</td>
          <td>${esc(m.category)}</td>
          <td class="mono">${m.distance}</td>
          <td><span class="${badge(m.similarity)}">${(m.similarity * 100).toFixed(1)}%</span></td>
        </tr>`).join('') || '<tr><td colspan="6" class="empty-state">No matches above threshold.</td></tr>'}</tbody></table>`;
  } catch (e) { res.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`; }
}

/* ==========================================================================
   LISTINGS WORKSPACE — live index, Suggested vs Live, glossary
   ========================================================================== */
const listingsState = { tab: 'live', sourceId: '', report: null };

async function renderListings(tab = listingsState.tab) {
  listingsState.tab = tab;
  const root = $('#view-root');
  root.innerHTML = `<div class="view"><div class="view-header"><div>
    <div class="view-title">Listings</div><div class="view-sub">Live listing content, suggested-content review, and shared catalog definitions.</div>
  </div></div>
  <div class="dm-tabs" role="tablist">
    <button class="dm-tab ${tab === 'live' ? 'active' : ''}" data-listing-tab="live" role="tab" aria-selected="${tab === 'live'}">Live Listings</button>
    <button class="dm-tab ${tab === 'suggested' ? 'active' : ''}" data-listing-tab="suggested" role="tab" aria-selected="${tab === 'suggested'}">Suggested vs Live</button>
    <button class="dm-tab ${tab === 'glossary' ? 'active' : ''}" data-listing-tab="glossary" role="tab" aria-selected="${tab === 'glossary'}">Glossary &amp; Registry</button>
  </div><div id="listings-workspace" style="margin-top:0.8rem"></div></div>`;
  root.querySelectorAll('[data-listing-tab]').forEach((button) => button.addEventListener('click', () => renderListings(button.dataset.listingTab)));
  if (tab === 'live') return renderLiveListings();
  if (tab === 'glossary') return renderListingGlossary();
  return renderSuggestedVsLive();
}

async function renderLiveListings() {
  const box = $('#listings-workspace'); box.innerHTML = '<div class="folder-loading">Loading local listing index…</div>';
  try {
    const products = await window.ConductorData.get('products');
    if (!products.length) { box.innerHTML = '<div class="empty-state">No listings are in the local catalog yet. Import a catalog source first.</div>'; return; }
    box.innerHTML = `<div class="data-table-wrap"><table class="data-table"><thead><tr><th>SKU</th><th>Listing title</th><th>Category</th><th>Market</th><th>Source</th><th>Added</th></tr></thead><tbody>${products.map((p) => `<tr class="row-click" data-product-id="${p.id}"><td class="mono">${esc(p.sku)}</td><td><b>${esc(p.name)}</b></td><td>${esc(p.category || '—')}</td><td>${esc(p.market || '—')}</td><td>${esc(p.source || '—')}</td><td>${esc(timeAgo(p.created_at))}</td></tr>`).join('')}</tbody></table></div>`;
    box.querySelectorAll('[data-product-id]').forEach((row) => row.addEventListener('click', () => renderProductDetail(Number(row.dataset.productId))));
  } catch (e) { box.innerHTML = `<div class="empty-state">Could not load listings: ${esc(e.message)}</div>`; }
}

async function renderSuggestedVsLive() {
  const box = $('#listings-workspace');
  box.innerHTML = `<div class="svl-form"><div class="settings-note">Diagnostic only — this comparison never publishes or modifies a live listing. Sources must be fresh within 48 hours for strict results.</div>
    <label class="field"><span>Suggested content file</span><input id="listing-suggested-file" type="file" accept=".xlsx,.xlsm,.csv,.tsv,.tab,.json,.ndjson,.jsonl" /></label>
    <div class="settings-actions"><button class="btn-primary" id="listing-upload"><span class="codicon codicon-cloud-upload"></span> Upload suggested content</button><button class="btn-secondary" id="listing-refresh"><span class="codicon codicon-refresh"></span> Refresh stale live data</button><button class="btn-primary" id="listing-compare"><span class="codicon codicon-arrow-swap"></span> Compare fresh records</button></div>
  </div><div id="listing-compare-results"></div>`;
  const results = $('#listing-compare-results');
  $('#listing-upload').addEventListener('click', async () => {
    const file = $('#listing-suggested-file').files[0]; if (!file) return toast('Choose a suggested content file first', 'warn');
    const data = new FormData(); data.append('file', file); results.innerHTML = '<div class="empty-state">Importing suggested content…</div>';
    try { const r = await fetch('/api/listings/suggested/upload', { method: 'POST', body: data }); if (!r.ok) throw new Error(await r.text()); const out = await r.json(); listingsState.sourceId = out.source_id; results.innerHTML = `<div class="settings-note">Imported <b>${fmtNum(out.records_accepted)}</b> suggested listing records from ${esc(file.name)}. Refresh live data before comparison.</div>`; } catch (e) { results.innerHTML = `<div class="empty-state">Upload failed: ${esc(e.message)}</div>`; }
  });
  $('#listing-refresh').addEventListener('click', async () => {
    if (!listingsState.sourceId) return toast('Upload suggested content first', 'warn'); results.innerHTML = '<div class="empty-state">Refreshing stale listing snapshots…</div>';
    try { const out = await api('/api/listings/refresh', { method: 'POST', body: { source_id: listingsState.sourceId } }); results.innerHTML = `<div class="settings-note">${esc(out.status)} — ${fmtNum(out.refreshed || 0)} refreshed / ${fmtNum(out.stale || 0)} stale targets. ${out.status !== 'success' ? 'Configure Keepa or another live adapter to refresh stale records.' : ''}</div>`; } catch (e) { results.innerHTML = `<div class="empty-state">Refresh blocked: ${esc(e.message)}</div>`; }
  });
  $('#listing-compare').addEventListener('click', async () => {
    if (!listingsState.sourceId) return toast('Upload suggested content first', 'warn'); results.innerHTML = '<div class="empty-state">Comparing suggested and fresh live content…</div>';
    try { const out = await api('/api/listings/compare', { method: 'POST', body: { source_id: listingsState.sourceId, strict_fresh: true } }); listingsState.report = out;
      results.innerHTML = `${out.stale_records ? `<div class="settings-note">${fmtNum(out.stale_records)} record(s) were excluded because live data is stale.</div>` : ''}<div class="data-table-wrap"><table class="data-table"><thead><tr><th>ASIN / SKU</th><th>Field</th><th>Suggested</th><th>Live</th><th>Similarity</th><th>Status</th><th>Recommendation</th></tr></thead><tbody>${out.rows.map((r) => `<tr><td class="mono">${esc(r.asin || r.sku)}</td><td class="mono">${esc(r.field)}</td><td>${esc(String(r.suggested).slice(0, 160))}</td><td>${esc(String(r.live).slice(0, 160))}</td><td>${(Math.max(r.levenshtein_similarity || 0, r.fuzzy_similarity || 0) * 100).toFixed(1)}%</td><td><span class="${r.match_status === 'match' ? 'pill-int pill-int-configured' : r.match_status === 'near_match' ? 'pill-int' : 'pill-int pill-int-missing'}">${esc(r.match_status)}</span></td><td>${esc(r.recommendation || '—')}</td></tr>`).join('') || '<tr><td colspan="7" class="empty-state">No fresh comparison rows. Refresh live data or use a configured adapter.</td></tr>'}</tbody></table></div>`;
    } catch (e) { results.innerHTML = `<div class="empty-state">Compare failed: ${esc(e.message)}</div>`; }
  });
}

async function renderListingGlossary() {
  const box = $('#listings-workspace'); box.innerHTML = '<div class="folder-loading">Loading the local registry…</div>';
  try {
    const [glossary, spine] = await Promise.all([api('/api/spine/glossary'), api('/api/spine/snapshot')]);
    const items = glossary.items || [];
    box.innerHTML = `<div class="settings-note">Canonical local-first registry: features, file types, statuses, lifecycle states, models, workflow nodes, datasets, and shared filters.</div><div class="data-table-wrap" style="margin-top:0.65rem"><table class="data-table"><thead><tr><th>Term</th><th>Type</th><th>Definition</th><th>Route</th><th>Status</th></tr></thead><tbody>${items.map((i) => `<tr><td class="mono">${esc(i.label)}</td><td>${esc(i.kind)}</td><td>${esc(i.description)}</td><td class="mono">${esc(i.route || '—')}</td><td><span class="pill-int pill-int-configured">${esc(i.status_key)}</span></td></tr>`).join('')}</tbody></table></div>`;
  } catch (e) { box.innerHTML = `<div class="empty-state">Registry unavailable: ${esc(e.message)}</div>`; }
}

async function renderSvl() { return renderListings('suggested'); }

/* ==========================================================================
   BRAND & CATEGORY COMPARISON — "brand X vs top competitors" across the
   T3 value attributes (Included Components, Target Audience, Recommended
   Uses, Specific Uses, Product Benefit, Active Ingredients, Special Ingredients)
   ========================================================================== */
const brandCompareState = { brand: '', category: '', market: '', limit: 6, meta: null, result: null };

async function renderBrandCompare() {
  const root = $('#view-root');
  root.innerHTML = `
    <div class="view">
      <div class="view-header"><div>
        <div class="view-title">Brand Compare</div>
        <div class="view-sub">I have brand X — see what the top competitors are doing. Compares the T3 value attributes across brands in a category.</div>
      </div></div>
      <div class="svl-form">
        <div class="field-row">
          <label class="field"><span>Your brand</span>
            <input id="bc-brand" list="bc-brands" placeholder="e.g. Acme…" value="${esc(brandCompareState.brand)}" />
            <datalist id="bc-brands"></datalist></label>
          <label class="field"><span>Category</span><select id="bc-category"></select></label>
          <label class="field"><span>Market</span><select id="bc-market"></select></label>
          <label class="field"><span>Top competitors</span><input id="bc-limit" type="number" min="1" max="12" value="${brandCompareState.limit}" /></label>
        </div>
        <div class="settings-actions">
          <button class="btn-primary" id="bc-run"><span class="codicon codicon-telescope"></span> Compare</button>
          <button class="btn-secondary" id="bc-brief"><span class="codicon codicon-sparkle"></span> AI competitive brief</button>
        </div>
      </div>
      <div id="bc-results"></div>
    </div>`;
  $('#bc-run').addEventListener('click', runBrandCompare);
  $('#bc-brand').addEventListener('keydown', (e) => { if (e.key === 'Enter') runBrandCompare(); });
  $('#bc-brief').addEventListener('click', runBrandBrief);

  try {
    const meta = await api('/api/brandcompare/meta');
    brandCompareState.meta = meta;
    $('#bc-brands').innerHTML = (meta.brands || []).map((b) => `<option value="${esc(b)}">`).join('');
    $('#bc-category').innerHTML = '<option value="">All categories</option>' +
      (meta.categories || []).map((c) => `<option value="${esc(c)}">`).join('');
    $('#bc-market').innerHTML = '<option value="">All markets</option>' +
      (meta.markets || []).map((m) => `<option value="${esc(m)}">`).join('');
    if ((meta.brands || []).length === 0) {
      $('#bc-results').innerHTML = `<div class="empty-state">No brands found in the catalog yet — import products (Catalog Ingest) to compare, or use the AI brief.</div>`;
    }
  } catch (e) {
    $('#bc-results').innerHTML = `<div class="empty-state">Could not load catalog meta: ${esc(e.message)}</div>`;
  }
}

/* ------------------------------------------------------------- keepa */
const keepaState = { asins: '', domain: 1, meta: null };

function keepaPrice(v) {
  if (v == null) return '—';
  return '$' + Number(v).toFixed(2);
}
function keepaMs(ms) {
  if (!ms) return '—';
  const d = new Date(ms);
  if (!Number.isFinite(d.getTime())) return '—';
  return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function keepaCard(p) {
  const c = p.current || {};
  const img = (p.images && p.images[0])
    ? `<img class="keepa-img" src="${esc(p.images[0])}" loading="lazy" referrerpolicy="no-referrer" alt="">`
    : `<div class="keepa-img keepa-img-empty"><span class="codicon codicon-package"></span></div>`;
  const brandLine = [p.brand, p.manufacturer !== p.brand ? p.manufacturer : ''].filter(Boolean).join(' · ');
  const features = (p.features || []).slice(0, 3).map((f) => `<li>${esc(f)}</li>`).join('');
  return `<div class="keepa-card">
    ${img}
    <div class="keepa-body">
      <div class="keepa-title" title="${esc(p.title || '')}">${esc(p.title || p.asin)}</div>
      <div class="keepa-meta">${esc(brandLine)}</div>
      <div class="keepa-asin">${esc(p.asin)}${p.domain ? ' · ' + esc(p.domain) : ''}${p.productGroup ? ' · ' + esc(p.productGroup) : ''}</div>
      <div class="keepa-stats">
        <div class="keepa-stat"><span>Price</span><b>${keepaPrice(c.price)}</b></div>
        <div class="keepa-stat"><span>Rank</span><b>${c.salesRank ? '#' + fmtNum(c.salesRank) : '—'}</b></div>
        <div class="keepa-stat"><span>Rating</span><b>${c.rating != null ? `★ ${c.rating} (${fmtNum(c.reviewsCount || 0)})` : '—'}</b></div>
        <div class="keepa-stat"><span>Updated</span><b>${keepaMs(p.lastUpdate)}</b></div>
      </div>
      ${features ? `<ul class="keepa-features">${features}</ul>` : ''}
    </div>
    <div class="keepa-foot">
      <span class="muted">${fmtNum(p.csvPoints || 0)} data points${c.isPrime ? ' · Prime' : ''}${c.isAdultProduct ? ' · Adult' : ''}</span>
      <button class="btn-primary btn-sm keepa-import" data-asin="${esc(p.asin)}"><span class="codicon codicon-cloud-upload"></span> Import to catalog</button>
    </div>
  </div>`;
}

async function renderKeepa() {
  const root = $('#view-root');
  root.innerHTML = `<div class="view">
    <div class="view-header"><div>
      <div class="view-title">Keepa</div>
      <div class="view-sub">Live Amazon product data by ASIN — price, sales rank, rating, images, brand. Pulled from the Keepa product API and cached locally so repeat lookups don't burn tokens.</div>
    </div></div>

    <div class="keepa-panel">
      <div class="keepa-config">
        <div class="keepa-config-head"><span class="codicon codicon-key"></span> API key <span class="pill-int pill-int-missing" id="keepa-key-state" style="margin-left:0.4rem">…</span></div>
        <div class="field-row">
          <label class="field"><span>Keepa API key</span><input id="keepa-key" type="password" placeholder="Paste your Keepa API key" autocomplete="off" /></label>
          <label class="field"><span>Domain</span><select id="keepa-domain"></select></label>
        </div>
        <div class="settings-actions">
          <button class="btn-secondary" id="keepa-save-key"><span class="codicon codicon-save"></span> Save key</button>
        </div>
      </div>

      <div class="keepa-lookup">
        <div class="keepa-config-head"><span class="codicon codicon-search"></span> Look up live product data</div>
        <div class="field-row">
          <label class="field" style="flex:1"><span>ASINs — comma- or space-separated, up to 100</span>
            <input id="keepa-asins" placeholder="B08N5WRWNW, B09G9FPHY6" value="${esc(keepaState.asins)}" /></label>
        </div>
        <div class="settings-actions">
          <button class="btn-primary" id="keepa-lookup"><span class="codicon codicon-search"></span> Look up</button>
          <button class="btn-secondary" id="keepa-lookup-fresh" title="Ignore cache and refetch live from Keepa"><span class="codicon codicon-refresh"></span> Refresh</button>
          <span class="muted" id="keepa-tokens" style="margin-left:0.25rem"></span>
        </div>
      </div>

      <!-- Brand Search & Seller Search Panel -->
      <div class="keepa-lookup" style="margin-top:16px;">
        <div class="keepa-config-head"><span class="codicon codicon-tag"></span> Brand & Seller Search</div>
        <div class="field-row">
          <label class="field" style="flex:2"><span>Search Term (Brand Name or Seller ID)</span>
            <input id="keepa-search-term" placeholder="e.g. Luminize or A1234SELLER" /></label>
          <label class="field" style="flex:1"><span>Search Type</span>
            <select id="keepa-search-type" class="input-select">
              <option value="brand">Brand Search</option>
              <option value="seller">Seller ID Search</option>
            </select>
          </label>
        </div>
        <div class="settings-actions">
          <button class="btn-primary" id="keepa-search-run"><span class="codicon codicon-search"></span> Search Brand / Seller</button>
        </div>
      </div>

      <!-- AI Assisted Query Writer Panel -->
      <div class="card" style="margin-top:16px; padding:14px; background:var(--t-surface-raised, #1e1e2e);">
        <div style="font-weight:600; margin-bottom:8px;">⚡ AI-Assisted Keepa Query Writer:</div>
        <div style="display:flex; gap:8px;">
          <input type="text" id="keepa-ai-query-input" class="input-text" style="flex:1;"
                 placeholder="Describe Keepa search criteria (e.g. 'Find top rank electronics for seller A1234 under $50')">
          <button class="btn-primary" id="btn-keepa-ai-query-run">Write Keepa Query</button>
        </div>
        <div id="keepa-ai-query-out" style="margin-top:10px; display:none; background:var(--t-surface-base, #111); padding:10px; border-radius:6px; border:1px solid var(--t-edges-borderColor, #333);"></div>
      </div>
    </div>

    <div id="keepa-results"></div>
    <div class="view-title" style="margin-top:1.5rem">Cached</div>
    <div class="view-sub" style="margin-bottom:0.5rem">Products already pulled and stored locally — import them any time without spending a token.</div>
    <div id="keepa-cached" class="keepa-grid"></div>
  </div>`;

  try {
    const st = await api('/api/keepa/status');
    keepaState.domain = st.domain || 1;
    $('#keepa-domain').innerHTML = (st.domains || []).map((d) => `<option value="${d.id}" ${d.id === st.domain ? 'selected' : ''}>${esc(d.code)} (${d.id})</option>`).join('');
    const keyState = $('#keepa-key-state');
    keyState.textContent = st.has_key ? `configured ${st.key_masked}` : 'not configured';
    keyState.className = 'pill-int ' + (st.has_key ? 'pill-int-configured' : 'pill-int-missing');
    if (!st.has_key) $('#keepa-key').placeholder = 'No key yet — paste your Keepa API key';
  } catch (e) { toast(e.message, 'err'); }

  $('#keepa-save-key').addEventListener('click', async () => {
    const key = $('#keepa-key').value.trim();
    const domain = Number($('#keepa-domain').value);
    if (!key) return toast('Enter a Keepa API key', 'warn');
    try {
      await api('/api/keepa/config', { method: 'POST', body: { api_key: key, domain } });
      toast('Keepa key saved', 'ok');
      await renderKeepa();
    } catch (e) { toast(e.message, 'err'); }
  });

  $('#keepa-search-run').addEventListener('click', async () => {
    const query = $('#keepa-search-term').value.trim();
    const type = $('#keepa-search-type').value;
    const domain = Number($('#keepa-domain').value || 1);
    if (!query) return toast('Enter a brand name or seller ID', 'warn');
    const resEl = $('#keepa-results');
    resEl.innerHTML = '<div class="empty-state">Searching Keepa products...</div>';
    try {
      const data = await api('/api/keepa/search', { method: 'POST', body: { query, type, domain } });
      toast(`Found ${data.count || 0} products matching ${query}`, 'info');
      resEl.innerHTML = `<div class="card" style="padding:12px;">
        <div style="font-weight:700;">Matched ${data.count} Products for ${esc(type.upper())} Search: "${esc(query)}"</div>
        <div style="margin-top:8px; display:flex; flex-direction:column; gap:6px;">
          ${(data.products || []).slice(0, 10).map((p) => `<div style="display:flex; justify-content:space-between; border-bottom:1px solid #333; padding-bottom:4px;">
            <span><b>${esc(p.title || 'Product')}</b> (<span class="mono">${esc(p.asin || '')}</span>)</span>
            <span>Brand: <b>${esc(p.brand || 'N/A')}</b></span>
          </div>`).join('')}
        </div>
      </div>`;
    } catch (e) { toast(e.message, 'err'); }
  });

  $('#btn-keepa-ai-query-run').addEventListener('click', async () => {
    const prompt = $('#keepa-ai-query-input').value.trim();
    if (!prompt) return toast('Enter search criteria prompt', 'warn');
    const outBox = $('#keepa-ai-query-out');
    outBox.style.display = 'block';
    outBox.innerHTML = '<i>Generating Keepa API query…</i>';
    try {
      const data = await api('/api/keepa/ai-query', { method: 'POST', body: { prompt } });
      outBox.innerHTML = `<div>${data.summary ? data.summary.replace(/\n/g, '<br>') : 'Query written'}</div>`;
    } catch (e) { outBox.innerHTML = `<span style="color:red;">Error: ${esc(e.message)}</span>`; }
  });

  const doLookup = async (refresh) => {
    keepaState.asins = $('#keepa-asins').value.trim();
    const domain = Number($('#keepa-domain').value);
    if (!keepaState.asins) return toast('Enter at least one ASIN', 'warn');
    const res = $('#keepa-results');
    res.innerHTML = '<div class="empty-state">Looking up live data on Keepa…</div>';
    try {
      const data = await api('/api/keepa/lookup', { method: 'POST', body: { asins: keepaState.asins, domain, refresh } });
      keepaState.meta = data.meta || null;
      const mt = data.meta || {};
      $('#keepa-tokens').textContent = mt.tokensLeft != null
        ? `tokens left: ${fmtNum(mt.tokensLeft)}${mt.refillRate ? ` · refill ${mt.refillRate}/min` : ''}${data.fromCache ? ` · ${data.fromCache} from cache` : ''}`
        : (data.fromCache ? `${data.fromCache} from cache` : '');
      if (!data.products.length) {
        res.innerHTML = `<div class="empty-state">No results${data.notFound && data.notFound.length ? ' — not found: ' + esc(data.notFound.join(', ')) : ''}. Check the ASIN, domain and key.</div>`;
        return;
      }
      res.innerHTML = `<div class="keepa-grid">${data.products.map((p) => keepaCard(p)).join('')}</div>`;
      wireKeepaImport(res);
      if (data.notFound && data.notFound.length) {
        res.insertAdjacentHTML('beforeend', `<div class="settings-note" style="margin-top:0.5rem">Not found on Keepa: ${esc(data.notFound.join(', '))}</div>`);
      }
    } catch (e) {
      res.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`;
    }
  };
  $('#keepa-lookup').addEventListener('click', () => doLookup(false));
  $('#keepa-lookup-fresh').addEventListener('click', () => doLookup(true));
  $('#keepa-asins').addEventListener('keydown', (e) => { if (e.key === 'Enter') doLookup(false); });

  try {
    const cached = await api('/api/keepa/products?limit=60');
    const grid = $('#keepa-cached');
    grid.innerHTML = cached.products.length
      ? cached.products.map((p) => keepaCard(p)).join('')
      : '<div class="empty-state">Nothing cached yet — run a lookup above.</div>';
    wireKeepaImport(grid);
  } catch (e) {
    $('#keepa-cached').innerHTML = `<div class="empty-state">Could not load cached products: ${esc(e.message)}</div>`;
  }
}

function wireKeepaImport(container) {
  container.querySelectorAll('.keepa-import').forEach((b) => b.addEventListener('click', async () => {
    const asin = b.dataset.asin;
    const domain = Number(($('#keepa-domain') && $('#keepa-domain').value) || keepaState.domain);
    b.disabled = true;
    b.innerHTML = 'Importing…';
    try {
      const r = await api('/api/keepa/import', { method: 'POST', body: { asins: asin, domain } });
      if (r.imported.includes(asin)) toast(`${asin} imported to catalog`, 'ok');
      else if (r.updated.includes(asin)) toast(`${asin} already in catalog — attributes updated`, 'ok');
      else toast(`${asin} not cached — look it up first`, 'warn');
      invalidateWarm();
      refreshCounts();
    } catch (e) { toast(e.message, 'err'); }
    b.disabled = false;
    b.innerHTML = '<span class="codicon codicon-cloud-upload"></span> Import to catalog';
  }));
}

function brandCompareCell(summary, total) {
  if (!summary || !summary.distinct) return '<span class="bc-empty">—</span>';
  return esc(summary.text);
}

function coverageBar(pct) {
  return `<div class="bc-cov"><div class="bc-cov-fill" style="width:${pct}%"></div></div><span class="bc-cov-num">${pct}%</span>`;
}

async function runBrandCompare() {
  brandCompareState.brand = $('#bc-brand').value.trim();
  brandCompareState.category = $('#bc-category').value;
  brandCompareState.market = $('#bc-market').value;
  brandCompareState.limit = Number($('#bc-limit').value || 6);
  if (!brandCompareState.brand) return toast('Enter your brand first', 'warn');
  const res = $('#bc-results');
  res.innerHTML = '<div class="empty-state">Comparing…</div>';
  try {
    const data = await api('/api/brandcompare/compare', { method: 'POST', body: {
      brand: brandCompareState.brand, category: brandCompareState.category,
      market: brandCompareState.market, limit: brandCompareState.limit,
    }});
    brandCompareState.result = data;
    renderBrandCompareResult(data);
  } catch (e) {
    res.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`;
  }
}

function renderBrandCompareResult(d) {
  const attrs = d.attributes || [];
  const you = d.your_brand || {};
  const comps = d.competitors || [];
  const columns = [{ key: '__you__', label: `Your brand${you.brand ? ` — ${you.brand}` : ''}`, summary: you }]
    .concat(comps.map((c) => ({ key: c.brand, label: c.brand, summary: c })));

  const scopeNote = `<div class="settings-note">${esc(d.note)} ${d.catalog_sourced ? '· catalog-sourced' : ''}</div>`;

  // competitor ranking strip
  let ranking = '';
  if (comps.length) {
    ranking = `<div class="bc-rank">
      <div class="bc-rank-title">Top competitors in this scope</div>
      ${comps.map((c) => `
        <div class="bc-rank-card">
          <div class="bc-rank-head"><b>${esc(c.brand)}</b><span class="mono">${c.product_count} product${c.product_count === 1 ? '' : 's'}</span></div>
          ${coverageBar(c.coverage_pct)}
          <div class="bc-rank-skus">${(c.sample_skus || []).map((s) => `<code>${esc(s)}</code>`).join(' ')}</div>
        </div>`).join('')}
    </div>`;
  } else {
    ranking = `<div class="empty-state">No competitor brands found in the catalog for this scope. Import competitor data (Catalog Ingest) — or run the AI brief below.</div>`;
  }

  if (!you.product_count && comps.length === 0 && !ranking) {
    // fully empty
  }

  const youNote = you.product_count === 0
    ? `<div class="settings-note">“${esc(d.brand)}” has no products in this scope — competitors below are other brands present in the catalog.</div>` : '';

  const head = `<tr><th class="bc-attr-head">Value attribute</th>${columns.map((c) =>
    `<th>${esc(c.label)}<div class="bc-th-sub">${c.summary.product_count} products · ${c.summary.coverage}/${attrs.length} attrs</div></th>`).join('')}</tr>`;

  const body = attrs.map((a) => `<tr>
    <td class="bc-attr">${esc(a.label)}</td>
    ${columns.map((c) => `<td>${brandCompareCell(c.summary.attributes[a.id])}</td>`).join('')}
  </tr>`).join('');

  $('#bc-results').innerHTML = `
    ${scopeNote}${youNote}${ranking}
    <table class="data-table bc-matrix"><thead>${head}</thead><tbody>${body}</tbody></table>`;
}

async function runBrandBrief() {
  const brand = $('#bc-brand').value.trim();
  const category = $('#bc-category').value;
  if (!brand) return toast('Enter your brand first', 'warn');
  if (!category) return toast('Pick a category for the AI brief', 'warn');
  const res = $('#bc-results');
  res.innerHTML = '<div class="empty-state">Generating competitive brief…</div>';
  try {
    const data = await api('/api/brandcompare/brief', { method: 'POST', body: { brand, category } });
    if (!data.ai) {
      res.innerHTML = `<div class="empty-state">${esc(data.error || 'No brief generated.')}</div>`;
      return;
    }
    const b = data.brief || {};
    const rows = (b.attributes || []).map((a) => `<tr>
      <td class="bc-attr">${esc(a.label || '')}</td>
      <td>${esc(a.summary || '')}</td>
    </tr>`).join('');
    res.innerHTML = `
      <div class="settings-note">AI-generated competitive brief · ${esc(brand)} · ${esc(category)} — synthesised, not sourced from your catalog.</div>
      ${b.overview ? `<div class="bc-brief-overview">${esc(b.overview)}</div>` : ''}
      <table class="data-table"><thead><tr><th>Value attribute</th><th>What top competitors typically do</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="2" class="empty-state">No attribute summaries returned.</td></tr>'}</tbody></table>`;
  } catch (e) {
    res.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`;
  }
}

/* ==========================================================================
   DATA MANAGEMENT — tables, pivot, charts, wrangler, saved views, Asana push
   ========================================================================== */
const dataState = { source: 'products', q: '', tag: '', mode: 'table', group_by: 'category', agg: 'count', measure: 'score', selected: new Set(), rows: [], columns: [] };

async function renderData() {
  const root = $('#view-root');
  root.innerHTML = `
    <div class="view">
      <div class="view-header">
        <div><div class="view-title">Data Management</div><div class="view-sub">Tables, pivot, charts, column profiling, saved views, Asana push, and ingest.</div></div>
        <div class="view-actions">
          <button class="btn-secondary" id="dm-canvas"><span class="codicon codicon-graph"></span> Flow Canvas</button>
          <button class="btn-secondary" id="dm-export"><span class="codicon codicon-cloud-upload"></span> Export CSV</button>
          <button class="btn-primary" id="dm-asana"><span class="codicon codicon-organization"></span> Push to Asana</button>
        </div>
      </div>
      <div class="dm-toolbar">
        <select id="dm-source"></select>
        <select id="dm-tag" style="display:none" title="Which tagged data set to view — sticky per module"></select>
        <input id="dm-q" type="text" placeholder="Search…" />
        <div class="dm-tabs">${['table', 'pivot', 'wrangler', 'views', 'ingest'].map((m) => `<button class="dm-tab ${dataState.mode === m ? 'active' : ''}" data-dm-mode="${m}">${m[0].toUpperCase() + m.slice(1)}</button>`).join('')}</div>
      </div>
      <div id="dm-body"></div>
    </div>`;
  try {
    const srcs = await api('/api/data/sources');
    $('#dm-source').innerHTML = srcs.map((s) => `<option value="${s.id}" ${s.id === dataState.source ? 'selected' : ''}>${esc(s.label)} (${s.count})</option>`).join('');
    const prod = srcs.find((s) => s.id === 'products');
    if (prod && prod.tags && prod.tags.length) {
      const tagSel = $('#dm-tag');
      tagSel.style.display = '';
      tagSel.innerHTML = '<option value="all">All tags</option>' + prod.tags.map((t) => `<option value="${esc(t.tag)}">${esc(t.tag)} (${t.count})</option>`).join('');
      try {
        const pref = await api('/api/settings/tagPref.data');
        const pv = pref.value;
        if (pv && pv !== 'all' && prod.tags.some((t) => t.tag === pv)) {
          dataState.tag = pv; tagSel.value = pv;
        }
      } catch { /* baseline default */ }
    }
  } catch { /* */ }
  $('#dm-source').addEventListener('change', (e) => {
    dataState.source = e.target.value; dataState.selected.clear();
    $('#dm-tag').style.display = dataState.source === 'products' && $('#dm-tag').options.length > 1 ? '' : 'none';
    renderDataBody();
  });
  $('#dm-tag').addEventListener('change', async (e) => {
    dataState.tag = e.target.value === 'all' ? '' : e.target.value;
    dataState.selected.clear();
    try { await api('/api/settings/tagPref.data', { method: 'PUT', body: { value: e.target.value } }); } catch { /* */ }
    renderDataBody();
  });
  $('#dm-q').value = dataState.q;
  $('#dm-q').addEventListener('input', (e) => { dataState.q = e.target.value; });
  $('#dm-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') renderDataBody(); });
  root.querySelectorAll('[data-dm-mode]').forEach((b) => b.addEventListener('click', () => { dataState.mode = b.dataset.dmMode; renderData(); }));
  $('#dm-canvas').addEventListener('click', () => showView('bernie'));
  $('#dm-export').addEventListener('click', exportDataCsv);
  $('#dm-asana').addEventListener('click', openAsanaPush);
  renderDataBody();
}

function renderDataBody() {
  const body = $('#dm-body');
  if (dataState.mode === 'pivot') return renderDataPivot(body);
  if (dataState.mode === 'wrangler') return renderDataWrangler(body);
  if (dataState.mode === 'views') return renderDataViews(body);
  if (dataState.mode === 'ingest') return renderDataIngest(body);
  renderDataTable(body);
}

async function renderDataTable(body) {
  body.innerHTML = '<div class="empty-state">Loading…</div>';
  try {
    const tagParam = dataState.tag ? `&tag=${encodeURIComponent(dataState.tag)}` : '';
    const data = await api(`/api/data/table?source=${dataState.source}&limit=500&q=${encodeURIComponent(dataState.q)}${tagParam}`);
    dataState.rows = data.rows; dataState.columns = data.columns;
    const cols = ['#', ...data.columns];
    const head = cols.map((c, i) => i === 0 ? '<th></th>' : `<th data-dm-sort="${esc(c)}">${esc(c)}</th>`).join('');
    const tbody = data.rows.map((r) => {
      const id = r.id ?? r.sku ?? r.name;
      const checked = dataState.selected.has(String(id)) ? 'checked' : '';
      return `<tr>
        <td><input type="checkbox" class="dm-sel" data-id="${esc(String(id))}" ${checked} /></td>
        ${data.columns.map((c) => `<td>${esc(r[c] ?? '')}</td>`).join('')}
      </tr>`;
    }).join('');
    body.innerHTML = `<table class="data-table" id="dm-table"><thead><tr>${head}</tr></thead><tbody>${tbody || '<tr><td colspan="99" class="empty-state">No rows.</td></tr>'}</tbody></table>`;
    body.querySelectorAll('.dm-sel').forEach((cb) => cb.addEventListener('change', () => {
      if (cb.checked) dataState.selected.add(cb.dataset.id); else dataState.selected.delete(cb.dataset.id);
    }));
  } catch (e) { body.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`; }
}

async function renderDataPivot(body) {
  body.innerHTML = `
    <div class="field-row" style="margin-bottom:0.5rem">
      <label class="field"><span>Group by</span><select id="dm-group"></select></label>
      <label class="field"><span>Aggregate</span><select id="dm-agg">
        <option value="count" ${dataState.agg === 'count' ? 'selected' : ''}>Count</option>
        <option value="avg" ${dataState.agg === 'avg' ? 'selected' : ''}>Average</option>
        <option value="sum" ${dataState.agg === 'sum' ? 'selected' : ''}>Sum</option>
        <option value="min" ${dataState.agg === 'min' ? 'selected' : ''}>Min</option>
        <option value="max" ${dataState.agg === 'max' ? 'selected' : ''}>Max</option>
      </select></label>
      <label class="field"><span>Measure</span><select id="dm-measure"><option value="score">score</option></select></label>
    </div>
    <div id="dm-pivot-out"></div>`;
  try {
    const srcs = await api('/api/data/sources');
    const src = srcs.find((s) => s.id === dataState.source) || { groupable: ['category'] };
    $('#dm-group').innerHTML = src.groupable.map((g) => `<option value="${esc(g)}" ${g === dataState.group_by ? 'selected' : ''}>${esc(g)}</option>`).join('');
  } catch { /* */ }
  const run = async () => {
    dataState.group_by = $('#dm-group').value; dataState.agg = $('#dm-agg').value;
    const out = $('#dm-pivot-out');
    out.innerHTML = '<div class="empty-state">Aggregating…</div>';
    try {
      const res = await api('/api/data/pivot', { method: 'POST', body: { source: dataState.source, group_by: dataState.group_by, agg: dataState.agg, measure: dataState.measure, q: dataState.q } });
      const rows = res.rows || [];
      const max = Math.max(1, ...rows.map((r) => Number(r.value) || 0));
      const bars = rows.map((r) => `<div class="dm-bar-row"><span class="dm-bar-label">${esc(r.key)}</span><div class="dm-bar-track"><div class="dm-bar-fill" style="width:${(Number(r.value) / max * 100).toFixed(1)}%"></div></div><span class="dm-bar-val">${r.value}</span></div>`).join('');
      out.innerHTML = `
        <div class="dm-chart">${bars || '<div class="empty-state">No data.</div>'}</div>
        <table class="data-table" style="margin-top:0.5rem"><thead><tr><th>${esc(res.group_by)}</th><th>${esc(res.agg)}${res.agg === 'count' ? '' : ` (${esc(res.measure)})`}</th><th>Rows</th></tr></thead>
        <tbody>${rows.map((r) => `<tr><td>${esc(r.key)}</td><td>${r.value}</td><td>${r.count}</td></tr>`).join('')}</tbody></table>`;
    } catch (e) { out.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`; }
  };
  $('#dm-group').addEventListener('change', run);
  $('#dm-agg').addEventListener('change', run);
  run();
}

async function renderDataWrangler(body) {
  body.innerHTML = '<div class="empty-state">Profiling…</div>';
  try {
    const data = await api(`/api/data/table?source=${dataState.source}&limit=1000&q=${encodeURIComponent(dataState.q)}`);
    const rows = data.rows; const columns = data.columns;
    const profile = columns.map((col) => {
      const vals = rows.map((r) => r[col]).filter((v) => v !== null && v !== undefined && v !== '');
      const uniq = new Set(vals.map((v) => String(v)));
      const examples = Array.from(uniq).slice(0, 3).join(', ');
      return `<tr>
        <td>${esc(col)}</td>
        <td>${rows.length - vals.length}</td>
        <td>${uniq.size}</td>
        <td style="color:var(--muted-fg);max-width:24rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(examples) || '—'}</td>
      </tr>`;
    }).join('');
    body.innerHTML = `
      <div class="settings-note">Column profiling over ${rows.length} rows — missing values, unique counts, and example values (a lightweight data-wrangler view).</div>
      <table class="data-table"><thead><tr><th>Column</th><th>Missing</th><th>Unique</th><th>Examples</th></tr></thead><tbody>${profile}</tbody></table>`;
  } catch (e) { body.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`; }
}

async function renderDataViews(body) {
  body.innerHTML = '<div class="empty-state">Loading saved views…</div>';
  const load = async () => {
    try {
      const views = await api('/api/data/views');
      body.innerHTML = `
        <div class="field-row" style="margin-bottom:0.5rem">
          <label class="field"><span>Save current view as</span><input id="dv-name" placeholder="e.g. Blockers in Beauty" /></label>
          <label class="field"><span>&nbsp;</span><button class="btn-primary" id="dv-save" style="min-height:var(--control-h)">Save</button></label>
        </div>
        <table class="data-table"><thead><tr><th>View</th><th>Source</th><th>Created</th><th></th></tr></thead>
        <tbody>${views.map((v) => `<tr><td>${esc(v.name)}</td><td>${esc(v.source)}</td><td class="mono">${fmtAgo(v.created_at) || '—'}</td><td style="text-align:right"><button class="btn-mini" data-dv-load="${v.id}">Open</button> <button class="btn-mini btn-mini-danger" data-dv-del="${v.id}">Delete</button></td></tr>`).join('') || '<tr><td colspan="4" class="empty-state">No saved views.</td></tr>'}</tbody></table>`;
      body.querySelector('#dv-save').addEventListener('click', async () => {
        const name = body.querySelector('#dv-name').value.trim();
        if (!name) return toast('Name is required', 'err');
        await api('/api/data/views', { method: 'POST', body: { name, source: dataState.source, config: { q: dataState.q, group_by: dataState.group_by, agg: dataState.agg } } });
        toast('View saved', 'ok'); load();
      });
      body.querySelectorAll('[data-dv-load]').forEach((b) => b.addEventListener('click', () => {
        dataState.mode = 'table'; renderData();
      }));
      body.querySelectorAll('[data-dv-del]').forEach((b) => b.addEventListener('click', async () => {
        await api(`/api/data/views/${b.dataset.dvDel}`, { method: 'DELETE' }); toast('View deleted', 'ok'); load();
      }));
    } catch (e) { body.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`; }
  };
  load();
}

async function renderDataIngest(body) {
  body.innerHTML = '<div class="empty-state">Loading ingest sources…</div>';
  try {
    const res = await api('/api/data/ingest/sources');
    const badge = (s) => s === 'ready' ? 'pill-int pill-int-configured' : 'pill-int pill-int-missing';
    body.innerHTML = `
      <div class="settings-note">Ingest sources for Data Management — ready sources are live, others need credentials.</div>
      <table class="data-table"><thead><tr><th>Source</th><th>Status</th><th>Notes</th></tr></thead>
      <tbody>${res.sources.map((s) => `<tr><td>${esc(s.label)}</td><td><span class="${badge(s.status)}">${esc(s.status)}</span></td><td style="color:var(--muted-fg)">${esc(s.note)}</td></tr>`).join('')}</tbody></table>`;
  } catch (e) { body.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`; }
}

async function exportDataCsv() {
  try {
    const data = await api(`/api/data/table?source=${dataState.source}&limit=2000&q=${encodeURIComponent(dataState.q)}`);
    const cols = data.columns;
    const escCsv = (v) => { const s = String(v ?? ''); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    const lines = [cols.map(escCsv).join(',')];
    data.rows.forEach((r) => lines.push(cols.map((c) => escCsv(r[c])).join(',')));
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = `conductor-${dataState.source}.csv`; a.click();
    URL.revokeObjectURL(a.href);
  } catch (e) { toast(`Export failed: ${e.message}`, 'err'); }
}

async function openAsanaPush() {
  let projects = [];
  try { projects = await api('/api/asana/projects'); } catch { /* */ }
  const projOpts = projects.map((p) => `<option value="${esc(p.name)}">${esc(p.name)}</option>`).join('');
  const count = dataState.selected.size || dataState.rows.length;
  openModal('Push to Asana', `
    <div class="settings-note">Create an Asana task${count ? ` — ${count} selected row${count === 1 ? '' : 's'} will be appended to the notes` : ''}.</div>
    <label class="field"><span>Task name</span><input id="ap-name" placeholder="e.g. Review catalog data quality" /></label>
    <label class="field"><span>Project</span><input id="ap-project" list="ap-projects" placeholder="Project name or GID" /><datalist id="ap-projects">${projOpts}</datalist></label>
    <label class="field"><span>Notes</span><textarea id="ap-notes" rows="3"></textarea></label>`,
    `<button class="btn-secondary" id="ap-cancel">Cancel</button>
     <button class="btn-primary" id="ap-do">Create task</button>`);
  $('#ap-cancel').addEventListener('click', closeModal);
  $('#ap-do').addEventListener('click', async () => {
    const name = $('#ap-name').value.trim();
    if (!name) return toast('Task name is required', 'err');
    const rows = dataState.rows.filter((r) => dataState.selected.has(String(r.id ?? r.sku ?? r.name)));
    try {
      const res = await api('/api/data/push-asana', { method: 'POST', body: { name, notes: $('#ap-notes').value, project: $('#ap-project').value, rows } });
      closeModal();
      if (res.executed === 'live') toast(`Asana task created: ${res.detail}`, 'ok');
      else toast(res.detail || 'Simulated (no Asana PAT configured)', 'warn');
    } catch (e) { toast(`Push failed: ${e.message}`, 'err'); }
  });
}

/* ==========================================================================
   FEATURE STUDIO — report → reusable feature → Asana → workflow + automation
   ========================================================================== */
const FT_TYPES = ['present', 'min_length', 'max_length', 'contains', 'in_values'];

function ftSerializeArgs(f) {
  const a = f.args || {};
  if (f.type === 'min_length') return a.min != null ? 'min:' + a.min : '';
  if (f.type === 'max_length') return a.max != null ? 'max:' + a.max : '';
  if (f.type === 'contains') return a.text ? 'text:' + a.text : '';
  if (f.type === 'in_values') return (a.values || []).join(',');
  return '';
}
function ftParseArgs(type, raw) {
  raw = (raw || '').trim();
  const args = {};
  if (type === 'min_length') { const m = parseInt(raw.replace('min:', ''), 10); if (!isNaN(m)) args.min = m; }
  else if (type === 'max_length') { const m = parseInt(raw.replace('max:', ''), 10); if (!isNaN(m)) args.max = m; }
  else if (type === 'contains') { args.text = raw.replace('text:', '').trim(); }
  else if (type === 'in_values') { args.values = raw.split(',').map((s) => s.trim()).filter(Boolean); }
  return args;
}
function ftFieldOptions(cur) {
  const fields = ['name', 'sku', 'category', 'market', 'brand', 'source'];
  if (cur && !fields.includes(cur)) fields.push(cur);
  return fields.map((f) => `<option value="${esc(f)}" ${cur === f ? 'selected' : ''}>${esc(f)}</option>`).join('');
}

async function renderFeatureStudio() {
  const root = $('#view-root');
  root.innerHTML = `
    <div class="view">
      <div class="view-header">
        <div>
          <div class="view-title">Feature Studio</div>
          <div class="view-sub">Turn a report into a reusable feature — derive the rating's factors with AI, run it on live data, push actions to Asana, then generate a workflow diagram + automation.</div>
        </div>
        <div class="view-actions"><button class="btn-primary" id="ft-new"><span class="codicon codicon-add"></span> New from report</button></div>
      </div>
      <div id="ft-list" class="empty-state">Loading…</div>
      <div id="ft-detail"></div>
    </div>`;
  $('#ft-new').addEventListener('click', () => openFeatureEditor(null));
  await refreshFeatureList();
}

async function refreshFeatureList() {
  const list = $('#ft-list');
  if (!list) return;
  try {
    const feats = await api('/api/features');
    if (!feats.length) {
      list.innerHTML = `<div class="empty-state"><div class="big"><span class="codicon codicon-beaker"></span></div><div>No features yet — paste a report and derive your first one.</div><button class="btn-primary" id="ft-new2" style="margin-top:0.75rem">New from report</button></div>`;
      const b = $('#ft-new2'); if (b) b.addEventListener('click', () => openFeatureEditor(null));
      return;
    }
    list.innerHTML = `<table class="data-table"><thead><tr><th>Feature</th><th>Rating</th><th>Factors</th><th>Bands</th><th>Updated</th><th></th></tr></thead><tbody>${feats.map((f) => `
      <tr>
        <td><b>${esc(f.name)}</b>${f.description ? `<div style="color:var(--muted-fg)">${esc(f.description)}</div>` : ''}</td>
        <td>${esc(f.rating_label)}</td>
        <td>${f.factor_count}</td>
        <td>${f.action_count}</td>
        <td class="mono">${fmtAgo(f.updated_at) || '—'}</td>
        <td style="text-align:right;white-space:nowrap">
          <button class="btn-mini" data-ft-run="${f.id}">Run</button>
          <button class="btn-mini" data-ft-push="${f.id}">Push</button>
          <button class="btn-mini" data-ft-build="${f.id}">Build</button>
          <button class="btn-mini" data-ft-edit="${f.id}">Edit</button>
          <button class="btn-mini btn-mini-danger" data-ft-del="${f.id}">Delete</button>
        </td>
      </tr>`).join('')}</tbody></table>`;
    list.querySelectorAll('[data-ft-run]').forEach((b) => b.addEventListener('click', () => ftRun(Number(b.dataset.ftRun))));
    list.querySelectorAll('[data-ft-push]').forEach((b) => b.addEventListener('click', () => ftPush(Number(b.dataset.ftPush))));
    list.querySelectorAll('[data-ft-build]').forEach((b) => b.addEventListener('click', () => ftBuild(Number(b.dataset.ftBuild))));
    list.querySelectorAll('[data-ft-edit]').forEach((b) => b.addEventListener('click', () => openFeatureEditor(Number(b.dataset.ftEdit))));
    list.querySelectorAll('[data-ft-del]').forEach((b) => b.addEventListener('click', async () => {
      if (!confirm('Delete this feature?')) return;
      await api(`/api/features/${b.dataset.ftDel}`, { method: 'DELETE' });
      toast('Feature deleted', 'ok'); refreshFeatureList();
    }));
  } catch (e) { list.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`; }
}

async function ftRun(id) {
  const detail = $('#ft-detail');
  detail.innerHTML = '<div class="empty-state">Scoring listings…</div>';
  try {
    const res = await api(`/api/features/${id}/run`, { method: 'POST', body: {} });
    const rows = res.results.map((r) => `
      <tr>
        <td class="mono">${esc(r.sku)}</td>
        <td>${esc(r.name)}</td>
        <td>${esc(r.category)}</td>
        <td><span class="${r.score < 60 ? 'pill-int pill-int-missing' : r.score < 80 ? 'pill-int' : 'pill-int pill-int-configured'}">${r.score}</span></td>
        <td style="color:var(--muted-fg);max-width:24rem">${r.failed_factors.length ? esc(r.failed_factors.join(', ')) : '—'}</td>
      </tr>`).join('');
    detail.innerHTML = `
      <div class="ft-detail-card">
        <div class="ft-detail-head"><b>${esc(res.feature.name)}</b> — ${res.results.length} listing(s) scored
          <span style="flex:1"></span>
          <button class="btn-secondary" id="ft-run-push"><span class="codicon codicon-organization"></span> Push to Asana</button>
          <button class="btn-secondary" id="ft-run-build"><span class="codicon codicon-graph"></span> Build workflow + automation</button>
        </div>
        <table class="data-table"><thead><tr><th>SKU</th><th>Name</th><th>Category</th><th>Score</th><th>Failed factors</th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="empty-state">No products to score.</td></tr>'}</tbody></table>
      </div>`;
    $('#ft-run-push').addEventListener('click', () => ftPush(id));
    $('#ft-run-build').addEventListener('click', () => ftBuild(id));
  } catch (e) { detail.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`; }
}

async function ftPush(id) {
  try {
    const res = await api(`/api/features/${id}/push-asana`, { method: 'POST', body: {} });
    const live = res.live || 0;
    toast(`${res.total} task(s) → ${live} live, ${res.total - live} simulated`, live ? 'ok' : 'warn');
  } catch (e) { toast(`Push failed: ${e.message}`, 'err'); }
}

async function ftBuild(id) {
  try {
    const res = await api(`/api/features/${id}/build`, { method: 'POST', body: {} });
    openModal('Feature built', `
      <div class="settings-note">Created a workflow diagram <b>#${res.canvas_id}</b> and an automation <b>#${res.automation_id}</b> (disabled — enable it once you review).</div>
      <div class="settings-note" style="margin-top:0.5rem">Open Flow Canvas to see/edit the diagram, or Automations to wire the trigger and enable it.</div>`,
      `<button class="btn-secondary" id="ft-bc">Close</button>
       <button class="btn-primary" id="ft-open-canvas">Open Flow Canvas</button>`);
    $('#ft-bc').addEventListener('click', closeModal);
    $('#ft-open-canvas').addEventListener('click', () => { closeModal(); showView('bernie'); });
  } catch (e) { toast(`Build failed: ${e.message}`, 'err'); }
}

let featDraft = null;

async function openFeatureEditor(id) {
  if (id) {
    const f = await api(`/api/features/${id}`);
    featDraft = JSON.parse(JSON.stringify(f.spec));
  } else {
    featDraft = {
      name: '', description: '', rating_label: 'Listing Quality Score (0-100)',
      factors: [],
      actions: [{ min_score: 0, max_score: 60, project: 'Catalog Ops', name_template: 'Fix listing {sku} ({score}/100)', notes_template: 'Score {score}/100. Failed: {failed_factors}' }],
      source_report: '',
    };
  }

  const renderFactors = () => {
    const rows = (featDraft.factors || []).map((f, i) => `
      <div class="ft-factor">
        <div class="ft-row">
          <input class="ft-f-label" value="${esc(f.label || '')}" placeholder="Check label" style="flex:2" />
          <select class="ft-f-field" style="flex:1">${ftFieldOptions(f.field)}</select>
          <select class="ft-f-type" style="flex:1">${FT_TYPES.map((t) => `<option value="${t}" ${f.type === t ? 'selected' : ''}>${t}</option>`).join('')}</select>
          <input class="ft-f-weight" type="number" min="1" max="100" value="${f.weight || 10}" title="Weight" style="width:4.5rem" />
          <button class="nav-mini nav-mini-danger" data-ft-fdel="${i}" title="Remove factor">×</button>
        </div>
        <div class="ft-row"><span class="ft-arglabel">args</span><input class="ft-f-args" value="${esc(ftSerializeArgs(f))}" placeholder="min:80 · max:200 · text:keyword · a,b,c" style="flex:1" /></div>
      </div>`).join('');
    $('#ft-factors').innerHTML = rows || '<div class="nav-empty">No factors — add below or derive from a report.</div>';
    $('#ft-factors').querySelectorAll('[data-ft-fdel]').forEach((b) => b.addEventListener('click', () => {
      featDraft.factors.splice(Number(b.dataset.ftFdel), 1); renderFactors();
    }));
  };

  const renderBands = () => {
    const rows = (featDraft.actions || []).map((b, i) => `
      <div class="ft-factor">
        <div class="ft-row">
          <input class="ft-b-min" type="number" value="${b.min_score ?? 0}" title="min score" style="width:4.5rem" />
          <input class="ft-b-max" type="number" value="${b.max_score ?? 60}" title="max score" style="width:4.5rem" />
          <input class="ft-b-project" value="${esc(b.project || '')}" placeholder="Asana project" style="flex:1" />
          <button class="nav-mini nav-mini-danger" data-ft-bdel="${i}" title="Remove band">×</button>
        </div>
        <div class="ft-row">
          <input class="ft-b-name" value="${esc(b.name_template || '')}" placeholder="Task name template (e.g. Fix listing {sku})" style="flex:1" />
          <input class="ft-b-notes" value="${esc(b.notes_template || '')}" placeholder="Notes template ({score},{failed_factors})" style="flex:1" />
        </div>
      </div>`).join('');
    $('#ft-actions').innerHTML = rows || '<div class="nav-empty">No action bands — add one.</div>';
    $('#ft-actions').querySelectorAll('[data-ft-bdel]').forEach((b) => b.addEventListener('click', () => {
      featDraft.actions.splice(Number(b.dataset.ftBdel), 1); renderBands();
    }));
  };

  openModal(id ? 'Edit Feature' : 'New Feature from Report', `
    <label class="field"><span>Report (paste the doc describing the new rating)</span>
      <textarea id="ft-report" rows="4" placeholder="Paste the report text here — the app will derive the rating's factors and scoring logic…"></textarea></label>
    <div class="settings-actions" style="margin-bottom:0.5rem">
      <button class="btn-primary" id="ft-derive"><span class="codicon codicon-sparkle"></span> Derive with AI</button>
      <span id="ft-derive-status" class="settings-note" style="margin:0"></span>
    </div>
    <div class="field-row">
      <label class="field"><span>Feature name</span><input id="ft-name" value="${esc(featDraft.name)}" placeholder="e.g. Listing Quality Score" /></label>
      <label class="field"><span>Rating label</span><input id="ft-rating" value="${esc(featDraft.rating_label)}" /></label>
    </div>
    <label class="field"><span>Description</span><input id="ft-desc" value="${esc(featDraft.description)}" placeholder="What this feature evaluates" /></label>
    <div class="field"><span>Factors (field → rule → weight)</span><div id="ft-factors" class="ft-grid"></div>
      <button class="btn-secondary" id="ft-add-factor" style="margin-top:0.375rem">＋ Add factor</button></div>
    <div class="field"><span>Asana action bands (score → task)</span><div id="ft-actions" class="ft-grid"></div>
      <button class="btn-secondary" id="ft-add-band" style="margin-top:0.375rem">＋ Add band</button></div>`,
    `<button class="btn-secondary" id="ft-cancel">Cancel</button>
     <button class="btn-primary" id="ft-save">Save feature</button>`);

  renderFactors();
  renderBands();

  $('#ft-derive').addEventListener('click', async () => {
    const report = $('#ft-report').value.trim();
    if (!report) return toast('Paste the report first', 'warn');
    const status = $('#ft-derive-status');
    status.textContent = 'Deriving…';
    try {
      const res = await api('/api/features/derive', { method: 'POST', body: { report } });
      featDraft = res.spec;
      $('#ft-name').value = featDraft.name || '';
      $('#ft-rating').value = featDraft.rating_label || '';
      $('#ft-desc').value = featDraft.description || '';
      renderFactors(); renderBands();
      status.textContent = res.ai ? `Derived ${featDraft.factors.length} factors.` : `No AI — ${res.error || 'built a blank template'}`;
    } catch (e) { status.textContent = `Derive failed: ${e.message}`; }
  });

  $('#ft-add-factor').addEventListener('click', () => {
    featDraft.factors = featDraft.factors || [];
    featDraft.factors.push({ label: '', field: 'name', type: 'present', args: {}, weight: 10 });
    renderFactors();
  });
  $('#ft-add-band').addEventListener('click', () => {
    featDraft.actions = featDraft.actions || [];
    featDraft.actions.push({ min_score: 0, max_score: 60, project: 'Catalog Ops', name_template: 'Fix listing {sku}', notes_template: '' });
    renderBands();
  });
  $('#ft-cancel').addEventListener('click', closeModal);
  $('#ft-save').addEventListener('click', async () => {
    const factors = Array.from(document.querySelectorAll('#ft-factors .ft-factor')).map((row) => ({
      label: row.querySelector('.ft-f-label').value.trim(),
      field: row.querySelector('.ft-f-field').value,
      type: row.querySelector('.ft-f-type').value,
      args: ftParseArgs(row.querySelector('.ft-f-type').value, row.querySelector('.ft-f-args').value),
      weight: Number(row.querySelector('.ft-f-weight').value || 10),
    })).filter((f) => f.field);
    const actions = Array.from(document.querySelectorAll('#ft-actions .ft-factor')).map((row) => ({
      min_score: Number(row.querySelector('.ft-b-min').value || 0),
      max_score: Number(row.querySelector('.ft-b-max').value || 60),
      project: row.querySelector('.ft-b-project').value.trim() || 'Catalog Ops',
      name_template: row.querySelector('.ft-b-name').value.trim(),
      notes_template: row.querySelector('.ft-b-notes').value.trim(),
    }));
    const spec = {
      name: $('#ft-name').value.trim(),
      description: $('#ft-desc').value.trim(),
      rating_label: $('#ft-rating').value.trim() || 'Listing Quality Score (0-100)',
      factors, actions,
      source_report: $('#ft-report').value.trim() || featDraft.source_report || '',
    };
    if (!spec.name) return toast('Feature name is required', 'err');
    if (!factors.length) return toast('Add at least one factor', 'err');
    try {
      if (id) await api(`/api/features/${id}`, { method: 'PUT', body: { spec } });
      else await api('/api/features', { method: 'POST', body: { spec } });
      closeModal(); toast('Feature saved', 'ok'); refreshFeatureList();
    } catch (e) { toast(`Save failed: ${e.message}`, 'err'); }
  });
}

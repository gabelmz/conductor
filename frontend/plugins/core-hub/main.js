/* core-hub — Tool Hub plugin (ported from LAW's plugins/core-hub).
 * Renders the Hub view into #view-root using Conductor's global helpers
 * (api/esc/showView) and registers palette commands + hub actions. */
const CATS = ['app', 'skill', 'module', 'plugin', 'theme'];
const STATUSES = ['live', 'draft', 'archived', 'planning', 'scaffold'];
const CAT_ICONS = { app: 'codicon-window', skill: 'codicon-lightbulb', module: 'codicon-puzzle', plugin: 'codicon-extensions', theme: 'codicon-symbol-color' };

let hubState = { q: '', cat: '', status: '', cards: [], editing: null };

async function loadCards() {
  const params = new URLSearchParams();
  if (hubState.cat) params.set('cat', hubState.cat);
  if (hubState.status) params.set('status', hubState.status);
  if (hubState.q) params.set('q', hubState.q);
  const res = await api(`/api/hub/cards?${params.toString()}`);
  hubState.cards = res.cards || [];
}

const CAT_LABEL = { app: 'App', skill: 'Skill', module: 'Module', plugin: 'Plugin', theme: 'Theme' };

function renderHub(container) {
  if (!container) return;
  container.innerHTML = `
    <div class="view">
      <div class="view-header">
        <div>
          <div class="view-title">Tool Hub</div>
          <div class="view-sub">Every tool in the workspace — apps, skills, modules, plugins, themes — with status, owner and tags.</div>
        </div>
        <div class="view-actions">
          <button class="btn-primary hub-btn-new"><span class="codicon codicon-add"></span> New card</button>
        </div>
      </div>
      <div class="hub-filters">
        <div class="hub-search"><span class="codicon codicon-search"></span><input id="hub-q" type="text" placeholder="Search cards…" value="${esc(hubState.q)}" /></div>
        <div class="hub-chips" id="hub-cat-chips">
          <button class="hub-chip ${hubState.cat === '' ? 'active' : ''}" data-cat="">All</button>
          ${CATS.map((c) => `<button class="hub-chip ${hubState.cat === c ? 'active' : ''}" data-cat="${c}">${CAT_LABEL[c]}</button>`).join('')}
        </div>
        <div class="hub-chips" id="hub-status-chips">
          ${STATUSES.map((s) => `<button class="hub-chip hub-chip-status ${hubState.status === s ? 'active' : ''}" data-status="${s}">${s}</button>`).join('')}
        </div>
      </div>
      <div class="hub-grid" id="hub-grid"></div>
    </div>`;

  container.querySelector('.hub-btn-new').addEventListener('click', () => { hubState.editing = {}; renderHub(container); });
  container.querySelector('#hub-q').addEventListener('input', (e) => {
    hubState.q = e.target.value;
    debouncedReload(container);
  });
  container.querySelectorAll('#hub-cat-chips .hub-chip').forEach((b) => b.addEventListener('click', () => {
    hubState.cat = b.dataset.cat; renderHub(container);
  }));
  container.querySelectorAll('#hub-status-chips .hub-chip').forEach((b) => b.addEventListener('click', () => {
    hubState.status = b.dataset.status; renderHub(container);
  }));

  if (hubState.editing) { renderHubForm(container); return; }
  loadCards().then(() => renderHubGrid(container));
}

let _debounce = null;
function debouncedReload(container) {
  clearTimeout(_debounce);
  _debounce = setTimeout(() => loadCards().then(() => renderHubGrid(container)), 250);
}

function renderHubGrid(container) {
  const grid = container.querySelector('#hub-grid');
  if (!grid) return;
  if (!hubState.cards.length) {
    grid.innerHTML = '<div class="hub-empty">No cards yet. Create one, or run “Rescan plugins” to seed it from installed plugins.</div>';
    return;
  }
  const actions = window.ConductorPlugins ? [...window.ConductorPlugins.registries.hubActions.values()] : [];
  grid.innerHTML = hubState.cards.map((card) => {
    const catIcon = CAT_ICONS[card.cat] || 'codicon-gift';
    const applies = actions.filter((a) => a.appliesTo === 'all' || a.appliesTo === card.cat);
    return `
    <div class="hub-card" data-id="${esc(card.id)}">
      <div class="hub-card-top">
        <span class="codicon ${catIcon} hub-card-ic"></span>
        <span class="hub-card-name">${esc(card.name)}</span>
        <span class="hub-status hub-status-${esc(card.status)}">${esc(card.status)}</span>
      </div>
      ${card.desc ? `<div class="hub-card-desc">${esc(card.desc)}</div>` : ''}
      <div class="hub-card-meta">
        <span>${CAT_LABEL[card.cat] || card.cat}</span>
        ${card.owner ? `<span>· ${esc(card.owner)}</span>` : ''}
        ${card.trigger ? `<span class="hub-trigger">“${esc(card.trigger)}”</span>` : ''}
      </div>
      ${(card.tags || []).length ? `<div class="hub-card-tags">${card.tags.map((t) => `<span class="hub-tag">${esc(t)}</span>`).join('')}</div>` : ''}
      <div class="hub-card-actions">
        <button class="btn-secondary hub-edit" data-id="${esc(card.id)}">Edit</button>
        <button class="btn-secondary hub-del" data-id="${esc(card.id)}">Delete</button>
        ${applies.map((a) => `<button class="btn-secondary hub-act" data-act="${esc(a.id)}" data-id="${esc(card.id)}">${esc(a.label)}</button>`).join('')}
      </div>
    </div>`;
  }).join('');

  grid.querySelectorAll('.hub-edit').forEach((b) => b.addEventListener('click', () => {
    hubState.editing = hubState.cards.find((c) => c.id === b.dataset.id) || {};
    renderHub(container);
  }));
  grid.querySelectorAll('.hub-del').forEach((b) => b.addEventListener('click', async () => {
    await api(`/api/hub/cards/${b.dataset.id}`, { method: 'DELETE' });
    toast('Card deleted', 'ok');
    loadCards().then(() => renderHubGrid(container));
  }));
  grid.querySelectorAll('.hub-act').forEach((b) => b.addEventListener('click', () => {
    const action = actions.find((a) => a.id === b.dataset.act);
    if (action) action.handler(b.dataset.id);
  }));
}

function renderHubForm(container) {
  const editing = hubState.editing;
  const grid = container.querySelector('#hub-grid');
  if (!grid) return;
  grid.innerHTML = `
    <div class="hub-form">
      <div class="hub-form-title">${editing.id ? 'Edit card' : 'New card'}</div>
      <div class="field-row">
        <label class="field"><span>Category</span>
          <select id="hf-cat">${CATS.map((c) => `<option value="${c}" ${editing.cat === c ? 'selected' : ''}>${CAT_LABEL[c]}</option>`).join('')}</select></label>
        <label class="field"><span>Status</span>
          <select id="hf-status">${STATUSES.map((s) => `<option value="${s}" ${(editing.status || 'draft') === s ? 'selected' : ''}>${s}</option>`).join('')}</select></label>
      </div>
      <label class="field"><span>Name</span><input id="hf-name" value="${esc(editing.name || '')}" placeholder="e.g. Keepa price monitor" /></label>
      <label class="field"><span>Description</span><input id="hf-desc" value="${esc(editing.desc || '')}" placeholder="What does it do?" /></label>
      <div class="field-row">
        <label class="field"><span>Owner</span><input id="hf-owner" value="${esc(editing.owner || '')}" placeholder="Team / person" /></label>
        <label class="field"><span>Trigger phrase</span><input id="hf-trigger" value="${esc(editing.trigger || '')}" placeholder="“when X happens…”" /></label>
      </div>
      <label class="field"><span>Tags (comma-separated)</span><input id="hf-tags" value="${esc((editing.tags || []).join(', '))}" placeholder="pricing, monitoring" /></label>
      <label class="field"><span>Note</span><textarea id="hf-note" rows="2" placeholder="Anything else">${esc(editing.note || '')}</textarea></label>
      <div class="settings-actions">
        <button class="btn-primary" id="hf-save">Save</button>
        <button class="btn-secondary" id="hf-cancel">Cancel</button>
        ${editing.id ? `<button class="btn-secondary" id="hf-rescan">Rescan plugins</button>` : ''}
      </div>
    </div>`;

  grid.querySelector('#hf-cancel').addEventListener('click', () => { hubState.editing = null; renderHub(container); });
  grid.querySelector('#hf-rescan')?.addEventListener('click', async () => {
    await api('/api/hub/scan', { method: 'POST' });
    toast('Plugin cards rescanned', 'ok');
    hubState.editing = null;
    loadCards().then(() => renderHub(container));
  });
  grid.querySelector('#hf-save').addEventListener('click', async () => {
    const body = {
      cat: grid.querySelector('#hf-cat').value,
      status: grid.querySelector('#hf-status').value,
      name: grid.querySelector('#hf-name').value.trim(),
      desc: grid.querySelector('#hf-desc').value.trim() || null,
      owner: grid.querySelector('#hf-owner').value.trim() || null,
      trigger: grid.querySelector('#hf-trigger').value.trim() || null,
      note: grid.querySelector('#hf-note').value.trim() || null,
      tags: grid.querySelector('#hf-tags').value.split(',').map((t) => t.trim()).filter(Boolean),
    };
    if (!body.name) return toast('Name is required', 'warn');
    try {
      if (editing.id) await api(`/api/hub/cards/${editing.id}`, { method: 'PATCH', body });
      else await api('/api/hub/cards', { method: 'POST', body });
      toast('Card saved', 'ok');
      hubState.editing = null;
      loadCards().then(() => renderHub(container));
    } catch (e) { toast(e.message, 'err'); }
  });
}

export function onload(api) {
  api.registerPage({ id: 'hub', title: 'Tool Hub', icon: 'codicon-gift', render: renderHub });
  api.registerCommand({ id: 'open', title: 'Open Tool Hub', handler: () => showView('hub') });
  api.registerCommand({ id: 'new-card', title: 'New Hub Card', handler: () => { showView('hub'); } });
  api.registerHubAction({
    id: 'mark-live',
    label: 'Mark live',
    appliesTo: 'all',
    handler: async (cardId) => {
      try {
        await api(`/api/hub/cards/${cardId}`, { method: 'PATCH', body: { status: 'live' } });
        toast('Card marked live', 'ok');
        loadCards().then(() => {
          const root = document.getElementById('view-root');
          if (root) renderHub(root);
        });
      } catch (e) { toast(e.message, 'err'); }
    },
  });
}

export function onunload() {
  hubState = { q: '', cat: '', status: '', cards: [], editing: null };
}

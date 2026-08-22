/**
 * Conductor — MCP & Supabase Sync Hub.
 *
 * A credential-safe control surface for MCP server registration and Supabase
 * data movement. Exposes window.ConductorMcpSync.render() and self-registers
 * the `mcpsync` view when app.js has made VIEW_RENDERERS available.
 */
'use strict';

window.ConductorMcpSync = (function () {
  const ENDPOINTS = {
    mcp: '/api/mcp',
    supabase: '/api/supabase',
  };

  const state = {
    servers: [],
    supabase: {},
    runs: [],
    loading: true,
    busy: new Set(),
    renderId: 0,
  };

  const byId = (id) => document.getElementById(id);
  const setBusy = (key, value) => value ? state.busy.add(key) : state.busy.delete(key);

  function icon(name) {
    return `<span class="codicon codicon-${name}" aria-hidden="true"></span>`;
  }

  function safeUrl(value) {
    if (!value) return '';
    try {
      const url = new URL(String(value));
      url.username = '';
      url.password = '';
      url.search = '';
      url.hash = '';
      return url.toString().replace(/\/$/, '');
    } catch (_) {
      return String(value).replace(/([?&](?:key|token|secret|password)=)[^&\s]+/gi, '$1••••');
    }
  }

  function statusName(value) {
    const raw = String(value || '').toLowerCase();
    if (['ok', 'ready', 'connected', 'configured', 'passed', 'success'].includes(raw)) return 'ready';
    if (['error', 'failed', 'offline', 'unhealthy'].includes(raw)) return 'error';
    if (['testing', 'running', 'pending'].includes(raw)) return 'busy';
    return 'idle';
  }

  function statusLabel(value, fallback) {
    const raw = String(value || fallback || 'not tested');
    return raw.replace(/[_-]+/g, ' ');
  }

  function normalizeServers(data) {
    const rows = Array.isArray(data) ? data : (data && (data.servers || data.items)) || [];
    return rows.map((server, index) => ({
      id: server.id || server.key || server.name || String(index),
      name: server.name || server.label || server.id || 'Untitled server',
      transport: String(server.transport || server.type || 'stdio').toLowerCase(),
      command: server.command || '',
      url: server.url || server.endpoint || '',
      status: server.status || (server.ok === true ? 'ready' : server.ok === false ? 'error' : 'idle'),
      detail: server.detail || server.message || '',
    }));
  }

  function normalizeRuns(data) {
    const rows = Array.isArray(data) ? data : (data && (data.runs || data.items)) || [];
    return rows.slice(0, 8);
  }

  function serverCard(server) {
    const key = encodeURIComponent(server.id);
    const status = statusName(server.status);
    const detail = server.transport === 'http'
      ? safeUrl(server.url)
      : (server.command ? `Command: ${server.command.split(/[\\/]/).pop()}` : 'Local process');
    return `<article class="ms-server" data-server-id="${esc(server.id)}" data-testid="mcp-server-card">
      <div class="ms-server-icon ms-server-icon-${esc(server.transport)}">${icon(server.transport === 'http' ? 'globe' : 'terminal')}</div>
      <div class="ms-server-main">
        <div class="ms-server-title-row">
          <strong class="ms-server-name">${esc(server.name)}</strong>
          <span class="ms-chip">${esc(server.transport)}</span>
          <span class="ms-status ms-status-${status}"><i></i>${esc(statusLabel(server.status))}</span>
        </div>
        <div class="ms-server-detail" title="${esc(detail)}">${esc(detail || 'No endpoint details')}</div>
        ${server.detail ? `<div class="ms-server-note">${esc(server.detail)}</div>` : ''}
      </div>
      <div class="ms-server-actions">
        <button class="btn-secondary ms-icon-btn" data-action="test-server" data-server-key="${key}" title="Test connection" aria-label="Test ${esc(server.name)}">${icon('debug-start')}<span>Test</span></button>
        <button class="btn-secondary ms-icon-btn ms-danger" data-action="remove-server" data-server-key="${key}" title="Remove server" aria-label="Remove ${esc(server.name)}">${icon('trash')}<span>Remove</span></button>
      </div>
    </article>`;
  }

  function serverList() {
    if (state.loading) return `<div class="ms-empty">${icon('loading codicon-modifier-spin')} Loading MCP servers…</div>`;
    if (!state.servers.length) return `<div class="ms-empty" id="mcp-empty-state">${icon('server-process')}<strong>No MCP servers registered</strong><span>Add a local stdio process or remote HTTP endpoint below.</span></div>`;
    return state.servers.map(serverCard).join('');
  }

  function runRow(run) {
    const status = statusName(run.status || (run.ok ? 'success' : 'idle'));
    const direction = run.direction || run.action || 'sync';
    const dataset = run.dataset || run.resource || run.table || 'data';
    const count = run.count ?? run.rows ?? run.synced ?? run.records;
    const stamp = run.finished_at || run.started_at || run.created_at || run.timestamp || '';
    const when = stamp ? new Date(stamp).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'Just now';
    return `<div class="ms-run" data-testid="sync-run-row">
      <span class="ms-run-icon ms-status-${status}">${icon(status === 'error' ? 'error' : status === 'busy' ? 'sync codicon-modifier-spin' : 'check')}</span>
      <div><strong>${esc(String(direction).toUpperCase())} · ${esc(dataset)}</strong><span>${esc(run.message || run.detail || (count != null ? `${count} records` : statusLabel(run.status, 'complete')))}</span></div>
      <time>${esc(when)}</time>
    </div>`;
  }

  function renderRuns() {
    const target = byId('sync-run-list');
    if (!target) return;
    target.innerHTML = state.runs.length
      ? state.runs.map(runRow).join('')
      : `<div class="ms-empty ms-empty-compact">${icon('history')} No sync runs yet.</div>`;
  }

  function renderServerList() {
    const target = byId('mcp-server-list');
    if (target) target.innerHTML = serverList();
  }

  function renderSupabaseStatus() {
    const target = byId('supabase-connection-status');
    if (!target) return;
    const configured = !!(state.supabase.configured || (state.supabase.url && state.supabase.has_service_key));
    const live = state.supabase.status || state.supabase.connection_status || (configured ? 'configured' : 'not configured');
    const cls = statusName(live);
    target.className = `ms-status ms-status-${cls}`;
    target.innerHTML = `<i></i>${esc(statusLabel(live))}`;
    const saved = byId('supabase-saved-note');
    if (saved) saved.textContent = state.supabase.has_service_key ? 'Service key saved in the Conductor local data store' : 'No service key saved';
  }

  function paint() {
    const root = byId('view-root');
    if (!root) return;
    const configured = !!(state.supabase.configured || (state.supabase.url && state.supabase.has_service_key));
    root.innerHTML = `<div class="view ms-view" id="mcp-sync-view" data-testid="mcp-sync-view">
      <header class="view-header ms-header">
        <div>
          <div class="ms-eyebrow">Connections &amp; data movement</div>
          <div class="view-title">MCP &amp; Sync Hub</div>
          <div class="view-sub">Manage Model Context Protocol servers and move operational data between Conductor and Supabase.</div>
        </div>
        <button class="btn-secondary" id="mcp-sync-refresh" data-testid="mcp-sync-refresh">${icon('refresh')} Refresh</button>
      </header>

      <section class="ms-section" aria-labelledby="mcp-section-title">
        <div class="ms-section-head">
          <div><h2 id="mcp-section-title">MCP servers</h2><p>Attach local tools over stdio or connect to remote HTTP servers.</p></div>
          <span class="ms-count" id="mcp-server-count">${state.servers.length}</span>
        </div>
        <div class="ms-server-list" id="mcp-server-list" data-testid="mcp-server-list">${serverList()}</div>

        <details class="ms-add" id="mcp-add-panel" open>
          <summary>${icon('add')} Add server <span>stdio or HTTP</span></summary>
          <form id="mcp-add-form" data-testid="mcp-add-form" autocomplete="off">
            <div class="ms-form-grid">
              <label class="field"><span>Name</span><input id="mcp-server-name" data-testid="mcp-server-name" name="name" required placeholder="Asana tools" /></label>
              <label class="field"><span>Transport</span><select id="mcp-server-transport" data-testid="mcp-server-transport" name="transport"><option value="stdio">stdio · local process</option><option value="http">HTTP · remote endpoint</option></select></label>
              <label class="field ms-stdio-field"><span>Command</span><input id="mcp-server-command" data-testid="mcp-server-command" name="command" placeholder="python" /></label>
              <label class="field ms-stdio-field"><span>Arguments</span><input id="mcp-server-args" data-testid="mcp-server-args" name="args" placeholder="backend/asana_mcp_stdio.py" /></label>
              <label class="field ms-http-field" hidden><span>Server URL</span><input id="mcp-server-url" data-testid="mcp-server-url" name="url" type="url" placeholder="https://mcp.example.com" /></label>
            </div>
            <div class="ms-form-foot">
              <p id="mcp-form-hint">Arguments are split on whitespace. Put credentials in the server environment, never in this form.</p>
              <button class="btn-primary" id="mcp-server-add" data-testid="mcp-server-add" type="submit">${icon('add')} Add server</button>
            </div>
          </form>
        </details>
      </section>

      <section class="ms-section" aria-labelledby="supabase-section-title">
        <div class="ms-section-head">
          <div><h2 id="supabase-section-title">Supabase connection</h2><p>Use a service-role key for server-side sync. Secrets are write-only in this interface.</p></div>
          <span class="ms-status ms-status-${configured ? 'ready' : 'idle'}" id="supabase-connection-status" data-testid="supabase-status"><i></i>${configured ? 'configured' : 'not configured'}</span>
        </div>
        <form class="ms-supabase-form" id="supabase-config-form" data-testid="supabase-config-form" autocomplete="off">
          <label class="field"><span>Project URL</span><input id="supabase-url" data-testid="supabase-url" type="url" required placeholder="https://project.supabase.co" value="${esc(state.supabase.url || '')}" /></label>
          <label class="field"><span>Service-role key</span><input id="supabase-service-key" data-testid="supabase-service-key" type="password" placeholder="${state.supabase.has_service_key ? 'Saved — enter to replace' : 'eyJ…'}" autocomplete="new-password" spellcheck="false" /></label>
          <label class="field"><span>Schema</span><input id="supabase-schema" data-testid="supabase-schema" value="${esc(state.supabase.schema || 'public')}" placeholder="public" pattern="[A-Za-z_][A-Za-z0-9_]*" /></label>
          <div class="ms-config-actions">
            <span id="supabase-saved-note">${state.supabase.has_service_key ? 'Service key saved in the Conductor local data store' : 'No service key saved'}</span>
            <button class="btn-secondary" id="supabase-test" data-testid="supabase-test" type="button">${icon('debug-start')} Test</button>
            <button class="btn-primary" id="supabase-save" data-testid="supabase-save" type="submit">${icon('save')} Save</button>
          </div>
        </form>
      </section>

      <section class="ms-section" aria-labelledby="sync-section-title">
        <div class="ms-section-head"><div><h2 id="sync-section-title">Sync operations</h2><p>Push local records to Supabase or pull the remote source of truth into Conductor.</p></div></div>
        <div class="ms-sync-grid">
          ${syncCard('products', 'package', 'Products', 'Catalog records, attributes, and compliance context')}
          ${syncCard('asana', 'checklist', 'Asana tasks', 'Mirrored tasks, ownership, projects, and completion state')}
        </div>
      </section>

      <section class="ms-section ms-runs" aria-labelledby="runs-section-title">
        <div class="ms-section-head"><div><h2 id="runs-section-title">Run output</h2><p>Latest sync activity and status messages.</p></div><button class="ms-text-btn" id="sync-runs-refresh">Refresh history</button></div>
        <div id="sync-run-output" data-testid="sync-run-output" class="ms-live-output" role="status" aria-live="polite">Ready.</div>
        <div id="sync-run-list" data-testid="sync-run-list"></div>
      </section>
    </div>`;
    wire();
    renderRuns();
  }

  function syncCard(dataset, glyph, title, description) {
    return `<article class="ms-sync-card" data-dataset="${dataset}">
      <div class="ms-sync-icon">${icon(glyph)}</div>
      <div class="ms-sync-copy"><strong>${title}</strong><span>${description}</span></div>
      <div class="ms-sync-actions">
        <button class="btn-secondary" id="sync-${dataset}-pull" data-testid="sync-${dataset}-pull" data-sync="${dataset}:pull">${icon('cloud-download')} Pull</button>
        <button class="btn-primary" id="sync-${dataset}-push" data-testid="sync-${dataset}-push" data-sync="${dataset}:push">${icon('cloud-upload')} Push</button>
      </div>
    </article>`;
  }

  async function load(options) {
    const quiet = options && options.quiet;
    if (!quiet) state.loading = true;
    const id = ++state.renderId;
    if (!quiet) paint();
    const results = await Promise.allSettled([
      api(ENDPOINTS.mcp),
      api(`${ENDPOINTS.supabase}/status`),
      api(`${ENDPOINTS.supabase}/runs`),
    ]);
    if (id !== state.renderId) return;
    if (results[0].status === 'fulfilled') state.servers = normalizeServers(results[0].value);
    if (results[1].status === 'fulfilled') state.supabase = results[1].value || {};
    if (results[2].status === 'fulfilled') state.runs = normalizeRuns(results[2].value);
    state.loading = false;
    paint();
    const failed = results.filter((r) => r.status === 'rejected');
    if (failed.length === results.length) toast('Could not load MCP & Sync Hub', 'err');
  }

  function setOutput(message, tone) {
    const output = byId('sync-run-output');
    if (!output) return;
    output.className = `ms-live-output${tone ? ` ms-output-${tone}` : ''}`;
    output.textContent = message;
  }

  function toggleTransport() {
    const transport = byId('mcp-server-transport').value;
    document.querySelectorAll('.ms-stdio-field').forEach((el) => { el.hidden = transport !== 'stdio'; });
    document.querySelectorAll('.ms-http-field').forEach((el) => { el.hidden = transport !== 'http'; });
    byId('mcp-server-command').required = transport === 'stdio';
    byId('mcp-server-url').required = transport === 'http';
  }

  async function addServer(event) {
    event.preventDefault();
    if (state.busy.has('add')) return;
    const transport = byId('mcp-server-transport').value;
    const payload = { name: byId('mcp-server-name').value.trim(), transport };
    if (transport === 'stdio') {
      payload.command = byId('mcp-server-command').value.trim();
      payload.args = byId('mcp-server-args').value.trim().split(/\s+/).filter(Boolean);
    } else payload.url = byId('mcp-server-url').value.trim();
    setBusy('add', true);
    const button = byId('mcp-server-add');
    button.disabled = true;
    button.innerHTML = `${icon('loading codicon-modifier-spin')} Adding…`;
    try {
      await api(ENDPOINTS.mcp, { method: 'POST', body: payload });
      event.currentTarget.reset();
      toggleTransport();
      toast(`${payload.name} added`, 'ok');
      await load({ quiet: true });
    } catch (error) {
      toast(error.message, 'err');
      button.disabled = false;
      button.innerHTML = `${icon('add')} Add server`;
    } finally { setBusy('add', false); }
  }

  async function serverAction(action, key, button) {
    const id = decodeURIComponent(key);
    const server = state.servers.find((row) => String(row.id) === id);
    if (!server || state.busy.has(`${action}:${id}`)) return;
    setBusy(`${action}:${id}`, true);
    button.disabled = true;
    try {
      if (action === 'test-server') {
        button.innerHTML = `${icon('loading codicon-modifier-spin')}<span>Testing</span>`;
        const result = await api(`${ENDPOINTS.mcp}/${encodeURIComponent(id)}/test`, { method: 'POST', body: {} });
        toast(result.message || `${server.name} connection passed`, result.ok === false ? 'err' : 'ok');
      } else {
        if (!window.confirm(`Remove “${server.name}”?`)) return;
        await api(`${ENDPOINTS.mcp}/${encodeURIComponent(id)}`, { method: 'DELETE' });
        toast(`${server.name} removed`, 'ok');
      }
      await load({ quiet: true });
    } catch (error) { toast(error.message, 'err'); }
    finally { setBusy(`${action}:${id}`, false); if (button.isConnected) button.disabled = false; }
  }

  function configPayload(includeEmptyKey) {
    const payload = {
      url: byId('supabase-url').value.trim().replace(/\/$/, ''),
      schema: byId('supabase-schema').value.trim() || 'public',
    };
    const serviceKey = byId('supabase-service-key').value.trim();
    if (serviceKey || includeEmptyKey) payload.service_key = serviceKey;
    return payload;
  }

  async function saveSupabase(event) {
    event.preventDefault();
    const button = byId('supabase-save');
    button.disabled = true;
    try {
      const payload = configPayload(false);
      const result = await api(`${ENDPOINTS.supabase}/config`, { method: 'POST', body: payload });
      byId('supabase-service-key').value = '';
      state.supabase = Object.assign({}, state.supabase, result || {}, { url: payload.url, schema: payload.schema });
      renderSupabaseStatus();
      toast('Supabase configuration saved', 'ok');
    } catch (error) { toast(error.message, 'err'); }
    finally { button.disabled = false; }
  }

  async function testSupabase() {
    const button = byId('supabase-test');
    button.disabled = true;
    button.innerHTML = `${icon('loading codicon-modifier-spin')} Testing…`;
    try {
      const result = await api(`${ENDPOINTS.supabase}/test`, { method: 'POST', body: configPayload(false) });
      toast(result.message || 'Supabase connection passed', result.ok === false ? 'err' : 'ok');
      state.supabase.status = result.ok === false ? 'error' : 'connected';
      renderSupabaseStatus();
    } catch (error) {
      state.supabase.status = 'error';
      renderSupabaseStatus();
      toast(error.message, 'err');
    } finally {
      button.disabled = false;
      button.innerHTML = `${icon('debug-start')} Test`;
      const secret = byId('supabase-service-key');
      if (secret) secret.value = '';
    }
  }

  async function runSync(dataset, direction, button) {
    const key = `${dataset}:${direction}`;
    if (state.busy.has(key)) return;
    setBusy(key, true);
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `${icon('loading codicon-modifier-spin')} ${direction === 'push' ? 'Pushing' : 'Pulling'}…`;
    setOutput(`${direction === 'push' ? 'Pushing' : 'Pulling'} ${dataset === 'asana' ? 'Asana tasks' : 'products'}…`, 'busy');
    try {
      const result = await api(`${ENDPOINTS.supabase}/sync/${dataset}/${direction}`, { method: 'POST', body: { schema: byId('supabase-schema').value.trim() || 'public' } });
      const count = result.count ?? result.rows ?? result.synced ?? result.records;
      const message = result.message || `${direction === 'push' ? 'Pushed' : 'Pulled'}${count != null ? ` ${count}` : ''} ${dataset === 'asana' ? 'Asana tasks' : 'products'}.`;
      setOutput(message, result.ok === false ? 'error' : 'ok');
      toast(message, result.ok === false ? 'err' : 'ok');
      state.runs.unshift(Object.assign({ dataset, direction, status: result.ok === false ? 'error' : 'success', created_at: new Date().toISOString() }, result));
      state.runs = state.runs.slice(0, 8);
      renderRuns();
    } catch (error) {
      setOutput(error.message, 'error');
      toast(error.message, 'err');
    } finally {
      setBusy(key, false);
      button.disabled = false;
      button.innerHTML = original;
    }
  }

  function wire() {
    byId('mcp-sync-refresh').addEventListener('click', () => load());
    byId('mcp-server-transport').addEventListener('change', toggleTransport);
    byId('mcp-add-form').addEventListener('submit', addServer);
    byId('mcp-server-list').addEventListener('click', (event) => {
      const button = event.target.closest('[data-action][data-server-key]');
      if (button) serverAction(button.dataset.action, button.dataset.serverKey, button);
    });
    byId('supabase-config-form').addEventListener('submit', saveSupabase);
    byId('supabase-test').addEventListener('click', testSupabase);
    document.querySelectorAll('[data-sync]').forEach((button) => button.addEventListener('click', () => {
      const [dataset, direction] = button.dataset.sync.split(':');
      runSync(dataset, direction, button);
    }));
    byId('sync-runs-refresh').addEventListener('click', async () => {
      try { state.runs = normalizeRuns(await api(`${ENDPOINTS.supabase}/runs`)); renderRuns(); }
      catch (error) { toast(error.message, 'err'); }
    });
    toggleTransport();
  }

  return {
    render: async function () {
      state.loading = true;
      paint();
      await load();
    },
  };
})();

try { VIEW_RENDERERS.mcpsync = () => window.ConductorMcpSync.render(); } catch (_) { /* app.js not loaded yet */ }

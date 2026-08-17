/* Conductor — command palette (ported from LAW's renderer palette).
 *
 * Ctrl/Cmd+K overlay with fuzzy search over two command sources:
 *   - built-ins: view switching, settings, sidebar/theme actions (registered
 *     in initBuiltins(), callable before the overlay opens)
 *   - plugin commands (runtime.js calls CommandRegistry.addPluginCommand)
 *
 * Fuzzy scoring (LAW's fuzzy.ts shape): consecutive-run bonus, word-start
 * bonus, earlier-position bonus; no match → score 0 → filtered out.
 */
(function () {
  const commands = new Map(); // id -> {id, title, group, handler}
  let pluginCount = 0;

  const CommandRegistry = {
    add(id, title, group, handler) {
      commands.set(id, { id, title, group, handler });
    },
    addPluginCommand(id, title, handler) {
      commands.set(id, { id, title, group: 'Plugins', handler });
    },
    list() { return [...commands.values()]; },
    get pluginCount() { return pluginCount; },
  };

  function initBuiltins() {
    const viewTitles = {
      chat: 'Chat', dashboard: 'Dashboard', processes: 'Process Discovery', automations: 'Automations',
      ai: 'AI Workflows', sops: 'SOPs & Runbooks', bernie: 'Flow Canvas (Bernie)', checks: 'Compliance Checks',
      products: 'Products', catalog: 'Catalog', agents: 'Agents', tasks: 'Tasks', regs: 'Regulations',
      integrations: 'Integrations', asana: 'Asana', events: 'Inbound Events', requests: 'HTTP Requests',
      hub: 'Tool Hub',
    };
    const known = new Set(['chat', 'dashboard', 'processes', 'automations', 'ai', 'sops', 'bernie', 'checks',
      'products', 'catalog', 'agents', 'tasks', 'regs', 'integrations', 'asana', 'events', 'requests', 'hub']);
    for (const [name, title] of Object.entries(viewTitles)) {
      if (!known.has(name)) continue;
      CommandRegistry.add(`view:${name}`, `Go to ${title}`, 'Views', () => showView(name));
    }
    CommandRegistry.add('side:full', 'Sidebar: full', 'Sidebar', () => setSidebarState('full'));
    CommandRegistry.add('side:rail', 'Sidebar: icon rail', 'Sidebar', () => setSidebarState('rail'));
    CommandRegistry.add('side:tucked', 'Sidebar: tucked away', 'Sidebar', () => setSidebarState('tucked'));
    CommandRegistry.add('settings:appearance', 'Settings → Appearance', 'Settings', () => openSettingsTab('appearance'));
    CommandRegistry.add('settings:chat', 'Settings → AI Chat', 'Settings', () => openSettingsTab('chat'));
    CommandRegistry.add('settings:asana', 'Settings → Asana Sync', 'Settings', () => openSettingsTab('asana'));
    CommandRegistry.add('settings:advanced', 'Settings → Advanced', 'Settings', () => openSettingsTab('advanced'));
    CommandRegistry.add('action:new-automation', 'New automation', 'Actions', () => showView('automations'));
    CommandRegistry.add('action:log-process', 'Log a process', 'Actions', () => showView('processes'));
    CommandRegistry.add('action:run-ai', 'Run an AI workflow', 'Actions', () => showView('ai'));
    CommandRegistry.add('action:clear-chat', 'Clear chat history', 'Actions', () => {
      state.chatHistory = [];
      const sc = document.getElementById('thread-scroll');
      if (sc) sc.innerHTML = '';
      welcome();
    });
    CommandRegistry.add('split:enter', 'Split view with chat (pane workspace)', 'Workspace', () => {
      if (window.ConductorSplit) window.ConductorSplit.enter(state.view && state.view !== 'chat' ? state.view : 'dashboard');
    });
    CommandRegistry.add('split:exit', 'End split (restore full view)', 'Workspace', () => {
      if (window.ConductorSplit) window.ConductorSplit.exit();
    });
    CommandRegistry.add('split:swap', 'Split: swap orientation', 'Workspace', () => {
      if (window.ConductorSplit) window.ConductorSplit.setDirection(window.ConductorSplit.state.direction === 'horizontal' ? 'vertical' : 'horizontal');
    });
  }

  function fuzzyScore(query, text) {
    if (!query) return 1;
    const q = query.toLowerCase(), t = text.toLowerCase();
    let qi = 0, score = 0, run = 0;
    for (let ti = 0; ti < t.length && qi < q.length; ti++) {
      if (t[ti] === q[qi]) {
        const wordStart = ti === 0 || /[\s\-_/:]/.test(t[ti - 1]);
        run = wordStart ? run + 2 : run + 1;
        score += run;
        qi++;
      } else {
        run = 0;
      }
    }
    if (qi < q.length) return 0;
    return score / (t.length + 1) + (t.startsWith(q) ? 2 : 0);
  }

  let overlay = null;

  function openPalette() {
    if (overlay) { closePalette(); return; }
    overlay = document.createElement('div');
    overlay.className = 'palette-overlay';
    overlay.innerHTML = `
      <div class="palette-box" role="dialog" aria-label="Command palette">
        <div class="palette-input-row">
          <span class="codicon codicon-search"></span>
          <input class="palette-input" placeholder="Type a command…" autocomplete="off" spellcheck="false" />
          <span class="kbd-hint">esc</span>
        </div>
        <div class="palette-list"></div>
        <div class="palette-empty" hidden>No commands match.</div>
      </div>`;
    document.body.appendChild(overlay);
    const input = overlay.querySelector('.palette-input');
    const list = overlay.querySelector('.palette-list');
    let selected = 0;
    let results = [];

    const render = () => {
      const q = input.value.trim();
      const all = CommandRegistry.list();
      results = all
        .map((c) => ({ ...c, score: fuzzyScore(q, c.title) }))
        .filter((c) => c.score > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, 40);
      selected = 0;
      if (!results.length) {
        list.innerHTML = '';
        overlay.querySelector('.palette-empty').hidden = false;
        return;
      }
      overlay.querySelector('.palette-empty').hidden = true;
      let html = '';
      let lastGroup = null;
      results.forEach((c, i) => {
        if (c.group !== lastGroup) {
          html += `<div class="palette-group">${c.group}</div>`;
          lastGroup = c.group;
        }
        html += `<div class="palette-item ${i === 0 ? 'selected' : ''}" data-i="${i}">
          <span>${c.title.replace(/[<>&]/g, '')}</span><span class="palette-kbd">↵</span></div>`;
      });
      list.innerHTML = html;
      list.querySelectorAll('.palette-item').forEach((item) => item.addEventListener('mousemove', () => {
        selected = Number(item.dataset.i);
        list.querySelectorAll('.palette-item').forEach((x) => x.classList.toggle('selected', x === item));
      }));
      list.querySelectorAll('.palette-item').forEach((item) => item.addEventListener('click', () => runCommand(results[Number(item.dataset.i)])));
    };

    const runCommand = (cmd) => {
      if (!cmd) return;
      closePalette();
      try { cmd.handler(); } catch (e) { console.error('[palette]', e); }
    };

    input.addEventListener('input', render);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); selected = Math.min(selected + 1, results.length - 1); highlight(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); selected = Math.max(selected - 1, 0); highlight(); }
      else if (e.key === 'Enter') { e.preventDefault(); runCommand(results[selected]); }
      else if (e.key === 'Escape') { closePalette(); }
    });
    const highlight = () => {
      list.querySelectorAll('.palette-item').forEach((x) => x.classList.toggle('selected', Number(x.dataset.i) === selected));
      const sel = list.querySelector('.palette-item.selected');
      if (sel) sel.scrollIntoView({ block: 'nearest' });
    };
    overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) closePalette(); });
    render();
    input.focus();
  }

  function closePalette() {
    if (overlay) { overlay.remove(); overlay = null; }
  }

  document.addEventListener('keydown', (e) => {
    // LAW's hotkey is Ctrl/Cmd+P (toggle); Ctrl+K kept as a second trigger.
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && (k === 'k' || k === 'p')) {
      e.preventDefault();
      openPalette();
    } else if (e.key === 'Escape' && overlay) {
      e.preventDefault();
      closePalette();
    }
  });

  initBuiltins();
  window.CommandRegistry = CommandRegistry;
})();

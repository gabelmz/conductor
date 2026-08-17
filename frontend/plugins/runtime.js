/* Conductor — plugin runtime (ported from LAW's renderer plugin runtime).
 *
 * LAW's PluginAPI surface, implemented for vanilla JS:
 *   registerPage(config)      — new view rendered into #view-root + sidebar nav
 *   registerCommand(config)   — palette command {id, title, handler}
 *   registerRailItem(config)  — sidebar button {id, icon, label, onClick}
 *   registerHubAction(config) — Tool Hub action {id, label, appliesTo, handler(cardId)}
 *   registerTheme(config)     — theme preset {id, tokens}
 *   logger.{info,warn,error}  — namespaced console logging
 *   store.{get,set,delete}    — per-plugin localStorage
 *   ipc.invoke(channel, ...)  — minimal bridge (guarded)
 *
 * Trust model (LAW Option B): declarative permissions, no runtime
 * enforcement; plugins are owner-authored. contextIsolation stays on — this
 * runtime only touches DOM + fetch, never node integration.
 */
(function () {
  const REGISTRIES = {
    pages: new Map(),      // id -> {id,title,icon,render}
    commands: new Map(),   // id -> {id,title,handler}
    railItems: new Map(),  // id -> {id,icon,label,onClick}
    hubActions: new Map(), // id -> {id,label,appliesTo,handler}
    themes: new Map(),     // id -> {id,tokens}
    canvasNodeTypes: new Map(), // type -> {type, component} (LAW canvasNodeTypeRegistry)
  };

  function createPluginAPI(pluginId) {
    return {
      registerPage(cfg) {
        if (!cfg || !cfg.id || typeof cfg.render !== 'function') return;
        REGISTRIES.pages.set(cfg.id, cfg);
        if (typeof VIEW_RENDERERS !== 'undefined') {
          VIEW_RENDERERS[cfg.id] = () => cfg.render(document.getElementById('view-root'));
        }
        addSidebarItem(cfg.id, cfg.title || cfg.id, cfg.icon || 'codicon-extensions');
      },
      registerCommand(cfg) {
        if (!cfg || !cfg.id || typeof cfg.handler !== 'function') return;
        REGISTRIES.commands.set(`${pluginId}:${cfg.id}`, {
          id: `${pluginId}:${cfg.id}`,
          title: cfg.title || cfg.id,
          handler: cfg.handler,
        });
        if (typeof CommandRegistry !== 'undefined') CommandRegistry.addPluginCommand(`${pluginId}:${cfg.id}`, cfg.title || cfg.id, cfg.handler);
      },
      registerRailItem(cfg) {
        if (!cfg || !cfg.id) return;
        REGISTRIES.railItems.set(cfg.id, cfg);
        addSidebarItem(cfg.id, cfg.label || cfg.id, cfg.icon || 'codicon-extensions', cfg.onClick);
      },
      registerHubAction(cfg) {
        if (!cfg || !cfg.id || typeof cfg.handler !== 'function') return;
        REGISTRIES.hubActions.set(cfg.id, {
          id: cfg.id,
          label: cfg.label || cfg.id,
          appliesTo: cfg.appliesTo || 'all',
          handler: cfg.handler,
        });
      },
      registerTheme(cfg) {
        if (!cfg || !cfg.id || !cfg.tokens) return;
        REGISTRIES.themes.set(cfg.id, cfg);
      },
      registerCanvasNodeType(cfg) {
        if (!cfg || !cfg.type) return;
        REGISTRIES.canvasNodeTypes.set(cfg.type, cfg);
        // Expose plugin node types to Bernie's palette (LAW canvasNodeTypeRegistry)
        if (window.BernieNodeTypes) window.BernieNodeTypes.register(cfg.type, cfg);
      },
      logger: {
        info: (m) => console.info(`[${pluginId}]`, m),
        warn: (m) => console.warn(`[${pluginId}]`, m),
        error: (m) => console.error(`[${pluginId}]`, m),
      },
      store: {
        get: (k) => { try { return JSON.parse(localStorage.getItem(`conductor.plugin.${pluginId}.${k}`)); } catch { return undefined; } },
        set: (k, v) => localStorage.setItem(`conductor.plugin.${pluginId}.${k}`, JSON.stringify(v)),
        delete: (k) => localStorage.removeItem(`conductor.plugin.${pluginId}.${k}`),
      },
      ipc: {
        async invoke(channel, ...args) {
          if (window.desktop && typeof window.desktop[channel] === 'function') return window.desktop[channel](...args);
          return null;
        },
      },
    };
  }

  function addSidebarItem(id, label, icon, onClick) {
    const scroll = document.querySelector('.sidebar-scroll');
    if (!scroll) return;
    if (document.getElementById(`nav-${id}`)) return;
    const btn = document.createElement('button');
    btn.className = 'sidebar-item';
    btn.id = `nav-${id}`;
    btn.dataset.view = id;
    btn.innerHTML = `<span class="codicon ${icon}"></span><span>${label.replace(/[<>&]/g, '')}</span>`;
    btn.addEventListener('click', () => (onClick ? onClick() : showView(id)));
    scroll.appendChild(btn);
  }

  async function loadPlugin(manifest) {
    const mod = await import(`/static/${manifest.main}?t=${Date.now()}`);
    if (mod && typeof mod.onload === 'function') {
      await mod.onload(createPluginAPI(manifest.id));
    }
  }

  async function initPluginRuntime() {
    try {
      const res = await fetch('/api/plugins');
      const data = await res.json();
      const plugins = data.plugins || [];
      for (const manifest of plugins) {
        if (manifest.enabled === false) continue;
        try {
          await loadPlugin(manifest);
        } catch (e) {
          console.error(`[plugin-runtime] failed to load ${manifest.id}:`, e);
        }
      }
      if (typeof document !== 'undefined') {
        document.dispatchEvent(new CustomEvent('conductor:plugins-loaded'));
      }
    } catch (e) {
      console.error('[plugin-runtime] init failed:', e);
    }
  }

  window.ConductorPlugins = {
    registries: REGISTRIES,
    init: initPluginRuntime,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPluginRuntime);
  } else {
    initPluginRuntime();
  }
})();

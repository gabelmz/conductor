/**
 * Conductor — data-driven sidebar.
 *
 * The sidebar is rendered from a preset + user config stored in
 * localStorage['conductor.sidebar.config']. Users can rework the nav from
 * Settings → Navigation: switch presets, hide/reorder/rename sections and
 * items, and add custom items.
 *
 * Loaded before app.js so window.ConductorSidebar is ready at boot.
 */
'use strict';

/* ------------------------------------------------------------------ registry
   Canonical nav-item registry: id -> {label, icon, view, count?}.
   `view` is the showView() renderer key. `count` is the data-count badge key.
   Custom (user-added) items live in the config under `custom`, not here. */
const NAV_ITEMS = {
  // Primary (Top Launchable Items)
  chat:            { label: 'Chat',               icon: 'codicon-comment-discussion', view: 'chat' },
  dashboard:       { label: 'Dashboard',          icon: 'codicon-dashboard',          view: 'dashboard' },
  keepa:           { label: 'Keepa',              icon: 'codicon-graph-line',         view: 'keepa' },
  asana:           { label: 'Asana',              icon: 'codicon-organization',       view: 'asana',    count: 'asana' },
  compliance:      { label: 'Compliance',         icon: 'codicon-shield',             view: 'checks',   count: 'checks' },
  models:          { label: 'Models',             icon: 'codicon-hubot',              view: 'models' },

  // Analytics & Data
  data:            { label: 'Data Management',    icon: 'codicon-database',           view: 'data' },
  datawrangler:    { label: 'DataWrangler',       icon: 'codicon-table',              view: 'datawrangler' },
  kpi:             { label: 'KPI Studio',         icon: 'codicon-graph-line',         view: 'kpi' },
  insights:        { label: 'Insights',           icon: 'codicon-graph',              view: 'insights' },
  reports:         { label: 'Reports',            icon: 'codicon-report',             view: 'reports' },
  import:          { label: 'Bulk Import',        icon: 'codicon-cloud-upload',       view: 'import' },
  sources:         { label: 'Local Sources',      icon: 'codicon-folder-opened',      view: 'sources' },
  attraudit:       { label: 'Attribute Audit',    icon: 'codicon-verified',           view: 'attraudit' },
  svl:             { label: 'SvL Comparison',     icon: 'codicon-arrow-swap',         view: 'svl' },
  brandcompare:    { label: 'Brand Compare',       icon: 'codicon-telescope',          view: 'brandcompare' },
  flatfile:        { label: 'Flat Files',         icon: 'codicon-table',              view: 'flatfile' },

  // Marketplace Platforms
  amazon:          { label: 'Amazon',            icon: 'codicon-globe',              view: 'amazon' },
  spapi:           { label: 'SP-API',            icon: 'codicon-git-merge',          view: 'productpipeline' },
  walmart:         { label: 'Walmart',            icon: 'codicon-globe',              view: 'walmart' },
  tiktok:          { label: 'TikTok',             icon: 'codicon-globe',              view: 'tiktok' },
  target:          { label: 'Target',             icon: 'codicon-globe',              view: 'target' },
  spp:             { label: 'SPP',                icon: 'codicon-globe',              view: 'spp' },
  coastal:         { label: 'Coastal',            icon: 'codicon-globe',              view: 'coastal' },
  agency:          { label: 'Agency',             icon: 'codicon-globe',              view: 'agency' },
  fba:             { label: 'FBA',                icon: 'codicon-package',            view: 'fba' },

  // Automation & AI
  workflows:       { label: 'Workflows',          icon: 'codicon-git-merge',          view: 'workflows' },
  automations:     { label: 'Automations',        icon: 'codicon-zap',                view: 'automations', count: 'automations' },
  workflowbuilder: { label: 'Workflow Builder',   icon: 'codicon-circuit-board',      view: 'automations' },
  processes:       { label: 'Process Discovery',  icon: 'codicon-lightbulb',          view: 'processes',   count: 'processes' },
  bernie:          { label: 'Flow Canvas',        icon: 'codicon-graph',              view: 'bernie' },
  asanarules:      { label: 'Asana Rules Canvas', icon: 'codicon-rules',              view: 'asanarules' },
  agents:          { label: 'Agents',             icon: 'codicon-robot',              view: 'agents',      count: 'agents' },
  aiworkflows:     { label: 'AI Workflows',       icon: 'codicon-sparkle',            view: 'ai',          count: 'ai' },
  agentbuilder:    { label: 'Agent Builder',      icon: 'codicon-rocket',             view: 'agentbuilder' },
  features:        { label: 'Feature Studio',     icon: 'codicon-beaker',             view: 'features' },

  // Operations
  products:        { label: 'Products',           icon: 'codicon-package',            view: 'products',    count: 'products' },
  brands:          { label: 'Brands',             icon: 'codicon-briefcase',          view: 'brands' },
  people:          { label: 'People',             icon: 'codicon-organization',       view: 'people' },
  sops:            { label: 'SOPs',               icon: 'codicon-book',               view: 'sops',        count: 'sops' },
  tasks:           { label: 'Action Queue',       icon: 'codicon-checklist',          view: 'tasks',       count: 'tasks' },
  listings:        { label: 'Listings',           icon: 'codicon-list-unordered',     view: 'listings' },
  variations:      { label: 'Variations',         icon: 'codicon-versions',           view: 'variation' },
  ingest:          { label: 'Catalog Ingest',     icon: 'codicon-cloud-upload',       view: 'ingest',      count: 'files' },
  regs:            { label: 'Regulations',        icon: 'codicon-law',                view: 'regs' },
  guidelines:      { label: 'Guidelines',         icon: 'codicon-symbol-property',    view: 'guidelines' },
  runbooks:        { label: 'Runbooks',           icon: 'codicon-notebook',           view: 'runbooks' },
  policies:        { label: 'Policies',           icon: 'codicon-library',            view: 'policies' },
  integrations:    { label: 'Integrations',       icon: 'codicon-plug',               view: 'integrations' },
  mcpsync:         { label: 'Sync Center',        icon: 'codicon-server-process',     view: 'mcpsync' },
  events:          { label: 'Events',             icon: 'codicon-radio-tower',        view: 'events',      count: 'events' },
  requests:        { label: 'HTTP',               icon: 'codicon-arrow-swap',         view: 'requests',    count: 'requests' },
  developer:       { label: 'Developer',          icon: 'codicon-wrench',             view: 'developer' },
  content:         { label: 'Content',            icon: 'codicon-notebook',           view: 'content' },
  case:            { label: 'Case',               icon: 'codicon-issue-opened',       view: 'case' },
  customerservice: { label: 'Customer Service',   icon: 'codicon-person',             view: 'customerservice' },
};

/* ------------------------------------------------------------- presets */
const SIDEBAR_PRESETS = {
  dayone: {
    label: 'Day One Hub',
    desc: 'Streamlined launchpad with Primary essentials, Analytics & Data, Marketplace Platforms, Automation & AI, and Operations.',
    sections: [
      { label: 'Primary',               items: ['chat', 'dashboard', 'keepa', 'asana', 'compliance', 'models'] },
      { label: 'Analytics & Data',      items: ['data', 'datawrangler', 'kpi', 'insights', 'reports', 'import', 'sources'] },
      { label: 'Marketplace Platforms', items: ['amazon', 'spapi', 'walmart', 'tiktok', 'target', 'fba'] },
      { label: 'Automation & AI',      items: ['workflows', 'automations', 'bernie', 'asanarules', 'agents', 'aiworkflows'] },
      { label: 'Operations',           items: ['products', 'brands', 'people', 'sops', 'tasks', 'integrations', 'mcpsync'] },
    ],
  },
  commerce: {
    label: 'Commerce Hub',
    desc: 'Complete overview organized into Primary, Analytics & Data, Marketplace Platforms, Automation & AI, and Operations.',
    sections: [
      { label: 'Primary',               items: ['chat', 'dashboard', 'keepa', 'asana', 'compliance', 'models'] },
      { label: 'Analytics & Data',      items: ['data', 'datawrangler', 'kpi', 'insights', 'reports', 'import', 'sources', 'attraudit', 'svl', 'brandcompare', 'flatfile'] },
      { label: 'Marketplace Platforms', items: ['amazon', 'spapi', 'walmart', 'tiktok', 'target', 'spp', 'coastal', 'agency', 'fba'] },
      { label: 'Automation & AI',      items: ['workflows', 'automations', 'workflowbuilder', 'processes', 'bernie', 'asanarules', 'agents', 'aiworkflows', 'agentbuilder', 'features'] },
      { label: 'Operations',           items: ['products', 'brands', 'people', 'sops', 'tasks', 'listings', 'variations', 'ingest', 'regs', 'guidelines', 'runbooks', 'policies', 'integrations', 'mcpsync', 'events', 'requests', 'developer', 'content', 'case', 'customerservice'] },
    ],
  },
  core: {
    label: 'Core (Business)',
    desc: 'Business-unit lens featuring Primary, Marketplace Platforms, and Operations.',
    sections: [
      { label: 'Primary',               items: ['chat', 'dashboard', 'models', 'keepa', 'asana'] },
      { label: 'Marketplace Platforms', items: ['amazon', 'spapi', 'walmart', 'tiktok', 'target', 'fba'] },
      { label: 'Operations',           items: ['products', 'brands', 'people', 'sops', 'compliance', 'tasks', 'mcpsync'] },
    ],
  },
  functional: {
    label: 'Functional',
    desc: 'Function-oriented lens — Analytics & Data, Automation & AI, Operations.',
    sections: [
      { label: 'Analytics & Data', items: ['data', 'datawrangler', 'kpi', 'insights', 'reports', 'import', 'sources', 'flatfile', 'svl', 'keepa'] },
      { label: 'Automation & AI', items: ['workflows', 'automations', 'workflowbuilder', 'processes', 'bernie', 'asanarules', 'agents', 'aiworkflows', 'agentbuilder', 'features'] },
      { label: 'Operations',      items: ['products', 'brands', 'people', 'sops', 'compliance', 'tasks', 'integrations', 'mcpsync', 'runbooks', 'policies'] },
    ],
  },
  classic: {
    label: 'BPA Classic',
    desc: 'The original Conductor nav layout (Primary, Operations, Automation & AI, Platform).',
    sections: [
      { label: 'Primary',         items: ['chat', 'dashboard', 'models', 'insights'] },
      { label: 'Operations',      items: ['compliance', 'products', 'ingest', 'tasks', 'regs', 'variations', 'sops'] },
      { label: 'Automation & AI', items: ['processes', 'automations', 'aiworkflows', 'agents', 'bernie', 'asanarules'] },
      { label: 'Platform',        items: ['integrations', 'mcpsync', 'asana', 'events', 'requests', 'developer'] },
    ],
  },
};
const SIDEBAR_PRESET_IDS = Object.keys(SIDEBAR_PRESETS);

/* --------------------------------------------------------------- config */
const SIDEBAR_KEY = 'conductor.sidebar.config';
const DEFAULT_PRESET = 'dayone';

function sidebarDefaultConfig() {
  return { preset: DEFAULT_PRESET, sections: JSON.parse(JSON.stringify(SIDEBAR_PRESETS[DEFAULT_PRESET].sections)), custom: {} };
}

function loadSidebarConfig() {
  try {
    const c = JSON.parse(localStorage.getItem(SIDEBAR_KEY) || 'null');
    if (c && Array.isArray(c.sections)) {
      const hasSync = c.sections.some((sec) => Array.isArray(sec.items) && sec.items.includes('mcpsync'));
      if (!hasSync && c.sections[0] && Array.isArray(c.sections[0].items)) {
        c.sections[0].items.push('mcpsync');
        localStorage.setItem(SIDEBAR_KEY, JSON.stringify(c));
      }
      // Migration: make sure the Asana Rules Canvas follows Flow Canvas.
      const hasRules = c.sections.some((sec) => Array.isArray(sec.items) && sec.items.includes('asanarules'));
      if (!hasRules) {
        let placed = false;
        for (const anchor of ['bernie', 'automations', 'processes', 'workflowbuilder']) {
          for (const sec of c.sections) {
            if (!Array.isArray(sec.items)) continue;
            const ai = sec.items.indexOf(anchor);
            if (ai >= 0) { sec.items.splice(ai + 1, 0, 'asanarules'); localStorage.setItem(SIDEBAR_KEY, JSON.stringify(c)); placed = true; break; }
          }
          if (placed) break;
        }
        if (!placed && c.sections[0] && Array.isArray(c.sections[0].items)) {
          c.sections[0].items.push('asanarules');
          localStorage.setItem(SIDEBAR_KEY, JSON.stringify(c));
        }
      }
      return c;
    }
  } catch { /* fall through */ }
  return sidebarDefaultConfig();
}

function saveSidebarConfig(cfg) {
  localStorage.setItem(SIDEBAR_KEY, JSON.stringify(cfg));
}

function resolveNavItem(id, cfg) {
  if (NAV_ITEMS[id]) return NAV_ITEMS[id];
  if (cfg.custom && cfg.custom[id]) return cfg.custom[id];
  return null;
}

/* -------------------------------------------------------------- render */
function sidebarItemHTML(id, item, cfg) {
  // icon is user-controlled on custom items — whitelist to safe class tokens.
  const icon = String(item.icon || 'codicon-circle').replace(/[^a-zA-Z0-9_-]/g, '');
  const view = item.view || ('url:' + (item.url || ''));
  const count = item.count ? `<span class="sidebar-count" data-count="${item.count}">0</span>` : '';
  return `<button class="sidebar-item" id="nav-${id}" data-view="${view}" data-nav-id="${id}">
      <span class="codicon ${icon}"></span>
      <span>${(item.label || id).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</span>
      ${count}
    </button>`;
}

function renderSidebar() {
  const scroll = document.getElementById('sidebar-scroll');
  if (!scroll) return;
  // Preserve plugin-injected nav items (they lack data-nav-id) across re-renders.
  const pluginItems = Array.from(scroll.querySelectorAll('.sidebar-item:not([data-nav-id])'));
  const cfg = loadSidebarConfig();
  const html = [];
  cfg.sections.forEach((sec, si) => {
    if (!sec || !Array.isArray(sec.items)) return;
    const items = sec.items.map((id) => {
      const item = resolveNavItem(id, cfg);
      return item ? sidebarItemHTML(id, item, cfg) : '';
    }).filter(Boolean);
    if (!items.length) return;
    const gap = si === 0 ? '' : ' sidebar-section-gap';
    html.push(`<div class="sidebar-section-label${gap}">${(sec.label || 'Section').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</div>`);
    html.push(items.join(''));
  });
  scroll.innerHTML = html.join('');
  pluginItems.forEach((el) => scroll.appendChild(el));
  // Restore active state for the current view (survives re-render).
  if (window.__sidebarActiveView) {
    scroll.querySelectorAll('.sidebar-item[data-view]').forEach((b) => b.classList.toggle('active', b.dataset.view === window.__sidebarActiveView));
  }
}

function applySidebarPreset(id) {
  const preset = SIDEBAR_PRESETS[id] || SIDEBAR_PRESETS[DEFAULT_PRESET];
  const cfg = { preset: id, sections: JSON.parse(JSON.stringify(preset.sections)), custom: {} };
  saveSidebarConfig(cfg);
  renderSidebar();
  return cfg;
}

/* ------------------------------------------------------- customization
   helper used by the Settings → Navigation tab. */
function sidebarAllItemIds() {
  return Object.keys(NAV_ITEMS);
}

function sidebarKnownViews() {
  return Array.from(new Set(Object.values(NAV_ITEMS).map((i) => i.view).filter((v) => !v.startsWith('url:'))));
}

window.ConductorSidebar = {
  NAV_ITEMS,
  SIDEBAR_PRESETS,
  SIDEBAR_PRESET_IDS,
  DEFAULT_PRESET,
  loadSidebarConfig,
  saveSidebarConfig,
  resolveNavItem,
  renderSidebar,
  applySidebarPreset,
  sidebarAllItemIds,
  sidebarKnownViews,
};

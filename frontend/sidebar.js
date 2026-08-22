/**
 * Conductor — data-driven sidebar.
 *
 * The sidebar is no longer hardcoded in index.html. It is rendered from a
 * preset + user config stored in localStorage['conductor.sidebar.config'].
 * Users can rework the nav any way they want from Settings → Navigation:
 * switch presets, hide/reorder/rename sections and items, and add custom items.
 *
 * Loaded before app.js so window.ConductorSidebar is ready at boot.
 */
'use strict';

/* ------------------------------------------------------------------ registry
   Canonical nav-item registry: id -> {label, icon, view, count?}.
   `view` is the showView() renderer key. `count` is the data-count badge key.
   Custom (user-added) items live in the config under `custom`, not here. */
const NAV_ITEMS = {
  // Core
  chat:            { label: 'Chat',               icon: 'codicon-comment-discussion', view: 'chat' },
  dashboard:       { label: 'Dashboard',          icon: 'codicon-dashboard',          view: 'dashboard' },
  workflows:       { label: 'Workflows',          icon: 'codicon-git-merge',          view: 'workflows' },
  data:            { label: 'Data Management',    icon: 'codicon-database',           view: 'data' },
  insights:        { label: 'Insights',           icon: 'codicon-graph',              view: 'insights' },
  import:          { label: 'Bulk Import',        icon: 'codicon-cloud-upload',       view: 'import' },
  sources:         { label: 'Local Sources',      icon: 'codicon-folder-opened',      view: 'sources' },
  // Departments
  compliance:      { label: 'Compliance',         icon: 'codicon-shield',             view: 'checks',  count: 'checks' },
  content:         { label: 'Content',            icon: 'codicon-notebook',           view: 'content' },
  case:            { label: 'Case',               icon: 'codicon-issue-opened',       view: 'case' },
  fba:             { label: 'FBA',                icon: 'codicon-package',            view: 'fba' },
  customerservice: { label: 'Customer Service',   icon: 'codicon-person',             view: 'customerservice' },
  // Operations
  products:        { label: 'Products',           icon: 'codicon-package',            view: 'products', count: 'products' },
  brands:          { label: 'Brands',             icon: 'codicon-briefcase',          view: 'brands' },
  people:          { label: 'People',             icon: 'codicon-organization',       view: 'people' },
  sops:            { label: 'SOPs',               icon: 'codicon-book',               view: 'sops',     count: 'sops' },
  // Platforms (marketplaces)
  amazon:          { label: 'Amazon',            icon: 'codicon-globe',              view: 'amazon' },
  spapi:           { label: 'SP-API',            icon: 'codicon-git-merge',          view: 'productpipeline' },
  walmart:         { label: 'Walmart',            icon: 'codicon-globe',              view: 'walmart' },
  tiktok:          { label: 'TikTok',             icon: 'codicon-globe',              view: 'tiktok' },
  target:          { label: 'Target',             icon: 'codicon-globe',              view: 'target' },
  spp:             { label: 'SPP',                icon: 'codicon-globe',              view: 'spp' },
  coastal:         { label: 'Coastal',            icon: 'codicon-globe',              view: 'coastal' },
  agency:          { label: 'Agency',             icon: 'codicon-globe',              view: 'agency' },
  // Catalog
  listings:        { label: 'Listings',           icon: 'codicon-list-unordered',     view: 'listings' },
  variations:      { label: 'Variations',         icon: 'codicon-versions',           view: 'variation' },
  ingest:          { label: 'Catalog Ingest',     icon: 'codicon-cloud-upload',       view: 'ingest',   count: 'files' },
  flatfile:        { label: 'Flat Files',         icon: 'codicon-table',              view: 'flatfile' },
  productpipeline: { label: 'Product Pipelines',  icon: 'codicon-git-merge',          view: 'productpipeline' },
  keepa:           { label: 'Keepa',              icon: 'codicon-graph-line',         view: 'keepa' },
  attraudit:       { label: 'Attribute Audit',    icon: 'codicon-verified',           view: 'attraudit' },
  svl:             { label: 'SvL Comparison',     icon: 'codicon-arrow-swap',         view: 'svl' },
  brandcompare:    { label: 'Brand Compare',       icon: 'codicon-telescope',          view: 'brandcompare' },
  regs:            { label: 'Regulations',        icon: 'codicon-law',                view: 'regs' },
  tasks:           { label: 'Action Queue',       icon: 'codicon-checklist',          view: 'tasks',    count: 'tasks' },
  reports:         { label: 'Reports',            icon: 'codicon-report',             view: 'reports' },
  guidelines:      { label: 'Guidelines',         icon: 'codicon-symbol-property',    view: 'guidelines' },
  // Automation
  automations:     { label: 'Automations',        icon: 'codicon-zap',                view: 'automations', count: 'automations' },
  workflowbuilder: { label: 'Workflow Builder',   icon: 'codicon-circuit-board',      view: 'automations' },
  processes:       { label: 'Process Discovery',  icon: 'codicon-lightbulb',          view: 'processes', count: 'processes' },
  bernie:          { label: 'Flow Canvas',        icon: 'codicon-graph',              view: 'bernie' },
  // AI
  aichat:          { label: 'AI Chat',            icon: 'codicon-comment-discussion', view: 'chat' },
  models:          { label: 'Models',             icon: 'codicon-hubot',              view: 'models' },
  agents:          { label: 'Agents',             icon: 'codicon-robot',              view: 'agents',   count: 'agents' },
  aiworkflows:     { label: 'AI Workflows',       icon: 'codicon-sparkle',            view: 'ai',       count: 'ai' },
  agentbuilder:    { label: 'Agent Builder',      icon: 'codicon-rocket',             view: 'agentbuilder' },
  features:        { label: 'Feature Studio',     icon: 'codicon-beaker',             view: 'features' },
  // Knowledge
  runbooks:        { label: 'Runbooks',           icon: 'codicon-notebook',           view: 'runbooks' },
  policies:        { label: 'Policies',           icon: 'codicon-library',            view: 'policies' },
  // Platform
  integrations:    { label: 'Integrations',       icon: 'codicon-plug',               view: 'integrations' },
  mcpsync:         { label: 'Sync Center',        icon: 'codicon-server-process',     view: 'mcpsync' },
  events:          { label: 'Events',             icon: 'codicon-radio-tower',        view: 'events',   count: 'events' },
  requests:        { label: 'HTTP',               icon: 'codicon-arrow-swap',         view: 'requests', count: 'requests' },
  developer:       { label: 'Developer',          icon: 'codicon-wrench',             view: 'developer' },
  asana:           { label: 'Asana',              icon: 'codicon-organization',       view: 'asana',    count: 'asana' },
};

/* ------------------------------------------------------------- presets */
const SIDEBAR_PRESETS = {
  commerce: {
    label: 'Commerce Hub',
    desc: 'Everything — Core, Departments, marketplaces, Catalog, Automation, AI, Knowledge, Platform.',
    sections: [
      { label: 'Core',        items: ['chat', 'dashboard', 'workflows', 'data', 'insights', 'import', 'sources'] },
      { label: 'Departments', items: ['compliance', 'content', 'case', 'fba', 'customerservice'] },
      { label: 'Operations',  items: ['brands', 'people'] },
      { label: 'Platforms',   items: ['amazon', 'spapi', 'walmart', 'tiktok', 'target', 'spp', 'coastal', 'agency'] },
      { label: 'Catalog',     items: ['products', 'listings', 'variations', 'ingest', 'flatfile', 'productpipeline', 'keepa', 'attraudit', 'svl', 'brandcompare', 'regs', 'tasks', 'reports', 'guidelines'] },
      { label: 'Automation',  items: ['automations', 'workflowbuilder', 'processes', 'bernie'] },
      { label: 'AI',          items: ['aichat', 'models', 'agents', 'aiworkflows', 'agentbuilder', 'features'] },
      { label: 'Knowledge',   items: ['sops', 'runbooks', 'policies'] },
      { label: 'Platform',    items: ['integrations', 'mcpsync', 'events', 'requests', 'developer', 'asana'] },
    ],
  },
  core: {
    label: 'Core (Business)',
    desc: 'Business-unit lens — Core, Departments, Operations, marketplaces.',
    sections: [
      { label: 'Core',        items: ['chat', 'models', 'dashboard', 'workflows', 'insights', 'import', 'sources', 'mcpsync'] },
      { label: 'Departments', items: ['compliance', 'content', 'listings', 'case', 'fba', 'customerservice'] },
      { label: 'Operations',  items: ['products', 'brands', 'people', 'sops'] },
      { label: 'Platforms',   items: ['amazon', 'spapi', 'walmart', 'tiktok', 'target', 'spp', 'coastal', 'agency'] },
    ],
  },
  functional: {
    label: 'Functional',
    desc: 'Function-oriented lens — Catalog, Automation, AI, Knowledge, Platform.',
    sections: [
      { label: 'Catalog',    items: ['products', 'listings', 'variations', 'ingest', 'flatfile', 'productpipeline', 'keepa', 'attraudit', 'svl', 'brandcompare', 'compliance', 'regs', 'tasks', 'insights'] },
      { label: 'Automation', items: ['automations', 'workflowbuilder', 'processes', 'bernie'] },
      { label: 'AI',         items: ['aichat', 'models', 'agents', 'agentbuilder', 'features'] },
      { label: 'Knowledge',  items: ['sops', 'runbooks', 'policies'] },
      { label: 'Platform',   items: ['integrations', 'mcpsync', 'events', 'requests', 'developer'] },
    ],
  },
  classic: {
    label: 'BPA Classic',
    desc: 'The original Conductor nav (Main, Operations, Automate, Integrations, System).',
    sections: [
      { label: 'Main',         items: ['chat', 'dashboard', 'models', 'insights'] },
      { label: 'Operations',   items: ['compliance', 'products', 'ingest', 'agents', 'tasks', 'regs', 'variations'] },
      { label: 'Automate',     items: ['processes', 'automations', 'aiworkflows', 'sops', 'bernie'] },
      { label: 'Integrations', items: ['integrations', 'mcpsync', 'asana', 'events'] },
      { label: 'System',       items: ['requests'] },
    ],
  },
};
const SIDEBAR_PRESET_IDS = Object.keys(SIDEBAR_PRESETS);

/* --------------------------------------------------------------- config */
const SIDEBAR_KEY = 'conductor.sidebar.config';
const DEFAULT_PRESET = 'core';

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

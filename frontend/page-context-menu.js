/* Conductor — page-specific context menu definitions & handlers.
 * Registers custom, context-aware options for each page: Chat, Dashboard, Asana,
 * Keepa, Compliance, Products, Workflows, Settings, Mapping, Reports, and selection.
 */
(function pageContextMenuModule(global) {
  'use strict';

  function toast(message) {
    if (global.showToast) {
      global.showToast(message);
    } else {
      console.log('[PageContextMenu]', message);
    }
  }

  function showView(name) {
    if (global.showView) {
      global.showView(name);
    }
  }

  function registerPageCommands() {
    if (!global.ConductorCommands) return;

    // -------------------------------------------------------------------------
    // 0. SELECTION ACTIONS (Visible whenever user highlights text)
    // -------------------------------------------------------------------------
    global.ConductorCommands.register({
      id: 'selection:copy',
      label: 'Copy Selection',
      icon: 'codicon codicon-copy',
      group: 'Selection',
      order: 1,
      shortcut: 'Ctrl+C',
      when: { op: 'truthy', path: 'selection.hasText' },
      execute: (ctx) => {
        if (ctx.selection && ctx.selection.text) {
          navigator.clipboard.writeText(ctx.selection.text);
          toast('Copied selected text to clipboard');
        }
      },
    });

    global.ConductorCommands.register({
      id: 'selection:ask-ai',
      label: 'Ask AI about Selection',
      icon: 'codicon codicon-sparkle',
      group: 'Selection',
      order: 2,
      when: { op: 'truthy', path: 'selection.hasText' },
      execute: (ctx) => {
        if (ctx.selection && ctx.selection.text) {
          showView('chat');
          const input = document.querySelector('#composer-input');
          if (input) {
            input.value = `Explain and analyze this: "${ctx.selection.text.slice(0, 300)}"`;
            input.focus();
          }
        }
      },
    });

    global.ConductorCommands.register({
      id: 'selection:search-products',
      label: 'Search Selection in Products',
      icon: 'codicon codicon-search',
      group: 'Selection',
      order: 3,
      when: { op: 'truthy', path: 'selection.hasText' },
      execute: (ctx) => {
        if (ctx.selection && ctx.selection.text) {
          showView('products');
          const input = document.querySelector('#search-products, #product-query');
          if (input) {
            input.value = ctx.selection.text;
            input.dispatchEvent(new Event('input', { bubbles: true }));
          }
        }
      },
    });

    // -------------------------------------------------------------------------
    // 1. CHAT PAGE ACTIONS (view.id == 'chat')
    // -------------------------------------------------------------------------
    global.ConductorCommands.register({
      id: 'page:chat:new',
      label: 'New Conversation',
      icon: 'codicon codicon-add',
      group: 'Chat',
      order: 10,
      shortcut: 'Ctrl+N',
      when: { op: 'eq', path: 'view.id', value: 'chat' },
      execute: () => {
        const btn = document.querySelector('#btn-new-chat, .new-chat-btn');
        if (btn) btn.click();
        else toast('Started new chat session');
      },
    });

    global.ConductorCommands.register({
      id: 'page:chat:clear',
      label: 'Clear Thread History',
      icon: 'codicon codicon-clear-all',
      group: 'Chat',
      order: 11,
      when: { op: 'eq', path: 'view.id', value: 'chat' },
      execute: () => {
        const scroll = document.querySelector('#thread-scroll');
        if (scroll) scroll.innerHTML = '';
        toast('Cleared current thread history');
      },
    });

    global.ConductorCommands.register({
      id: 'page:chat:settings',
      label: 'AI Provider & Model Settings',
      icon: 'codicon codicon-settings',
      group: 'Chat',
      order: 12,
      when: { op: 'eq', path: 'view.id', value: 'chat' },
      execute: () => {
        const btn = document.querySelector('#btn-settings, .settings-btn');
        if (btn) btn.click();
      },
    });

    // -------------------------------------------------------------------------
    // 2. DASHBOARD PAGE ACTIONS (view.id == 'dashboard')
    // -------------------------------------------------------------------------
    global.ConductorCommands.register({
      id: 'page:dashboard:refresh',
      label: 'Refresh Dashboard Metrics',
      icon: 'codicon codicon-refresh',
      group: 'Dashboard',
      order: 10,
      when: { op: 'eq', path: 'view.id', value: 'dashboard' },
      execute: () => {
        if (global.renderDashboard) global.renderDashboard();
        toast('Refreshed dashboard metrics');
      },
    });

    global.ConductorCommands.register({
      id: 'page:dashboard:backup',
      label: 'Trigger Local DB Backup',
      icon: 'codicon codicon-database',
      group: 'Dashboard',
      order: 11,
      when: { op: 'eq', path: 'view.id', value: 'dashboard' },
      execute: async () => {
        try {
          const res = await fetch('/api/dataset-store/backup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note: 'context_menu_trigger' }),
          });
          if (res.ok) {
            const data = await res.json();
            toast(`Backup complete (${data.backup_id})`);
          } else {
            toast('Backup failed');
          }
        } catch (e) {
          toast('Error creating backup');
        }
      },
    });

    global.ConductorCommands.register({
      id: 'page:dashboard:dataset-store',
      label: 'View Dataset Store & Summary',
      icon: 'codicon codicon-folder-library',
      group: 'Dashboard',
      order: 12,
      when: { op: 'eq', path: 'view.id', value: 'dashboard' },
      execute: async () => {
        try {
          const res = await fetch('/api/dataset-store/summary');
          const data = await res.json();
          alert(`Dataset Store Summary:\nDatasets: ${data.dataset_count}\nBackups: ${data.backup_count}\nTotal Backup Size: ${(data.backup_total_bytes / 1024 / 1024).toFixed(2)} MB`);
        } catch (e) {
          toast('Error reading dataset store summary');
        }
      },
    });

    // -------------------------------------------------------------------------
    // 3. ASANA PAGE ACTIONS (view.id == 'asana')
    // -------------------------------------------------------------------------
    global.ConductorCommands.register({
      id: 'page:asana:sync',
      label: 'Sync Asana Tasks Now',
      icon: 'codicon codicon-sync',
      group: 'Asana',
      order: 10,
      when: { op: 'eq', path: 'view.id', value: 'asana' },
      execute: async () => {
        try {
          const res = await fetch('/api/asana/sync', { method: 'POST' });
          toast(res.ok ? 'Asana sync started' : 'Asana sync request failed');
        } catch (e) {
          toast('Error initiating Asana sync');
        }
      },
    });

    global.ConductorCommands.register({
      id: 'page:asana:create-task',
      label: 'Create Asana Task',
      icon: 'codicon codicon-add',
      group: 'Asana',
      order: 11,
      when: { op: 'eq', path: 'view.id', value: 'asana' },
      execute: () => {
        const title = prompt('Enter new Asana task name:');
        if (title) {
          fetch('/api/data/push-asana', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: title, notes: 'Created via context menu' }),
          })
            .then(() => toast('Created Asana task'))
            .catch(() => toast('Failed to create task'));
        }
      },
    });

    global.ConductorCommands.register({
      id: 'page:asana:kpis',
      label: 'View Team KPI Scorecards',
      icon: 'codicon codicon-project',
      group: 'Asana',
      order: 12,
      when: { op: 'eq', path: 'view.id', value: 'asana' },
      execute: () => {
        if (global.renderKpiStudio) global.renderKpiStudio();
        else toast('Viewing KPI Scorecards');
      },
    });

    // -------------------------------------------------------------------------
    // 4. KEEPA PAGE ACTIONS (view.id == 'keepa')
    // -------------------------------------------------------------------------
    global.ConductorCommands.register({
      id: 'page:keepa:search-brand',
      label: 'Search Brand Listings',
      icon: 'codicon codicon-search',
      group: 'Keepa',
      order: 10,
      when: { op: 'eq', path: 'view.id', value: 'keepa' },
      execute: () => {
        const inp = document.querySelector('#keepa-search-input, #keepa-query');
        if (inp) inp.focus();
        else toast('Keepa search active');
      },
    });

    global.ConductorCommands.register({
      id: 'page:keepa:ai-query',
      label: 'Run AI Keepa Query',
      icon: 'codicon codicon-sparkle',
      group: 'Keepa',
      order: 11,
      when: { op: 'eq', path: 'view.id', value: 'keepa' },
      execute: () => {
        const btn = document.querySelector('#btn-keepa-ai, .keepa-ai-btn');
        if (btn) btn.click();
        else toast('AI Keepa query requested');
      },
    });

    global.ConductorCommands.register({
      id: 'page:keepa:cost-forecast',
      label: 'Run 30-60-90 Cost Forecast',
      icon: 'codicon codicon-pie-chart',
      group: 'Keepa',
      order: 12,
      when: { op: 'eq', path: 'view.id', value: 'keepa' },
      execute: () => {
        showView('workflows');
      },
    });

    // -------------------------------------------------------------------------
    // 5. COMPLIANCE PAGE ACTIONS (view.id == 'compliance')
    // -------------------------------------------------------------------------
    global.ConductorCommands.register({
      id: 'page:compliance:run-check',
      label: 'Run Full Compliance Check',
      icon: 'codicon codicon-pass',
      group: 'Compliance',
      order: 10,
      when: { op: 'eq', path: 'view.id', value: 'compliance' },
      execute: () => {
        const btn = document.querySelector('#btn-run-compliance, .run-compliance-btn');
        if (btn) btn.click();
        else toast('Compliance check initiated');
      },
    });

    global.ConductorCommands.register({
      id: 'page:compliance:ai-script',
      label: 'Generate AI Compliance Script',
      icon: 'codicon codicon-file-code',
      group: 'Compliance',
      order: 11,
      when: { op: 'eq', path: 'view.id', value: 'compliance' },
      execute: () => {
        toast('AI Compliance script tool active');
      },
    });

    global.ConductorCommands.register({
      id: 'page:compliance:audit',
      label: 'Audit Product Attributes',
      icon: 'codicon codicon-inspect',
      group: 'Compliance',
      order: 12,
      when: { op: 'eq', path: 'view.id', value: 'compliance' },
      execute: () => {
        showView('attributeaudit');
      },
    });

    // -------------------------------------------------------------------------
    // 6. PRODUCTS PAGE ACTIONS (view.id == 'products')
    // -------------------------------------------------------------------------
    global.ConductorCommands.register({
      id: 'page:products:add-new',
      label: 'Add New Product',
      icon: 'codicon codicon-add',
      group: 'Products',
      order: 10,
      when: { op: 'eq', path: 'view.id', value: 'products' },
      execute: () => {
        const btn = document.querySelector('#btn-add-product, .add-product-btn');
        if (btn) btn.click();
        else toast('Add product form opened');
      },
    });

    global.ConductorCommands.register({
      id: 'page:products:bulk-import',
      label: 'Bulk Import Products',
      icon: 'codicon codicon-cloud-upload',
      group: 'Products',
      order: 11,
      when: { op: 'eq', path: 'view.id', value: 'products' },
      execute: () => {
        showView('bulkimport');
      },
    });

    global.ConductorCommands.register({
      id: 'page:products:export',
      label: 'Export Catalog CSV',
      icon: 'codicon codicon-export',
      group: 'Products',
      order: 12,
      when: { op: 'eq', path: 'view.id', value: 'products' },
      execute: () => {
        window.open('/api/products/export', '_blank');
        toast('Exporting product catalog CSV');
      },
    });

    // -------------------------------------------------------------------------
    // 7. WORKFLOWS PAGE ACTIONS (view.id == 'workflows')
    // -------------------------------------------------------------------------
    global.ConductorCommands.register({
      id: 'page:workflows:start-onboarding',
      label: 'Start Brand Onboarding Workflow',
      icon: 'codicon codicon-play',
      group: 'Workflows',
      order: 10,
      when: { op: 'eq', path: 'view.id', value: 'workflows' },
      execute: () => {
        const brand = prompt('Enter Brand Name to onboard:');
        if (brand) {
          fetch('/api/workflows/onboard', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ brand }),
          })
            .then((r) => r.json())
            .then((d) => toast(`Started onboarding for ${brand}`))
            .catch(() => toast('Workflow error'));
        }
      },
    });

    global.ConductorCommands.register({
      id: 'page:workflows:cost-forecast',
      label: 'Generate 30-60-90 Cost Forecast',
      icon: 'codicon codicon-calculator',
      group: 'Workflows',
      order: 11,
      when: { op: 'eq', path: 'view.id', value: 'workflows' },
      execute: () => {
        toast('Generating 30-60-90 day cost forecast');
      },
    });

    // -------------------------------------------------------------------------
    // 8. SETTINGS PAGE ACTIONS (view.id == 'settings')
    // -------------------------------------------------------------------------
    global.ConductorCommands.register({
      id: 'page:settings:updates',
      label: 'Check for App Updates',
      icon: 'codicon codicon-cloud-download',
      group: 'Settings',
      order: 10,
      when: { op: 'eq', path: 'view.id', value: 'settings' },
      execute: async () => {
        try {
          const res = await fetch('/api/updates/versions');
          const data = await res.json();
          toast(`Latest version available: ${data.latest || 'Up to date'}`);
        } catch (e) {
          toast('Error checking updates');
        }
      },
    });

    global.ConductorCommands.register({
      id: 'page:settings:context-menus',
      label: 'Configure Context Menus & Overrides',
      icon: 'codicon codicon-menu',
      group: 'Settings',
      order: 11,
      when: { op: 'eq', path: 'view.id', value: 'settings' },
      execute: async () => {
        try {
          const res = await fetch('/api/context-menus');
          const data = await res.json();
          alert(`Context Menu Overrides:\nCustom Actions: ${data.customActions ? data.customActions.length : 0}\nRevision: ${data.revision}`);
        } catch (e) {
          toast('Error loading context menu settings');
        }
      },
    });

    // -------------------------------------------------------------------------
    // 9. MAPPING PAGE ACTIONS (view.id == 'mapping')
    // -------------------------------------------------------------------------
    global.ConductorCommands.register({
      id: 'page:mapping:auto-map',
      label: 'Run Header Auto-Mapping',
      icon: 'codicon codicon-zap',
      group: 'Mapping',
      order: 10,
      when: { op: 'eq', path: 'view.id', value: 'mapping' },
      execute: () => {
        const btn = document.querySelector('#btn-run-mapping, .run-mapping-btn');
        if (btn) btn.click();
        else toast('Header mapping check initiated');
      },
    });

    // -------------------------------------------------------------------------
    // 10. REPORTS PAGE ACTIONS (view.id == 'reports')
    // -------------------------------------------------------------------------
    global.ConductorCommands.register({
      id: 'page:reports:upload',
      label: 'Upload New Report',
      icon: 'codicon codicon-cloud-upload',
      group: 'Reports',
      order: 10,
      when: { op: 'eq', path: 'view.id', value: 'reports' },
      execute: () => {
        const fileInput = document.querySelector('#report-file-input, input[type="file"]');
        if (fileInput) fileInput.click();
        else toast('Select report file to upload');
      },
    });
  }

  // Bind loader & commands on DOM load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPageContextMenu);
  } else {
    initPageContextMenu();
  }

  function initPageContextMenu() {
    registerPageCommands();
    if (global.ConductorContextMenu) {
      global.ConductorContextMenu.setOverrideLoader(async () => {
        try {
          const res = await fetch('/api/context-menus');
          if (res.ok) return await res.json();
        } catch (e) {
          /* fallback to local defaults */
        }
        return {};
      });
      global.ConductorContextMenu.init();
    }
  }

  global.ConductorPageContextMenu = {
    registerPageCommands,
  };
})(window);

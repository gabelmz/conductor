/* Conductor — global context-menu runtime.
 * Renders registered commands with text nodes only; it never evaluates page data.
 */
(function contextMenuModule(global) {
  'use strict';

  const MENU_CLASS = 'conductor-context-menu';
  const editableSelector = 'input, textarea, select, [contenteditable]:not([contenteditable="false"])';
  const overrideFields = new Set(['hidden', 'label', 'order', 'shortcut']);
  let menu = null;
  let current = null;
  let overrideLoader = null;
  let overrides = Object.freeze(Object.create(null));
  let typeahead = '';
  let typeaheadTimer = 0;
  let removeRegistrySubscription = null;

  function safeString(value, maxLength) {
    if (value === undefined || value === null) return '';
    return String(value).slice(0, maxLength || 500);
  }

  function dataKey(attributeName) {
    return attributeName.slice('data-context-'.length).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
  }

  function scalar(value) {
    if (value === 'true') return true;
    if (value === 'false') return false;
    if (value === 'null') return null;
    if (/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value) && value.length < 18) return Number(value);
    return safeString(value);
  }

  function explicitTarget(element) {
    const host = element && element.closest
      ? element.closest('[data-context], [data-context-type], [data-context-kind], [data-context-menu]')
      : null;
    if (!host) return null;
    const target = Object.create(null);
    Array.from(host.attributes).forEach((attribute) => {
      if (!attribute.name.startsWith('data-context-')) return;
      const key = dataKey(attribute.name);
      if (/^[A-Za-z][A-Za-z0-9]*$/.test(key)) target[key] = scalar(attribute.value);
    });
    if (host.hasAttribute('data-context')) target.kind = scalar(host.getAttribute('data-context'));
    if (!target.kind && target.type) target.kind = target.type;
    target.explicit = true;
    target.element = host;
    return target;
  }

  function fallbackTarget(element) {
    const target = Object.create(null);
    const anchor = element && element.closest ? element.closest('a[href]') : null;
    const row = element && element.closest ? element.closest('tr, [role="row"]') : null;
    const button = element && element.closest ? element.closest('button, [role="button"]') : null;
    const card = element && element.closest ? element.closest('[data-id], .card') : null;
    const nav = element && element.closest ? element.closest('[data-view], nav, .sidebar-item') : null;

    if (anchor) {
      target.kind = 'link';
      target.href = anchor.href;
      target.label = safeString(anchor.textContent.trim(), 300);
      target.element = anchor;
    } else if (row) {
      target.kind = 'row';
      target.id = row.getAttribute('data-id') || row.getAttribute('data-row-id') || '';
      target.element = row;
    } else if (button) {
      target.kind = 'button';
      target.id = button.id || '';
      target.label = safeString(button.getAttribute('aria-label') || button.textContent.trim(), 300);
      target.element = button;
    } else if (nav) {
      target.kind = 'navigation';
      target.view = nav.getAttribute('data-view') || '';
      target.element = nav;
    } else if (card) {
      target.kind = 'card';
      target.id = card.getAttribute('data-id') || '';
      target.element = card;
    } else {
      target.kind = 'app';
      target.element = element || document.body;
    }
    target.explicit = false;
    return target;
  }

  function resolveTarget(element) {
    const target = explicitTarget(element) || fallbackTarget(element);
    const commandSource = target.commands || target.menu;
    if (typeof commandSource === 'string') {
      target.commandIds = Object.freeze(commandSource.split(',').map((id) => id.trim()).filter(Boolean));
    }
    return target;
  }

  function isNativeMenuTarget(element) {
    if (!element || !element.closest) return false;
    const editable = element.closest(editableSelector);
    if (editable) return true;
    const fileControl = element.closest('input[type="file"]');
    return Boolean(fileControl);
  }

  function buildContext(element, trigger, event) {
    const target = resolveTarget(element);
    const selectedText = global.getSelection ? safeString(global.getSelection().toString(), 10000) : '';
    const context = Object.create(null);
    context.app = Object.freeze({ name: 'Conductor' });
    context.surface = Object.freeze({ kind: target.kind || 'app' });
    context.target = target;
    context.selection = Object.freeze({ text: selectedText, hasText: Boolean(selectedText) });
    context.event = Object.freeze({ trigger, pointerType: event && event.pointerType ? event.pointerType : '' });
    context.view = Object.freeze({ id: document.body && document.body.dataset ? document.body.dataset.view || '' : '' });
    return context;
  }

  function normalizeOverrides(value) {
    const clean = Object.create(null);
    if (!value || typeof value !== 'object' || Array.isArray(value)) return Object.freeze(clean);
    Object.keys(value).forEach((id) => {
      if (!global.ConductorCommands || !global.ConductorCommands.isValidId(id)) return;
      const source = value[id];
      if (!source || typeof source !== 'object' || Array.isArray(source)) return;
      const entry = Object.create(null);
      Object.keys(source).forEach((key) => {
        if (!overrideFields.has(key)) return;
        if (key === 'hidden') entry.hidden = source.hidden === true;
        else if (key === 'order' && Number.isFinite(Number(source.order))) entry.order = Number(source.order);
        else if (key === 'label') entry.label = safeString(source.label, 160);
        else if (key === 'shortcut') entry.shortcut = safeString(source.shortcut, 80);
      });
      clean[id] = Object.freeze(entry);
    });
    return Object.freeze(clean);
  }

  function setOverrides(value) {
    overrides = normalizeOverrides(value);
    if (menu && current) rerenderCurrent();
    document.dispatchEvent(new CustomEvent('conductor:context-menu-overrides', { detail: { overrides } }));
    return overrides;
  }

  async function loadOverrides(loader) {
    if (loader !== undefined) overrideLoader = loader;
    if (!overrideLoader) return overrides;
    try {
      const value = typeof overrideLoader === 'function' ? await overrideLoader() : overrideLoader;
      return setOverrides(value);
    } catch (error) {
      document.dispatchEvent(new CustomEvent('conductor:context-menu-overrides-error', { detail: { error } }));
      console.error('[context-menu] failed to load overrides', error);
      return overrides;
    }
  }

  function commandsFor(context) {
    if (!global.ConductorCommands) return [];
    let entries = global.ConductorCommands.list(context);
    if (context.target.commandIds && context.target.commandIds.length) {
      const allowed = new Set(context.target.commandIds);
      entries = entries.filter((command) => allowed.has(command.id));
    }
    return entries
      .map((command, index) => {
        const overlay = overrides[command.id] || Object.create(null);
        if (overlay.hidden) return null;
        return Object.assign({}, command, {
          label: overlay.label || command.label,
          shortcut: overlay.shortcut !== undefined ? overlay.shortcut : command.shortcut,
          order: overlay.order !== undefined ? overlay.order : command.order,
          originalIndex: index,
        });
      })
      .filter(Boolean)
      .sort((left, right) => left.order - right.order || left.originalIndex - right.originalIndex);
  }

  function iconClasses(icon) {
    return safeString(icon, 100).split(/\s+/).filter((token) => /^[-_a-zA-Z0-9]+$/.test(token));
  }

  function makeItem(command, index) {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'conductor-context-menu-item';
    item.setAttribute('role', 'menuitem');
    item.setAttribute('tabindex', '-1');
    item.dataset.commandId = command.id;
    item.dataset.menuIndex = String(index);
    if (!command.enabled) {
      item.disabled = true;
      item.setAttribute('aria-disabled', 'true');
    }
    if (command.destructive) item.classList.add('is-destructive');

    const icon = document.createElement('span');
    icon.className = 'conductor-context-menu-icon';
    icon.setAttribute('aria-hidden', 'true');
    iconClasses(command.icon).forEach((token) => icon.classList.add(token));
    const label = document.createElement('span');
    label.className = 'conductor-context-menu-label';
    label.textContent = command.label;
    const shortcut = document.createElement('span');
    shortcut.className = 'conductor-context-menu-shortcut';
    shortcut.setAttribute('aria-hidden', 'true');
    shortcut.textContent = command.shortcut || '';
    item.append(icon, label, shortcut);
    return item;
  }

  function menuItems(enabledOnly) {
    if (!menu) return [];
    const items = Array.from(menu.querySelectorAll('[role="menuitem"]'));
    return enabledOnly ? items.filter((item) => !item.disabled && item.getAttribute('aria-disabled') !== 'true') : items;
  }

  function focusItem(item) {
    if (!item) return;
    menuItems(false).forEach((candidate) => candidate.setAttribute('tabindex', candidate === item ? '0' : '-1'));
    item.focus({ preventScroll: true });
  }

  function focusAt(position) {
    const items = menuItems(true);
    if (!items.length) return;
    const activeIndex = items.indexOf(document.activeElement);
    let next = position;
    if (position === 'next') next = activeIndex < 0 ? 0 : (activeIndex + 1) % items.length;
    if (position === 'previous') next = activeIndex < 0 ? items.length - 1 : (activeIndex - 1 + items.length) % items.length;
    if (position === 'first') next = 0;
    if (position === 'last') next = items.length - 1;
    focusItem(items[next]);
  }

  function renderMenu(entries) {
    menu = document.createElement('div');
    menu.className = MENU_CLASS;
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', 'Context menu');
    menu.setAttribute('tabindex', '-1');
    if (global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      menu.classList.add('reduced-motion');
    }
    let previousGroup = null;
    entries.forEach((command, index) => {
      if (previousGroup !== null && command.group !== previousGroup) {
        const separator = document.createElement('div');
        separator.className = 'conductor-context-menu-separator';
        separator.setAttribute('role', 'separator');
        menu.appendChild(separator);
      }
      menu.appendChild(makeItem(command, index));
      previousGroup = command.group;
    });
    menu.addEventListener('click', onMenuClick);
    menu.addEventListener('pointermove', onMenuPointerMove);
    menu.addEventListener('keydown', onMenuKeyDown);
    document.body.appendChild(menu);
    requestAnimationFrame(() => { if (menu) menu.classList.add('is-open'); });
    return menu;
  }

  function placeMenu(x, y) {
    if (!menu) return;
    const margin = 6;
    const viewportWidth = Math.max(document.documentElement.clientWidth, global.innerWidth || 0);
    const viewportHeight = Math.max(document.documentElement.clientHeight, global.innerHeight || 0);
    menu.style.left = '0px';
    menu.style.top = '0px';
    menu.style.maxHeight = `${Math.max(80, viewportHeight - margin * 2)}px`;
    const rect = menu.getBoundingClientRect();
    const left = Math.max(margin, Math.min(x, viewportWidth - rect.width - margin));
    const top = Math.max(margin, Math.min(y, viewportHeight - rect.height - margin));
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
  }

  function installDismissListeners() {
    document.addEventListener('pointerdown', onOutsidePointer, true);
    global.addEventListener('blur', onWindowBlur);
    global.addEventListener('resize', close);
    global.addEventListener('scroll', close, true);
  }

  function removeDismissListeners() {
    document.removeEventListener('pointerdown', onOutsidePointer, true);
    global.removeEventListener('blur', onWindowBlur);
    global.removeEventListener('resize', close);
    global.removeEventListener('scroll', close, true);
  }

  function onOutsidePointer(event) {
    if (menu && !menu.contains(event.target)) close();
  }

  function onWindowBlur() { close(); }

  function open(options) {
    const opts = options || Object.create(null);
    const invoker = opts.invoker || opts.target || document.activeElement || document.body;
    if (isNativeMenuTarget(opts.target || invoker)) return false;
    close({ restoreFocus: false });
    const context = opts.context || buildContext(opts.target || invoker, opts.trigger || 'programmatic', opts.event);
    const entries = commandsFor(context);
    if (!entries.length) return false;
    current = { context, invoker, x: Number(opts.x) || 0, y: Number(opts.y) || 0, trigger: opts.trigger || 'programmatic' };
    renderMenu(entries);
    placeMenu(current.x, current.y);
    installDismissListeners();
    if (current.trigger !== 'pointer') focusAt('first');
    document.dispatchEvent(new CustomEvent('conductor:context-menu-opened', { detail: { context, commandIds: entries.map((item) => item.id) } }));
    return true;
  }

  function close(options) {
    if (!menu) return false;
    const opts = options || Object.create(null);
    const restoreFocus = opts.restoreFocus !== false;
    const oldMenu = menu;
    const oldCurrent = current;
    menu = null;
    current = null;
    clearTimeout(typeaheadTimer);
    typeahead = '';
    removeDismissListeners();
    oldMenu.remove();
    if (restoreFocus && oldCurrent && oldCurrent.invoker && oldCurrent.invoker.isConnected && typeof oldCurrent.invoker.focus === 'function') {
      oldCurrent.invoker.focus({ preventScroll: true });
    }
    document.dispatchEvent(new CustomEvent('conductor:context-menu-closed'));
    return true;
  }

  async function activate(item) {
    if (!item || item.disabled || !current || !global.ConductorCommands) return;
    const id = item.dataset.commandId;
    const context = current.context;
    const invoker = current.invoker;
    close();
    try {
      await global.ConductorCommands.execute(id, context, { source: 'context-menu', invoker });
    } catch (error) {
      console.error(`[context-menu] command "${id}" failed`, error);
      document.dispatchEvent(new CustomEvent('conductor:context-menu-command-error', { detail: { id, error } }));
    }
  }

  function onMenuClick(event) {
    const item = event.target.closest('[role="menuitem"]');
    if (item && menu.contains(item)) activate(item);
  }

  function onMenuPointerMove(event) {
    const item = event.target.closest('[role="menuitem"]');
    if (item && menu.contains(item) && !item.disabled) focusItem(item);
  }

  function onMenuKeyDown(event) {
    if (event.key === 'ArrowDown') { event.preventDefault(); focusAt('next'); return; }
    if (event.key === 'ArrowUp') { event.preventDefault(); focusAt('previous'); return; }
    if (event.key === 'Home') { event.preventDefault(); focusAt('first'); return; }
    if (event.key === 'End') { event.preventDefault(); focusAt('last'); return; }
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(document.activeElement); return; }
    if (event.key === 'Escape') { event.preventDefault(); close(); return; }
    if (event.key === 'Tab') { close({ restoreFocus: false }); return; }
    if (event.ctrlKey || event.metaKey || event.altKey || event.key.length !== 1 || /\s/.test(event.key)) return;

    typeahead += event.key.toLocaleLowerCase();
    clearTimeout(typeaheadTimer);
    typeaheadTimer = global.setTimeout(() => { typeahead = ''; }, 650);
    const items = menuItems(true);
    const start = Math.max(0, items.indexOf(document.activeElement));
    for (let offset = 1; offset <= items.length; offset += 1) {
      const candidate = items[(start + offset) % items.length];
      const label = candidate.querySelector('.conductor-context-menu-label');
      if (label && label.textContent.trim().toLocaleLowerCase().startsWith(typeahead)) {
        event.preventDefault();
        focusItem(candidate);
        break;
      }
    }
  }

  function onContextMenu(event) {
    if (event.defaultPrevented || isNativeMenuTarget(event.target)) return;
    const context = buildContext(event.target, 'pointer', event);
    const entries = commandsFor(context);
    if (!entries.length) return;
    event.preventDefault();
    open({ target: event.target, invoker: document.activeElement || event.target, x: event.clientX, y: event.clientY, trigger: 'pointer', event, context });
  }

  function onGlobalKeyDown(event) {
    const isMenuKey = event.key === 'ContextMenu' || event.key === 'Apps' || (event.shiftKey && event.key === 'F10');
    if (!isMenuKey || event.defaultPrevented) return;
    const target = document.activeElement || event.target || document.body;
    if (isNativeMenuTarget(target)) return;
    const context = buildContext(target, 'keyboard', event);
    if (!commandsFor(context).length) return;
    const rect = target.getBoundingClientRect ? target.getBoundingClientRect() : { left: 8, bottom: 8 };
    event.preventDefault();
    open({ target, invoker: target, x: rect.left, y: rect.bottom, trigger: 'keyboard', event, context });
  }

  function rerenderCurrent() {
    if (!current) return;
    const snapshot = current;
    const entries = commandsFor(snapshot.context);
    close({ restoreFocus: false });
    if (entries.length) open(Object.assign({}, snapshot, { target: snapshot.invoker }));
  }

  function init(options) {
    const opts = options || Object.create(null);
    if (opts.overrideLoader !== undefined) {
      overrideLoader = opts.overrideLoader;
      loadOverrides();
    }
    document.removeEventListener('contextmenu', onContextMenu);
    document.removeEventListener('keydown', onGlobalKeyDown);
    document.addEventListener('contextmenu', onContextMenu);
    document.addEventListener('keydown', onGlobalKeyDown);
    if (!removeRegistrySubscription && global.ConductorCommands) {
      removeRegistrySubscription = global.ConductorCommands.subscribe((change) => {
        if (menu && ['registered', 'updated', 'unregistered', 'owner-unregistered'].includes(change.type)) rerenderCurrent();
      });
    }
    return api;
  }

  function destroy() {
    close({ restoreFocus: false });
    document.removeEventListener('contextmenu', onContextMenu);
    document.removeEventListener('keydown', onGlobalKeyDown);
    if (removeRegistrySubscription) removeRegistrySubscription();
    removeRegistrySubscription = null;
  }

  const api = Object.freeze({
    init,
    destroy,
    open,
    close,
    isOpen: () => Boolean(menu),
    resolveTarget,
    buildContext,
    setOverrides,
    loadOverrides,
    setOverrideLoader(loader) { overrideLoader = loader; },
    getOverrides: () => overrides,
  });

  global.ConductorContextMenu = api;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => init(), { once: true });
  else init();
})(window);

/* Conductor — shared, context-aware command registry.
 * Plain browser JavaScript: no eval, Function constructors, or HTML rendering.
 */
(function commandRegistryModule(global) {
  'use strict';

  const commands = new Map();
  const subscribers = new Set();
  const blockedSegments = new Set(['__proto__', 'prototype', 'constructor']);
  const allowedRoots = new Set([
    'app', 'capabilities', 'data', 'event', 'permissions', 'plugin', 'selection',
    'source', 'surface', 'target', 'user', 'view',
  ]);
  const idPattern = /^[a-z][a-z0-9_-]*(?:[.:/][a-z][a-z0-9_-]*)+$/i;
  let sequence = 0;

  function assertId(id) {
    if (typeof id !== 'string' || !idPattern.test(id)) {
      throw new TypeError('Command id must be a namespaced id (for example, "core:copy").');
    }
    return id;
  }

  function safePath(path) {
    const parts = Array.isArray(path) ? path.slice() : String(path || '').split('.');
    if (!parts.length || !allowedRoots.has(parts[0])) return null;
    if (parts.some((part) => !/^[A-Za-z0-9_-]+$/.test(part) || blockedSegments.has(part))) return null;
    return parts;
  }

  function resolvePath(context, path, fallback) {
    const parts = safePath(path);
    if (!parts) return fallback;
    let value = context;
    for (const part of parts) {
      if (value === null || (typeof value !== 'object' && typeof value !== 'function')) return fallback;
      if (!Object.prototype.hasOwnProperty.call(value, part)) return fallback;
      const descriptor = Object.getOwnPropertyDescriptor(value, part);
      // Do not invoke accessors supplied by a plugin or page.
      if (!descriptor || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) return fallback;
      value = descriptor.value;
    }
    return value;
  }

  function sameValue(left, right) {
    return left === right || (Number.isNaN(left) && Number.isNaN(right));
  }

  function evaluate(predicate, context) {
    if (predicate === undefined || predicate === null || predicate === true) return true;
    if (predicate === false || typeof predicate !== 'object' || Array.isArray(predicate)) return false;

    // Accept both {op:'all', args:[...]} and the concise {all:[...]} AST shape.
    const op = String(predicate.op || (predicate.all ? 'all' : predicate.any ? 'any' : predicate.not ? 'not' : '')).toLowerCase();
    if (op === 'all' || op === 'and') {
      const args = predicate.args || predicate.all;
      return Array.isArray(args) && args.every((item) => evaluate(item, context));
    }
    if (op === 'any' || op === 'or') {
      const args = predicate.args || predicate.any;
      return Array.isArray(args) && args.some((item) => evaluate(item, context));
    }
    if (op === 'not') return !evaluate(predicate.arg !== undefined ? predicate.arg : predicate.not, context);

    const value = resolvePath(context, predicate.path);
    if (op === 'exists') return value !== undefined && value !== null;
    if (op === 'truthy') return Boolean(value);
    if (op === 'falsy') return !value;
    if (op === 'eq' || op === 'equals') return sameValue(value, predicate.value);
    if (op === 'neq' || op === 'not-equals') return !sameValue(value, predicate.value);
    if (op === 'in') return Array.isArray(predicate.values) && predicate.values.some((item) => sameValue(value, item));
    if (op === 'not-in') return Array.isArray(predicate.values) && !predicate.values.some((item) => sameValue(value, item));
    if (op === 'includes') {
      return (Array.isArray(value) || typeof value === 'string') && value.includes(predicate.value);
    }
    if (op === 'matches') {
      // Deliberately support only literal membership-style matching, never user regular expressions.
      return Array.isArray(predicate.values) && predicate.values.some((item) => String(item) === String(value));
    }
    return false;
  }

  function predicateResult(predicate, context, defaultValue) {
    if (predicate === undefined || predicate === null) return defaultValue;
    try { return evaluate(predicate, context || Object.create(null)); } catch (_) { return false; }
  }

  function publicCommand(command, context) {
    const visible = predicateResult(command.visibleWhen !== undefined ? command.visibleWhen : command.when, context, true);
    const enabled = visible && predicateResult(command.enabledWhen, context, true);
    return Object.freeze({
      id: command.id,
      label: command.label,
      title: command.label,
      icon: command.icon,
      group: command.group,
      order: command.order,
      shortcut: command.shortcut,
      destructive: command.destructive,
      owner: command.owner,
      visible,
      enabled,
    });
  }

  function dispatch(type, detail) {
    const payload = Object.freeze(Object.assign({ type }, detail || {}));
    subscribers.forEach((subscriber) => {
      try { subscriber(payload); } catch (error) { console.error('[commands] subscriber failed', error); }
    });
    if (global.document && typeof global.CustomEvent === 'function') {
      global.document.dispatchEvent(new global.CustomEvent(`conductor:command-${type}`, { detail: payload }));
      global.document.dispatchEvent(new global.CustomEvent('conductor:commands-changed', { detail: payload }));
    }
  }

  function normalize(definition, options) {
    if (!definition || typeof definition !== 'object') throw new TypeError('A command definition is required.');
    const id = assertId(definition.id);
    const handler = definition.execute || definition.handler;
    if (typeof handler !== 'function') throw new TypeError(`Command "${id}" requires an execute function.`);
    const owner = String((options && options.owner) || definition.owner || 'core');
    if (!owner.trim()) throw new TypeError('Command owner cannot be empty.');
    return Object.freeze({
      id,
      label: String(definition.label || definition.title || id),
      icon: definition.icon ? String(definition.icon) : '',
      group: String(definition.group || 'General'),
      order: Number.isFinite(Number(definition.order)) ? Number(definition.order) : 0,
      shortcut: definition.shortcut ? String(definition.shortcut) : '',
      destructive: definition.destructive === true,
      when: definition.when,
      visibleWhen: definition.visibleWhen,
      enabledWhen: definition.enabledWhen,
      execute: handler,
      owner,
      sequence: ++sequence,
    });
  }

  function register(definition, options) {
    const command = normalize(definition, options);
    const existing = commands.get(command.id);
    if (existing && existing.owner !== command.owner && !(options && options.replace === true)) {
      throw new Error(`Command "${command.id}" is owned by "${existing.owner}".`);
    }
    commands.set(command.id, command);
    dispatch(existing ? 'updated' : 'registered', { command: publicCommand(command, Object.create(null)) });
    return function disposeCommand() { unregister(command.id, command.owner); };
  }

  function unregister(id, owner) {
    assertId(id);
    const command = commands.get(id);
    if (!command) return false;
    if (owner !== undefined && command.owner !== owner) return false;
    commands.delete(id);
    dispatch('unregistered', { id, owner: command.owner });
    return true;
  }

  function unregisterOwner(owner) {
    const removed = [];
    commands.forEach((command, id) => {
      if (command.owner === owner) {
        commands.delete(id);
        removed.push(id);
      }
    });
    if (removed.length) dispatch('owner-unregistered', { owner, ids: Object.freeze(removed.slice()) });
    return removed.length;
  }

  function get(id, context) {
    const command = commands.get(id);
    return command ? publicCommand(command, context || Object.create(null)) : undefined;
  }

  function list(context, options) {
    const includeHidden = options && options.includeHidden === true;
    return Array.from(commands.values())
      .map((command) => ({ command, public: publicCommand(command, context || Object.create(null)) }))
      .filter((entry) => includeHidden || entry.public.visible)
      .sort((left, right) => left.command.order - right.command.order || left.command.sequence - right.command.sequence)
      .map((entry) => entry.public);
  }

  async function execute(id, context, invocation) {
    const command = commands.get(assertId(id));
    if (!command) throw new Error(`Unknown command "${id}".`);
    const state = publicCommand(command, context || Object.create(null));
    if (!state.visible) throw new Error(`Command "${id}" is not visible in this context.`);
    if (!state.enabled) throw new Error(`Command "${id}" is disabled in this context.`);
    dispatch('executing', { id, owner: command.owner, context, invocation });
    try {
      const result = await command.execute(context || Object.create(null), invocation || Object.create(null));
      dispatch('executed', { id, owner: command.owner, context, result });
      return result;
    } catch (error) {
      dispatch('error', { id, owner: command.owner, context, error });
      throw error;
    }
  }

  function subscribe(subscriber) {
    if (typeof subscriber !== 'function') throw new TypeError('Subscriber must be a function.');
    subscribers.add(subscriber);
    return function unsubscribe() { subscribers.delete(subscriber); };
  }

  function registerPlugin(owner, definition) {
    if (typeof owner !== 'string' || !owner.trim()) throw new TypeError('Plugin owner is required.');
    return register(definition, { owner: `plugin:${owner}` });
  }

  global.ConductorCommands = Object.freeze({
    register,
    registerPlugin,
    unregister,
    unregisterOwner,
    get,
    list,
    execute,
    subscribe,
    evaluatePredicate: (predicate, context) => predicateResult(predicate, context, false),
    resolvePath: (path, context, fallback) => resolvePath(context, path, fallback),
    isValidId: (id) => typeof id === 'string' && idPattern.test(id),
  });
})(window);

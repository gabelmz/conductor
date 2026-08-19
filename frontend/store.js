/**
 * Conductor — centralized client data store.
 *
 * One canonical data set per datatype (products, checks, people, …). Every view
 * reads through `ConductorData.get(key)` instead of hitting the API itself, so a
 * mutation anywhere is immediately reflected on every page — no per-view copies
 * drifting out of sync.
 *
 *   ConductorData.get('products')      // cached-first (background refresh if stale)
 *   ConductorData.get('products', { force: true })   // force a fresh fetch
 *   ConductorData.invalidate('products')  // drop the cache after a mutation
 *
 * Uses globals provided by app.js (`window.api`) — loaded before app.js.
 */
'use strict';

window.ConductorStore = (function () {
  const cache = {};     // key -> { data, ts }
  const inflight = {};  // key -> Promise (dedupe concurrent fetches)
  const gen = {};       // key -> generation (guards against stale resurrection)

  function _set(key, data) { cache[key] = { data, ts: Date.now() }; }

  // Fetch + cache. Dedupes in-flight requests; a fetch started before an
  // invalidate() will NOT write its (now-stale) result back.
  async function refresh(key, fetchFn) {
    if (inflight[key]) return inflight[key];
    if (typeof fetchFn !== 'function') return peek(key);
    const myGen = gen[key] || 0;
    const p = Promise.resolve()
      .then(fetchFn)
      .then((data) => {
        if ((gen[key] || 0) === myGen) _set(key, data);
        return data;
      });
    inflight[key] = p;
    try { return await p; } finally { delete inflight[key]; }
  }

  // Cache-first read. If a fresh copy exists it is returned immediately and, when
  // it has aged past `maxAge`, a background refresh is kicked off (not awaited).
  async function get(key, fetchFn, opts = {}) {
    const { force = false, maxAge = 15000 } = opts;
    const hit = cache[key];
    if (hit && !force) {
      if (fetchFn && Date.now() - hit.ts > maxAge) refresh(key, fetchFn).catch(() => {});
      return hit.data;
    }
    return refresh(key, fetchFn);
  }

  function invalidate(key) {
    delete cache[key];
    gen[key] = (gen[key] || 0) + 1;
  }

  function invalidateAll() {
    Object.keys(cache).forEach((k) => { delete cache[k]; gen[k] = (gen[k] || 0) + 1; });
  }

  function set(key, data) { _set(key, data); }
  function peek(key) { const h = cache[key]; return h ? h.data : null; }
  function keys() { return Object.keys(cache); }

  return { get, refresh, invalidate, invalidateAll, set, peek, keys };
})();

/* Canonical fetchers — one per datatype. Add a new datatype here, then every
   view reads `ConductorData.get('<key>')` and mutations call
   `ConductorData.invalidate('<key>')`. */
window.ConductorData = {
  sources: {
    products: () => window.api('/api/products?limit=300'),
    checks:   () => window.api('/api/checks/summary'),
    people:   () => window.api('/api/people'),
  },
  get(key, opts) {
    const fn = this.sources[key];
    if (!fn) throw new Error('No data source registered for "' + key + '"');
    return window.ConductorStore.get(key, fn, opts);
  },
  invalidate(key) { return window.ConductorStore.invalidate(key); },
  preload(keys) {
    const list = keys || Object.keys(this.sources);
    return Promise.all(list.map((k) => this.get(k).catch(() => null)));
  },
};

/* Conductor - Model Gallery
 *
 * Renders the model catalog as animated JSON cards. The catalog is whatever the
 * provider endpoints actually returned (see POST /api/chat/catalog/refresh);
 * this view never invents or hardcodes model ids.
 *
 * Card styling is user-configurable and also lives in its own Settings section,
 * persisted under conductor.gallery.style.
 *
 * Depends on globals from app.js: $, esc, api, toast, fmtBytes, fmtNum.
 */
window.ConductorModelGallery = (function () {
  "use strict";

  const STYLE_KEY = "conductor.gallery.style";
  const DEFAULT_STYLE = {
    density: "comfortable", // comfortable | compact
    animate: true,
    showJson: true,
    highlightHardware: true,
  };

  function loadStyle() {
    try {
      const saved = JSON.parse(localStorage.getItem(STYLE_KEY) || "{}") || {};
      return Object.assign({}, DEFAULT_STYLE, saved);
    } catch {
      return Object.assign({}, DEFAULT_STYLE);
    }
  }

  function saveStyle(patch) {
    const next = Object.assign({}, loadStyle(), patch);
    try {
      localStorage.setItem(STYLE_KEY, JSON.stringify(next));
    } catch {
      /* private mode */
    }
    return next;
  }

  /* ---------------------------------------------------------- hardware fit */

  // Rough working-set estimate for a GGUF: file size plus KV-cache headroom.
  // Deliberately conservative - a card that claims "fits" and then OOMs is
  // worse than one that says "tight".
  function fitFor(sizeBytes, sys) {
    if (!sizeBytes || !sys || !sys.ram_available) return null;
    const need = sizeBytes * 1.2;
    const avail = sys.ram_available;
    if (need <= avail * 0.6) return { level: "ok", label: "fits comfortably" };
    if (need <= avail) return { level: "warning", label: "fits, tight" };
    if (need <= (sys.ram_total || avail)) return { level: "high", label: "needs free RAM" };
    return { level: "critical", label: "exceeds system RAM" };
  }

  /* ------------------------------------------------------------- rendering */

  function jsonBlock(obj, style) {
    if (!style.showJson) return "";
    const text = JSON.stringify(obj, null, 2);
    return '<pre class="mg-json' + (style.animate ? " mg-json-animate" : "") + '">' + esc(text) + "</pre>";
  }

  function providerCard(pid, entry, style) {
    const models = entry.models || [];
    const src = entry.source || "unknown";
    const badge =
      src === "endpoint" ? "ok"
      : src === "cache" ? "warning"
      : src === "error" ? "critical"
      : "info";
    const when = entry.fetchedAt ? "pulled " + esc(entry.fetchedAt) : "never pulled";
    const list =
      models.length ?
        models.map((m) => '<li class="mg-model"><span class="mono">' + esc(m.id) + "</span></li>").join("")
      : '<li class="mg-model mg-model-empty">' + esc(entry.error || "no models returned") + "</li>";
    const payload = {
      provider: pid,
      source: src,
      fetchedAt: entry.fetchedAt,
      models: models.map((m) => m.id),
    };
    return (
      '<article class="mg-card mg-card-' + esc(style.density) + (style.animate ? " mg-animate" : "") + '">' +
      '<header class="mg-head"><span class="mg-title">' + esc(pid) + "</span>" +
      '<span class="pill-int pill-int-activity-' + badge + '">' + esc(src) + "</span></header>" +
      '<div class="mg-sub">' + esc(String(models.length)) + " model(s) &middot; " + when + "</div>" +
      '<ul class="mg-models">' + list + "</ul>" +
      jsonBlock(payload, style) +
      "</article>"
    );
  }

  function localCard(m, sys, style) {
    const fit = style.highlightHardware ? fitFor(m.sizeBytes, sys) : null;
    const fitBadge = fit
      ? '<span class="pill-int pill-int-activity-' + fit.level + '">' + esc(fit.label) + "</span>"
      : "";
    return (
      '<article class="mg-card mg-card-' + esc(style.density) +
      (style.animate ? " mg-animate" : "") + (fit ? " mg-fit-" + fit.level : "") + '">' +
      '<header class="mg-head"><span class="mg-title">' + esc(m.name || m.id || "model") + "</span>" +
      fitBadge + "</header>" +
      '<div class="mg-sub">' + (m.sizeBytes ? esc(fmtBytes(m.sizeBytes)) : "size unknown") +
      " &middot; " + esc(m.kind || "chat") + "</div>" +
      jsonBlock(m, style) +
      "</article>"
    );
  }

  /* ----------------------------------------------------------------- view */

  async function render() {
    const root = $("#view-root");
    const style = loadStyle();
    root.innerHTML =
      '<div class="view"><div class="view-header"><div>' +
      '<div class="view-title">Model Gallery</div>' +
      '<div class="view-sub">Loading catalog...</div></div></div></div>';

    const [catalog, sys, disc, servers] = await Promise.all([
      api("/api/chat/catalog").catch(() => ({ providers: {} })),
      api("/api/hf/system").catch(() => null),
      api("/api/llama/discover").catch(() => ({ models: [] })),
      api("/api/llama/servers").catch(() => ({ servers: [] })),
    ]);

    const providers = catalog.providers || {};
    const provKeys = Object.keys(providers).sort();
    const locals = disc.models || [];
    const running = servers.servers || [];

    const hw = sys
      ? '<div class="view-sub">Detected hardware: ' + esc(fmtBytes(sys.ram_total)) +
        " RAM (" + esc(fmtBytes(sys.ram_available)) + " free) &middot; " +
        esc(String(sys.cpu_threads)) + " threads &middot; " +
        esc(fmtBytes(sys.disk_free)) + " disk free</div>"
      : "";

    const runningLine = running.length
      ? '<div class="view-sub">Running: ' +
        running.map((s) => esc(String(s.port) + (s.model ? " (" + s.model + ")" : ""))).join(", ") +
        "</div>"
      : '<div class="view-sub">No local model server currently running.</div>';

    const styleBar =
      '<div class="view-actions" style="margin:0 0 .5rem;flex-wrap:wrap;gap:.4rem">' +
      '<span class="view-sub">Cards</span>' +
      '<button class="btn-mini' + (style.density === "comfortable" ? " active" : "") + '" data-mg-density="comfortable">Comfortable</button>' +
      '<button class="btn-mini' + (style.density === "compact" ? " active" : "") + '" data-mg-density="compact">Compact</button>' +
      '<button class="btn-mini' + (style.animate ? " active" : "") + '" data-mg-toggle="animate">Animate</button>' +
      '<button class="btn-mini' + (style.showJson ? " active" : "") + '" data-mg-toggle="showJson">Show JSON</button>' +
      '<button class="btn-mini' + (style.highlightHardware ? " active" : "") + '" data-mg-toggle="highlightHardware">Hardware fit</button>' +
      '<span class="view-sub" style="margin-left:auto">Card styling also lives in Settings &rarr; Model cards</span>' +
      "</div>";

    root.innerHTML =
      '<div class="view"><div class="view-header"><div>' +
      '<div class="view-title">Model Gallery</div>' +
      '<div class="view-sub">Every model the configured provider endpoints actually returned. Model ids are never hardcoded &mdash; click Refresh to re-pull from each endpoint.</div>' +
      hw + runningLine +
      '</div><div class="view-actions">' +
      '<button class="btn-primary" id="mg-refresh"><span class="codicon codicon-refresh"></span> Refresh from endpoints</button>' +
      "</div></div>" +
      styleBar +
      '<div class="section-title">Local models (' + fmtNum(locals.length) + ")</div>" +
      '<div class="mg-grid">' +
      (locals.length
        ? locals.map((m) => localCard(m, sys, style)).join("")
        : '<div class="vv-empty">No local GGUF models found.</div>') +
      "</div>" +
      '<div class="section-title" style="margin-top:1rem">Provider catalogs (' + fmtNum(provKeys.length) + ")</div>" +
      '<div class="mg-grid">' +
      (provKeys.length
        ? provKeys.map((pid) => providerCard(pid, providers[pid], style)).join("")
        : '<div class="vv-empty">No catalog pulled yet &mdash; click Refresh from endpoints.</div>') +
      "</div></div>";

    root.querySelector("#mg-refresh").addEventListener("click", async (ev) => {
      const btn = ev.currentTarget;
      btn.disabled = true;
      btn.textContent = "Pulling from endpoints...";
      try {
        const r = await api("/api/chat/catalog/refresh", { method: "POST", body: {} });
        const c = r.counts || {};
        toast(
          "Pulled " + fmtNum(r.totalModels || 0) + " models from " + (c.endpoint || 0) + " endpoint(s)" +
            (c.error ? ", " + c.error + " unreachable" : ""),
          c.error ? "warn" : "ok",
        );
      } catch (e) {
        toast("Refresh failed: " + e.message, "error");
      }
      render();
    });

    root.querySelectorAll("[data-mg-density]").forEach((b) =>
      b.addEventListener("click", () => {
        saveStyle({ density: b.dataset.mgDensity });
        render();
      }),
    );
    root.querySelectorAll("[data-mg-toggle]").forEach((b) =>
      b.addEventListener("click", () => {
        const k = b.dataset.mgToggle;
        const cur = loadStyle();
        const patch = {};
        patch[k] = !cur[k];
        saveStyle(patch);
        render();
      }),
    );
  }

  // VIEW_RENDERERS is a top-level const in app.js, not a window property,
  // so reference it bare the way models.js does.
  try {
    VIEW_RENDERERS.modelgallery = () => render();
  } catch (e) {
    /* app.js not loaded yet */
  }

  return { render, loadStyle, saveStyle, fitFor, DEFAULT_STYLE };
})();

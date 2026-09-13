/* Conductor - Mapping View
 *
 * Header mapping and schema reconciliation page.
 * Displays pending uploads/syncs, header matching results, fuzzy AI field suggestions,
 * and user mapping controls to persist header-to-field mapping presets.
 */
window.ConductorMapping = (function () {
  "use strict";

  async function render() {
    const root = document.querySelector("#view-root");
    if (!root) return;

    root.innerHTML =
      '<div class="view"><div class="view-header"><div>' +
      '<div class="view-title">Schema & Header Mapping</div>' +
      '<div class="view-sub">Reconcile report headers with known spine fields. New uploads, schemas, and syncs land here.</div></div></div>' +
      '<div class="view-body"><div class="view-sub">Loading mapping dashboard...</div></div></div>';

    try {
      const [pendingRes, knownRes, presetsRes] = await Promise.all([
        fetch("/api/mapping/pending").then((r) => r.json()).catch(() => ({ pending: [] })),
        fetch("/api/mapping/known-fields").then((r) => r.json()).catch(() => ({ fields: [] })),
        fetch("/api/mapping/presets").then((r) => r.json()).catch(() => ({ presets: [] })),
      ]);

      const pending = pendingRes.pending || [];
      const known = knownRes.fields || [];
      const presets = presetsRes.presets || [];

      let pendingHtml = "";
      if (pending.length === 0) {
        pendingHtml = '<div class="vv-empty">No pending uploads or syncs requiring header mapping.</div>';
      } else {
        pendingHtml =
          '<table class="data-table"><thead><tr><th>ID / Name</th><th>Source</th><th>Status</th><th>Records</th><th>Action</th></tr></thead><tbody>' +
          pending
            .map(
              (p) =>
                "<tr>" +
                "<td><strong>" + esc(p.name || p.id) + "</strong></td>" +
                "<td>" + esc(p.source) + "</td>" +
                '<td><span class="pill-int pill-int-activity-info">' + esc(p.status) + "</span></td>" +
                "<td>" + esc(String(p.records)) + "</td>" +
                '<td><button class="btn-mini btn-primary" data-map-id="' + esc(p.id) + '">Map Headers</button></td>' +
                "</tr>"
            )
            .join("") +
          "</tbody></table>";
      }

      let presetsHtml = "";
      if (presets.length === 0) {
        presetsHtml = '<div class="vv-empty">No saved header mapping presets yet.</div>';
      } else {
        presetsHtml =
          '<div class="mg-grid">' +
          presets
            .map(
              (pr) =>
                '<div class="mg-card"><header class="mg-head"><span class="mg-title">' + esc(pr.name) + "</span>" +
                '<span class="pill-int pill-int-activity-ok">Preset</span></header>' +
                '<div class="mg-sub">' + esc(String((pr.headers || []).length)) + " header(s) mapped</div>" +
                '<pre class="mg-json">' + esc(JSON.stringify(pr.mappings || {}, null, 2)) + "</pre></div>"
            )
            .join("") +
          "</div>";
      }

      root.innerHTML =
        '<div class="view"><div class="view-header"><div>' +
        '<div class="view-title">Schema & Header Mapping</div>' +
        '<div class="view-sub">All new uploads, report arrivals, and sync schemas land here for fuzzy & AI auto-mapping into Spine fields.</div></div>' +
        '<div class="view-actions">' +
        '<button class="btn-secondary" id="btn-refresh-mapping"><span class="codicon codicon-refresh"></span> Refresh</button>' +
        "</div></div>" +
        '<div class="view-body" style="display:flex;flex-direction:column;gap:1.5rem">' +
        '<section><h3>Pending Report & Schema Arrivals</h3>' + pendingHtml + "</section>" +
        '<section><h3>Saved Header Mapping Presets (' + presets.length + ")</h3>" + presetsHtml + "</section>" +
        '<section><h3>Known Spine Fields (' + known.length + ")</h3>" +
        '<div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-top:0.5rem">' +
        known.map((f) => '<span class="pill-int pill-int-activity-info" title="Aliases: ' + esc((f.aliases||[]).join(', ')) + '">' + esc(f.label) + ' (' + esc(f.key) + ')</span>').join('') +
        "</div></section>" +
        "</div></div>";

      const refBtn = root.querySelector("#btn-refresh-mapping");
      if (refBtn) refBtn.addEventListener("click", () => render());

    } catch (err) {
      root.innerHTML =
        '<div class="view"><div class="view-header"><div class="view-title">Schema Mapping</div></div>' +
        '<div class="view-body"><div class="vv-empty">Error loading mapping page: ' + esc(err.message) + "</div></div></div>";
    }
  }

  try {
    if (typeof VIEW_RENDERERS !== "undefined") {
      VIEW_RENDERERS.mapping = () => render();
    }
  } catch (e) {
    /* app.js pending load */
  }

  return { render };
})();

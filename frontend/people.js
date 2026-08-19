/**
 * Conductor — People view (list + add form).
 *
 * Exposes window.ConductorPeople.render() and routes the existing `people` nav
 * view (previously a module stub) to it. Uses the globals provided by app.js
 * ($, $$, api, esc, toast, refreshCounts) — loaded after app.js.
 */
'use strict';

window.ConductorPeople = {
  render: async function () {
    const root = $('#view-root');
    root.innerHTML = `
      <div class="view">
        <div class="view-header">
          <div>
            <div class="view-title">People</div>
            <div class="view-sub">Team, roles, and the people behind the operation. Bulk-load a roster from the Bulk Import view.</div>
          </div>
        </div>
        <div class="view-toolbar" style="flex-wrap:wrap;align-items:flex-end">
          <form id="person-form" style="display:contents">
            <label class="field"><span>Name *</span><input id="p-name" placeholder="Jane Doe" /></label>
            <label class="field"><span>Role</span><input id="p-role" placeholder="Analyst" /></label>
            <label class="field"><span>Email</span><input id="p-email" placeholder="jane@example.com" /></label>
            <label class="field"><span>Team</span><input id="p-team" placeholder="Catalog" /></label>
            <label class="field"><span>Notes</span><input id="p-notes" placeholder="…" /></label>
            <button type="submit" class="btn-primary"><span class="codicon codicon-add"></span> Add person</button>
          </form>
        </div>
        <div id="people-body" class="data-table-wrap"><div class="folder-loading">Loading…</div></div>
      </div>`;

    const form = root.querySelector('#person-form');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const body = {
        name: form.querySelector('#p-name').value,
        role: form.querySelector('#p-role').value,
        email: form.querySelector('#p-email').value,
        team: form.querySelector('#p-team').value,
        notes: form.querySelector('#p-notes').value,
      };
      if (!body.name.trim()) { toast('Name is required', 'warn'); return; }
      try {
        await api('/api/people', { method: 'POST', body });
        toast('Person added', 'ok');
        if (window.ConductorData) window.ConductorData.invalidate('people');
        if (typeof refreshCounts === 'function') refreshCounts();
        window.ConductorPeople.render();
      } catch (err) { toast(err.message, 'err'); }
    });

    let people = [];
    try { people = await window.ConductorData.get('people'); } catch (e) { toast(e.message, 'err'); }
    const wrap = root.querySelector('#people-body');
    if (!people.length) {
      wrap.innerHTML = `<div class="empty-state">No people yet — add one above, or bulk-import a roster from Bulk Import.</div>`;
      return;
    }
    wrap.innerHTML = `<table class="data-table">
      <tr><th>Name</th><th>Role</th><th>Email</th><th>Team</th><th>Notes</th><th></th></tr>
      ${people.map((p) => `<tr data-id="${p.id}">
        <td><b>${esc(p.name)}</b></td>
        <td>${esc(p.role || '—')}</td>
        <td>${esc(p.email || '—')}</td>
        <td>${p.team ? `<span class="pill-status">${esc(p.team)}</span>` : '—'}</td>
        <td>${esc(p.notes || '—')}</td>
        <td><button class="btn-secondary btn-sm btn-person-del" data-id="${p.id}" title="Remove"><span class="codicon codicon-trash"></span></button></td>
      </tr>`).join('')}
    </table>`;

    wrap.querySelectorAll('.btn-person-del').forEach((b) => b.addEventListener('click', async () => {
      try {
        await api(`/api/people/${b.dataset.id}`, { method: 'DELETE' });
        toast('Person removed', 'ok');
        if (window.ConductorData) window.ConductorData.invalidate('people');
        if (typeof refreshCounts === 'function') refreshCounts();
        window.ConductorPeople.render();
      } catch (err) { toast(err.message, 'err'); }
    }));
  }
};

// Route the existing `people` nav view (a stub in app.js) to this module.
try { VIEW_RENDERERS.people = () => window.ConductorPeople.render(); } catch (e) { /* noop */ }

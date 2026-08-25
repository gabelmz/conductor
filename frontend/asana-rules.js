/* ==========================================================================
   ASANA RULES CANVAS — ported from Process Visualizer (ReactFlow app.html)
   into Conductor as a second Bernie-style canvas. Full-window takeover,
   own skin environment (5 PV skins), Asana rules mode + generic mode,
   run simulation, asana-rules/v1 export, process-visualizer/v1 round-trip.
   Self-registers VIEW_RENDERERS.asanarules; view name 'asanarules'.
   ========================================================================== */
(function () {
  const AR = {
    canvases: [],
    canvasId: null,
    name: 'Untitled ruleset',
    mode: 'asana',
    skin: 'flat',
    nodes: [],   // {id,label,note,x,y,kind|style}
    edges: [],   // {from,to,label}
    sel: null,
    connecting: null,
    drag: null,
    pan: null,
    runningOrder: null,
  };
  let uid = 100;

  /* ------------------------------------------------------------ vocabulary */
  const ASANA_TRIGGERS = [
    'Task added to project', 'Task completed', 'Task marked incomplete', 'Due date arrives',
    'Due date is approaching', 'Assignee changed', 'Section changed', 'Tag added', 'Attachment added',
    'Comment added', 'Custom field changed', 'Story/dependency changed',
  ];
  const ASANA_ACTIONS = [
    'Assign to person', 'Set due date', 'Move to section', 'Add tag', 'Add collaborator',
    'Add comment', 'Create subtask', 'Change custom field', 'Approve task', 'Duplicate task',
    'Send to another project', 'Reassign to requester',
  ];
  const KINDS = ['trigger', 'condition', 'action', 'approval'];
  const STYLES = [
    ['entry', 'entry'], ['task', 'task'], ['process', 'process'],
    ['decision', 'decision'], ['wait', 'wait'], ['end', 'end'],
  ];

  const SKINS = {
    flat:      { name: 'Flat',      vars: { bg:'#f6f6f7', card:'#ffffff', fg:'#111114', muted:'#6b6b76', border:'#e3e3e8', accent:'#2563eb' }, radius:'4px', shadow:'3px 3px 0 rgba(17,17,20,.14)', borderW:'2px' },
    glass:     { name: 'Glass',     vars: { bg:'#eef1f6', card:'rgba(255,255,255,.72)', fg:'#16181d', muted:'#667085', border:'rgba(22,24,29,.16)', accent:'#2563eb' }, radius:'4px', shadow:'0 8px 28px rgba(22,24,29,.12)', borderW:'1px' },
    midnight:  { name: 'Midnight',  vars: { bg:'#0b0d10', card:'#14171c', fg:'#e8eaee', muted:'#8b93a1', border:'#262b33', accent:'#5b8cff' }, radius:'4px', shadow:'0 4px 14px rgba(0,0,0,.45)', borderW:'1px' },
    blueprint: { name: 'Blueprint', vars: { bg:'#0e2a47', card:'#123356', fg:'#dceafc', muted:'#7fa3cc', border:'#2a5583', accent:'#ffd166' }, radius:'4px', shadow:'none', borderW:'1.5px' },
    paper:     { name: 'Paper',     vars: { bg:'#faf6ef', card:'#fffdf8', fg:'#33302a', muted:'#8a8375', border:'#e2dbcc', accent:'#c2410c' }, radius:'4px', shadow:'2px 3px 6px rgba(80,70,50,.12)', borderW:'1.5px' },
  };

  function applySkin(key) {
    const s = SKINS[key]; if (!s) return;
    const v = document.querySelector('.ar-view'); if (!v) return;
    for (const k in s.vars) v.style.setProperty('--ar-' + k, s.vars[k]);
    v.style.setProperty('--ar-radius', s.radius);
    v.style.setProperty('--ar-shadow', s.shadow);
    v.style.setProperty('--ar-borderw', s.borderW);
    AR.skin = key;
  }

  /* ------------------------------------------------------------- templates */
  const TEMPLATES = {
    'asana · intake triage': {
      mode: 'asana',
      nodes: [
        ['New Request', 'trigger', 'Task added to project'],
        ['Is Complete Form?', 'condition', 'Custom field: intake_type = form'],
        ['Auto-assign Owner', 'action', "Assign to requester's manager"],
        ['Set SLA Due Date', 'action', 'Due date = +3 days'],
        ['Route: Bugs', 'action', 'Move to section "Bugs"'],
        ['Route: Features', 'action', 'Move to section "Features"'],
        ['Needs Triage', 'wait', 'human review required'],
      ],
      edges: [['New Request','Is Complete Form?'],['Is Complete Form?','Auto-assign Owner','true'],
        ['Is Complete Form?','Needs Triage','false'],['Auto-assign Owner','Set SLA Due Date'],
        ['Set SLA Due Date','Route: Bugs','bug'],['Set SLA Due Date','Route: Features','feature']],
    },
    'asana · launch checklist': {
      mode: 'asana',
      nodes: [
        ['Launch Task Created', 'trigger', 'Task added to section "Launch Queue"'],
        ['All Subtasks Done?', 'condition', 'subtasks complete'],
        ['Request Approval', 'approval', 'Add approver: PM'],
        ['Approved?', 'condition', 'Approve task action'],
        ['Send Feedback', 'action', 'Add comment requesting changes'],
        ['Mark Shipped', 'action', 'Move to "Shipped" + tag launch-2026'],
        ['Blocked Escalation', 'action', 'Assign to team lead + due today'],
      ],
      edges: [['Launch Task Created','All Subtasks Done?'],
        ['All Subtasks Done?','Request Approval','yes'],['All Subtasks Done?','Blocked Escalation','no'],
        ['Request Approval','Approved?'],['Approved?','Mark Shipped','approved'],
        ['Approved?','Send Feedback','changes requested'],['Send Feedback','Request Approval']],
    },
    'software release': {
      mode: 'generic',
      nodes: [
        ['Ticket Created','entry','story filed'],['Dev Branch','task','cut branch + PR'],
        ['Code Review','decision','approve?'],['Changes Requested','wait','back to dev'],
        ['CI + Tests','process','build · lint · test'],['Deploy Staging','process','smoke test'],
        ['Go / No-Go','decision','sign-off?'],['Deploy Prod','process','release + tag'],['Done','end','closed'],
      ],
      edges: [['Ticket Created','Dev Branch'],['Dev Branch','Code Review'],
        ['Code Review','CI + Tests','yes'],['Code Review','Changes Requested','no'],
        ['Changes Requested','Dev Branch','rework'],['CI + Tests','Deploy Staging'],
        ['Deploy Staging','Go / No-Go'],['Go / No-Go','Deploy Prod','go'],['Go / No-Go','Dev Branch','no-go'],
        ['Deploy Prod','Done']],
    },
    'support triage': {
      mode: 'generic',
      nodes: [
        ['Ticket In','entry','new request'],['Classify','decision','severity?'],
        ['P1 Queue','process','page on-call · SLA 1h'],['P2 Queue','process','SLA 24h'],
        ['Backlog','wait','batch weekly'],['Resolved','end','customer confirmed'],
      ],
      edges: [['Ticket In','Classify'],['Classify','P1 Queue','p1'],['Classify','P2 Queue','p2'],
        ['Classify','Backlog','p3'],['P1 Queue','Resolved'],['P2 Queue','Resolved'],['Backlog','Resolved']],
    },
  };

  function loadTemplate(name) {
    const t = TEMPLATES[name]; if (!t) return;
    AR.nodes = t.nodes.map((n, i) => ({
      id: 'n' + i, label: n[0], note: n[2],
      kind: t.mode === 'asana' ? n[1] : undefined,
      style: t.mode === 'generic' ? n[1] : undefined,
      x: 60 + Math.floor(i / 4) * 270, y: 40 + (i % 4) * 165,
    }));
    const byLabel = {}; t.nodes.forEach((n, i) => (byLabel[n[0]] = 'n' + i));
    AR.edges = t.edges.map((e) => ({ from: byLabel[e[0]], to: byLabel[e[1]], label: e[2] || '' }));
    AR.name = name; AR.mode = t.mode; AR.canvasId = null; AR.sel = null; AR.runningOrder = null;
  }

  /* -------------------------------------------------------- rule computing */
  function computeRules() {
    const incoming = new Set(AR.edges.map((e) => e.to));
    const triggers = AR.nodes.filter((n) => !incoming.has(n.id) && n.kind !== 'action');
    const adj = {};
    AR.edges.forEach((e) => (adj[e.from] = adj[e.from] || []).push(e.to));
    const byId = Object.fromEntries(AR.nodes.map((n) => [n.id, n]));
    const rules = [];
    triggers.forEach((t) => {
      const paths = [];
      (function dfs(id, path, visited) {
        visited[id] = true; path = path.concat([id]);
        const outs = adj[id] || [];
        if (!outs.length) { paths.push(path); return; }
        outs.forEach((o) => { if (visited[o]) { paths.push(path); return; } dfs(o, path, Object.assign({}, visited)); });
      })(t.id, [], {});
      paths.forEach((p, pi) => {
        const steps = p.map((id) => {
          const n = byId[id] || {};
          return { step: n.label || id, kind: n.kind || 'action', config: n.note || '' };
        });
        rules.push({
          name: (steps[0].step + ' — path ' + (pi + 1)).toLowerCase(),
          trigger: steps[0].config || steps[0].step,
          conditions: steps.filter((s) => s.kind === 'condition').map((s) => s.step + (s.config ? ' (' + s.config + ')' : '')),
          actions: steps.filter((s) => s.kind === 'action' || s.kind === 'approval').map((s) => s.step + (s.config ? ' → ' + s.config : '')),
        });
      });
    });
    return rules;
  }

  function serialize() {
    return {
      format: 'process-visualizer/v1',
      name: AR.name, mode: AR.mode, skin: AR.skin,
      generated: new Date().toISOString(),
      nodes: AR.nodes.map((n) => {
        const o = { id: n.id, label: n.label, note: n.note || '', x: Math.round(n.x), y: Math.round(n.y) };
        if (AR.mode === 'asana') o.kind = n.kind || 'action'; else o.style = n.style || 'task';
        return o;
      }),
      edges: AR.edges.map((e) => ({ from: e.from, to: e.to, label: e.label || undefined })),
    };
  }

  function parseWorkflow(text) {
    const wf = JSON.parse(text);
    if (wf.format !== 'process-visualizer/v1' && !wf.nodes) throw new Error('unrecognized structure');
    const asanaMode = wf.mode === 'asana' || (wf.nodes[0] && wf.nodes[0].kind !== undefined);
    const nodes = wf.nodes.map((n, i) => ({
      id: String(n.id || 'n' + i), label: String(n.label || 'Node ' + i), note: String(n.note || ''),
      kind: asanaMode ? (n.kind || 'action') : undefined,
      style: asanaMode ? undefined : (n.style || 'task').replace(/^st-/, ''),
      x: Number(n.x) || i * 270, y: Number(n.y) || (i % 4) * 165,
    }));
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
    const byLabel = {}; nodes.forEach((n) => (byLabel[n.label] = n.id));
    const edges = (wf.edges || []).map((e) => {
      const src = byId[e.from] ? e.from : byLabel[e.from];
      const tgt = byId[e.to] ? e.to : byLabel[e.to];
      return src && tgt ? { from: src, to: tgt, label: e.label || '' } : null;
    }).filter(Boolean);
    return { name: wf.name || 'Imported workflow', nodes, edges, mode: asanaMode ? 'asana' : 'generic' };
  }

  /* ------------------------------------------------------------ run engine */
  function computeRun() {
    const incoming = new Set(AR.edges.map((e) => e.to));
    let starts = AR.nodes.filter((n) => !incoming.has(n.id));
    if (!starts.length) starts = AR.nodes.slice(0, 1);
    const adj = {};
    AR.edges.forEach((e) => (adj[e.from] = adj[e.from] || []).push(e.to));
    const order = [], seen = {};
    let frontier = starts.map((n) => n.id);
    while (frontier.length) {
      const next = [];
      frontier.forEach((id) => {
        if (seen[id]) return; seen[id] = true; order.push(id);
        (adj[id] || []).forEach((t) => { if (!next.includes(t)) next.push(t); });
      });
      frontier = next;
    }
    return order;
  }

  async function api(path, opts) {
    const r = await fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts));
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.status === 204 ? null : r.json();
  }

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function toast(msg, err) {
    let el = document.querySelector('.ar-toast');
    if (!el) { el = document.createElement('div'); el.className = 'ar-toast'; document.body.appendChild(el); }
    el.textContent = msg; el.classList.toggle('err', !!err); el.classList.add('show');
    clearTimeout(toast._t); toast._t = setTimeout(() => el.classList.remove('show'), 2600);
  }

  /* ---------------------------------------------------------------- render */
  function render() {
    const root = document.getElementById('view-root');
    root.innerHTML = `
      <div class="view ar-view">
        <div class="ar-topbar">
          <h1>Asana Rules &amp; Routing</h1>
          <span class="ar-tag ar-tag-mode">${AR.mode === 'asana' ? 'ASANA RULES MODE' : 'GENERIC MODE'}</span>
          <input id="ar-name" value="${esc(AR.name)}" title="Ruleset name" />
          <select id="ar-load"><option value="">Load saved…</option></select>
          <span class="ar-spacer"></span>
          ${AR.mode === 'asana' ? '<button class="ar-btn" id="ar-rules-copy">Copy Rules</button><button class="ar-btn" id="ar-rules-export">Export Rules</button>' : ''}
          <button class="ar-btn ar-btn-primary" id="ar-run">▶ Run Flow</button>
          <button class="ar-btn" id="ar-add">+ Add Node</button>
          <button class="ar-btn" id="ar-import">Import</button>
          <button class="ar-btn" id="ar-copy">Copy JSON</button>
          <button class="ar-btn" id="ar-download">Export</button>
          <button class="ar-btn" id="ar-save"><span class="codicon codicon-save"></span> Save</button>
          <button class="ar-btn" id="ar-exit" title="Back to Conductor"><span class="codicon codicon-chevron-left"></span> Back</button>
        </div>
        <div class="ar-main">
          <aside class="ar-inspector">
            <div class="ar-ih" id="ar-ih">${AR.sel ? 'RULE STEP' : 'WORKFLOW'}</div>
            <div class="ar-ib" id="ar-ib"></div>
          </aside>
          <div class="ar-canvas-wrap" id="ar-wrap">
            <svg id="ar-svg"></svg>
            <div id="ar-nodes"></div>
            <div class="ar-iohint">drag node edge → node edge to connect · double-click node to rename</div>
            <input type="file" id="ar-file" accept=".json" hidden />
          </div>
        </div>
      </div>`;
    applySkin(AR.skin);
    wire(root);
    renderNodes();
    renderInspector();
    refreshLoad();
  }

  function refreshLoad() {
    api('/api/asana-rules/canvases').then((cs) => {
      AR.canvases = cs;
      const sel = document.getElementById('ar-load');
      if (!sel) return;
      sel.innerHTML = '<option value="">Load saved…</option>' +
        cs.map((c) => `<option value="${c.id}"${AR.canvasId === c.id ? ' selected' : ''}>${esc(c.name)} (${c.node_count}n)</option>`).join('');
    }).catch(() => {});
  }

  function headClass(n) {
    if (AR.mode === 'asana') {
      return { trigger: 'st-entry', condition: 'st-decision', action: 'st-process', approval: 'st-wait' }[n.kind] || 'st-task';
    }
    return 'st-' + (n.style || 'task');
  }

  function renderNodes() {
    const wrap = document.getElementById('ar-nodes'); if (!wrap) return;
    wrap.innerHTML = '';
    AR.runningOrder = AR.runningOrder || [];
    AR.nodes.forEach((n) => {
      const idx = AR.runningOrder.indexOf(n.id);
      const cls = idx >= 0 ? (AR._runDone && AR._runDone.has(n.id) ? 'done' : idx === AR._runIdx ? 'running' : '') : '';
      const el = document.createElement('div');
      el.className = `ar-node ${headClass(n)} ${cls} ${AR.sel === n.id ? 'selected' : ''}`;
      el.dataset.id = n.id;
      el.style.left = n.x + 'px'; el.style.top = n.y + 'px';
      el.innerHTML = `
        <div class="head"><span class="dot"></span><span class="lbl">${esc(n.label)}</span>${AR.mode === 'asana' ? `<span class="badge">${esc((n.kind || 'action').toUpperCase())}</span>` : ''}</div>
        ${n.note ? `<div class="body">${esc(n.note)}</div>` : ''}
        <span class="handle in" data-h="in"></span><span class="handle out" data-h="out"></span>`;
      wrap.appendChild(el);
    });
    drawEdges();
  }

  function drawEdges() {
    const svg = document.getElementById('ar-svg'); if (!svg) return;
    svg.innerHTML = '';
    svg.setAttribute('width', '100%'); svg.setAttribute('height', '100%');
    AR.edges.forEach((e) => {
      const a = AR.nodes.find((n) => n.id === e.from), b = AR.nodes.find((n) => n.id === e.to);
      if (!a || !b) return;
      const x1 = a.x + 200, y1 = a.y + 20, x2 = b.x, y2 = b.y + 20;
      const mx = (x1 + x2) / 2;
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      p.setAttribute('d', `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`);
      p.setAttribute('class', 'ar-edge');
      g.appendChild(p);
      if (e.label) {
        const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        t.setAttribute('x', mx); t.setAttribute('y', (y1 + y2) / 2 - 6);
        t.setAttribute('text-anchor', 'middle'); t.setAttribute('class', 'ar-elabel');
        t.textContent = e.label;
        g.appendChild(t);
      }
      // delete hit target
      const hit = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      hit.setAttribute('d', p.getAttribute('d'));
      hit.setAttribute('class', 'ar-edge-hit');
      hit.title = 'click to delete edge';
      hit.addEventListener('click', () => { AR.edges = AR.edges.filter((x) => x !== e); dirty(); renderNodes(); });
      g.insertBefore(hit, p);
      svg.appendChild(g);
    });
    if (AR.connecting) {
      const a = AR.nodes.find((n) => n.id === AR.connecting.fromId);
      if (a) {
        const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const x1 = a.x + 200, y1 = a.y + 20;
        p.setAttribute('d', `M ${x1} ${y1} L ${AR.connecting.mx} ${AR.connecting.my}`);
        p.setAttribute('class', 'ar-edge ar-edge-temp');
        svg.appendChild(p);
      }
    }
  }

  function dirty() { AR._dirty = true; }

  /* ------------------------------------------------------------- inspector */
  function renderInspector() {
    const ib = document.getElementById('ar-ib'); const ih = document.getElementById('ar-ih');
    if (!ib) return;
    ih.textContent = AR.sel ? (AR.mode === 'asana' ? 'RULE STEP' : 'NODE') : 'WORKFLOW';
    if (AR.sel) {
      const n = AR.nodes.find((x) => x.id === AR.sel);
      if (!n) { AR.sel = null; return renderInspector(); }
      ib.innerHTML = `
        <div class="ar-sect">${AR.mode === 'asana' ? 'rule step' : 'node'}</div>
        <label class="ar-frow"><span>name</span><input type="text" id="ar-f-label" value="${esc(n.label)}" /></label>
        ${AR.mode === 'asana'
          ? `<label class="ar-frow"><span>kind</span><select id="ar-f-kind">${KINDS.map((k) => `<option value="${k}"${n.kind === k ? ' selected' : ''}>${k}</option>`).join('')}</select></label>`
          : `<label class="ar-frow"><span>style</span><select id="ar-f-style">${STYLES.map(([v, l]) => `<option value="${v}"${(n.style || 'task') === v ? ' selected' : ''}>${l}</option>`).join('')}</select></label>`}
        <label class="ar-frow"><span>config</span><textarea id="ar-f-note" placeholder="${AR.mode === 'asana' ? 'e.g. Assign to requester' : 'note'}">${esc(n.note || '')}</textarea></label>
        ${AR.mode === 'asana' && n.kind === 'trigger' ? `<div class="ar-sect">trigger event</div><label class="ar-frow"><span>event</span><select id="ar-f-trigger"><option value="">custom…</option>${ASANA_TRIGGERS.map((t) => `<option${n.note === t ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select></label>` : ''}
        ${AR.mode === 'asana' && n.kind === 'action' ? `<div class="ar-sect">action verb</div><label class="ar-frow"><span>verb</span><select id="ar-f-action"><option value="">custom…</option>${ASANA_ACTIONS.map((t) => `<option${n.note === t ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select></label>` : ''}
        <div class="ar-sect">danger zone</div>
        <button class="ar-btn danger" id="ar-del">✕ Delete Node</button>`;
      ib.querySelector('#ar-f-label').addEventListener('input', (e) => { n.label = e.target.value; dirty(); renderNodes(); relabelSel(); });
      const kindEl = ib.querySelector('#ar-f-kind'); if (kindEl) kindEl.addEventListener('change', (e) => { n.kind = e.target.value; dirty(); renderNodes(); });
      const styleEl = ib.querySelector('#ar-f-style'); if (styleEl) styleEl.addEventListener('change', (e) => { n.style = e.target.value; dirty(); renderNodes(); });
      const noteEl = ib.querySelector('#ar-f-note');
      noteEl.addEventListener('change', (e) => { n.note = e.target.value; dirty(); renderNodes(); });
      const trg = ib.querySelector('#ar-f-trigger'); if (trg) trg.addEventListener('change', (e) => { if (e.target.value) { n.note = e.target.value; noteEl.value = n.note; dirty(); renderNodes(); } });
      const act = ib.querySelector('#ar-f-action'); if (act) act.addEventListener('change', (e) => { if (e.target.value) { n.note = e.target.value; noteEl.value = n.note; dirty(); renderNodes(); } });
      ib.querySelector('#ar-del').addEventListener('click', () => {
        AR.nodes = AR.nodes.filter((x) => x.id !== AR.sel);
        AR.edges = AR.edges.filter((e) => e.from !== AR.sel && e.to !== AR.sel);
        AR.sel = null; dirty(); renderNodes(); renderInspector();
      });
      function relabelSel() {
        const lbl = document.getElementById('ar-ib');
        if (lbl && AR.mode !== 'asana') {} // label re-render handled in renderNodes
      }
    } else {
      const incoming = new Set(AR.edges.map((e) => e.to));
      const entries = AR.nodes.filter((n) => !incoming.has(n.id)).length;
      const rules = AR.mode === 'asana' ? computeRules() : [];
      ib.innerHTML = `
        <div class="ar-sect">stats</div>
        <div class="ar-kv"><span>nodes</span><b>${AR.nodes.length}</b></div>
        <div class="ar-kv"><span>links</span><b>${AR.edges.length}</b></div>
        <div class="ar-kv"><span>entry points</span><b>${entries}</b></div>
        ${AR.mode === 'asana' ? `<div class="ar-kv"><span>rules compiled</span><b>${rules.length}</b></div>` : ''}
        <div class="ar-sect">templates</div>
        <div>${Object.keys(TEMPLATES).map((t) => `<button class="ar-chip" data-tpl="${esc(t)}">${esc(t)}</button>`).join('')}</div>
        <div class="ar-sect">skins</div>
        <div>${Object.keys(SKINS).map((k) => `<button class="ar-chip${AR.skin === k ? ' active' : ''}" data-skin="${k}">${SKINS[k].name}</button>`).join('')}</div>
        <div class="ar-sect">mode</div>
        <div><button class="ar-chip${AR.mode === 'asana' ? ' active' : ''}" data-mode="asana">asana rules</button><button class="ar-chip${AR.mode === 'generic' ? ' active' : ''}" data-mode="generic">generic flow</button></div>
        ${AR.mode === 'asana' ? `<div class="ar-hint">triggers: ${ASANA_TRIGGERS.length} known events · actions: ${ASANA_ACTIONS.length} known verbs.<br />EXPORT RULES converts every trigger→path into a named rule with conditions + actions.</div>` : ''}
        <div class="ar-sect">how it works</div>
        <div class="ar-hint">Drag from a node's right handle to another's left handle to connect.<br />Click an edge to delete it.<br />RUN walks the graph from entry points.</div>`;
      ib.querySelectorAll('[data-tpl]').forEach((b) => b.addEventListener('click', () => { loadTemplate(b.dataset.tpl); dirty(); renderAll(); }));
      ib.querySelectorAll('[data-skin]').forEach((b) => b.addEventListener('click', () => { applySkin(b.dataset.skin); dirty(); renderInspector(); }));
      ib.querySelectorAll('[data-mode]').forEach((b) => b.addEventListener('click', () => { AR.mode = b.dataset.mode; dirty(); renderAll(); }));
    }
  }
  function renderAll() { renderNodes(); renderInspector(); }

  /* ------------------------------------------------------------ interactions */
  function wire(root) {
    root.querySelector('#ar-exit').addEventListener('click', () => window.showView('chat'));
    root.querySelector('#ar-add').addEventListener('click', addNode);
    root.querySelector('#ar-save').addEventListener('click', saveCanvas);
    root.querySelector('#ar-load').addEventListener('change', (e) => { const id = Number(e.target.value); if (id) openCanvas(id); });
    root.querySelector('#ar-run').addEventListener('click', runFlow);
    root.querySelector('#ar-copy').addEventListener('click', () => {
      navigator.clipboard.writeText(JSON.stringify(serialize(), null, 2)).then(() => toast('workflow JSON copied'), () => toast('clipboard blocked', true));
    });
    root.querySelector('#ar-download').addEventListener('click', downloadJson);
    root.querySelector('#ar-import').addEventListener('click', () => root.querySelector('#ar-file').click());
    root.querySelector('#ar-file').addEventListener('change', (e) => { const f = e.target.files[0]; if (f) f.text().then((t) => ingest(t, f.name)); });
    const rc = root.querySelector('#ar-rules-copy'); if (rc) rc.addEventListener('click', exportRules.bind(null, false));
    const re = root.querySelector('#ar-rules-export'); if (re) re.addEventListener('click', exportRules.bind(null, true));
    const nameEl = root.querySelector('#ar-name');
    nameEl.addEventListener('change', () => { AR.name = nameEl.value; dirty(); });

    const wrap = root.querySelector('#ar-canvas-wrap') || root.querySelector('.ar-canvas-wrap');
    wrap.addEventListener('mousedown', onCanvasDown);
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);

    // paste JSON
    window.addEventListener('keydown', arKeyHandler);
  }

  function arKeyHandler(e) {
    const view = document.querySelector('.ar-view');
    if (!view || view.offsetParent === null) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v' && !e.target.closest('input,textarea')) {
      navigator.clipboard.readText().then((t) => { if (t) ingest(t, 'clipboard'); }, () => {});
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c' && !e.target.closest('input,textarea')) {
      navigator.clipboard.writeText(JSON.stringify(serialize(), null, 2)).then(() => toast('workflow JSON copied'), () => {});
    }
  }

  function addNode() {
    uid++;
    const id = 'user' + uid;
    AR.nodes.push({
      id, label: 'New Step', note: '',
      kind: AR.mode === 'asana' ? 'action' : undefined,
      style: AR.mode === 'asana' ? undefined : 'task',
      x: 80 + Math.round(Math.random() * 250), y: 60 + Math.round(Math.random() * 280),
    });
    AR.sel = id; dirty(); renderAll();
  }

  function onCanvasDown(e) {
    const handle = e.target.closest('.handle');
    const nodeEl = e.target.closest('.ar-node');
    if (handle && nodeEl) {
      e.preventDefault();
      AR.connecting = { fromId: nodeEl.dataset.id, mx: e.clientX, my: e.clientY };
      drawEdges();
      return;
    }
    if (nodeEl) {
      e.preventDefault();
      const n = AR.nodes.find((x) => x.id === nodeEl.dataset.id);
      AR.drag = { id: n.id, dx: e.clientX - n.x, dy: e.clientY - n.y, moved: false };
      if (AR.sel !== n.id) { AR.sel = n.id; renderNodes(); renderInspector(); }
      return;
    }
    if (AR.sel) { AR.sel = null; renderNodes(); renderInspector(); }
  }

  function onMove(e) {
    if (AR.connecting) {
      const rect = document.getElementById('ar-wrap').getBoundingClientRect();
      AR.connecting.mx = e.clientX - rect.left; AR.connecting.my = e.clientY - rect.top;
      drawEdges(); return;
    }
    if (AR.drag) {
      e.preventDefault();
      const n = AR.nodes.find((x) => x.id === AR.drag.id);
      n.x = e.clientX - AR.drag.dx; n.y = e.clientY - AR.drag.dy;
      AR.drag.moved = true; dirty();
      renderNodes();
    }
  }

  function onUp(e) {
    if (AR.connecting) {
      const el = document.elementFromPoint(e.clientX, e.clientY);
      const nodeEl = el && el.closest ? el.closest('.ar-node') : null;
      if (nodeEl) {
        const to = nodeEl.dataset.id;
        if (to !== AR.connecting.fromId && !AR.edges.some((x) => x.from === AR.connecting.fromId && x.to === to)) {
          AR.edges.push({ from: AR.connecting.fromId, to, label: '' });
          dirty(); toast('connected');
        }
      }
      AR.connecting = null; renderNodes();
    }
    AR.drag = null;
  }

  function runFlow() {
    const btn = document.getElementById('ar-run');
    const order = computeRun();
    if (!order.length) { toast('nothing to run', true); return; }
    AR.runningOrder = order; AR._runIdx = -1; AR._runDone = new Set();
    btn.textContent = 'RUNNING…';
    order.forEach((id, i) => {
      setTimeout(() => { AR._runIdx = i; if (i > 0) AR._runDone.add(order[i - 1]); renderNodes(); }, 300 + i * 450);
    });
    setTimeout(() => {
      AR._runDone = new Set(order); AR._runIdx = -1; renderNodes();
      btn.textContent = '▶ Run Flow';
      toast('run complete · ' + order.length + ' steps');
    }, 300 + order.length * 450 + 350);
  }

  function ingest(text, label) {
    try {
      const wf = parseWorkflow(text);
      AR.name = wf.name; AR.nodes = wf.nodes; AR.edges = wf.edges; AR.mode = wf.mode;
      AR.canvasId = null; AR.sel = null; dirty(); applySkin(AR.skin);
      document.querySelector('#ar-name').value = AR.name;
      renderAll(); refreshLoad();
      toast(`loaded "${wf.name}" · ${wf.nodes.length} nodes${label ? ' (' + label + ')' : ''}`);
    } catch (err) { toast('could not parse: ' + err.message, true); }
  }

  function downloadJson() {
    const text = JSON.stringify(serialize(), null, 2);
    const blob = new Blob([text], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (AR.name || 'workflow').replace(/[^a-z0-9]+/gi, '-').toLowerCase() + '.json';
    a.click(); URL.revokeObjectURL(a.href);
    toast('downloaded ' + a.download);
  }

  function exportRules(download) {
    if (AR.mode !== 'asana') { toast('switch to asana rules mode first', true); return; }
    const payload = { format: 'asana-rules/v1', workflow: AR.name, generated: new Date().toISOString(), rules: computeRules() };
    const text = JSON.stringify(payload, null, 2);
    if (download) {
      const blob = new Blob([text], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = (AR.name || 'rules').replace(/[^a-z0-9]+/gi, '-').toLowerCase() + '.rules.json';
      a.click(); URL.revokeObjectURL(a.href);
    } else {
      navigator.clipboard.writeText(text);
    }
    toast(payload.rules.length + ' asana rules ' + (download ? 'downloaded' : 'copied'));
  }

  async function saveCanvas() {
    const payload = { name: AR.name || 'Untitled ruleset', mode: AR.mode, skin: AR.skin, nodes: AR.nodes, edges: AR.edges };
    try {
      if (AR.canvasId) await api(`/api/asana-rules/canvases/${AR.canvasId}`, { method: 'PATCH', body: JSON.stringify(payload) });
      else {
        const created = await api('/api/asana-rules/canvases', { method: 'POST', body: JSON.stringify(payload) });
        AR.canvasId = created.id;
      }
      AR._dirty = false;
      toast(`Ruleset "${AR.name}" saved`, false);
      refreshLoad();
    } catch (err) { toast('save failed: ' + err.message, true); }
  }

  async function openCanvas(id) {
    try {
      const c = await api(`/api/asana-rules/canvases/${id}`);
      AR.canvasId = c.id; AR.name = c.name; AR.mode = c.mode; AR.skin = c.skin || 'flat';
      AR.nodes = c.nodes || []; AR.edges = c.edges || []; AR.sel = null; AR.runningOrder = null;
      document.querySelector('#ar-name').value = AR.name;
      applySkin(AR.skin); renderAll();
    } catch (err) { toast('load failed: ' + err.message, true); }
  }

  window.ConductorAsanaRules = { render, computeRules };
  if (window.VIEW_RENDERERS) window.VIEW_RENDERERS.asanarules = () => render();
})();

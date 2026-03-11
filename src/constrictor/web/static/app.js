/* Constrictor Graph Explorer — app.js
 *
 * Layout: left panel (views/controls) | D3 graph | right panel (node detail)
 * New in this version: view switching, depth+direction controls, edge-type
 * filter, path inspector, and audit list view.
 */

// ─── Node type colours & sizes ─────────────────────────────────────────────

const NODE_COLORS = {
  MODULE:            '#60a5fa', PACKAGE:           '#93c5fd',
  CLASS:             '#a78bfa', FUNCTION:          '#34d399',
  METHOD:            '#6ee7b7', ENDPOINT:          '#fbbf24',
  SERVICE:           '#f87171', COMPONENT:         '#fb923c',
  SQLALCHEMY_MODEL:  '#c084fc', TABLE:             '#fb923c',
  EXTERNAL_MODULE:   '#94a3b8', EXTERNAL_SERVICE:  '#94a3b8',
  EXTERNAL_ENDPOINT: '#94a3b8', VARIABLE:          '#cbd5e1',
  DECORATOR:         '#e2e8f0', JS_MODULE:         '#60a5fa',
  JS_FUNCTION:       '#34d399', JS_COMPONENT:      '#fb923c',
};

const NODE_RADIUS = {
  SERVICE: 14, COMPONENT: 12, MODULE: 10, PACKAGE: 10,
  CLASS: 9, FUNCTION: 7, METHOD: 6, ENDPOINT: 8, default: 6,
};

// Node types shown per view (null = all)
const VIEW_FILTER = {
  topology: null,
  services: new Set(['SERVICE', 'COMPONENT', 'ENDPOINT', 'EXTERNAL_SERVICE', 'EXTERNAL_ENDPOINT']),
  data:     new Set(['SQLALCHEMY_MODEL', 'TABLE', 'MODULE', 'PACKAGE']),
  audit:    null,
};

function nodeColor(type) { return NODE_COLORS[type] || '#cbd5e1'; }
function nodeRadius(type) { return NODE_RADIUS[type] || NODE_RADIUS.default; }

// ─── State ─────────────────────────────────────────────────────────────────

let allNodes = [];
let allEdges = [];
let visibleTypes  = new Set();   // driven by node-type checkboxes
let filteredEdge  = '';          // single edge-type filter, '' = all
let currentView   = 'topology';
let impactDir     = 'downstream';
let impactDepth   = 6;
let showAmbiguous = true;
let focusQuery    = '';
let selectedNode  = null;

// ─── D3 selections ─────────────────────────────────────────────────────────

const svg       = d3.select('#graph-svg');
const zoomGroup = svg.select('#zoom-group');
const tooltip   = document.getElementById('tooltip');
let linkSel, nodeSel, simulation;

// ─── Bootstrap ─────────────────────────────────────────────────────────────

async function init() {
  try {
    const [sumRes, nodeRes, edgeRes] = await Promise.all([
      fetch('/api/summary'), fetch('/api/nodes'), fetch('/api/edges'),
    ]);
    const summary = await sumRes.json();
    allNodes = await nodeRes.json();
    allEdges = await edgeRes.json();
    visibleTypes = new Set(allNodes.map(n => n.type));

    renderStatsTiles(summary);
    buildNodeTypeFilter();
    buildEdgeTypeFilter();
    wireControls();
    buildGraph();
  } catch (err) {
    console.error('Constrictor init failed:', err);
  }
}

// ─── Stats tiles ───────────────────────────────────────────────────────────

function renderStatsTiles(summary) {
  const s   = summary.statistics || {};
  const ntc = s.node_type_counts || {};
  const tiles = [
    { key: 'NODES',     val: s.total_nodes  ?? allNodes.length },
    { key: 'EDGES',     val: s.total_edges  ?? allEdges.length },
    { key: 'ENDPOINTS', val: ntc.ENDPOINT   ?? 0 },
    { key: 'FUNCTIONS', val: (ntc.FUNCTION ?? 0) + (ntc.METHOD ?? 0) },
    { key: 'CLASSES',   val: ntc.CLASS      ?? 0 },
    { key: 'SERVICES',  val: (ntc.SERVICE ?? 0) + (ntc.COMPONENT ?? 0) },
    { key: 'AMBIGUOUS', val: s.warning_count ?? 0 },
  ];
  document.getElementById('stats-tiles').innerHTML =
    tiles.map(t => `<div class="stat-tile">
      <div class="stat-val">${fmtNum(t.val)}</div>
      <div class="stat-key">${t.key}</div>
    </div>`).join('');
}

function fmtNum(n) {
  if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
  return String(n ?? 0);
}

// ─── Node type filter (left panel checklist) ───────────────────────────────

function buildNodeTypeFilter() {
  const types = [...new Set(allNodes.map(n => n.type))].sort();
  const list  = document.getElementById('nodetype-list');
  list.innerHTML = '';
  for (const t of types) {
    const label = document.createElement('label');
    label.className = 'fc-item';
    const dot = document.createElement('span');
    dot.className = 'fc-dot';
    dot.style.background = nodeColor(t);
    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.checked = true;
    cb.addEventListener('change', () => {
      if (cb.checked) visibleTypes.add(t); else visibleTypes.delete(t);
      rebuildGraph();
    });
    label.appendChild(cb); label.appendChild(dot);
    label.appendChild(document.createTextNode(t));
    list.appendChild(label);
  }
}

// ─── Edge type filter ──────────────────────────────────────────────────────

function buildEdgeTypeFilter() {
  const types = [...new Set(allEdges.map(e => e.type))].sort();
  const sel   = document.getElementById('edgetype-filter');
  for (const t of types) {
    const opt = document.createElement('option');
    opt.value = t; opt.textContent = t; sel.appendChild(opt);
  }
  sel.addEventListener('change', () => {
    const chosen = [...sel.selectedOptions].map(o => o.value).filter(Boolean);
    filteredEdge = chosen.length ? chosen[0] : '';
    rebuildGraph();
  });
}

// ─── Wire controls ─────────────────────────────────────────────────────────

function wireControls() {
  // View buttons
  document.querySelectorAll('.view-btn').forEach(btn =>
    btn.addEventListener('click', () => {
      document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      switchView(btn.dataset.view);
    })
  );

  // Focus search
  document.getElementById('focus-search').addEventListener('input', e => {
    focusQuery = e.target.value.trim().toLowerCase();
    applyHighlights();
  });

  // Direction toggle
  document.querySelectorAll('.dir-btn').forEach(btn =>
    btn.addEventListener('click', () => {
      document.querySelectorAll('.dir-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      impactDir = btn.dataset.dir;
      if (selectedNode) showRightPanel(selectedNode);
    })
  );

  // Depth slider
  const slider = document.getElementById('depth-slider');
  const valEl  = document.getElementById('depth-val');
  slider.addEventListener('input', () => {
    impactDepth = parseInt(slider.value, 10);
    valEl.textContent = impactDepth;
    if (selectedNode) showRightPanel(selectedNode);
  });

  // Show ambiguous toggle
  document.getElementById('show-ambiguous').addEventListener('change', e => {
    showAmbiguous = e.target.checked;
    rebuildGraph();
  });

  // Path inspector
  document.getElementById('find-paths-btn').addEventListener('click', runPathInspector);
  document.getElementById('path-from').addEventListener('keydown', e => { if (e.key === 'Enter') runPathInspector(); });
  document.getElementById('path-to').addEventListener('keydown',   e => { if (e.key === 'Enter') runPathInspector(); });
}

// ─── View switching ────────────────────────────────────────────────────────

function switchView(view) {
  currentView = view;
  const graphView = document.getElementById('graph-view');
  const auditView = document.getElementById('audit-view');
  if (view === 'audit') {
    graphView.style.display = 'none';
    auditView.style.display = '';
    renderAuditView();
  } else {
    graphView.style.display = '';
    auditView.style.display = 'none';
    rebuildGraph();
  }
}

// ─── Audit view ────────────────────────────────────────────────────────────

async function renderAuditView() {
  const container = document.getElementById('audit-content');
  container.innerHTML = '<div style="color:var(--text-muted);padding:20px">Loading audit data\u2026</div>';
  try {
    const res  = await fetch('/api/audit');
    if (!res.ok) throw new Error(res.statusText);
    const data  = await res.json();
    const edges = data.edges || [];

    if (edges.length === 0) {
      container.innerHTML = '<div class="audit-empty">\u2713 No ambiguous or unresolved edges found.</div>';
      return;
    }

    container.innerHTML =
      `<div class="audit-header">Ambiguous / Unresolved Audit</div>` +
      `<div class="audit-counts">${data.unresolved_count} unresolved \u00b7 ${data.ambiguous_count} ambiguous</div>`;

    for (const e of edges.slice(0, 300)) {
      const cert      = (e.certainty || '').toUpperCase();
      const certClass = cert === 'UNRESOLVED' ? 'unresolved' : 'inferred';
      const certLabel = cert || 'AMBIGUOUS';
      const name      = e.display_name || `${e.source_name} \u2192 ${e.target_name}`;
      const srcFile   = e.source_file ? `<span style="color:var(--border)"> \u00b7 </span><span style="color:var(--cyan)">${escHtml(shortPath(e.source_file))}</span>` : '';
      const div = document.createElement('div');
      div.className = 'audit-edge';
      div.innerHTML =
        `<div class="audit-edge-type">${escHtml(e.type || '')}</div>` +
        `<div class="audit-edge-name">${escHtml(name)}</div>` +
        `<div class="audit-edge-meta"><span class="cert-badge ${certClass}">${certLabel}</span>${escHtml(e.source_name || '')}${srcFile}</div>`;
      container.appendChild(div);
    }
    if (edges.length > 300) {
      const more = document.createElement('div');
      more.className = 'audit-empty';
      more.textContent = `\u2026and ${edges.length - 300} more`;
      container.appendChild(more);
    }
  } catch (err) {
    container.innerHTML = `<div class="audit-empty">Error loading audit: ${escHtml(String(err))}</div>`;
  }
}

// ─── Path inspector ────────────────────────────────────────────────────────

async function runPathInspector() {
  const from    = document.getElementById('path-from').value.trim();
  const to      = document.getElementById('path-to').value.trim();
  const results = document.getElementById('path-results');
  if (!from || !to) {
    results.innerHTML = '<span style="color:var(--red)">Enter both nodes.</span>';
    return;
  }
  results.innerHTML = '<span style="color:var(--text-muted)">Searching\u2026</span>';
  try {
    const resp = await fetch(
      `/api/paths?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&depth=${impactDepth}`
    );
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      results.innerHTML = `<span style="color:var(--red)">${escHtml(err.detail || 'Not found')}</span>`;
      return;
    }
    const data  = await resp.json();
    const paths = data.paths || [];
    if (paths.length === 0) {
      results.innerHTML = '<span style="color:var(--text-muted)">No paths found.</span>';
      return;
    }
    results.innerHTML = `<div style="margin-bottom:4px;font-size:10px;color:var(--text-muted)">${paths.length} path${paths.length > 1 ? 's' : ''} found</div>`;
    for (const p of paths.slice(0, 10)) {
      const nodes    = (p.nodes || []).map(n => n.display_name || n.qualified_name || String(n));
      const hopCount = p.hop_count !== undefined ? p.hop_count : (p.edges || []).length;
      const div = document.createElement('div');
      div.className = 'path-entry';
      div.innerHTML =
        `<div class="path-hop-count">${hopCount} hop${hopCount !== 1 ? 's' : ''}</div>` +
        `<div class="path-nodes">${nodes.map(escHtml).join(' \u2192 ')}</div>`;
      results.appendChild(div);
    }
    if (paths.length > 10) {
      const more = document.createElement('div');
      more.style.cssText = 'font-size:10px;color:var(--text-muted);text-align:center';
      more.textContent = `\u2026and ${paths.length - 10} more`;
      results.appendChild(more);
    }
  } catch (err) {
    results.innerHTML = `<span style="color:var(--red)">${escHtml(String(err))}</span>`;
  }
}

// ─── Graph build ───────────────────────────────────────────────────────────

function getVisibleNodes() {
  let nodes = allNodes.filter(n => visibleTypes.has(n.type));
  const vf = VIEW_FILTER[currentView];
  if (vf) nodes = nodes.filter(n => vf.has(n.type));
  return nodes;
}

function getVisibleEdges(visNodeIds) {
  let edges = allEdges.filter(
    e => visNodeIds.has(e.source_id) && visNodeIds.has(e.target_id)
  );
  if (filteredEdge) edges = edges.filter(e => e.type === filteredEdge);
  if (!showAmbiguous) edges = edges.filter(e => !e.certainty || e.certainty === 'EXACT');
  return edges;
}

function buildGraph() {
  const container = document.getElementById('graph-view');
  svg.call(
    d3.zoom().scaleExtent([0.05, 5])
      .on('zoom', e => zoomGroup.attr('transform', e.transform))
  );
  renderGraph(container.clientWidth, container.clientHeight);
}

function rebuildGraph() {
  if (currentView === 'audit') return;
  const container = document.getElementById('graph-view');
  if (simulation) simulation.stop();
  zoomGroup.selectAll('*').remove();
  renderGraph(container.clientWidth, container.clientHeight);
}

function renderGraph(width, height) {
  const visNodes   = getVisibleNodes();
  const visNodeIds = new Set(visNodes.map(n => n.id));
  const visEdges   = getVisibleEdges(visNodeIds);
  const serviceMap = buildServiceMap(visNodes, visEdges);
  const simNodes   = visNodes.map(n => ({ ...n }));
  const nodeById   = Object.fromEntries(simNodes.map(n => [n.id, n]));

  const simEdges = visEdges.map(e => ({
    ...e,
    source: nodeById[e.source_id] ?? e.source_id,
    target: nodeById[e.target_id] ?? e.target_id,
  })).filter(e => typeof e.source === 'object' && typeof e.target === 'object');

  const hullGroup = zoomGroup.append('g').attr('class', 'hulls');
  renderHulls(hullGroup, serviceMap, nodeById);

  linkSel = zoomGroup.append('g').attr('class', 'links')
    .selectAll('line').data(simEdges).join('line').attr('class', 'link');

  nodeSel = zoomGroup.append('g').attr('class', 'nodes')
    .selectAll('g').data(simNodes).join('g').attr('class', 'node')
    .call(d3.drag()
      .on('start', dragStart).on('drag', dragging).on('end', dragEnd))
    .on('click', onNodeClick)
    .on('mouseover', onNodeHover)
    .on('mouseout', onNodeOut);

  nodeSel.append('circle')
    .attr('r', d => nodeRadius(d.type))
    .attr('fill', d => nodeColor(d.type))
    .attr('stroke', d => d3.color(nodeColor(d.type)).brighter(0.6))
    .attr('stroke-opacity', 0.6);

  nodeSel.append('text')
    .attr('dy', d => nodeRadius(d.type) + 4)
    .text(d => truncate(d.display_name, 20));

  simulation = d3.forceSimulation(simNodes)
    .force('link', d3.forceLink(simEdges).id(d => d.id).distance(60).strength(0.3))
    .force('charge', d3.forceManyBody().strength(-120))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collide', d3.forceCollide(d => nodeRadius(d.type) + 8))
    .on('tick', () => {
      linkSel
        .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => targetX(d)).attr('y2', d => targetY(d));
      nodeSel.attr('transform', d => `translate(${d.x},${d.y})`);
      updateHulls(hullGroup, serviceMap, nodeById);
    });

  applyHighlights();
}

// ─── Service hulls ─────────────────────────────────────────────────────────

function buildServiceMap(nodes, edges) {
  const map = new Map();
  for (const n of nodes) {
    if (n.type === 'SERVICE' || n.type === 'COMPONENT') map.set(n.id, new Set([n.id]));
  }
  for (const e of edges) {
    if (e.type === 'BELONGS_TO_SERVICE' && map.has(e.target_id))
      map.get(e.target_id).add(e.source_id);
  }
  return map;
}

function renderHulls(g, serviceMap, nodeById) {
  g.selectAll('.hull').data([...serviceMap.keys()]).join('path')
    .attr('class', 'hull')
    .attr('fill',   id => nodeColor((nodeById[id] || {}).type || 'SERVICE'))
    .attr('stroke', id => nodeColor((nodeById[id] || {}).type || 'SERVICE'));
}

function updateHulls(g, serviceMap, nodeById) {
  g.selectAll('.hull').each(function(id) {
    const members = serviceMap.get(id);
    if (!members || members.size < 2) return;
    const pts = [...members].map(i => nodeById[i]).filter(Boolean).map(n => [n.x, n.y]);
    if (pts.length < 2) return;
    try {
      const hull = d3.polygonHull(padHull(pts, 20));
      if (hull) d3.select(this).attr('d', `M${hull.join('L')}Z`);
    } catch (_) {}
  });
}

function padHull(pts, pad) {
  const cx = d3.mean(pts, d => d[0]), cy = d3.mean(pts, d => d[1]);
  return pts.map(([x, y]) => {
    const dx = x - cx, dy = y - cy, len = Math.sqrt(dx * dx + dy * dy) || 1;
    return [x + (dx / len) * pad, y + (dy / len) * pad];
  });
}

// ─── Arrow geometry ────────────────────────────────────────────────────────

function targetX(d) {
  const r = nodeRadius(d.target.type) + 6;
  const dx = d.target.x - d.source.x, dy = d.target.y - d.source.y;
  const dist = Math.sqrt(dx * dx + dy * dy) || 1;
  return d.target.x - (dx / dist) * r;
}
function targetY(d) {
  const r = nodeRadius(d.target.type) + 6;
  const dx = d.target.x - d.source.x, dy = d.target.y - d.source.y;
  const dist = Math.sqrt(dx * dx + dy * dy) || 1;
  return d.target.y - (dy / dist) * r;
}

// ─── Drag ──────────────────────────────────────────────────────────────────

function dragStart(e, d) { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }
function dragging(e, d)  { d.fx = e.x; d.fy = e.y; }
function dragEnd(e, d)   { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }

// ─── Node click ────────────────────────────────────────────────────────────

function onNodeClick(event, d) {
  event.stopPropagation();
  selectedNode = d;
  showRightPanel(d);
  applyHighlights();
}

svg.on('click', () => {
  selectedNode = null;
  hideRightPanel();
  applyHighlights();
});

// ─── Tooltip ───────────────────────────────────────────────────────────────

function onNodeHover(event, d) {
  tooltip.innerHTML =
    `<strong>${escHtml(d.display_name)}</strong><br>` +
    `<span class="tt-type">${d.type}</span>` +
    (d.file_path ? `<br><span style="color:#22d3ee;font-size:10px">${escHtml(shortPath(d.file_path))}</span>` : '');
  tooltip.classList.add('visible');
  moveTooltip(event);
}
function onNodeOut() { tooltip.classList.remove('visible'); }
document.addEventListener('mousemove', e => {
  if (tooltip.classList.contains('visible')) moveTooltip(e);
});
function moveTooltip(e) {
  const pad = 14;
  let x = e.clientX + pad, y = e.clientY + pad;
  if (x + 290 > window.innerWidth)  x = e.clientX - 290 - pad;
  if (y + 80  > window.innerHeight) y = e.clientY - 80;
  tooltip.style.left = `${x}px`; tooltip.style.top = `${y}px`;
}

// ─── Right panel ───────────────────────────────────────────────────────────

async function showRightPanel(node) {
  document.getElementById('rp-empty').style.display = 'none';
  const content = document.getElementById('rp-content');
  content.style.display = 'flex';

  const dirLabel = impactDir === 'downstream' ? 'Downstream Impact' : 'Upstream (Dependents)';
  content.innerHTML = `
    <div class="card">
      <span class="node-badge">
        <span class="fc-dot" style="background:${nodeColor(node.type)}"></span>
        ${escHtml(node.type)}
      </span>
      <div class="node-name">${escHtml(node.display_name)}</div>
      <div class="node-qname">${escHtml(node.qualified_name)}</div>
      ${node.file_path ? `<div class="node-file">${escHtml(shortPath(node.file_path))}${node.line_number ? ':' + node.line_number : ''}</div>` : ''}
    </div>
    ${Object.keys(node.metadata || {}).length ? `
    <div class="card">
      <h3>Metadata</h3>
      <table class="meta-table">
        ${Object.entries(node.metadata).map(([k, v]) =>
          `<tr><td>${escHtml(k)}</td><td>${escHtml(v)}</td></tr>`
        ).join('')}
      </table>
    </div>` : ''}
    <div class="card" id="impact-card">
      <h3>${dirLabel}</h3>
      <div id="impact-loading" style="font-size:11px;color:var(--text-muted)">Loading\u2026</div>
    </div>`;

  try {
    const resp = await fetch(
      `/api/impact?node=${encodeURIComponent(node.id)}&direction=${impactDir}&depth=${impactDepth}`
    );
    if (!resp.ok) throw new Error(resp.statusText);
    renderImpactList('impact-card', dirLabel, await resp.json(), impactDir);
  } catch (_) {
    const el = document.getElementById('impact-loading');
    if (el) el.textContent = 'Could not load impact.';
  }
}

function renderImpactList(cardId, title, subgraph, direction) {
  const card  = document.getElementById(cardId);
  if (!card) return;
  const nodes = subgraph.nodes || [];
  const edges = subgraph.edges || [];
  const edgeLabel = {};
  for (const e of edges) {
    const key = direction === 'downstream' ? e.target_id : e.source_id;
    edgeLabel[key] = e.type;
  }
  card.innerHTML = `<h3>${title} <span style="color:var(--text-muted);font-weight:400;font-size:10px">(${nodes.length})</span></h3>`;
  if (nodes.length === 0) {
    card.innerHTML += `<div style="font-size:11px;color:var(--text-muted)">None found.</div>`;
    return;
  }
  const ul = document.createElement('ul');
  ul.className = 'impact-list';
  for (const n of nodes.slice(0, 40)) {
    const li = document.createElement('li');
    li.className = 'impact-item';
    li.innerHTML = `
      <span class="fc-dot" style="background:${nodeColor(n.type)};flex-shrink:0;margin-top:3px"></span>
      <span style="flex:1">${escHtml(n.display_name)}</span>
      ${edgeLabel[n.id] ? `<span class="edge-label">${escHtml(edgeLabel[n.id])}</span>` : ''}`;
    li.addEventListener('click', () => {
      const d = nodeSel && nodeSel.data().find(x => x.id === n.id);
      if (d) { selectedNode = d; showRightPanel(d); applyHighlights(); }
    });
    ul.appendChild(li);
  }
  if (nodes.length > 40) {
    const more = document.createElement('li');
    more.style.cssText = 'font-size:10px;color:var(--text-muted);padding:3px 5px';
    more.textContent = `\u2026and ${nodes.length - 40} more`;
    ul.appendChild(more);
  }
  card.appendChild(ul);
}

function hideRightPanel() {
  document.getElementById('rp-empty').style.display = '';
  document.getElementById('rp-content').style.display = 'none';
}

// ─── Highlights ────────────────────────────────────────────────────────────

function applyHighlights() {
  if (!nodeSel || !linkSel) return;
  const q = focusQuery.toLowerCase();
  nodeSel.classed('selected', d => selectedNode && d.id === selectedNode.id);

  if (!selectedNode && !q) {
    nodeSel.classed('dimmed', false);
    linkSel.classed('highlight', false).classed('dimmed', false);
    return;
  }

  if (q && !selectedNode) {
    nodeSel.classed('dimmed', d => !matchesSearch(d, q));
    linkSel.classed('dimmed', true).classed('highlight', false);
    return;
  }

  const connected = new Set([selectedNode.id]);
  linkSel.each(d => {
    const s = typeof d.source === 'object' ? d.source.id : d.source;
    const t = typeof d.target === 'object' ? d.target.id : d.target;
    if (s === selectedNode.id || t === selectedNode.id) { connected.add(s); connected.add(t); }
  });

  nodeSel.classed('dimmed', d => !connected.has(d.id));
  linkSel
    .classed('highlight', d => {
      const s = typeof d.source === 'object' ? d.source.id : d.source;
      const t = typeof d.target === 'object' ? d.target.id : d.target;
      return s === selectedNode.id || t === selectedNode.id;
    })
    .classed('dimmed', d => {
      const s = typeof d.source === 'object' ? d.source.id : d.source;
      const t = typeof d.target === 'object' ? d.target.id : d.target;
      return !(connected.has(s) && connected.has(t));
    });
}

function matchesSearch(node, q) {
  return (
    node.display_name.toLowerCase().includes(q)    ||
    node.qualified_name.toLowerCase().includes(q)  ||
    (node.file_path || '').toLowerCase().includes(q)
  );
}

// ─── Utilities ─────────────────────────────────────────────────────────────

function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function truncate(str, max) { return str && str.length > max ? str.slice(0, max) + '\u2026' : str; }
function shortPath(p) {
  if (!p) return '';
  const parts = p.replace(/\\/g, '/').split('/');
  return parts.length > 3 ? '\u2026/' + parts.slice(-3).join('/') : p;
}

// ─── Start ─────────────────────────────────────────────────────────────────

init();


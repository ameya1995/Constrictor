/* Constrictor Graph Explorer — app.js
 *
 * Uses D3 v7 for force-directed graph rendering.
 * Data is fetched from the Constrictor web API at runtime.
 */

// ─── Node type colours ─────────────────────────────────────────────────────

const NODE_COLORS = {
  MODULE:          '#60a5fa',
  PACKAGE:         '#93c5fd',
  CLASS:           '#a78bfa',
  FUNCTION:        '#34d399',
  METHOD:          '#6ee7b7',
  ENDPOINT:        '#fbbf24',
  SERVICE:         '#f87171',
  COMPONENT:       '#fb923c',
  SQLALCHEMY_MODEL:'#c084fc',
  TABLE:           '#fb923c',
  EXTERNAL_MODULE: '#94a3b8',
  EXTERNAL_SERVICE:'#94a3b8',
  EXTERNAL_ENDPOINT:'#94a3b8',
  VARIABLE:        '#cbd5e1',
  DECORATOR:       '#e2e8f0',
};

const NODE_RADIUS = {
  SERVICE:   14,
  COMPONENT: 12,
  MODULE:    10,
  PACKAGE:   10,
  CLASS:      9,
  FUNCTION:   7,
  METHOD:     6,
  ENDPOINT:   8,
  default:    6,
};

function nodeColor(type) { return NODE_COLORS[type] || '#cbd5e1'; }
function nodeRadius(type) { return NODE_RADIUS[type] || NODE_RADIUS.default; }

// ─── State ─────────────────────────────────────────────────────────────────

let allNodes = [];
let allEdges = [];
let visibleTypes = new Set(Object.keys(NODE_COLORS));
let selectedNode = null;
let searchQuery = '';

// ─── D3 selections ─────────────────────────────────────────────────────────

const svg = d3.select('#graph-svg');
const zoomGroup = svg.select('#zoom-group');
const tooltip = document.getElementById('tooltip');

let linkSel, nodeSel, simulation;

// ─── Bootstrap ─────────────────────────────────────────────────────────────

async function init() {
  try {
    const [summaryRes, nodesRes, edgesRes] = await Promise.all([
      fetch('/api/summary'),
      fetch('/api/nodes'),
      fetch('/api/edges'),
    ]);
    const summary = await summaryRes.json();
    allNodes = await nodesRes.json();
    allEdges = await edgesRes.json();

    renderStatsBar(summary.statistics);
    buildFilterBar();
    buildGraph();
  } catch (err) {
    document.getElementById('stats-bar').textContent = 'Error loading graph data.';
    console.error(err);
  }
}

// ─── Stats bar ─────────────────────────────────────────────────────────────

function renderStatsBar(stats) {
  const el = document.getElementById('stats-bar');
  el.textContent = `${stats.total_nodes ?? allNodes.length} nodes · ${stats.total_edges ?? allEdges.length} edges`;
}

// ─── Filter bar ────────────────────────────────────────────────────────────

function buildFilterBar() {
  const presentTypes = [...new Set(allNodes.map(n => n.type))].sort();
  const bar = document.getElementById('filter-bar');
  bar.innerHTML = '';

  for (const t of presentTypes) {
    const chip = document.createElement('label');
    chip.className = 'filter-chip';

    const dot = document.createElement('span');
    dot.className = 'dot';
    dot.style.background = nodeColor(t);

    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = true;
    cb.addEventListener('change', () => {
      if (cb.checked) visibleTypes.add(t);
      else visibleTypes.delete(t);
      rebuildGraph();
    });

    chip.appendChild(dot);
    chip.appendChild(cb);
    chip.appendChild(document.createTextNode(t));
    bar.appendChild(chip);
  }
}

// ─── Search ────────────────────────────────────────────────────────────────

document.getElementById('search-box').addEventListener('input', (e) => {
  searchQuery = e.target.value.trim().toLowerCase();
  applyHighlights();
});

// ─── Graph build ───────────────────────────────────────────────────────────

function getVisibleNodes() {
  return allNodes.filter(n => visibleTypes.has(n.type));
}

function getVisibleEdges(visibleNodeIds) {
  return allEdges.filter(
    e => visibleNodeIds.has(e.source_id) && visibleNodeIds.has(e.target_id)
  );
}

function buildGraph() {
  const width = document.getElementById('graph-container').clientWidth;
  const height = document.getElementById('graph-container').clientHeight;

  svg.call(
    d3.zoom()
      .scaleExtent([0.05, 5])
      .on('zoom', (event) => zoomGroup.attr('transform', event.transform))
  );

  renderGraph(width, height);
}

function rebuildGraph() {
  const width = document.getElementById('graph-container').clientWidth;
  const height = document.getElementById('graph-container').clientHeight;
  if (simulation) simulation.stop();
  zoomGroup.selectAll('*').remove();
  renderGraph(width, height);
}

function renderGraph(width, height) {
  const visNodes = getVisibleNodes();
  const visNodeIds = new Set(visNodes.map(n => n.id));
  const visEdges = getVisibleEdges(visNodeIds);

  // Build service → member map for hull rendering
  const serviceMap = buildServiceMap(visNodes, visEdges);

  // D3 wants mutable objects for simulation
  const simNodes = visNodes.map(n => ({ ...n }));
  const nodeById = Object.fromEntries(simNodes.map(n => [n.id, n]));

  const simEdges = visEdges.map(e => ({
    ...e,
    source: nodeById[e.source_id] ?? e.source_id,
    target: nodeById[e.target_id] ?? e.target_id,
  })).filter(e => typeof e.source === 'object' && typeof e.target === 'object');

  // Service hulls (rendered first so they sit behind nodes)
  const hullGroup = zoomGroup.append('g').attr('class', 'hulls');
  renderHulls(hullGroup, serviceMap, nodeById);

  // Links
  linkSel = zoomGroup.append('g')
    .attr('class', 'links')
    .selectAll('line')
    .data(simEdges)
    .join('line')
    .attr('class', 'link');

  // Nodes
  nodeSel = zoomGroup.append('g')
    .attr('class', 'nodes')
    .selectAll('g')
    .data(simNodes)
    .join('g')
    .attr('class', 'node')
    .call(
      d3.drag()
        .on('start', dragStart)
        .on('drag', dragging)
        .on('end', dragEnd)
    )
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
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => targetX(d))
        .attr('y2', d => targetY(d));

      nodeSel.attr('transform', d => `translate(${d.x},${d.y})`);
      updateHulls(hullGroup, serviceMap, nodeById);
    });

  applyHighlights();
}

// ─── Hulls (service boundaries) ────────────────────────────────────────────

function buildServiceMap(nodes, edges) {
  const services = nodes.filter(n => n.type === 'SERVICE' || n.type === 'COMPONENT');
  const map = new Map(); // serviceId -> Set of member node ids

  for (const svc of services) {
    map.set(svc.id, new Set([svc.id]));
  }

  for (const edge of edges) {
    if (edge.type === 'BELONGS_TO_SERVICE') {
      const svcId = edge.target_id;
      if (map.has(svcId)) {
        map.get(svcId).add(edge.source_id);
      }
    }
  }
  return map;
}

function renderHulls(g, serviceMap, nodeById) {
  g.selectAll('.hull').data([...serviceMap.keys()]).join('path')
    .attr('class', 'hull')
    .attr('fill', (svcId) => nodeColor((nodeById[svcId] || {}).type || 'SERVICE'))
    .attr('stroke', (svcId) => nodeColor((nodeById[svcId] || {}).type || 'SERVICE'));
}

function updateHulls(g, serviceMap, nodeById) {
  g.selectAll('.hull').each(function(svcId) {
    const memberIds = serviceMap.get(svcId);
    if (!memberIds || memberIds.size < 2) return;

    const pts = [...memberIds]
      .map(id => nodeById[id])
      .filter(Boolean)
      .map(n => [n.x, n.y]);

    if (pts.length < 2) return;

    try {
      const padded = padHull(pts, 20);
      const hull = d3.polygonHull(padded);
      if (hull) d3.select(this).attr('d', `M${hull.join('L')}Z`);
    } catch (_) {}
  });
}

function padHull(pts, padding) {
  const cx = d3.mean(pts, d => d[0]);
  const cy = d3.mean(pts, d => d[1]);
  return pts.map(([x, y]) => {
    const dx = x - cx, dy = y - cy;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    return [x + (dx / len) * padding, y + (dy / len) * padding];
  });
}

// ─── Arrow helpers ─────────────────────────────────────────────────────────

function targetX(d) {
  const r = nodeRadius(d.target.type) + 6;
  const dx = d.target.x - d.source.x;
  const dy = d.target.y - d.source.y;
  const dist = Math.sqrt(dx * dx + dy * dy) || 1;
  return d.target.x - (dx / dist) * r;
}
function targetY(d) {
  const r = nodeRadius(d.target.type) + 6;
  const dx = d.target.x - d.source.x;
  const dy = d.target.y - d.source.y;
  const dist = Math.sqrt(dx * dx + dy * dy) || 1;
  return d.target.y - (dy / dist) * r;
}

// ─── Drag ──────────────────────────────────────────────────────────────────

function dragStart(event, d) {
  if (!event.active) simulation.alphaTarget(0.3).restart();
  d.fx = d.x; d.fy = d.y;
}
function dragging(event, d) { d.fx = event.x; d.fy = event.y; }
function dragEnd(event, d) {
  if (!event.active) simulation.alphaTarget(0);
  d.fx = null; d.fy = null;
}

// ─── Node click ────────────────────────────────────────────────────────────

function onNodeClick(event, d) {
  event.stopPropagation();
  selectedNode = d;
  showSidebar(d);
  applyHighlights();
}

svg.on('click', () => {
  selectedNode = null;
  hideSidebar();
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

function onNodeOut() {
  tooltip.classList.remove('visible');
}

document.addEventListener('mousemove', (e) => {
  if (tooltip.classList.contains('visible')) moveTooltip(e);
});

function moveTooltip(e) {
  const pad = 14;
  let x = e.clientX + pad;
  let y = e.clientY + pad;
  if (x + 290 > window.innerWidth) x = e.clientX - 290 - pad;
  if (y + 80 > window.innerHeight) y = e.clientY - 80;
  tooltip.style.left = `${x}px`;
  tooltip.style.top = `${y}px`;
}

// ─── Sidebar ───────────────────────────────────────────────────────────────

async function showSidebar(node) {
  const empty = document.getElementById('sidebar-empty');
  const content = document.getElementById('sidebar-content');
  empty.style.display = 'none';
  content.style.display = 'flex';

  content.innerHTML = `
    <div class="card">
      <span class="node-badge">
        <span class="dot" style="background:${nodeColor(node.type)}"></span>
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
      <h3>Downstream Impact</h3>
      <div id="impact-loading">Loading…</div>
    </div>
  `;

  try {
    const resp = await fetch(`/api/impact?node=${encodeURIComponent(node.id)}&direction=downstream&depth=6`);
    if (!resp.ok) throw new Error(resp.statusText);
    const subgraph = await resp.json();
    renderImpactList('impact-card', 'Downstream Impact', subgraph, 'downstream');
  } catch (err) {
    document.getElementById('impact-loading').textContent = 'Could not load impact.';
  }

  // Upstream impact card
  const upstreamCard = document.createElement('div');
  upstreamCard.className = 'card';
  upstreamCard.id = 'upstream-card';
  upstreamCard.innerHTML = '<h3>Upstream (Dependents)</h3><div id="upstream-loading">Loading…</div>';
  content.appendChild(upstreamCard);

  try {
    const resp2 = await fetch(`/api/impact?node=${encodeURIComponent(node.id)}&direction=upstream&depth=6`);
    if (!resp2.ok) throw new Error(resp2.statusText);
    const up = await resp2.json();
    renderImpactList('upstream-card', 'Upstream (Dependents)', up, 'upstream');
  } catch (_) {
    document.getElementById('upstream-loading').textContent = 'Could not load dependents.';
  }
}

function renderImpactList(cardId, title, subgraph, direction) {
  const card = document.getElementById(cardId);
  const nodes = subgraph.nodes || [];
  const edges = subgraph.edges || [];

  // Build edge map: target_id -> edge type (downstream) or source_id -> edge type (upstream)
  const edgeLabel = {};
  for (const e of edges) {
    const key = direction === 'downstream' ? e.target_id : e.source_id;
    edgeLabel[key] = e.type;
  }

  card.innerHTML = `<h3>${title} <span style="color:var(--text-muted);font-weight:400;font-size:11px">(${nodes.length} node${nodes.length !== 1 ? 's' : ''})</span></h3>`;

  if (nodes.length === 0) {
    card.innerHTML += `<div style="font-size:12px;color:var(--text-muted)">None found.</div>`;
    return;
  }

  const ul = document.createElement('ul');
  ul.className = 'impact-list';

  for (const n of nodes.slice(0, 40)) {
    const li = document.createElement('li');
    li.className = 'impact-item';
    li.innerHTML = `
      <span class="dot" style="background:${nodeColor(n.type)};width:8px;height:8px;border-radius:50%;flex-shrink:0;margin-top:3px"></span>
      <span style="flex:1">${escHtml(n.display_name)}</span>
      ${edgeLabel[n.id] ? `<span class="edge-label">${escHtml(edgeLabel[n.id])}</span>` : ''}
    `;
    li.addEventListener('click', () => {
      const d = nodeSel && nodeSel.data().find(x => x.id === n.id);
      if (d) { selectedNode = d; showSidebar(d); applyHighlights(); }
    });
    ul.appendChild(li);
  }
  if (nodes.length > 40) {
    const more = document.createElement('li');
    more.style.cssText = 'font-size:11px;color:var(--text-muted);padding:4px 6px';
    more.textContent = `…and ${nodes.length - 40} more`;
    ul.appendChild(more);
  }
  card.appendChild(ul);
}

function hideSidebar() {
  document.getElementById('sidebar-empty').style.display = '';
  document.getElementById('sidebar-content').style.display = 'none';
}

// ─── Highlights ────────────────────────────────────────────────────────────

function applyHighlights() {
  if (!nodeSel || !linkSel) return;

  const q = searchQuery.toLowerCase();

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

  // A node is selected — dim everything not connected
  const connected = new Set([selectedNode.id]);
  linkSel.each(d => {
    const sid = typeof d.source === 'object' ? d.source.id : d.source;
    const tid = typeof d.target === 'object' ? d.target.id : d.target;
    if (sid === selectedNode.id || tid === selectedNode.id) {
      connected.add(sid);
      connected.add(tid);
    }
  });

  nodeSel.classed('dimmed', d => !connected.has(d.id));
  linkSel
    .classed('highlight', d => {
      const sid = typeof d.source === 'object' ? d.source.id : d.source;
      const tid = typeof d.target === 'object' ? d.target.id : d.target;
      return sid === selectedNode.id || tid === selectedNode.id;
    })
    .classed('dimmed', d => {
      const sid = typeof d.source === 'object' ? d.source.id : d.source;
      const tid = typeof d.target === 'object' ? d.target.id : d.target;
      return !(connected.has(sid) && connected.has(tid));
    });
}

function matchesSearch(node, q) {
  return (
    node.display_name.toLowerCase().includes(q) ||
    node.qualified_name.toLowerCase().includes(q) ||
    (node.file_path || '').toLowerCase().includes(q)
  );
}

// ─── Utilities ─────────────────────────────────────────────────────────────

function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function truncate(str, max) {
  return str && str.length > max ? str.slice(0, max) + '…' : str;
}

function shortPath(p) {
  if (!p) return '';
  const parts = p.replace(/\\/g, '/').split('/');
  return parts.length > 3 ? '…/' + parts.slice(-3).join('/') : p;
}

// ─── Start ─────────────────────────────────────────────────────────────────

init();

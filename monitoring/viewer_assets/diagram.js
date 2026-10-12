const $ = (id) => document.getElementById(id);
const WIDTH = 280, HEADER = 36, ROW = 22, GAP = 80;

export function createDiagram(openTable) {
  const canvas = $('schema-canvas'), scene = $('schema-scene');
  let nodes = new Map(), edges = [], scale = 1, x = 0, y = 0, drag, frame;
  let width = 1, height = 1, data;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.classList.add('schema-lines');
  function transform() {
    scene.style.transform = `translate(${x}px,${y}px) scale(${scale})`;
    $('diagram-zoom').textContent = `${Math.round(scale * 100)}%`;
  }
  function lines() {
    const selected = $('diagram-focus').value;
    for (const edge of edges) {
      const from = nodes.get(edge.from), to = nodes.get(edge.to);
      const forward = from.x < to.x;
      const sx = from.x + (forward ? WIDTH : 0), tx = to.x + (forward ? 0 : WIDTH);
      const fields = $('diagram-fields').checked;
      const sy = from.y + (fields ? HEADER + ROW * (edge.fromIndex + .5) : HEADER / 2);
      const ty = to.y + (fields ? HEADER + ROW * (edge.toIndex + .5) : HEADER / 2);
      const bend = Math.max(45, Math.abs(tx - sx) / 2);
      edge.path.setAttribute('d', from === to
        ? `M ${sx} ${sy} C ${sx - 60} ${sy}, ${tx - 60} ${ty}, ${tx} ${ty}`
        : `M ${sx} ${sy} C ${sx + (forward ? bend : -bend)} ${sy}, ${tx + (forward ? -bend : bend)} ${ty}, ${tx} ${ty}`);
      edge.path.classList.toggle('focused', Boolean(selected) && (edge.from === selected || edge.to === selected));
    }
  }
  function fit() {
    scale = Math.max(.05, Math.min(1, (canvas.clientWidth - 40) / width, (canvas.clientHeight - 40) / height));
    x = (canvas.clientWidth - width * scale) / 2; y = (canvas.clientHeight - height * scale) / 2;
    transform();
  }
  function zoom(next, cx = canvas.clientWidth / 2, cy = canvas.clientHeight / 2) {
    const previous = scale; scale = Math.max(.05, Math.min(2, next));
    x = cx - (cx - x) * scale / previous; y = cy - (cy - y) * scale / previous; transform();
  }
  function focus() {
    const selected = $('diagram-focus').value;
    const related = new Set([selected]);
    for (const edge of edges) if (edge.from === selected || edge.to === selected) { related.add(edge.from); related.add(edge.to); }
    for (const [name, item] of nodes) {
      item.element.classList.toggle('focused', name === selected);
      item.element.classList.toggle('dimmed', Boolean(selected) && !related.has(name));
    }
    lines();
    if (!selected) { fit(); return; }
    const item = nodes.get(selected);
    scale = Math.min(1, (canvas.clientWidth - 32) / WIDTH, (canvas.clientHeight - 32) / item.height);
    x = canvas.clientWidth / 2 - (item.x + WIDTH / 2) * scale;
    y = canvas.clientHeight / 2 - (item.y + item.height / 2) * scale; transform();
  }
  function render(database) {
    data = database;
    const previousFocus = $('diagram-focus').value;
    $('diagram-focus').replaceChildren(new Option('All tables', ''));
    for (const table of data.tables) $('diagram-focus').add(new Option(table.name, table.name));
    scene.replaceChildren(svg); svg.replaceChildren(); nodes = new Map(); edges = [];
    const levels = new Map();
    function level(table, visiting = new Set()) {
      if (levels.has(table.name)) return levels.get(table.name);
      if (visiting.has(table.name)) return 0;
      const next = new Set(visiting); next.add(table.name);
      const parents = table.relationships.map((link) => data.tables.find((candidate) => candidate.name === link.table))
        .filter((parent) => parent && parent.name !== table.name);
      const depth = parents.length ? Math.max(...parents.map((parent) => level(parent, next))) + 1 : 0;
      levels.set(table.name, depth); return depth;
    }
    const positions = new Map(); width = 1; height = 1;
    for (const table of data.tables) {
      const column = level(table), nodeX = 20 + column * (WIDTH + GAP), nodeY = positions.get(column) ?? 20;
      const nodeHeight = HEADER + ($('diagram-fields').checked ? table.fields.length * ROW : 0) + 2;
      positions.set(column, nodeY + nodeHeight + 30);
      const element = document.createElement('article'); element.className = 'schema-node'; element.dataset.table = table.name;
      element.style.left = `${nodeX}px`; element.style.top = `${nodeY}px`;
      const header = document.createElement('header'), title = document.createElement('button'), count = document.createElement('span');
      title.textContent = table.name; title.title = `Open ${table.name}`; title.onclick = () => openTable(table.name);
      count.textContent = String(table.count); header.append(title, count); element.append(header);
      if ($('diagram-fields').checked) for (const field of table.fields) {
        const row = document.createElement('div'); row.className = 'schema-field'; row.title = `${field.name}: ${field.type}`;
        const key = document.createElement('span'), name = document.createElement('span'), type = document.createElement('span');
        key.className = 'key'; type.className = 'type';
        key.textContent = [field.pk ? 'PK' : '', table.relationships.some((link) => link.from === field.name) ? 'FK' : ''].filter(Boolean).join('/');
        name.textContent = field.name; type.textContent = field.type; row.append(key, name, type); element.append(row);
      }
      header.onpointerdown = (event) => {
        if (event.target.closest('button')) return;
        drag = { kind: 'node', name: table.name, startX: event.clientX, startY: event.clientY, x: nodes.get(table.name).x, y: nodes.get(table.name).y };
        canvas.setPointerCapture(event.pointerId); event.preventDefault();
      };
      scene.append(element); nodes.set(table.name, { x: nodeX, y: nodeY, height: nodeHeight, element, table });
      width = Math.max(width, nodeX + WIDTH + 20); height = Math.max(height, nodeY + nodeHeight + 20);
    }
    for (const table of data.tables) for (const link of table.relationships) {
      if (!nodes.has(link.table)) continue;
      const path = document.createElementNS(svg.namespaceURI, 'path');
      svg.append(path); edges.push({ from: table.name, to: link.table,
        fromIndex: table.fields.findIndex((field) => field.name === link.from),
        toIndex: nodes.get(link.table).table.fields.findIndex((field) => field.name === link.to), path });
    }
    svg.setAttribute('width', width); svg.setAttribute('height', height);
    $('diagram-count').textContent = `${nodes.size} tables / ${edges.length} foreign-key links`;
    $('diagram-focus').value = nodes.has(previousFocus) ? previousFocus : '';
    focus();
  }
  canvas.onpointerdown = (event) => {
    if (event.target.closest('.schema-node')) return;
    drag = { kind: 'pan', startX: event.clientX, startY: event.clientY, x, y };
    canvas.setPointerCapture(event.pointerId);
  };
  canvas.onpointermove = (event) => {
    if (!drag) return;
    const dx = event.clientX - drag.startX, dy = event.clientY - drag.startY;
    if (drag.kind === 'pan') { x = drag.x + dx; y = drag.y + dy; transform(); }
    else {
      const item = nodes.get(drag.name); item.x = Math.max(0, drag.x + dx / scale); item.y = Math.max(0, drag.y + dy / scale);
      item.element.style.left = `${item.x}px`; item.element.style.top = `${item.y}px`;
      if (!frame) frame = requestAnimationFrame(() => { frame = null; lines(); });
    }
  };
  canvas.onpointerup = canvas.onpointercancel = () => {
    if (drag?.kind === 'node') {
      width = Math.max(...[...nodes.values()].map((item) => item.x + WIDTH + 20));
      height = Math.max(...[...nodes.values()].map((item) => item.y + item.height + 20));
      svg.setAttribute('width', width); svg.setAttribute('height', height);
    }
    drag = null;
  };
  canvas.addEventListener('wheel', (event) => {
    event.preventDefault(); const bounds = canvas.getBoundingClientRect();
    zoom(scale * Math.exp(-event.deltaY * .0015), event.clientX - bounds.left, event.clientY - bounds.top);
  }, { passive: false });
  canvas.onkeydown = (event) => {
    if (event.target !== canvas) return;
    if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', '+', '-', '='].includes(event.key)) {
      event.preventDefault();
      if (event.key === '+' || event.key === '=') zoom(scale * 1.25);
      else if (event.key === '-') zoom(scale / 1.25);
      else { x += event.key === 'ArrowLeft' ? 40 : event.key === 'ArrowRight' ? -40 : 0;
             y += event.key === 'ArrowUp' ? 40 : event.key === 'ArrowDown' ? -40 : 0; transform(); }
    }
  };
  $('diagram-zoom-in').onclick = () => zoom(scale * 1.25);
  $('diagram-zoom-out').onclick = () => zoom(scale / 1.25);
  $('diagram-fit').onclick = fit; $('diagram-reset').onclick = () => zoom(1);
  $('diagram-fields').onchange = () => render(data); $('diagram-focus').onchange = focus;
  new ResizeObserver(() => { if (!$('diagram-view').hidden && !$('diagram-focus').value) fit(); }).observe(canvas);
  return { render };
}

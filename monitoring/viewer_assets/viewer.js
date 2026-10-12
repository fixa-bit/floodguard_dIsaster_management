const $ = (id) => document.getElementById(id);
let database, selected, page = 1, request, timer, rawMode = false;
let diagram;
const labels = {
  stations: 'Station names, rivers and coordinates',
  providers: 'APIs, trained model versions and planned future models',
  station_values: 'Station-linked measurements and predictions by timestamp',
  thresholds: 'Station reference limits; NULL means not verified or configured',
};
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function valueText(value) {
  if (value === null) return 'Not configured / unavailable';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return value.toLocaleString('en-PK', { maximumFractionDigits: 8 });
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
function displayValue(value) {
  if (value !== null && typeof value === 'object') return JSON.stringify(value, null, 2);
  if (typeof value === 'string' && /^[\[{]/.test(value)) {
    try { return JSON.stringify(JSON.parse(value), null, 2); } catch { /* Preserve provider text. */ }
  }
  return valueText(value);
}
function showError(message) { $('error').textContent = message; $('error').hidden = !message; }
async function get(url, signal) {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error('Database unavailable. Check the viewer process, then refresh.');
  return response.json();
}
function nav() {
  $('table-nav').replaceChildren();
  const filter = $('table-filter').value.trim().toLowerCase();
  const databaseOrder = $('nav-order').value === 'database';
  const groups = databaseOrder ? ['Tables'] : [...new Set(database.tables.map((table) => table.group))];
  const ordered = databaseOrder ? database.schemaOrder.map((name) => database.tables.find((table) => table.name === name)) : database.tables;
  for (const group of groups) {
    const tables = ordered.filter((table) => (databaseOrder || table.group === group) && table.name.includes(filter));
    if (!tables.length) continue;
    $('table-nav').append(node('h2', group));
    for (const table of tables) {
      const button = node('button', undefined, selected?.name === table.name ? 'active' : '');
      button.append(node('span', table.name), node('span', table.count.toLocaleString()));
      button.onclick = () => openTable(table.name);
      $('table-nav').append(button);
    }
  }
}
function overview() {
  $('database-name').textContent = `${database.database} / Schema ${database.versions.at(-1)}`;
  const count = (name) => database.tables.find((table) => table.name === name)?.count ?? 0;
  $('summary').replaceChildren();
  for (const [label, value] of [['Tables', database.tables.length], ['Stations', count('stations')],
                               ['Stored values', count('station_values')], ['APIs / models', count('providers')]]) {
    const item = node('div'); item.append(node('span', label), node('strong', value.toLocaleString())); $('summary').append(item);
  }
  $('groups').replaceChildren();
  for (const group of [...new Set(database.tables.map((table) => table.group))]) {
    const section = node('section', undefined, 'group-section'); section.append(node('h2', group));
    const list = node('div', undefined, 'group-list');
    for (const table of database.tables.filter((table) => table.group === group)) {
      const button = node('button'); const title = node('div', table.name);
      title.append(node('small', labels[table.name] ?? `${table.fields.length} fields`));
      button.append(title, node('b', table.count.toLocaleString())); button.onclick = () => openTable(table.name); list.append(button);
    }
    section.append(list); $('groups').append(section);
  }
}
function rawText(value) { return value === null ? 'NULL' : String(value); }
function tableElement(headers, rows, raw = false) {
  const table = node('table'), head = node('thead'), tr = node('tr'), body = node('tbody');
  for (const header of headers) tr.append(node('th', header));
  head.append(tr); table.append(head, body);
  for (const cells of rows) {
    const row = node('tr');
    for (const value of cells) {
      const cell = node('td');
      if (value instanceof HTMLElement) cell.append(value);
      else { cell.textContent = raw ? rawText(value) : valueText(value); if (value === null) cell.className = 'missing'; cell.title = raw ? rawText(value) : displayValue(value); }
      row.append(cell);
    }
    body.append(row);
  }
  return table;
}
function fieldSchema() {
  $('fields').replaceChildren(tableElement(['Field', 'Type', 'Required', 'Key', 'Default'], selected.fields.map((field) =>
    [field.name, field.type, field.notnull || field.pk ? 'Yes' : 'No', field.pk ? `Primary ${field.pk}` : '', field.dflt_value])));
  $('relationships').replaceChildren();
  const links = selected.relationships.map((link) => ({ from: `${selected.name}.${link.from}`, to: `${link.table}.${link.to}`, target: link.table }));
  for (const table of database.tables) {
    for (const link of table.relationships.filter((link) => link.table === selected.name))
      links.push({ from: `${table.name}.${link.from}`, to: `${selected.name}.${link.to}`, target: table.name });
  }
  for (const link of links) {
    const item = node('div', undefined, 'relationship'), button = node('button', 'Open related table');
    button.onclick = () => openTable(link.target);
    item.append(node('span', `${link.from} -> ${link.to}`), button); $('relationships').append(item);
  }
  if (!links.length) $('relationships').append(node('p', 'No foreign-key relationships.'));
  $('indexes').replaceChildren(...selected.indexes.map((index) => node('p', `${index.name}${index.unique ? ' (unique)' : ''}`)));
}
function tab(which) {
  for (const name of ['data', 'raw', 'schema']) {
    $(`${name}-tab`).setAttribute('aria-selected', String(name === which));
  }
  $('data-panel').hidden = which === 'schema';
  $('schema-panel').hidden = which !== 'schema';
  if (which !== 'schema') {
    const changed = rawMode !== (which === 'raw');
    rawMode = which === 'raw';
    $('data-panel').setAttribute('aria-labelledby', `${which}-tab`);
    $('raw-order-control').hidden = !rawMode;
    if (rawMode) { $('nav-order').value = 'database'; nav(); }
    if (changed) { page = 1; loadRecords(); }
  }
}
function openTable(name) {
  $('diagram-view').hidden = true;
  selected = database.tables.find((table) => table.name === name);
  page = 1; $('record-search').value = ''; $('table-title').textContent = selected.name;
  $('table-count').textContent = `${selected.count.toLocaleString()} records`;
  $('overview').hidden = true; $('table-view').hidden = false;
  fieldSchema(); nav(); tab(rawMode ? 'raw' : 'data'); loadRecords();
}
function rowDetails(record) {
  $('row-details').replaceChildren();
  for (const [name, value] of Object.entries(record)) {
    $('row-details').append(node('dt', name), node('dd', rawMode ? rawText(value) : displayValue(value), value === null ? 'missing' : ''));
  }
  $('row-dialog').showModal();
}
async function loadRecords() {
  request?.abort(); request = new AbortController();
  const signal = request.signal;
  $('records').replaceChildren(node('p', 'Loading records...', 'empty'));
  $('previous').disabled = true; $('next').disabled = true;
  try {
    const query = new URLSearchParams({ table: selected.name, page, size: $('page-size').value,
      search: $('record-search').value, raw: rawMode ? '1' : '0', order: rawMode ? $('row-order').value : 'primary' });
    const result = await get(`/api/records?${query}`, signal);
    showError('');
    $('page-status').textContent = `${result.total.toLocaleString()} records / Page ${page} of ${Math.max(1, Math.ceil(result.total / result.size))}`;
    $('previous').disabled = page <= 1; $('next').disabled = page * result.size >= result.total;
    const headers = result.columns;
    $('records').classList.toggle('raw-table', rawMode);
    if (rawMode) {
      const table = tableElement(headers, result.rows.map((record) => headers.map((key) => record[key])), true);
      [...table.tBodies[0].rows].forEach((row, index) => {
        row.tabIndex = 0; row.title = 'Inspect record';
        row.onclick = () => rowDetails(result.rows[index]);
        row.onkeydown = (event) => { if (event.key === 'Enter') rowDetails(result.rows[index]); };
      });
      $('records').replaceChildren(table);
      if (!result.rows.length) $('records').append(node('p', 'No records available.', 'empty'));
      return;
    }
    if (!result.rows.length) { $('records').replaceChildren(node('p', 'No records available.', 'empty')); return; }
    $('records').replaceChildren(tableElement(['Details', ...headers], result.rows.map((record) => {
      const button = node('button', 'Inspect'); button.onclick = () => rowDetails(record);
      return [button, ...headers.map((key) => record[key])];
    })));
  } catch (error) { if (error.name !== 'AbortError') { showError(error.message); $('records').replaceChildren(); } }
}
async function refresh() {
  $('refresh').disabled = true;
  try {
    database = await get('/api/schema'); overview(); nav(); showError('');
    if (!$('diagram-view').hidden) diagram?.render(database);
    else if (selected) openTable(selected.name);
  }
  catch (error) { showError(error.message); }
  finally { $('refresh').disabled = false; }
}
$('refresh').onclick = refresh;
$('open-diagram').onclick = async () => {
  if (!database) return;
  request?.abort(); selected = null; nav();
  $('overview').hidden = true; $('table-view').hidden = true; $('diagram-view').hidden = false;
  try {
    if (!diagram) diagram = (await import('/diagram.js')).createDiagram(openTable);
    diagram.render(database);
  } catch { showError('Schema diagram unavailable. Refresh to retry.'); }
};
$('diagram-back').onclick = () => { $('diagram-view').hidden = true; $('overview').hidden = false; };
$('table-filter').oninput = nav;
$('nav-order').onchange = nav;
$('back').onclick = () => { request?.abort(); selected = null; $('table-view').hidden = true; $('overview').hidden = false; nav(); };
$('data-tab').onclick = () => tab('data'); $('raw-tab').onclick = () => tab('raw'); $('schema-tab').onclick = () => tab('schema');
const tabs = ['data', 'raw', 'schema'];
for (const name of tabs) $(`${name}-tab`).onkeydown = (event) => {
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    const next = tabs[(tabs.indexOf(name) + (event.key === 'ArrowRight' ? 1 : 2)) % 3];
    tab(next); $(`${next}-tab`).focus();
  }
};
$('record-search').oninput = () => { clearTimeout(timer); timer = setTimeout(() => { page = 1; loadRecords(); }, 250); };
$('page-size').onchange = () => { page = 1; loadRecords(); };
$('row-order').onchange = () => { page = 1; loadRecords(); };
$('previous').onclick = () => { page--; loadRecords(); }; $('next').onclick = () => { page++; loadRecords(); };
$('close-dialog').onclick = () => $('row-dialog').close();
refresh();

'use strict';
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
let key = sessionStorage.getItem('studio-key') || '';
let records = {analysts: [], setups: [], portfolios: []};
let editing = {analyst: 'new', setup: 'new', portfolio: 'new'};
let bars = [], currentJob = null, unlocked = false;
const today = new Date().toLocaleDateString('en-CA');
const number = value => value == null ? '—' : Number(value).toLocaleString(undefined, {maximumFractionDigits: 2});
const symbols = value => value.split(/[\s,]+/).map(s => s.trim().toUpperCase()).filter(Boolean);
function node(tag, text, cls) { const el = document.createElement(tag); if (text != null) el.textContent = text; if (cls) el.className = cls; return el; }
function notice(message) { $('#notice').textContent = message; }
async function api(path, method = 'GET', data) {
  const response = await fetch('/api/' + path, {method, headers: {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body: data === undefined ? undefined : JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail || result));
  return result;
}
function guard(fn) { return async event => { event?.preventDefault(); const button = event?.submitter; if (button) button.disabled = true; try { await fn(event); } catch (error) { notice(error.message); } finally { if (button) button.disabled = false; } }; }
function page(name) {
  $$('[data-view]').forEach(el => el.hidden = el.dataset.view !== name);
  $$('nav button').forEach(el => el.classList.toggle('active', el.dataset.page === name));
  if (name === 'jobs' && unlocked) refreshJobs().catch(error => notice(error.message));
  if (name === 'dashboard') requestAnimationFrame(drawChart);
}
$$('[data-page]').forEach(button => button.addEventListener('click', () => page(button.dataset.page)));
$('.brand').addEventListener('click', event => { event.preventDefault(); page('dashboard'); });
$$('input[type=date]').forEach(el => { el.max = today; if (!el.value) el.value = today; });
async function unlock() {
  const status = await api('status'); unlocked = true;
  sessionStorage.setItem('studio-key', key);
  $('#unlock').hidden = true; $('#workspace').hidden = false;
  $('#connection').textContent = status.signed_in ? 'ChatGPT signed in' : 'ChatGPT sign-in needed';
  notice(status.signed_in ? 'Workspace connected. Choose a symbol or a saved research setup.' : 'Workspace connected. Before AI research, run tradingagents login chatgpt in the server terminal.');
  await refreshRecords();
}
$('#unlock-form').addEventListener('submit', guard(async () => { key = $('#access-key').value.trim(); await unlock(); $('#access-key').value = ''; }));
$('#lock').addEventListener('click', () => { sessionStorage.removeItem('studio-key'); location.reload(); });
function option(value, label) { const el = node('option', label); el.value = value; return el; }
function fillSelect(el, rows, empty) { const value = el.value; el.replaceChildren(); if (empty) el.append(option('', empty)); rows.forEach(r => el.append(option(r.id, r.name))); if (rows.some(r => r.id === value)) el.value = value; }
function action(text, callback, cls = 'subtle') { const button = node('button', text, cls); button.type = 'button'; button.addEventListener('click', guard(callback)); return button; }
function renderRecords(kind, selector, edit, extra) {
  const list = $(selector); list.replaceChildren();
  if (!records[kind].length) { list.append(node('div', 'Nothing saved yet. Create your first ' + ({analysts:'analyst', setups:'setup', portfolios:'snapshot'}[kind]) + '.', 'empty')); return; }
  records[kind].forEach(record => {
    const card = node('article', null, 'card'); card.append(node('h2', record.name));
    card.append(node('p', kind === 'analysts' ? record.instructions : kind === 'setups' ? record.analysts.join(' · ') + ' · ' + record.custom_analysts.length + ' custom reviewers' : record.as_of + ' · ' + record.currency + ' · ' + record.positions.length + ' holdings', 'muted'));
    if (record.notes) card.append(node('p', record.notes, 'muted'));
    const buttons = node('div', null, 'actions'); buttons.append(action('Edit', () => edit(record)));
    if (extra) buttons.append(extra(record));
    buttons.append(action('Delete', async () => { if (!confirm('Delete ' + record.name + '?')) return; await api('records/' + kind + '/' + record.id, 'DELETE'); await refreshRecords(); }));
    card.append(buttons); list.append(card);
  });
}
async function refreshRecords() {
  const values = await Promise.all(['analysts','setups','portfolios'].map(kind => api('records/' + kind)));
  [records.analysts, records.setups, records.portfolios] = values;
  fillSelect($('#analysis-setup'), records.setups, 'Choose a setup');
  fillSelect($('#backtest-setup'), records.setups.filter(s => !s.custom_analysts.length), 'Choose a core-only setup');
  fillSelect($('#analysis-portfolio'), records.portfolios, 'No portfolio context');
  const checked = $$('input:checked', $('#custom-options')).map(el => el.value);
  $('#custom-options').replaceChildren();
  records.analysts.forEach(a => { const label = node('label', null, 'check'); const input = document.createElement('input'); input.type = 'checkbox'; input.name = 'custom_analysts'; input.value = a.id; input.checked = checked.includes(a.id); label.append(input, document.createTextNode(a.name)); $('#custom-options').append(label); });
  if (!records.analysts.length) $('#custom-options').append(node('p', 'Create custom analysts in the AI analysts tab.', 'muted'));
  renderRecords('analysts', '#analyst-list', r => { editing.analyst = r.id; fillForm($('#analyst-form'), r); $('#analyst-title').textContent = 'Edit analyst'; });
  renderRecords('setups', '#setup-list', r => { editing.setup = r.id; fillForm($('#setup-form'), r); $('#setup-title').textContent = 'Edit setup'; });
  renderRecords('portfolios', '#portfolio-list', r => { editing.portfolio = r.id; fillForm($('#portfolio-form'), r); $('#holdings').replaceChildren(); r.positions.forEach(addHolding); $('#portfolio-title').textContent = 'Edit snapshot'; }, r => action('Value holdings →', async () => queue(await api('portfolios/' + r.id + '/value', 'POST'))));
}
function fillForm(form, data) { $$('input,textarea,select', form).forEach(el => { if (!(el.name in data)) return; if (el.type === 'checkbox') el.checked = data[el.name].includes(el.value); else el.value = data[el.name]; }); }
function data(form) { return Object.fromEntries(new FormData(form)); }
$('#analyst-form').addEventListener('submit', guard(async () => { await api('records/analysts/' + editing.analyst, 'PUT', data($('#analyst-form'))); $('#analyst-form').reset(); await refreshRecords(); notice('Analyst saved. Add it to a setup to include its review.'); }));
$('#setup-form').addEventListener('submit', guard(async () => { const form = $('#setup-form'); const value = data(form); value.analysts = $$('input[name=analysts]:checked', form).map(el => el.value); value.custom_analysts = $$('input[name=custom_analysts]:checked', form).map(el => el.value); value.debate_rounds = Number(value.debate_rounds); await api('records/setups/' + editing.setup, 'PUT', value); form.reset(); await refreshRecords(); notice('Research setup saved.'); }));
['analyst','setup','portfolio'].forEach(kind => $('#' + kind + '-form').addEventListener('reset', () => { editing[kind] = 'new'; $('#' + kind + '-title').textContent = kind === 'portfolio' ? 'Save a snapshot' : 'Create a ' + (kind === 'analyst' ? 'custom analyst' : 'setup'); if (kind === 'portfolio') setTimeout(() => { $('#holdings').replaceChildren(); $('#portfolio-form [name=as_of]').value = today; }, 0); }));
$('#load-models').addEventListener('click', guard(async () => { const result = await api('models'); $('#model-options').replaceChildren(...result.models.map(m => option(m[1], m[0]))); notice('Available models loaded. Choose a model in either model field.'); }));
function addHolding(value = {}) {
  const row = node('div', null, 'holding'); const grid = node('div', null, 'three-col');
  [['ticker','Symbol','text'],['quantity','Quantity','number'],['average_price','Average price','number']].forEach(([name,title,type]) => { const label = node('label', title); const input = document.createElement('input'); input.dataset.field = name; input.type = type; input.required = true; if (type === 'number') { input.min = '0.00000001'; input.step = 'any'; } input.value = value[name] ?? ''; label.append(input); grid.append(label); });
  row.append(grid, action('Remove holding', () => row.remove())); $('#holdings').append(row);
}
$('#add-holding').addEventListener('click', () => addHolding());
$('#portfolio-form').addEventListener('submit', guard(async () => { const value = data($('#portfolio-form')); value.cash = Number(value.cash); value.positions = $$('.holding').map(row => ({ticker: $('[data-field=ticker]', row).value.toUpperCase(), quantity: Number($('[data-field=quantity]', row).value), average_price: Number($('[data-field=average_price]', row).value), currency: value.currency})); await api('records/portfolios/' + editing.portfolio, 'PUT', value); await refreshRecords(); notice('Portfolio snapshot saved. Choose Value holdings for current prices.'); }));
$('#analysis-form').addEventListener('submit', guard(async () => queue(await api('analyze', 'POST', {ticker: $('#symbol').value.trim().toUpperCase(), as_of: $('#analysis-date').value, setup_id: $('#analysis-setup').value, portfolio_id: $('#analysis-portfolio').value || null}))));
$('#scan-form').addEventListener('submit', guard(async () => { const value = data($('#scan-form')); value.tickers = symbols(value.tickers); ['min_price','min_change','min_volume'].forEach(k => value[k] = Number(value[k])); await queue(await api('scan','POST',value)); }));
$('#backtest-form').addEventListener('input', () => { const value = data($('#backtest-form')); const days = (new Date(value.end) - new Date(value.start)) / 86400000; const count = (Math.floor(days / Number(value.every_n_days)) + 1) * symbols(value.tickers).length; $('#cell-count').textContent = Number.isFinite(count) && count > 0 ? count + ' research cells · maximum 30' : 'Choose a valid date range.'; });
$('#backtest-form').addEventListener('submit', guard(async () => { const value = data($('#backtest-form')); value.tickers = symbols(value.tickers); value.every_n_days = Number(value.every_n_days); await queue(await api('backtest','POST',value)); }));
async function queue(job) { currentJob = job.id; notice('Research queued. You can keep using Studio while it runs.'); page('jobs'); await refreshJobs(); }
async function refreshJobs() {
  const jobs = await api('jobs'); const list = $('#job-list'); list.replaceChildren();
  if (!jobs.length) list.append(node('div','No research yet. Start with a saved setup or a stock scan.','empty'));
  jobs.forEach(job => { const card = node('article', null, 'card'); const title = node('div', null, 'job-title'); title.append(node('h2', job.kind + (job.request.ticker ? ' · ' + job.request.ticker : '')), node('span', job.status, 'status')); card.append(title, node('p', new Date(job.updated_at).toLocaleString(), 'muted'), action('View result', async () => { currentJob = job.id; await showJob(); })); list.append(card); });
  if (currentJob) await showJob();
}
function table(rows, columns) {
  const wrap = node('div',null,'table-wrap'); const t = node('table'); const head = node('tr'); columns.forEach(([label]) => head.append(node('th',label))); const thead = node('thead'); thead.append(head); t.append(thead); const body = node('tbody');
  rows.forEach(row => { const tr = node('tr'); columns.forEach(([,key]) => tr.append(node('td', typeof row[key] === 'number' ? number(row[key]) : row[key] ?? '—'))); body.append(tr); }); t.append(body); wrap.append(t); return wrap;
}
async function showJob() {
  const job = await api('jobs/' + currentJob); const view = $('#job-result'); view.hidden = false; view.replaceChildren(node('p', job.status.toUpperCase(), 'eyebrow'), node('h2', job.kind + ' result'));
  if (job.status !== 'completed') { view.append(node('p', job.error || 'Research is ' + job.status + '. Results will appear here when ready.', 'muted')); return; }
  const r = job.result;
  if (job.kind === 'analysis') {
    view.append(node('h2', r.ticker + ' · ' + r.rating), node('p', 'As of ' + r.as_of, 'muted'));
    const reports = [...Object.entries(r.reports), ...r.custom_reviews.map(a => ['Custom review: ' + a.name, a.report])];
    reports.forEach(([title,text]) => { const d = node('details'); d.append(node('summary', title.replaceAll('_',' ')), node('pre', typeof text === 'string' ? text : JSON.stringify(text,null,2))); view.append(d); });
  } else if (job.kind === 'scan') {
    view.append(table(r.matches, [['Symbol','ticker'],['Price','price'],['Currency','currency'],['Change %','change'],['Volume','volume'],['Bar date','date']]));
    if (!r.matches.length) view.append(node('p','No symbols matched the filters.'));
    r.errors.forEach(error => view.append(node('p', error.ticker + ': ' + error.error,'muted')));
  } else if (job.kind === 'portfolio') {
    view.append(node('h2', r.complete ? number(r.equity) + ' ' + r.currency + ' equity' : 'Valuation incomplete'), node('p','Unrealized P/L: ' + number(r.unrealized_pnl) + ' ' + r.currency));
    view.append(table(r.positions, [['Symbol','ticker'],['Units','quantity'],['Price','price'],['Value','value'],['P/L','unrealized_pnl'],['Bar date','date'],['Issue','error']]));
  } else { view.append(node('pre',r.explanation), node('p','Cells completed: ' + r.cells_run)); if (r.failures.length || r.settlement_failures.length) view.append(node('pre',JSON.stringify({failures:r.failures, settlement_failures:r.settlement_failures},null,2))); }
  view.append(action('Download result JSON', () => { const url = URL.createObjectURL(new Blob([JSON.stringify(job,null,2)], {type:'application/json'})); const a = node('a'); a.href = url; a.download = 'studio-' + job.id + '.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000); }));
}
$('#refresh-jobs').addEventListener('click', guard(refreshJobs));
setInterval(() => { if (unlocked && !document.hidden && !$('[data-view=jobs]').hidden) refreshJobs().catch(error => notice(error.message)); }, 5000);
$('#chart-form').addEventListener('submit', guard(async () => { notice('Loading daily price history…'); const result = await api('history/' + encodeURIComponent($('#symbol').value.trim().toUpperCase()) + '?period=' + $('#range').value); bars = result.bars; $('#chart-name').textContent = result.ticker + ' / ' + (result.currency || 'Currency unavailable'); $('#price').textContent = number(bars.at(-1).close); const change = (bars.at(-1).close / bars[0].close - 1) * 100; $('#change').textContent = (change >= 0 ? '+' : '') + number(change) + '% this range'; $('#change').className = change >= 0 ? 'positive' : 'negative'; $('#chart-slider').max = bars.length - 1; $('#chart-slider').value = bars.length - 1; $('#chart-source').textContent = result.source + ' · fetched ' + new Date(result.fetched_at).toLocaleString(); drawChart(); notice('Price history loaded. Last bar: ' + bars.at(-1).date + '.'); }));
function drawChart() {
  const canvas = $('#chart'); if (!bars.length || !canvas.clientWidth) return;
  const width = canvas.clientWidth, height = canvas.clientHeight, ratio = window.devicePixelRatio || 1; canvas.width = width * ratio; canvas.height = height * ratio; const c = canvas.getContext('2d'); c.scale(ratio,ratio);
  const prices = bars.map(b => b.close), low = Math.min(...prices), high = Math.max(...prices), span = high-low || 1, left = 10, right = width-65, top = 15, bottom = height-25;
  const x = i => left + i / Math.max(1,bars.length-1) * (right-left), y = p => bottom - (p-low)/span*(bottom-top);
  c.font = '10px system-ui'; c.textAlign = 'left';
  for (let n=0;n<4;n++) { const p=low+span*n/3, py=y(p); c.strokeStyle='#e6ebe4'; c.beginPath(); c.moveTo(left,py); c.lineTo(right,py); c.stroke(); c.fillStyle='#86978c'; c.fillText(number(p),right+10,py+4); }
  c.beginPath(); prices.forEach((p,i) => i ? c.lineTo(x(i),y(p)) : c.moveTo(x(i),y(p))); c.strokeStyle='#416d39'; c.lineWidth=2; c.stroke(); c.lineTo(right,bottom); c.lineTo(left,bottom); c.closePath(); const fill=c.createLinearGradient(0,top,0,bottom); fill.addColorStop(0,'#c6e59d66'); fill.addColorStop(1,'#c6e59d00'); c.fillStyle=fill; c.fill();
  const index = Math.min(Number($('#chart-slider').value), bars.length-1), bar = bars[index]; c.strokeStyle='#91a879'; c.setLineDash([4,4]); c.beginPath(); c.moveTo(x(index),top); c.lineTo(x(index),bottom); c.stroke(); c.setLineDash([]); c.fillStyle='#355c31'; c.beginPath(); c.arc(x(index),y(bar.close),4,0,Math.PI*2); c.fill();
  $('#chart-detail').textContent = bar.date + ' · Open ' + number(bar.open) + ' · High ' + number(bar.high) + ' · Low ' + number(bar.low) + ' · Close ' + number(bar.close) + ' · Volume ' + number(bar.volume);
}
$('#chart-slider').addEventListener('input', drawChart);
$('#chart').addEventListener('pointermove', event => { if (!bars.length) return; const rect = event.currentTarget.getBoundingClientRect(); $('#chart-slider').value = Math.round(Math.max(0,Math.min(1,(event.clientX-rect.left-10)/(rect.width-75)))*(bars.length-1)); drawChart(); });
window.addEventListener('resize', drawChart);
window.addEventListener('offline', () => notice('Offline. The app shell is available; research and prices need the server.'));
window.addEventListener('online', () => notice('Network restored. Refresh to retrieve current research.'));
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
if (key) unlock().catch(error => { key=''; sessionStorage.removeItem('studio-key'); notice(error.message); });

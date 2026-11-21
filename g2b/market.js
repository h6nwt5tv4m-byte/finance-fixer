'use strict';

const get = id => document.getElementById(id);
const number = new Intl.NumberFormat('ko-KR');
const won = value => number.format(value) + '원';
const eok = value => (value / 100000000).toLocaleString('ko-KR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '억 원';
const percent = (part, total) => total ? (part / total * 100).toFixed(1) + '%' : '—';
const compact = text => text.normalize('NFC').replace(/\s+/gu, '').toLowerCase();
const byName = (a, b) => a.localeCompare(b, 'ko');
const perPage = 12;
let awards = [];
let scoped = [];
let ranking = [];
let expanded = false;
let preferredProjectKey = null;
let searchTimer;
let page = 1;
const projects = new Map();
const verifiedArtKorea = new Set(['20240600280', 'R25BK00716899', 'R26BK01399555']);

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function action(text, handler, className = 'link') {
  const button = element('button', text, className);
  button.type = 'button';
  button.addEventListener('click', handler);
  return button;
}

function source(row) {
  const link = element('a', row.no + '-' + row.order + ' ↗', 'source');
  const url = new URL('https://www.g2b.go.kr/link/PNPE027_01/single/');
  url.search = new URLSearchParams({bidPbancNo: row.no, bidPbancOrd: row.order});
  link.href = url.href;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.setAttribute('aria-label', row.title + ' 나라장터 공고 ' + row.no + '-' + row.order + ' (새 창)');
  return link;
}

function fillSelect(select, pairs, firstLabel) {
  const current = select.value;
  const options = pairs.map(([value, label]) => new Option(label, value));
  if (firstLabel) options.unshift(new Option(firstLabel, ''));
  select.replaceChildren(...options);
  if (options.some(option => option.value === current)) select.value = current;
}

// 연도 범위(2024~2026 등)는 과업의 일부다. 단일 연도 접두사만 제거한다.
function projectTitle(title) {
  const prefix = /^(?:19|20)\d{2}(?:\s*년도?|\s+|(?=회계연도))\s*/u;
  const remainder = title.replace(prefix, '').trim();
  if (!remainder || /^[~～–—./-]|^부터|^\d{1,2}\s*월/u.test(remainder)) return title;
  return remainder;
}

function projectKey(row) {
  return JSON.stringify([row.agency, compact(projectTitle(row.title))]);
}

function summarize(rows) {
  const firms = new Map();
  for (const row of rows) {
    if (!firms.has(row.winner)) firms.set(row.winner, {name: row.winner, count: 0, amount: 0});
    const firm = firms.get(row.winner);
    firm.count++;
    firm.amount += row.amount;
  }
  return [...firms.values()].sort((a, b) => b.count - a.count || b.amount - a.amount || byName(a.name, b.name));
}

function showFirm(name) {
  get('firm').value = name;
  page = 1;
  renderRecords();
  get('records-title').focus();
}

const shareColors = ['#164c3b', '#c28638', '#477c96', '#9a6665', '#77844c', '#bdc1b6'];

function renderShares(ordered, totalAmount) {
  const metric = get('sort').value;
  const isMoney = metric === 'amount';
  const total = isMoney ? totalAmount : scoped.length;
  const unit = isMoney ? won : value => number.format(value) + '건';
  document.querySelectorAll('[data-metric]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.metric === metric));
  });
  get('share-legend').replaceChildren();
  get('donut').hidden = !total;
  if (!total) {
    get('share-summary').textContent = '선택한 조건에서 비중을 계산할 낙찰 자료가 없습니다.';
    return;
  }
  const leaders = ordered.filter(firm => firm[metric] === ordered[0][metric]);
  const top = ordered.slice(0, 5);
  const topSum = top.reduce((sum, firm) => sum + firm[metric], 0);
  const slices = top.map(firm => ({name: firm.name, value: firm[metric], firm: true}));
  if (ordered.length > top.length) {
    slices.push({name: '기타 ' + (ordered.length - top.length) + '개 상호', value: total - topSum, firm: false});
  }
  const stops = [];
  let sum = 0;
  for (const [index, slice] of slices.entries()) {
    const color = shareColors[slice.firm ? index : 5];
    const start = sum / total * 100;
    sum += slice.value;
    const end = index === slices.length - 1 ? 100 : sum / total * 100;
    stops.push(color + ' ' + start + '% ' + end + '%');
    const item = element('li');
    const swatch = element('i');
    swatch.style.backgroundColor = color;
    const label = slice.firm ? action(slice.name, () => showFirm(slice.name)) : element('span', slice.name);
    const share = slice.value > 0 && slice.value / total < .0005 ? '<0.1%' : percent(slice.value, total);
    item.append(swatch, label, element('b', share));
    item.title = slice.name + ' · ' + unit(slice.value) + ' / ' + unit(total);
    item.append(element('span', unit(slice.value) + ' / ' + unit(total), 'share-details'));
    get('share-legend').append(item);
  }
  // 한 조각에는 그라디언트 대신 같은 색을 사용한다.
  get('donut').style.background = slices.length === 1 ? shareColors[0] : 'conic-gradient(' + stops.join(',') + ')';
  const tied = leaders.length > 1;
  const highest = percent(ordered[0][metric], total);
  get('leader-label').textContent = tied ? '공동 1위' : '1위';
  get('leader-share').textContent = highest;
  get('leader-name').textContent = tied ? leaders.length + '개 상호' : ordered[0].name;
  const who = tied ? '공동 1위 ' + leaders.length + '개 상호' : '1위 ' + ordered[0].name;
  get('share-summary').textContent = who + (tied ? ' · 각 ' : ' · ') + highest + ' (' + unit(ordered[0][metric]) + ' / ' + unit(total) + ')';
}

function renderRanks(total) {
  const ordered = [...ranking];
  if (get('sort').value === 'amount') ordered.sort((a, b) => b.amount - a.amount || b.count - a.count || byName(a.name, b.name));
  renderShares(ordered, total);
  const displayed = expanded ? ordered : ordered.slice(0, 5);
  const nodes = displayed.map((firm, index) => {
    const row = element('tr');
    const name = element('th');
    name.scope = 'row';
    name.append(element('span', String(index + 1), 'pos'), action(firm.name, () => showFirm(firm.name)));
    const count = element('td', firm.count + '건');
    count.append(element('small', percent(firm.count, scoped.length)));
    const amount = element('td', eok(firm.amount));
    amount.append(element('small', percent(firm.amount, total)));
    row.append(name, count, amount);
    return row;
  });
  get('ranking').replaceChildren(...nodes);
  const more = get('all-ranks');
  more.hidden = ordered.length <= 5;
  more.textContent = expanded ? '상위 5개만 보기' : '전체 ' + ordered.length + '개 상호 보기';
  more.setAttribute('aria-expanded', String(expanded));
}

function longestRun(rows) {
  const counts = new Map();
  for (const r of rows) {
    const year = r.date.slice(0, 4);
    counts.set(year, (counts.get(year) || 0) + 1);
  }
  let previous;
  let length = 0;
  let longest = 0;
  let end = '';
  let winner = '';
  for (const row of rows) {
    const year = row.date.slice(0, 4);
    if (counts.get(year) > 1) {
      length = 0;
      previous = undefined;
      continue;
    }
    const continues = previous && previous.winner === row.winner && Number(previous.date.slice(0, 4)) + 1 === Number(year);
    length = continues ? length + 1 : 1;
    if (length >= longest) {
      longest = length;
      end = Number(year);
      winner = row.winner;
    }
    previous = row;
  }
  return longest > 1 ? ' · ' + winner + ' ' + (end - longest + 1) + '–' + end + '년 연속 낙찰' : '';
}

function renderHistory() {
  const rows = projects.get(get('project').value) || [];
  const verified = rows.length === verifiedArtKorea.size && rows.every(row => verifiedArtKorea.has(row.no));
  const description = verified ? '확인한 동일 사업' + longestRun(rows) : '수요기관·공고명 기준';
  get('history-meta').textContent = rows.length
    ? rows[0].agency + ' · 전체 수록기간 ' + rows.length + '건 · ' + description
    : '선택한 범위에 해당하는 사업이 없습니다.';
  get('timeline').replaceChildren(...rows.map(row => {
    const li = element('li');
    const time = element('time', row.date);
    time.dateTime = row.date;
    li.append(time, element('b', row.winner), element('span', won(row.amount) + ' · 참가 ' + row.bidders + '곳'), source(row));
    return li;
  }));
}

function selectProjects() {
  const keys = [...new Set(scoped.map(projectKey))];
  keys.sort((a, b) => {
    const left = projects.get(a);
    const right = projects.get(b);
    return right.length - left.length || byName(left[0].agency, right[0].agency) || byName(left[0].title, right[0].title);
  });
  const previous = get('project').value;
  fillSelect(get('project'), keys.map(key => {
    const rows = projects.get(key);
    return [key, projectTitle(rows[0].title) + ' · ' + rows[0].agency + ' (전체 기간 ' + rows.length + '건)'];
  }));
  const example = keys.find(key => projects.get(key).some(row => row.no === 'R26BK01399555'));
  if (keys.includes(preferredProjectKey)) get('project').value = preferredProjectKey;
  else if (!keys.includes(previous) && example) get('project').value = example;
  get('project').disabled = !keys.length;
  renderHistory();
}

function chooseProject(row) {
  preferredProjectKey = projectKey(row);
  get('project').value = preferredProjectKey;
  renderHistory();
  get('project').focus();
}

function makeRecord(row) {
  const li = element('li');
  const about = element('div');
  const meta = element('div', row.date + ' 개찰 · ', 'record-meta');
  meta.append(action(row.agency, () => {
    get('agency').value = row.agency;
    updateScope();
    get('agency').focus();
  }));
  about.append(meta, action(row.title, () => chooseProject(row), 'link record-title'));
  const result = element('div', undefined, 'record-result');
  result.append(element('b', row.winner), element('div', won(row.amount) + ' · 참가 ' + row.bidders + '곳', 'record-meta'), source(row));
  li.append(about, result);
  return li;
}

function renderRecords() {
  const firm = get('firm').value;
  const rows = firm ? scoped.filter(row => row.winner === firm) : scoped;
  const pages = Math.ceil(rows.length / perPage);
  page = Math.min(Math.max(page, 1), pages || 1);
  const start = (page - 1) * perPage;
  get('record-count').textContent = (firm ? firm + ' · ' : '') + rows.length + '건 · 개찰일 최신순';
  get('records').replaceChildren(...rows.slice(start, start + perPage).map(makeRecord));
  get('page').textContent = pages ? page + ' / ' + pages : '0건';
  get('prev').disabled = page <= 1;
  get('next').disabled = page >= pages;
}

function updateScope() {
  const year = get('year').value;
  const agency = get('agency').value;
  const query = compact(get('query').value);
  scoped = awards.filter(r => (!year || r.date.startsWith(year)) && (!agency || r.agency === agency) && compact(r.title).includes(query));
  ranking = summarize(scoped);
  const top = ranking.slice(0, 5);
  const count = top.reduce((sum, firm) => sum + firm.count, 0);
  const amount = top.reduce((sum, firm) => sum + firm.amount, 0);
  const total = ranking.reduce((sum, firm) => sum + firm.amount, 0);
  get('concentration-label').textContent = top.length ? '건수 상위 ' + top.length + '개 상호의 낙찰 비중' : '선택 범위의 낙찰 비중';
  get('concentration').textContent = percent(count, scoped.length);
  get('concentration-count').textContent = scoped.length + '건 중 ' + count + '건';
  get('concentration-amount').textContent = total ? '낙찰금액의 ' + percent(amount, total) + ' · ' + eok(total) + ' 중 ' + eok(amount) : '해당 공고 없음';
  get('status').textContent = scoped.length
    ? '선택한 범위 ' + scoped.length + '건 · 낙찰 상호 ' + ranking.length + '개 · 낙찰금액 ' + won(total)
    : '조건에 맞는 공고가 없습니다. 연도·기관을 바꾸거나 검색어를 줄여 보세요.';
  expanded = false;
  page = 1;
  renderRanks(total);
  selectProjects();
  const selectedFirm = get('firm').value;
  const firms = ranking.map(firm => [firm.name, firm.name]);
  if (selectedFirm && !firms.some(([name]) => name === selectedFirm)) {
    firms.push([selectedFirm, selectedFirm + ' (0건)']);
  }
  fillSelect(get('firm'), firms, '전체 상호');
  renderRecords();
}

async function load() {
  get('retry').hidden = true;
  get('status').textContent = '자료를 불러오는 중입니다.';
  try {
    const res = await fetch('current.json', {cache: 'no-cache'});
    if (!res.ok) throw new Error(String(res.status));
    const snapshot = await res.json();
    if (snapshot.schema !== 1 || !Array.isArray(snapshot.awards) || !snapshot.awards.length) throw new Error('자료 형식 오류');
    awards = snapshot.awards;
    projects.clear();
    for (const row of awards) {
      const key = projectKey(row);
      if (!projects.has(key)) projects.set(key, []);
      projects.get(key).push(row);
    }
    for (const rows of projects.values()) rows.sort((a, b) => a.date.localeCompare(b.date) || a.no.localeCompare(b.no));
    awards.sort((a, b) => b.date.localeCompare(a.date) || b.no.localeCompare(a.no));
    const firstDate = awards[awards.length - 1].date;
    get('coverage').textContent = firstDate + ' — ' + awards[0].date + ' 개찰분';
    const checked = new Intl.DateTimeFormat('ko-KR', {timeZone:'Asia/Seoul',year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(snapshot.checkedAt));
    const stale = Date.now() - Date.parse(snapshot.checkedAt) > 48 * 60 * 60 * 1000;
    get('refresh-note').textContent = '매일 오전 7시 15분(KST) 갱신 · 마지막 확인 ' + checked + ' (KST) · ' + snapshot.registeredThrough + ' 등록분까지 · 확인 대기 ' + snapshot.pending + '건' + (snapshot.pending ? ' · 잠정 순위' : '') + (stale ? ' · 최근 갱신 지연' : '');
    const agencies = [...new Set(awards.map(row => row.agency))].sort(byName);
    const years = [...new Set(awards.map(row => row.date.slice(0, 4)))].sort().reverse();
    fillSelect(get('agency'), agencies.map(v => [v, v]), '전체 기관');
    fillSelect(get('year'), years.map(v => [v, v + '년']), '전체 기간');
    updateScope();
    get('filters').disabled = false;
    get('analysis').hidden = false;
    get('shares').hidden = false;
  } catch (error) {
    get('status').textContent = '공고 자료를 불러오지 못했습니다.';
    get('retry').hidden = false;
  }
}

get('year').addEventListener('change', updateScope);
get('agency').addEventListener('change', updateScope);
get('query').addEventListener('input', event => {
  clearTimeout(searchTimer);
  if (event.isComposing) searchTimer = setTimeout(updateScope, 120);
  else updateScope();
});
get('query').addEventListener('compositionend', () => {
  clearTimeout(searchTimer);
  updateScope();
});
document.querySelectorAll('[data-metric]').forEach(button => {
  button.addEventListener('click', () => {
    get('sort').value = button.dataset.metric;
    get('sort').dispatchEvent(new Event('change'));
  });
});
get('sort').addEventListener('change', () => renderRanks(scoped.reduce((sum, row) => sum + row.amount, 0)));
get('all-ranks').addEventListener('click', () => {
  expanded = !expanded;
  renderRanks(scoped.reduce((sum, row) => sum + row.amount, 0));
});
get('firm').addEventListener('change', () => { page = 1; renderRecords(); });
get('project').addEventListener('change', () => {
  preferredProjectKey = get('project').value;
  renderHistory();
});
get('reset').addEventListener('click', () => {
  for (const id of ['year', 'agency', 'query', 'firm']) get(id).value = '';
  clearTimeout(searchTimer);
  preferredProjectKey = null;
  get('project').selectedIndex = -1;
  get('sort').value = 'amount';
  updateScope();
});
for (const [id, delta] of [['prev', -1], ['next', 1]]) {
  get(id).addEventListener('click', () => {
    page += delta;
    renderRecords();
    if (get(id).disabled) get(id === 'prev' ? 'next' : 'prev').focus();
  });
}
get('retry').addEventListener('click', load);
load();

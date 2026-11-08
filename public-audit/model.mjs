// Presentation and download use the same public snapshot and field definitions.
export const PAGE_SIZE = 25;
export const normalize = value => String(value || '').normalize('NFC').replace(/\s+/gu, '').toLocaleLowerCase('ko');
export function readState(search, data) {
  const p = new URLSearchParams(search);
  const state = {q:(p.get('q') || '').trim().slice(0,100), group:'', type:'', region:'', year:data.years[0], page:1, id:p.get('id') || ''};
  for (const key of ['group','type','region']) {
    const v = p.get(key) || '';
    if (data.institutions.some(o => (key === 'region' ? o.region || '미수록' : o[key]) === v)) state[key] = v;
  }
  if (data.years.includes(Number(p.get('year')))) state.year = Number(p.get('year'));
  if (/^[1-9]\d{0,5}$/.test(p.get('page') || '')) state.page = Number(p.get('page'));
  return state;
}
export function stateURL(state) {
  const p = new URLSearchParams();
  for (const key of ['q','group','type','region']) if (state[key]) p.set(key,state[key]);
  if (state.year) p.set('year',state.year);
  if (state.page > 1) p.set('page',state.page);
  if (state.id) p.set('id',state.id);
  const query = p.toString();
  return '/public-audit/' + (query ? '?' + query : '');
}
export function matches(o, query, data) {
  const q = normalize(query); if (!q) return [];
  const labels = [];
  if (normalize(o.name).includes(q)) labels.push('기관명');
  for (const h of o.history) if (normalize(h.auditor).includes(q)) labels.push(`${h.year} 감사인`);
  if (normalize(data.contracts[o.currentContract]?.party).includes(q)) labels.push(`${data.contractYear || 2026} 대상 계약상대자`);
  if (normalize(data.contracts[o.latestContract]?.party).includes(q)) labels.push('최근 계약상대자');
  return labels;
}
export function filterInstitutions(data, state) {
  return data.institutions.filter(o => (!state.group || o.group === state.group) &&
    (!state.type || o.type === state.type) && (!state.region || (o.region || '미수록') === state.region) &&
    (!normalize(state.q) || matches(o,state.q,data).length));
}
export function pageNumbers(page, total) {
  return [...new Set([1,page-1,page,page+1,total])].filter(x=>x>=1 && x<=total).sort((a,b)=>a-b);
}
export const CONTRACT_COLUMNS = [
  ['id','근거ID'],['source','근거종류'],['title','계약명'],['buyer','수요기관'],['party','계약상대자'],
  ['years','대상연도'],['yearBasis','연도근거'],['installment','금차계약금액(원)'],['total','총계약금액(원)'],
  ['annual','명시된연간보수(원)'],['paid','지급액(원)'],['amountNote','금액주의'],['vat','부가세'],['tax','세무조정'],
  ['signed','계약일'],['start','착수일'],['installmentEnd','금차완료일'],['end','총완료일'],['periodText','기간원문'],['url','원문URL'],['checkedAt','계약 확인일'],['carried','이전자료 유지'],['reviewNote','검토안내']
];
export function workbookSheets(data, orgs, state) {
  const orgRows = [['기관ID','기관명','구분','유형','지역','주무부처',`${state.year} 감사인`,`${state.year} 확인상태`,'검색 일치 항목','연속 확인구간(최초수임 아님)',`${data.contractYear || 2026} 대상계약 근거ID`,`${data.contractYear || 2026} 계약 확인상태`,'최근 확인계약 근거ID','공시URL']];
  const hist = [['기관ID','기관명','회계연도','감사인','확인상태','공시URL','보고서URL','PDF페이지','이력 확인일','이전자료 유지','검토안내']];
  const refs = new Set();
  for (const o of orgs) {
    const h = o.history.find(h=>h.year === state.year);
    orgRows.push([o.id,o.name,o.group,o.type,o.region,o.ministry,h.auditor,h.status,matches(o,state.q,data).join(' / '),o.consecutiveRange,o.currentContract,o.currentStatus,o.latestContract,o.disclosure]);
    for (const h of o.history) for (const s of h.sources.length ? h.sources : [{url:'',page:''}]) {
      hist.push([o.id,o.name,h.year,h.auditor,h.status,h.disclosure,s.url,s.page,h.checkedAt || data.reportAsOf || data.asOf,h.carried?'예':'아니오',h.reviewNote || '']);
    }
    for (const ref of [o.currentContract,o.latestContract]) if (ref) refs.add(ref);
  }
  const contracts = [['연결기관ID','공동계약(기관별 배분불가)',...CONTRACT_COLUMNS.map(c=>c[1])]];
  for (const ref of refs) {
    const c = data.contracts[ref];
    contracts.push([c.institutionIds.join(' | '),c.joint?'예':'아니오',...CONTRACT_COLUMNS.map(([key])=>key==='carried'?(c.carried?'예':'아니오'):c[key])]);
  }
  const scope = [['항목','설명'],['다운로드 범위',`${orgs.length}곳 / 전체 ${data.institutions.length}곳. 검색 결과 전체 페이지이며 5년 이력과 관련 계약을 함께 수록합니다.`],
    ['검색어',state.q || '전체'],['기관 구분',state.group || '전체'],['기관 유형',state.type || '전체'],['지역',state.region || '전체'],
    ['목록 이력연도',`${state.year}년. 이력연도는 기관 시트의 감사인에만 적용됩니다. 계약 및 5년이력 시트는 별도 기간입니다.`],
    ['감사인 검색 범위',`${data.years[data.years.length-1]}~${data.years[0]} 이력 및 수록 계약상대자 전체. 기관 시트의 검색 일치 항목에서 실제 일치 연도를 확인하세요.`],...data.notes];
  return [{name:'읽는법',rows:scope},{name:'기관',rows:orgRows},{name:'5년이력',rows:hist},{name:'계약근거',rows:contracts}];
}

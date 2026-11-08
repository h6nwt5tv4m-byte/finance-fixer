import {PAGE_SIZE,readState,stateURL,matches,filterInstitutions,pageNumbers,workbookSheets} from './model.mjs';
import {workbookBytes} from './xlsx.mjs';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = value => typeof value === 'number' && Number.isFinite(value) ? `${value.toLocaleString('ko-KR')}원` : '미확인';
const hosts = new Set(['www.alio.go.kr','www.cleaneye.go.kr','www.g2b.go.kr','www.kobaco.co.kr','www.sisul.or.kr']);
function link(url,label) {
  try {const u=new URL(url);if(u.protocol==='https:' && hosts.has(u.hostname) && !u.username && !u.password)return `<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`;}catch{}
  return esc(label)+' (링크 미확인)';
}
let data,state,filtered=[];
const title = '공공기관·지방공기업 감사현황 | 재무해결사';
function years(c) {
  if(!c.years)return '대상연도 미확인';
  const value = c.years.split(',').join('·')+'년';
  return value + (['회계/사업연도 명시','기관 원문 명시'].includes(c.yearBasis) ? ' 대상' : ' 제목 표기 · 회계연도 미확인');
}
function fee(c) {
  if(!c)return '<span class="sub">공개 계약금액 미확인</span>';
  if(c.joint)return '<span class="money">공동계약 · 기관별 배분불가</span>';
  const parts=[];
  if(c.total !== null)parts.push(`총액 ${money(c.total)}`);
  if(c.installment !== null && c.installment !== c.total)parts.push(`금차 ${money(c.installment)}`);
  return parts.length ? parts.map(v=>`<span class="money num">${esc(v)}</span>`).join('<br>') : '<span class="sub">계약금액 미확인</span>';
}
function syncForm() {
  for(const key of ['q','group','type','region','year'])$(key).value=state[key];
}
function navigate(next, {replace=false,scroll=false}={}) {
  state={...state,...next};
  history[replace?'replaceState':'pushState'](null,'',stateURL(state));
  render();
  if(scroll) {
    const target=state.id ? $('detail-view').querySelector('h1') : $('result-count');
    target.tabIndex=-1;target.focus({preventScroll:true});target.scrollIntoView({block:'start'});
  }
}
function renderList() {
  document.title=title;
  const count=filtered.length;
  $('result-count').textContent=`${count.toLocaleString('ko-KR')}곳 / 전체 766곳 · ${state.year}년 이력`;
  $('download').disabled=!count;
  const rows=filtered.slice((state.page-1)*PAGE_SIZE,state.page*PAGE_SIZE);
  $('results').innerHTML=count ? `<table class="result-table"><thead><tr><th scope="col">기관</th><th scope="col">${state.year}년 감사인</th><th scope="col">최근 확인 계약 · 금액</th></tr></thead><tbody>${rows.map(o=>{
    const h=o.history.find(h=>h.year===state.year),c=data.contracts[o.latestContract];
    const matched=state.q?`<span class="sub">검색 일치: ${esc(matches(o,state.q,data).join(' · '))}</span>`:'';
    return `<tr><td><a class="org-link" data-id="${esc(o.id)}" href="${esc(stateURL({...state,id:o.id}))}">${esc(o.name)} →</a><span class="sub">${esc(o.group)} · ${esc(o.type)} · ${esc(o.region || '지역 미수록')}</span>${matched}</td><td data-label="${state.year}년 감사인">${esc(h.auditor || '미확인')}<br><span class="quality">${esc(h.status)}</span></td><td data-label="최근 확인 계약 · 선택 이력연도와 별개">${fee(c)}${c?`<span class="sub">${esc(years(c))}<br>계약일 ${esc(c.signed || '미확인')} · ${esc(c.vat === '포함' ? 'VAT 포함' : 'VAT '+(c.vat || '미확인'))}</span>`:''}</td></tr>`;
  }).join('')}</tbody></table>` : '<p class="empty">검색조건에 맞는 기관이 없습니다. 기관명이나 감사인을 짧게 입력하거나 검색조건을 초기화해 주세요.</p>';
  const total=Math.ceil(count/PAGE_SIZE);
  let prior=0;
  $('pagination').innerHTML=total<=1?'':`${state.page>1?`<a data-page="${state.page-1}" href="${esc(stateURL({...state,page:state.page-1,id:''}))}" aria-label="이전 페이지">이전</a>`:''}${pageNumbers(state.page,total).map(p=>{
    const gap=prior && p-prior>1?'<span aria-hidden="true">…</span>':'';prior=p;
    return gap+`<a data-page="${p}" href="${esc(stateURL({...state,page:p,id:''}))}" ${state.page===p?'aria-current="page"':''} aria-label="${p}페이지">${p}</a>`;
  }).join('')}${state.page<total?`<a data-page="${state.page+1}" href="${esc(stateURL({...state,page:state.page+1,id:''}))}" aria-label="다음 페이지">다음</a>`:''}`;
}
function facts(rows) {return '<dl class="facts">'+rows.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v === null || v === undefined || v === ''?'미확인':v)}</dd></div>`).join('')+'</dl>';}
function contractCard(c, label) {
  return `<article class="contract"><p class="eyebrow">${esc(label)} · ${esc(c.source)}</p><h3>${esc(c.title)}</h3>${c.joint?'<p class="notice">공동계약 전체 금액입니다. 이 기관의 보수로 배분할 수 없습니다.</p>':''}${facts([
    ['계약상대자',c.party],['대상연도',years(c)],['대상연도 근거',c.yearBasis],['계약체결일',c.signed],
    [c.joint?'공동계약 금차액':'금차 계약금액',money(c.installment)],[c.joint?'공동계약 총액':'계약 총액',money(c.total)],
    ['원문 명시 연간액 · 적용범위는 아래 설명',money(c.annual)],['공개 지급액 · 계약금액과 별개',money(c.paid)],['부가세',c.vat],['세무조정',c.tax],
    ['금차 완료일',c.installmentEnd],['전체 계약완료일',c.end]
  ])}<p class="notice">${esc(c.amountNote || '금차와 총액은 연간보수와 다를 수 있습니다. 합산하지 마세요.')}<br>계약완료일은 선임 종료 회계연도가 아닙니다.${c.periodText?'<br>기간 원문: '+esc(c.periodText):''}</p><p>${link(c.url,'계약 공개 원문')}</p><p class="hint">근거 ${esc(c.id)}</p></article>`;
}
function renderDetail() {
  const o=data.institutions.find(o=>o.id===state.id);
  const back=`<a class="back" data-back href="${esc(stateURL({...state,id:''}))}">← 검색 결과로</a>`;
  if(!o){document.title='기관을 찾을 수 없습니다 | 재무해결사';$('detail-view').innerHTML=back+'<h1>기관을 찾을 수 없습니다</h1><p>현재 공개자료에 없는 기관 코드입니다. 검색 결과에서 기관을 다시 선택해 주세요.</p>';return;}
  document.title=o.name+' 감사현황 | 재무해결사';
  const current=data.contracts[o.currentContract],latest=data.contracts[o.latestContract];
  $('detail-view').innerHTML=back+`<div class="detail-heading"><p class="eyebrow">${esc(o.group)} · ${esc(o.type)} · ${esc(o.region || '지역 미수록')}</p><h1>${esc(o.name)}</h1>${o.ministry?'<p>주무부처 '+esc(o.ministry)+'</p>':''}<p class="hint">자료 기준일 ${data.asOf} · 기관코드 ${esc(o.id)}</p><p>${link(o.disclosure,'기관 감사 공시')}</p></div>
    <section class="section"><h2>5년 감사이력</h2><p class="notice">${o.consecutive?`2025년 기준 ${o.consecutive}개 회계연도 연속 확인 · ${esc(o.consecutiveRange)}`:'2025년 감사인 미확인으로 연속기간을 산정하지 않았습니다.'}</p><ol class="timeline">${o.history.map(h=>`<li><span class="year">${h.year}</span><div><p>${esc(h.auditor || '미확인')}</p><span class="quality">${esc(h.status)}</span></div><div class="sources">${link(h.disclosure,'공시')}${h.sources.filter(s=>s.url!==h.disclosure).map((s,i)=>link(s.url,`보고서${h.sources.length>1?' '+(i+1):''}${s.page?' · PDF '+s.page+'쪽':''}`)).join('')}</div></li>`).join('')}</ol></section>
    <section class="section"><h2>공개 계약정보</h2><p class="hint">수행완료 이력과 별개입니다. 최근 확인 계약과 2026 대상 계약을 수록하며, 모든 계약의 목록은 아닙니다.</p>${current?contractCard(current,current.id===latest?.id?'2026 대상 계약 · 최근 확인 계약':'2026 대상 계약'):`<p class="notice">2026 회계·사업연도 대상 계약: ${esc(o.currentStatus)}</p>`}${latest && latest.id!==current?.id?contractCard(latest,'최근 확인 계약'):''}${!latest?'<p>최근 확인 계약은 공개자료에서 미확인입니다.</p>':''}</section>`;
}
function render() {
  state=readState(location.search,data);
  filtered=filterInstitutions(data,state);
  state.page=Math.min(state.page,Math.max(1,Math.ceil(filtered.length/PAGE_SIZE)));
  if(location.pathname+location.search!==stateURL(state))history.replaceState(null,'',stateURL(state));
  syncForm();
  $('list-view').hidden=!!state.id;$('detail-view').hidden=!state.id;
  if(state.id)renderDetail();else renderList();
}
function submit() {
  const next={id:'',page:1};for(const key of ['q','group','type','region','year'])next[key]=$(key).value;
  next.year=Number(next.year);navigate(next);
}
$('search-form').addEventListener('submit',e=>{e.preventDefault();if(data)submit();});
for(const key of ['group','type','region','year'])$(key).addEventListener('change',submit);
$('reset').addEventListener('click',()=>navigate({q:'',group:'',type:'',region:'',year:2025,page:1,id:''}));
document.addEventListener('click',e=>{
  const a=e.target.closest('a[data-id],a[data-page],a[data-back]');
  if(!a || e.button!==0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey)return;
  e.preventDefault();
  if(a.hasAttribute('data-id'))navigate({id:a.dataset.id},{scroll:true});
  else if(a.hasAttribute('data-page'))navigate({page:Number(a.dataset.page),id:''},{scroll:true});
  else navigate({id:''},{scroll:true});
});
addEventListener('popstate',()=>{if(data)render();});
$('download').addEventListener('click',async()=>{
  const button=$('download');button.disabled=true;button.textContent='엑셀 만드는 중…';
  try {
    await new Promise(resolve=>setTimeout(resolve,0));
    const bytes=workbookBytes(workbookSheets(data,filtered,state));
    const blob=new Blob([bytes],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`공공기관_감사현황_${data.asOf}_${filtered.length}곳.xlsx`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
    $('result-count').textContent=`${filtered.length}곳의 엑셀 다운로드를 요청했습니다. 파일이 보이지 않으면 아래 전체 엑셀 링크를 이용하거나 기본 브라우저에서 열어 주세요.`;
  }catch(error){$('result-count').textContent='엑셀을 만들지 못했습니다. 아래 전체 공개용 엑셀을 이용해 주세요.';console.error(error);}
  finally{button.textContent='검색 결과 엑셀';button.disabled=!filtered.length;}
});
async function load() {
  $('load-error').hidden=true;$('results').setAttribute('aria-busy','true');
  $('result-count').textContent='자료를 불러오고 있습니다.';$('retry').disabled=true;
  try {
    const response=await fetch('data-20261108.json');if(!response.ok)throw new Error('Data unavailable');
    const value=await response.json();
    if(value.schema!==1 || value.asOf!=='2026-11-08' || value.institutions.length!==766 || !value.contracts)throw new Error('Snapshot mismatch');
    data=value;
    for(const key of ['group','type','region']) {
      const values=[...new Set(data.institutions.map(o=>key==='region'?o.region||'미수록':o[key]))].sort((a,b)=>a.localeCompare(b,'ko'));
      $(key).innerHTML='<option value="">전체</option>'+values.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');
    }
    $('method-notes').innerHTML=data.notes.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('');
    $('controls').disabled=false;render();
  }catch(error){$('load-error').hidden=false;$('result-count').textContent='자료를 불러오지 못했습니다.';console.error(error);}
  finally{$('results').setAttribute('aria-busy','false');$('retry').disabled=false;}
}
$('retry').addEventListener('click',load);
load();

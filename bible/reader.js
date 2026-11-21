import {createReadAloud} from './read-aloud.js?v=20261121';
const $ = id => document.getElementById(id);
let narration = {setChapter(){},reset(){},refreshKorean(){}};
try { narration=createReadAloud(); } catch { const status=$('narration-status');if(status)status.textContent='기기 음성 낭독을 준비하지 못했습니다. 정식 낭독 링크를 이용해 주세요.'; }
const local = ['127.0.0.1', 'localhost'].includes(location.hostname);
const api = local ? '/bible/api' : 'https://bible-api.finance-fixer.net';
const locationKey = 'finance-fixer:bible:reader:location';
let books = [], current, generation = 0, controller, timer;
let koreanState='loading', englishState='loading';
const koreanCache=new Map();
function refreshRetry(){ $('retry').hidden=!(koreanState==='error'||englishState==='error'); }

// Unexpected markup fails as a whole, before anything enters the live document.
export function bibleFragment(html) {
  const template = document.createElement('template');
  template.innerHTML = html;
  const tags = new Set(['DIV','SPAN','P','BR','TABLE','THEAD','TBODY','TR','TD','TH','EM','STRONG','B','I','SUP','SUB','HR']);
  const attrs = new Set(['class','v','usfm','colspan','rowspan','title','data-usfm']);
  function copy(node) {
    if (node.nodeType === Node.TEXT_NODE) return document.createTextNode(node.data);
    if (node.nodeType !== Node.ELEMENT_NODE || !tags.has(node.tagName)) throw new Error('unsupported_markup');
    const clean = document.createElement(node.tagName.toLowerCase());
    for (const attr of node.attributes) {
      if (!attrs.has(attr.name)) throw new Error('unsupported_attribute');
      if (attr.name === 'class' && !/^[a-zA-Z0-9_ -]*$/.test(attr.value)) throw new Error('invalid_class');
      clean.setAttribute(attr.name, attr.value);
    }
    for (const child of node.childNodes) clean.append(copy(child));
    return clean;
  }
  const result = document.createDocumentFragment();
  for (const child of template.content.childNodes) result.append(copy(child));
  if (result.textContent !== template.content.textContent) throw new Error('text_mismatch');
  return result;
}

function option(value, text) {
  const item = document.createElement('option'); item.value = value; item.textContent = text; return item;
}
function setChapters(book, chapter) {
  $('chapter').replaceChildren(...Array.from({length:book.chapters}, (_,i) => option(String(i+1), `${i+1}장`)));
  $('chapter').value = String(chapter);
}
function validSelection(book, chapter) {
  const selected = books.find(b => b.id === book);
  return selected && Number.isInteger(chapter) && chapter >= 1 && chapter <= selected.chapters ? {book:selected,chapter} : null;
}
function fromURL() {
  const params = new URLSearchParams(location.search);
  return validSelection(params.get('book'), Number(params.get('chapter')));
}
function remember(book, chapter) {
  try { localStorage.setItem(locationKey, JSON.stringify({book:book.id,chapter})); } catch {}
}
function links(book, chapter) {
  $('audio-link').href = `https://www.biblegateway.com/passage/?search=${encodeURIComponent(`${book.english} ${chapter}`)}&version=NIV`;
  $('krv-original').href = `https://www.bskorea.or.kr/bible/korbibReadpage.php?version=HAN&book=${book.bsk}&chap=${chapter}&sec=0`;
  $('context-link').href = book.id === 'MRK' ? 'https://bibleproject.com/guides/book-of-mark/' : 'https://bibleproject.com/explore/book-overviews/';
  $('context-link').textContent = book.id === 'MRK' ? 'BibleProject 마가복음 개요 · 영어 ↗' : 'BibleProject 성경 개요 ↗';
}
async function getJSON(url, signal) {
  const response = await fetch(url, {signal,cache:url.startsWith(api)?'no-store':'default',credentials:'omit',referrerPolicy:'no-referrer'});
  if (!response.ok) {
    if(response.status===429)throw new Error('rate_limit');
    if(response.status===503){const body=await response.json().catch(()=>null);if(body?.error==='niv_suspended')throw new Error('suspended');}
    throw new Error('unavailable');
  }
  return response.json();
}
function renderKorean(data, book, chapter) {
  if (data.id !== book.id || !Array.isArray(data.chapters)) throw new Error('invalid_krv');
  const selected = data.chapters.find(c => c.chapter === chapter);
  if (!selected || !Array.isArray(selected.verses) || selected.verses.length !== book.verses[chapter-1]) throw new Error('invalid_krv');
  const fragment = document.createDocumentFragment();
  for (const [index, verse] of selected.verses.entries()) {
    if (verse.verse !== index+1 || typeof verse.text !== 'string' || !verse.text.trim()) throw new Error('invalid_krv');
    const p = document.createElement('p'); p.className = 'korean-verse'; p.id = `krv-${verse.verse}`;
    const number = document.createElement('span'); number.className = 'verse-number'; number.textContent = verse.verse;
    const text = document.createElement('span'); text.textContent = verse.text;
    p.append(number,text); fragment.append(p);
  }
  return fragment;
}
function errorText(error) {
  if(error.message==='suspended')return 'NIV 읽기를 잠시 쉬고 있습니다. 한글 본문이나 Bible Gateway 원문을 이용해 주세요.';
  if(['invalid_niv','unsupported_markup','unsupported_attribute','invalid_class','text_mismatch'].includes(error.message))return '현재 이 장의 영어 본문을 표시할 수 없습니다. Bible Gateway 원문을 이용해 주세요.';
  return error.message === 'rate_limit' ? '이용량 제한에 도달했습니다. 나중에 다시 시도하거나 Bible Gateway 원문을 이용해 주세요.' : 'NIV 본문을 불러오지 못했습니다. 연결을 확인한 뒤 다시 시도해 주세요.';
}
async function loadKorean(book,chapter,seq,signal){
  try{
    let data=koreanCache.get(book.id);
    if(!data)data=await getJSON(`./krv/${book.id}.json`,signal);
    if(seq!==generation)return;
    const fragment=renderKorean(data,book,chapter);
    koreanCache.delete(book.id);koreanCache.set(book.id,data);
    if(koreanCache.size>3)koreanCache.delete(koreanCache.keys().next().value);
    $('krv-content').replaceChildren(fragment);$('krv-status').textContent='';koreanState='ready';
    narration.refreshKorean();
    if($('verse').value)jumpVerse({scroll:false});
  }catch(error){
    if(seq!==generation||error.name==='AbortError')return;
    koreanState='error';$('krv-status').textContent='한글 본문을 불러오지 못했습니다. 다시 시도하거나 아래 대한성서공회 원문 링크를 이용해 주세요.';
  }
  refreshRetry();
}
async function loadEnglish(book, chapter, seq, signal) {
  try {
    const data = await getJSON(`${api}/chapter?book=${book.id}&chapter=${chapter}`,signal);
    if (seq !== generation) return;
    if (data.id !== `${book.id}.${chapter}` || typeof data.html !== 'string' || typeof data.copyright !== 'string' || !data.copyright.trim()) throw new Error('invalid_niv');
    const fragment = bibleFragment(data.html);
    $('niv-content').replaceChildren(fragment);
    $('niv-copyright').textContent = data.copyright;
    $('niv-status').textContent = '';
    englishState='ready';
    narration.setChapter();
    const selected=$('verse').value;
    const numbers=new Set(Array.from({length:book.verses[chapter-1]},(_,i)=>i+1));
    for(const marker of $('niv-content').querySelectorAll('.yv-v[v]')){
      const match=/^(\d+)(?:-(\d+))?$/.exec(marker.getAttribute('v'));
      if(match)for(let n=Number(match[1]);n<=Math.min(Number(match[2]||match[1]),200);n++)numbers.add(n);
    }
    $('verse').replaceChildren(option('','절 선택'),...[...numbers].sort((a,b)=>a-b).map(n=>option(String(n),`${n}절`)));
    $('verse').value=selected;if(selected)jumpVerse({scroll:false});
    refreshRetry();
  } catch (error) {
    if (seq !== generation || error.name === 'AbortError') return;
    $('niv-content').replaceChildren(); $('niv-copyright').textContent = '';
    $('niv-status').textContent = errorText(error);
    englishState=['invalid_niv','unsupported_markup','unsupported_attribute','invalid_class','text_mismatch','suspended'].includes(error.message)?'unavailable':'error';
    refreshRetry();
  }
}
function load(book, chapter, {historyMode='push',debounce=true}={}) {
  narration.reset();
  controller?.abort(); clearTimeout(timer);
  controller = new AbortController(); const signal = controller.signal; const seq = ++generation;
  current = {book,chapter}; koreanState='loading';englishState='loading';
  $('book').value = book.id; setChapters(book,chapter);
  $('chapter-title').textContent = `${book.name} ${chapter}장`;
  $('chapter-english').textContent = `${book.english.toUpperCase()} ${chapter}`;
  document.title = `${book.name} ${chapter}장 · NIV와 개역한글 | 성경으로 영어 공부`;
  $('reader-status').textContent = '책이나 장을 바꾸어 이어서 읽을 수 있습니다.';
  $('niv-content').replaceChildren(); $('krv-content').replaceChildren(); $('niv-copyright').textContent = '';
  $('niv-status').textContent = '영어 본문을 불러오고 있습니다.';
  $('krv-status').textContent = '한글 본문을 불러오고 있습니다.';
  $('verse-status').textContent = ''; $('retry').hidden = true;
  $('verse').replaceChildren(option('','절 선택'),...Array.from({length:book.verses[chapter-1]},(_,i)=>option(String(i+1),`${i+1}절`)));
  $('previous').disabled = book.id === books[0].id && chapter === 1;
  $('next').disabled = book.id === books.at(-1).id && chapter === book.chapters;
  links(book,chapter); remember(book,chapter);
  if (historyMode !== 'none') {
    const url = new URL(location.href); url.searchParams.set('book',book.id); url.searchParams.set('chapter',chapter); url.hash='';
    try{history[historyMode === 'replace' ? 'replaceState' : 'pushState'](null,'',url);}catch{}
  }
  loadKorean(book,chapter,seq,signal);
  timer = setTimeout(()=>loadEnglish(book,chapter,seq,signal),debounce?250:0);
}
function retryCurrent(){
  controller?.abort();clearTimeout(timer);controller=new AbortController();const signal=controller.signal;const seq=++generation;
  if(koreanState!=='ready'){
    koreanState='loading';$('krv-status').textContent='한글 본문을 불러오고 있습니다.';
    loadKorean(current.book,current.chapter,seq,signal);
  }
  if(englishState==='error'||englishState==='loading'){
    englishState='loading';$('niv-status').textContent='영어 본문을 불러오고 있습니다.';
    loadEnglish(current.book,current.chapter,seq,signal);
  }
  refreshRetry();
}
function move(delta) {
  let {book,chapter}=current; const index=books.indexOf(book); chapter+=delta;
  if(chapter<1){if(index===0)return;book=books[index-1];chapter=book.chapters;}
  if(chapter>book.chapters){if(index===books.length-1)return;book=books[index+1];chapter=1;}
  load(book,chapter);
}
function jumpVerse({scroll=true}={}) {
  document.querySelectorAll('.selected-verse').forEach(n=>n.classList.remove('selected-verse'));
  const verse=$('verse').value; if(!verse)return;
  const korean=$(`krv-${verse}`);
  const english=[...$('niv-content').querySelectorAll('.yv-v[v]')].find(n=>{
    const match=/^(\d+)(?:-(\d+))?$/.exec(n.getAttribute('v'));
    return match&&Number(verse)>=Number(match[1])&&Number(verse)<=Number(match[2]||match[1]);
  });
  korean?.classList.add('selected-verse'); english?.classList.add('selected-verse');
  let hasText=false;
  if(english){
    const markers=[...$('niv-content').querySelectorAll('.yv-v')];
    const next=markers[markers.indexOf(english)+1];
    const range=document.createRange();range.setStartAfter(english);
    if(next)range.setEndBefore(next);else range.setEnd($('niv-content'),$('niv-content').childNodes.length);
    const fragment=range.cloneContents();fragment.querySelectorAll('.yv-n,.yv-vlbl,.yv-h').forEach(n=>n.remove());
    hasText=!!fragment.textContent.trim();
  }
  $('verse-status').textContent=hasText?'같은 절 번호에 표시했습니다.':$('niv-content').textContent?'NIV에는 이 절의 본문이 없습니다. 번역본의 절 구분이나 각주를 확인해 주세요.':'영어 본문을 불러온 뒤 절을 다시 선택해 주세요.';
  if(scroll)(english||korean)?.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
}
async function start() {
  try {
    books=await getJSON('./books.json');
    if(!Array.isArray(books)||books.length!==66||new Set(books.map(b=>b.id)).size!==66)throw new Error('books');
    for(const [value,label]of[['old','구약'],['new','신약']]){
      const group=document.createElement('optgroup');group.label=label;
      for(const book of books.filter(b=>b.testament===value))group.append(option(book.id,book.name));
      $('book').append(group);
    }
    document.querySelector('.toolbar').hidden=false;document.querySelector('.reading-tools').hidden=false;
    $('book').addEventListener('change',()=>load(books.find(b=>b.id===$('book').value),1));
    $('chapter').addEventListener('change',()=>load(current.book,Number($('chapter').value)));
    $('previous').addEventListener('click',()=>move(-1));$('next').addEventListener('click',()=>move(1));
    $('verse').addEventListener('change',jumpVerse);
    $('retry').addEventListener('click',retryCurrent);
    window.addEventListener('popstate',()=>{const chosen=fromURL()||{book:books.find(b=>b.id==='MRK'),chapter:1};load(chosen.book,chosen.chapter,{historyMode:'none'});});
    let chosen=fromURL();
    if(!chosen&&!new URLSearchParams(location.search).has('book'))try{const saved=JSON.parse(localStorage.getItem(locationKey));chosen=validSelection(saved?.book,saved?.chapter);}catch{}
    chosen ||= {book:books.find(b=>b.id==='MRK'),chapter:1};
    const font=document.createElement('link');font.rel='stylesheet';font.crossOrigin='anonymous';font.href=`${api}/fonts.css`;document.head.append(font);
    load(chosen.book,chosen.chapter,{historyMode:'replace',debounce:false});
  } catch {
    $('reader-status').textContent='책 목록을 불러오지 못했습니다. 새로고침하거나 첫 학습 단원을 이용해 주세요.';
    $('niv-status').textContent='';$('krv-status').textContent='';
  }
}
start();

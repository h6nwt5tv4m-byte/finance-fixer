import {attachFilmWords, clearFilmWords, followFilm} from './read-along/film-words.js?v=1';
import {attachReadAlong, detachReadAlong, readAlongChapter} from './read-along/paired-player.js?v=20261124-paired-v3';
const $ = id => document.getElementById(id);
const local = ['127.0.0.1', 'localhost'].includes(location.hostname);
const api = local ? '/bible/api' : 'https://bible-api.finance-fixer.net';
const locationKey = 'finance-fixer:bible:reader:location';
const study = $('study');
const audioPanel = $('chapter-audio');
const passage = $('passage');
const staticCache = new Map();
let books = [], current, request, fetchTimer, playerTimer;
let englishReady = false, koreanVerses;
let englishError = false, koreanError = false;

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
async function getJSON(url, signal) {
  const response = await fetch(url, {signal,cache:url.startsWith(api)?'no-store':'default',credentials:'omit',referrerPolicy:'no-referrer'});
  if (!response.ok) {
    if(response.status===429)throw new Error('rate_limit');
    if(response.status===503){const body=await response.json().catch(()=>null);if(body?.error==='niv_suspended')throw new Error('suspended');}
    throw new Error('unavailable');
  }
  return response.json();
}

async function localChapter(edition, book, chapter, signal) {
  const key = edition + '/' + book.id;
  let data = staticCache.get(key);
  if (!data) {
    data = await getJSON('./' + key + '.json', signal);
    if (!signal.aborted) {
      if (staticCache.size >= 6) staticCache.delete(staticCache.keys().next().value);
      staticCache.set(key, data);
    }
  }
  if (edition === 'bsb') {
    const selected = data[chapter - 1];
    if (!Array.isArray(selected) || !selected.every(v => typeof v === 'string')) throw new Error('invalid_bsb');
    return selected;
  }
  const selected = data.chapters?.[chapter - 1];
  if (data.id !== book.id || selected?.chapter !== chapter || selected.verses?.length !== book.verses[chapter - 1] ||
    !selected.verses.every((v, i) => v.verse === i + 1 && typeof v.text === 'string')) throw new Error('invalid_krv');
  return selected.verses.map(v => v.text);
}

// Keep the provider's headings, paragraphs, poetry, table structure and notes.
// A table stays together so that column labels retain their meaning.
function nivBlocks(html, chapterLength) {
  const root = document.createElement('div');
  root.append(bibleFragment(html));
  const starts = [];
  let heading = null;
  const verseNumber = el => /^(\d+)(?:-(\d+))?$/.exec(el.getAttribute('v') || '');
  for (const node of root.querySelectorAll('.yv-h,table,.yv-v[v]')) {
    if (node.closest('.yv-n') || node.parentElement.closest('table')) continue;
    if (node.matches('.yv-h')) { heading ||= node; continue; }
    const markers = node.matches('table') ? [...node.querySelectorAll('.yv-v[v]')] : [node];
    const numbers = markers.map(verseNumber).filter(Boolean);
    if (!numbers.length) continue;
    const first = Number(numbers[0][1]), last = Number(numbers.at(-1)[2] || numbers.at(-1)[1]);
    if (first < 1 || last > 200 || last < first || (starts.length && first <= starts.at(-1).end)) continue;
    starts.push({start:first, end:last, node:heading || node});
    heading = null;
  }
  if (!starts.length) return [{start:1, end:chapterLength, content:root.firstChild ? root : null}];
  const items = starts.map((item, i) => {
    const range = document.createRange();
    range.selectNodeContents(root);
    if (i) range.setStartBefore(item.node);
    if (starts[i + 1]) range.setEndBefore(starts[i + 1].node);
    let content = range.cloneContents();
    for (let parent = range.commonAncestorContainer; parent && parent !== root; parent = parent.parentNode) {
      if (parent.nodeType !== Node.ELEMENT_NODE) continue;
      const wrap = parent.cloneNode(false);
      wrap.append(content); content = wrap;
    }
    return {...item, content};
  });
  if (items.map(item => item.content.textContent).join('') !== root.textContent) throw new Error('text_mismatch');
  return items;
}
const filmOrigin = 'https://bible-api.finance-fixer.net';
const film = $('lumo');
const filmScreen = $('film-screen');
let filmLoadTimer;
function leaveFilm() {
  film.classList.remove('playing');
  filmScreen.firstElementChild?.contentWindow.postMessage({type:'lumo-pause'}, filmOrigin);
}
function filmUnavailable() {
  clearTimeout(filmLoadTimer);
  filmScreen.replaceChildren();
  filmScreen.hidden = true;
  film.classList.remove('playing');
  followFilm(undefined, 'error');
  $('film-status').textContent = '영상에 연결할 수 없습니다. 다시 연결하거나 원본 영상을 열어 주세요.';
  $('film-retry').hidden = false;
}
function filmChapter() {
  return current?.version === 'NIV' && isLesson();
}
function removeFilm() {
  clearTimeout(filmLoadTimer);
  $('film-retry').hidden = true;
  clearFilmWords();
  filmScreen.replaceChildren();
  $('film-status').textContent = '';
  film.classList.remove('playing');
  film.hidden = true;
}
function showFilm() {
  if (!filmChapter() || filmScreen.firstElementChild) return;
  const frame = document.createElement('iframe');
  frame.title = 'LUMO 마가복음 1장 NIV 영상 플레이어';
  frame.allow = 'autoplay; encrypted-media; fullscreen; picture-in-picture';
  frame.allowFullscreen = true;
  frame.referrerPolicy = 'origin';
  frame.src = filmOrigin + '/player/lumo.html?v=3&site=' + encodeURIComponent(location.origin);
  film.hidden = false;
  filmScreen.hidden = false;
  $('film-retry').hidden = true;
  $('film-status').textContent = '영상 플레이어를 불러오는 중…';
  filmScreen.append(frame);
  filmLoadTimer = setTimeout(() => {
    if (filmScreen.firstElementChild === frame) filmUnavailable();
  }, 18000);
}
window.addEventListener('message', event => {
  const frame = filmScreen.firstElementChild;
  if (!frame || event.source !== frame.contentWindow || event.origin !== filmOrigin || event.data?.type !== 'lumo') return;
  const {kind, time} = event.data;
  if (kind === 'ready') {
    clearTimeout(filmLoadTimer);
    $('film-status').textContent = '';
  }
  if (kind === 'error') { filmUnavailable(); return; }
  if (kind === 'play') {
    document.dispatchEvent(new Event('stop-study-audio'));
    film.classList.add('playing');
  } else if (kind === 'ended') {
    film.classList.remove('playing');
  }
  followFilm(time, kind);
});
function clearOfficial() {
  clearTimeout(playerTimer);
  $('audio-player').replaceChildren();
}
function updateOfficial() {
  clearOfficial();
  if (!current || current.version !== 'NIV' || filmChapter() || !audioPanel.open) return;
  document.dispatchEvent(new Event('stop-study-audio'));
  const {book, chapter} = current;
  playerTimer = setTimeout(() => {
    const frame = document.createElement('iframe');
    frame.title = 'YouVersion NIV 낭독 · ' + book.name + ' ' + chapter + '장';
    frame.referrerPolicy = 'no-referrer';
    frame.src = 'https://www.bible.com/audio-bible/111/' + book.id + '.' + chapter + '.NIV';
    $('audio-player').replaceChildren(frame);
  }, 150);
}
function koreanNumbers(englishNumber, last) {
  const {book, chapter} = current;
  const id = book.id + '.' + chapter;
  if (id === '1SA.30' && last === 31 && englishNumber === 31) return [];
  if (id === '2CO.13' && last === 14 && englishNumber >= 12) return englishNumber === 12 ? [] : [englishNumber - 1];
  if (id === 'SNG.6' && last === 13 && englishNumber === 13) return [13,14];
  if (id === '3JN.1' && last === 14 && englishNumber === 14) return [14,15];
  return [englishNumber];
}
function joinPrevious(verse, last) {
  return (current.book.id === '1SA' && current.chapter === 30 && last === 31 && verse === 31) ||
    (current.book.id === '2CO' && current.chapter === 13 && last === 14 && verse === 12);
}
function rowFor(verse) {
  return passage.querySelector('.verse-row[data-start="' + verse + '"]') ||
    [...passage.querySelectorAll('.verse-row')].find(row => +row.dataset.start <= verse && verse <= +row.dataset.end);
}
function fillKorean() {
  if (!koreanVerses) return;
  for (const cell of passage.querySelectorAll('.ko-text')) {
    cell.replaceChildren();
    const numbers = cell.dataset.verses.split(',').map(Number);
    const row = cell.parentElement;
    for (const n of numbers) {
      if (!n || !koreanVerses[n-1]) continue;
      const p = document.createElement('p');
      if (numbers.length > 1 || n !== Number(row.dataset.start) || row.dataset.start !== row.dataset.end) {
        const num = document.createElement('sup'); num.textContent = n; p.append(num);
      }
      p.append(koreanVerses[n-1]); cell.append(p);
    }
  }
}
function renderPassage(items) {
  const fragment = document.createDocumentFragment();
  const kCount = current.book.verses[current.chapter-1];
  const last = items.at(-1)?.end || kCount;
  const entries = new Map(items.map(item => [item.start,item]));
  const covered = new Set(items.flatMap(item => Array.from({length:item.end-item.start},(_,i) => item.start+i+1)));
  let previous, cell;
  for (let n = 1; n <= last; n++) {
    if (covered.has(n)) continue;
    const item = entries.get(n);
    const end = item?.end || n;
    let row = previous;
    if (!row || !joinPrevious(n,last)) {
      row = document.createElement('div'); row.className = 'verse-row'; row.id = 'v' + n;
      row.dataset.start = n;
      const number = document.createElement('span'); number.className = 'number'; number.textContent = n;
      cell = document.createElement('div'); cell.className = 'en-text'; cell.lang = 'en';
      if (current.version === 'NIV') { cell.dataset.yvSdk=''; cell.dataset.slot='yv-bible-renderer'; }
      const ko = document.createElement('div'); ko.className = 'ko-text'; ko.lang = 'ko'; ko.dataset.verses = '';
      row.append(number, cell, ko); fragment.append(row); previous = row;
    }
    row.dataset.end = end;
    if (n !== +row.dataset.start || end > n) row.firstChild.textContent = row.dataset.start + '–' + end;
    if (item?.content) {
      if (cell.childNodes.length) cell.append(' ');
      cell.append(item.content);
    } else if (englishReady) {
      const missing=document.createElement('small'); missing.lang='ko'; missing.textContent='이 판본에 해당 절 본문 없음'; cell.append(missing);
    }
    const ko = row.lastElementChild;
    const numbers = [];
    for (let i=n; i<=end; i++) numbers.push(...koreanNumbers(i,last));
    ko.dataset.verses = [ko.dataset.verses, ...numbers.filter(v=>v <= kCount)].filter(Boolean).join(',');
  }
  // If English has fewer numbered verses with no known equivalence, retain the Korean text.
  const mapped = new Set([...fragment.querySelectorAll('.ko-text')].flatMap(c => c.dataset.verses.split(',').map(Number)));
  for (let n=1; n<=kCount; n++) {
    if (mapped.has(n)) continue;
    const row=document.createElement('div'); row.className='verse-row';
    row.dataset.start=n; row.dataset.end=n;
    const en=document.createElement('div'); en.className='en-text';
    const ko=document.createElement('div'); ko.className='ko-text'; ko.dataset.verses=String(n);
    row.append(en,ko); fragment.append(row);
  }
  if (passage.contains(study)) passage.after(study);
  passage.replaceChildren(fragment);
  fillKorean();
  if (isLesson()) rowFor(8)?.after(study);
  const selected=$('verse').value;
  $('verse').replaceChildren(option('','절 선택'), ...Array.from({length:Math.max(last,kCount)},(_,i)=>option(String(i+1),(i+1)+'절')));
  $('verse').value=selected;
  if (selected) jump(false);
}
function isLesson() {return current.book.id==='MRK' && current.chapter===1;}
function jump(scroll) {
  passage.querySelector('.selected')?.classList.remove('selected');
  const n=Number($('verse').value);
  if (!n) return;
  const row=rowFor(n) || [...passage.querySelectorAll('.ko-text')].find(c=>c.dataset.verses.split(',').includes(String(n)))?.parentElement;
  row?.classList.add('selected');
  if (scroll) { leaveFilm(); row?.scrollIntoView({block:'center',behavior:'instant'}); }
}
function anchor() {
  const hash=location.hash.slice(1);
  if (['study','english','review','context'].includes(hash) && isLesson()) {
    leaveFilm(); study.open=true; $(hash)?.scrollIntoView({block:'start',behavior:'instant'});
  } else if ((hash==='lumo' || hash==='chapter-audio') && filmChapter()) {
    film.scrollIntoView({block:'start',behavior:'instant'});
  } else if (hash==='chapter-audio' && current.version==='NIV') {
    audioPanel.open=true; audioPanel.scrollIntoView({block:'start',behavior:'instant'});
  } else if (hash==='readalong' && !$('readalong').hidden) {
    $('readalong').scrollIntoView({block:'start',behavior:'instant'});
  } else if (/^v\d+$/.test(hash)) {
    $('verse').value=hash.slice(1); jump(true);
  }
}
function englishFailure(err) {
  if (current.version==='BSB') return 'BSB 본문을 불러오지 못했습니다.';
  if (err.message==='rate_limit') return 'NIV 조회 한도에 도달했습니다. 같은 장을 BSB로 계속 읽을 수 있습니다.';
  if (err.message==='suspended') return 'NIV 제공이 일시 중단되었습니다. 같은 장을 BSB로 읽을 수 있습니다.';
  return 'NIV 본문을 불러오지 못했습니다. 다시 시도하거나 같은 장을 BSB로 읽어 보세요.';
}
function bsbBlocks(verses) {
  return verses.map((text,i) => ({start:i+1,end:i+1,content:text}));
}
function displayEnglish(items, copyright, version) {
  englishReady=true; $('english-status').textContent='';
  $('niv-copyright').textContent=copyright;
  renderPassage(items);
  if (version==='BSB' && isLesson()) attachReadAlong();
  if (filmChapter()) attachFilmWords(passage);
  anchor();
}
async function english(book,chapter,version,signal) {
  let items, copyright='';
  if (version==='BSB') {
    const verses=await localChapter('bsb',book,chapter,signal);
    items=bsbBlocks(verses);
  } else {
    const data=await getJSON(api+'/chapter?book='+book.id+'&chapter='+chapter,signal);
    if (signal.aborted) return;
    if (data.id!==book.id+'.'+chapter || typeof data.html!=='string' || typeof data.copyright!=='string' || !data.copyright.trim()) throw new Error('invalid_niv');
    items=nivBlocks(data.html, book.verses[chapter-1]); copyright=data.copyright;
  }
  if (!signal.aborted) displayEnglish(items, copyright, version);
}
function retryVisibility() { $('retry').hidden=!(englishError||koreanError); }
async function loadKorean(book, chapter, signal) {
  koreanError=false; retryVisibility();
  try {
    const data=await localChapter('krv',book,chapter,signal);
    if(signal.aborted)return;
    koreanVerses=data; fillKorean(); $('krv-status').textContent='';
  } catch {
    if(signal.aborted)return;
    koreanError=true; $('krv-status').textContent='한글 본문을 불러오지 못했습니다.'; retryVisibility();
  }
}
async function loadEnglish(book, chapter, version, signal) {
  englishError=false; retryVisibility(); $('use-bsb').hidden=true;
  try { await english(book,chapter,version,signal); }
  catch(err) {
    if(signal.aborted)return;
    englishError=true; $('english-status').textContent=englishFailure(err);
    retryVisibility(); $('use-bsb').hidden=version!=='NIV'; anchor();
  }
}
function select(book,chapter,version,historyMode='push',hash='') {
  const keepOfficial = audioPanel.open && current?.version === 'NIV' && version === 'NIV';
  request?.abort(); clearTimeout(fetchTimer); clearOfficial(); removeFilm();
  detachReadAlong(); document.dispatchEvent(new Event('stop-study-audio'));
  request=new AbortController(); const signal=request.signal;
  current={book,chapter,version}; englishReady=false; koreanVerses=null; englishError=false; koreanError=false;
  const url=new URL(location.href);
  url.searchParams.set('book',book.id); url.searchParams.set('chapter',String(chapter)); url.searchParams.set('version',version); url.hash=hash;
  if (historyMode!=='none') history[historyMode+'State'](null,'',url);
  try {localStorage.setItem(locationKey,JSON.stringify({book:book.id,chapter,version}));} catch {}
  $('book').value=book.id; $('chapter').replaceChildren(...Array.from({length:book.chapters},(_,i)=>option(String(i+1),i+1+'장')));
  $('chapter').value=String(chapter); $('version').value=version; $('verse').value='';
  $('version-choice').hidden = version !== 'NIV';
  if (version === 'NIV') {
    const styles = $('niv-styles');
    if (styles) {
      const links = styles.content.cloneNode(true);
      links.querySelector('[data-fonts]').href = api + '/fonts.css';
      styles.replaceWith(links);
    }
  }
  $('chapter-title').textContent=book.name+' '+chapter+'장'; $('chapter-english').textContent=book.english+' '+chapter;
  document.title=$('chapter-title').textContent+' · '+version+' 한영 성경 읽기';
  $('edition-title').textContent=version==='BSB'?'Berean Standard Bible · BSB':'New International Version · NIV';
  $('bsb-credit').hidden=version!=='BSB'; $('voice-credit').hidden=!isLesson(); $('niv-credit').hidden=version!=='NIV';
  $('niv-copyright').textContent=''; $('english-status').textContent=version+' 본문을 불러오는 중…'; $('krv-status').textContent='';
  $('retry').hidden=true; $('use-bsb').hidden=true;
  $('audio-link').href='https://www.biblegateway.com/audio/mclean/niv/'+book.osis+'.'+chapter;
  $('krv-original').href='https://www.bskorea.or.kr/bible/korbibReadpage.php?version=HAN&book='+book.bsk+'&chap='+chapter+'&sec=0';
  $('context-link').href=book.id==='MRK'?'https://bibleproject.com/guides/book-of-mark/':'https://bibleproject.com/explore/book-overviews/';
  audioPanel.hidden = version !== 'NIV' || filmChapter();
  audioPanel.open = !audioPanel.hidden && (hash === '#chapter-audio' || keepOfficial);
  if (filmChapter()) showFilm();
  else if (audioPanel.open) updateOfficial();
  study.open=false; study.hidden=!isLesson();
  $('lesson-entry').textContent=isLesson()?'1–8절 단어·배경·복습':'마가복음 첫 학습 구절';
  $('lesson-entry').href='?book=MRK&chapter=1&version='+version+'#study';
  $('previous').disabled=book===books[0]&&chapter===1; $('next').disabled=book===books.at(-1)&&chapter===book.chapters;
  renderPassage([]);
  loadKorean(book,chapter,signal);
  if (version === 'BSB' && isLesson()) displayEnglish(bsbBlocks(readAlongChapter()), '', version);
  else fetchTimer=setTimeout(()=>loadEnglish(book,chapter,version,signal), historyMode==='push' && version==='NIV'?180:0);
  if (hash==='#study' || hash==='#context' || hash==='#review' || hash==='#english') anchor();
}
function move(delta) {
  let {book, chapter,version}=current; const i=books.indexOf(book); chapter+=delta;
  if (chapter<1) {book=books[i-1];chapter=book.chapters;}
  if (chapter>book.chapters) {book=books[i+1];chapter=1;}
  select(book,chapter,version); $('reading').scrollIntoView({block:'start',behavior:'instant'});
}
function openLocation(mode) {
  const params=new URLSearchParams(location.search);
  let saved={};
  try {saved=JSON.parse(localStorage.getItem(locationKey))||{};} catch {}
  const hasRef=params.has('book')||params.has('chapter');
  let book=books.find(b=>b.id===(hasRef?params.get('book'):saved.book));
  let chapter=Number(hasRef?params.get('chapter'):saved.chapter);
  // Only a legacy audio bookmark can imply NIV when the URL omits the edition.
  const requested = params.get('version');
  const legacyAudio = ['#chapter-audio','#lumo'].includes(location.hash);
  const version = requested === 'NIV' || (requested === null && legacyAudio) ? 'NIV' : 'BSB';
  const filmBookmark = !hasRef && version === 'NIV' && location.hash === '#lumo';
  if (filmBookmark || !book || !Number.isInteger(chapter) || chapter < 1 || chapter > book.chapters) {
    book=books.find(b=>b.id==='MRK'); chapter=1;
  }
  if (mode === 'none' && current?.book === book && current.chapter === chapter && current.version === version) {
    if (!['#study','#english','#review','#context'].includes(location.hash)) study.open = false;
    anchor();
    return;
  }
  select(book,chapter,version,mode,location.hash);
}
async function start() {
  books=await getJSON('./books.json?v=20261121-audio');
  if (books.length!==66) throw new Error('books');
  for (const [value,label] of [['old','구약'],['new','신약']]) {
    const group=document.createElement('optgroup'); group.label=label;
    for (const book of books.filter(b=>b.testament===value)) group.append(option(book.id,book.name));
    $('book').append(group);
  }
  $('selectors').hidden=false; $('reading-tools').hidden=false;
  $('book').onchange=()=>select(books.find(b=>b.id===$('book').value),1,current.version);
  $('chapter').onchange=()=>select(current.book,Number($('chapter').value),current.version);
  $('version').onchange=()=>select(current.book,current.chapter,$('version').value);
  $('use-bsb').onclick=()=>select(current.book,current.chapter,'BSB');
  $('previous').onclick=()=>move(-1); $('next').onclick=()=>move(1);
  $('verse').onchange=()=>jump(true);
  $('show-korean').onchange=()=>document.querySelector('main').classList.toggle('no-korean',!$('show-korean').checked);
  $('retry').onclick=()=>{
    const {book,chapter,version}=current;
    if(koreanError)loadKorean(book,chapter,request.signal);
    if(englishError)loadEnglish(book,chapter,version,request.signal);
  };
  $('lesson-entry').onclick=event=>{
    if(event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
    event.preventDefault();
    if(!isLesson()) {select(books.find(b=>b.id==='MRK'),1,current.version,'push','#study'); return;}
    if(location.hash!=='#study') history.pushState(null,'','#study');
    anchor();
  };
  $('film-retry').onclick = showFilm;
  study.addEventListener('focusin', leaveFilm);
  study.querySelector('summary')?.addEventListener('click', leaveFilm);
  audioPanel.addEventListener('toggle',updateOfficial);
  document.addEventListener('stop-passage-audio', () => {
    audioPanel.open = false;
    clearOfficial();
    leaveFilm();
  });
  window.addEventListener('pagehide',()=>{clearOfficial(); removeFilm();});
  window.addEventListener('pageshow', e => {
    if (!e.persisted) return;
    if (filmChapter()) { showFilm(); if (englishReady) attachFilmWords(passage); }
    else updateOfficial();
  });
  window.addEventListener('popstate',()=>openLocation('none'));
  const header=document.querySelector('.top');
  function measure(){document.documentElement.style.setProperty('--site-header',header.offsetHeight+'px');}
  measure(); if(window.ResizeObserver)new ResizeObserver(measure).observe(header);
  openLocation('replace');
}
start().catch(()=>{$('reader-status').textContent='책 목록을 불러오지 못했습니다. 새로고침해 주세요.';});

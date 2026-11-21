// Read the displayed text using voices reported by the browser as local.
// No audio service, recording, download, or persistent text storage.
const excluded = '.yv-n,.yv-vlbl,.yv-h,.s,.s1,.s2,.s3,.s4,.s5,.ms,.ms1,.ms2,.mr,.r,.sr,.sp,.d,.qa,.cl,.cd';
const noop = {setChapter(){},reset(){},refreshKorean(){}};
const effectVoice = /Albert|Bad News|Bahh|Bells|Boing|Bubbles|Cellos|Wobble|Fred|Good News|Jester|Junior|Kathy|Organ|Superstar|Ralph|Trinoids|Whisper|Zarvox|Eddy|Flo|Grandma|Grandpa|Reed|Rocko|Sandy|Shelley/i;
export function voiceRank(voice) {
  const name = `${voice.name} ${voice.voiceURI}`;
  return (/premium|enhanced|natural|neural/i.test(name)?100:0) +
    (/Samantha|Daniel|Alex|Karen|Moira|Tessa|Rishi|Aria|Jenny|Guy|David|Zira/i.test(name)?30:0) +
    (/^en[-_]US$/i.test(voice.lang)?10:/^en[-_]GB$/i.test(voice.lang)?5:0) - (effectVoice.test(voice.name)?50:0);
}

export function collectReadings(root) {
  const entries = [];
  let active;
  function space() {
    if (active?.text && !/\s$/.test(active.text)) active.text += ' ';
  }
  function visit(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (active && node.data) {
        active.runs.push({node, start:active.text.length, end:active.text.length + node.data.length});
        active.text += node.data;
      }
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE || node.matches(excluded)) return;
    if (node.matches('.yv-v[v]')) {
      const match = /^(\d+)(?:-(\d+))?$/.exec(node.getAttribute('v'));
      if (!match) throw new Error('verse_format');
      const from = Number(match[1]), to = Number(match[2] || match[1]);
      if (from < 1 || to < from || to > 200) throw new Error('verse_format');
      if (!active || active.from !== from || active.to !== to) {
        if (active && from <= active.to) throw new Error('verse_order');
        active = {from, to, label:match[0], marker:node, text:'', runs:[]};
        entries.push(active);
      }
    }
    const block = node.tagName === 'BR' || ['P','DIV','TR','TD','LI'].includes(node.tagName) ||
      (node.tagName === 'SPAN' && ['block','list-item'].includes(getComputedStyle(node).display));
    if (block) space();
    for (const child of node.childNodes) visit(child);
    if (block) space();
  }
  visit(root);
  return entries.filter(entry => entry.text.trim()).map(entry => ({...entry,
    words:[...entry.text.matchAll(/[\p{L}\p{N}]+(?:[’'][\p{L}\p{N}]+)*/gu)].map(m => ({start:m.index,end:m.index+m[0].length}))
  }));
}

function ranges(entry, start=0, end=entry.text.length) {
  const result = [];
  for (const run of entry.runs) {
    if (run.end <= start || run.start >= end) continue;
    if (!run.node.isConnected) throw new Error('detached');
    const range = document.createRange();
    range.setStart(run.node, Math.max(start,run.start)-run.start);
    range.setEnd(run.node, Math.min(end,run.end)-run.start);
    result.push(range);
  }
  return result;
}

export function createReadAloud() {
  const $ = id => document.getElementById(id);
  const root = $('niv-content'), panel = $('read-aloud'), status = $('narration-status');
  const play = $('narration-play'), stopButton = $('narration-stop'), floating = $('narration-floating');
  const voiceSelect = $('narration-voice');
  if (!root || !panel || !status || !play || !stopButton || !floating || !voiceSelect) return noop;
  const synth = window.speechSynthesis;
  const highlightOK = !!(window.CSS?.highlights && window.Highlight);
  let entries = [], voices = [], ready = false, serial = 0, utterance = null, currentEntry = null;
  let state = 'idle', nextTimer, startTimer, endTimer, voiceTimer, manualUntil = 0, voiceSettled=false, parseFailed=false;
  let outlined = [];
  const outline=document.createElementNS('http://www.w3.org/2000/svg','svg');
  outline.classList.add('narration-outline');outline.setAttribute('aria-hidden','true');
  document.body.append(outline);
  function paintOutline(active=outlined) {
    outlined=active;outline.replaceChildren();
    for(const range of active)for(const box of range.getClientRects()){
      if(!box.width||!box.height||box.bottom<0||box.top>innerHeight)continue;
      const rect=document.createElementNS('http://www.w3.org/2000/svg','rect');
      for(const[key,value]of Object.entries({x:box.left-2,y:box.top-1,width:box.width+4,height:box.height+2,rx:2}))rect.setAttribute(key,String(value));
      outline.append(rect);
    }
  }
  function idleMessage() {
    if(!voices.length)return voiceSettled?'이 브라우저에서 기기 내 영어 음성을 찾지 못했습니다. 기기의 영어 음성을 설치한 뒤 음성 다시 찾기를 누르거나, 위의 정식 낭독 링크를 이용해 주세요.':'기기의 영어 음성을 확인하고 있습니다.';
    if(parseFailed)return '이 장의 낭독용 본문을 구분하지 못했습니다. 다른 장이나 정식 낭독 링크를 이용해 주세요.';
    return ready?'절을 고른 뒤 영어 낭독을 눌러 보세요.':'영어 본문을 불러오면 읽을 수 있습니다.';
  }
  const observer = new MutationObserver(() => stop('본문이 바뀌어 낭독을 멈췄습니다. 다시 눌러 주세요.'));
  panel.hidden = false;
  function update() {
    play.disabled = !ready || !voices.length;
    stopButton.disabled = state === 'idle';
    floating.hidden = state === 'idle';
    document.body.classList.toggle('narrating', state !== 'idle');
  }
  function clearHighlight() {
    paintOutline([]);
    if (highlightOK) {
      CSS.highlights.delete('bible-reading');
      CSS.highlights.delete('bible-word');
    }
    document.querySelectorAll('.narrated-verse').forEach(el => el.classList.remove('narrated-verse'));
  }
  function korean() {
    $('narration-korean').textContent='';
    document.querySelectorAll('#krv-content .narrated-verse').forEach(el => el.classList.remove('narrated-verse'));
    if (!currentEntry) return;
    const texts=[];
    for (let n=currentEntry.from; n<=currentEntry.to; n++) {
      const verse=$(`krv-${n}`);verse?.classList.add('narrated-verse');
      const text=verse?.querySelector('span:last-child')?.textContent;if(text)texts.push(`${n}절 ${text}`);
    }
    $('narration-korean').textContent=texts.length?texts.join(' '):'같은 절 번호의 한글 본문이 없습니다.';
  }
  function stop(message='') {
    serial++;
    observer.disconnect();
    clearTimeout(nextTimer); clearTimeout(startTimer); clearTimeout(endTimer);
    const hadUtterance = !!utterance;
    utterance = null; currentEntry = null; state = 'idle';
    $('narration-korean').textContent='';
    if (hadUtterance) try { synth?.cancel(); } catch {}
    clearHighlight(); update();
    if (message) status.textContent = message;
  }
  function follow(range) {
    if (!$('narration-follow').checked || performance.now() < manualUntil) return;
    const rect = range.getBoundingClientRect();
    const top = (document.querySelector('.top')?.getBoundingClientRect().bottom || 0) + 18;
    const bottom = innerHeight - (floating.hidden?20:floating.getBoundingClientRect().height+32);
    if (rect.height && (rect.top < top || rect.bottom > bottom))
      window.scrollBy({top:rect.top - (top + Math.max(0,bottom-top)/2), behavior:'instant'});
  }
  function show(entry) {
    clearHighlight();
    currentEntry = entry;
    entry.marker.classList.add('narrated-verse');
    korean();
    const all = ranges(entry);
    if (highlightOK) CSS.highlights.set('bible-reading', new Highlight(...all));
    const visible=all.find(r=>r.getBoundingClientRect().height);if(visible)follow(visible);
  }
  function refreshVoices(settled=false) {
    const wasIdle=state==='idle';
    voiceSettled=settled;
    const selected = voiceSelect.value;
    try { voices = synth.getVoices().filter(v => v.localService === true && /^en(?:[-_]|$)/i.test(v.lang)).sort((a,b)=>voiceRank(b)-voiceRank(a)); }
    catch { voices = []; }
    if (state !== 'idle' && !voices.some(v => v.voiceURI === selected)) stop('기기 음성이 변경되어 낭독을 멈췄습니다.');
    voiceSelect.replaceChildren();
    voices.forEach(v => voiceSelect.add(new Option(`${v.name} · ${v.lang}`,v.voiceURI)));
    if (voices.length) {
      clearTimeout(voiceTimer);
      voiceSelect.value = voices.find(v=>v.voiceURI===selected)?.voiceURI || voices[0].voiceURI;
    } else {
      voiceSelect.add(new Option(settled?'기기 영어 음성 없음':'음성 확인 중',''));
    }
    if(wasIdle)status.textContent=idleMessage();
    $('narration-preview').disabled=!voices.length;
    update();
  }
  function findVoices() {
    stop(); clearTimeout(voiceTimer); refreshVoices();
    if (!voices.length) voiceTimer = setTimeout(()=>refreshVoices(true),2500);
  }
  function setChapter() {
    stop();
    parseFailed=false;
    try { entries = collectReadings(root); } catch { entries = [];parseFailed=true; }
    if(root.textContent.trim()&&!entries.length)parseFailed=true;
    ready = entries.length > 0;
    status.textContent=idleMessage();
    update();
  }
  function start() {
    const wasBusy = state !== 'idle';
    stop();
    try { entries = collectReadings(root); } catch { entries = []; }
    const verse = Number($('verse').value);
    const index = verse ? entries.findIndex(e=>verse>=e.from&&verse<=e.to) : 0;
    if (index < 0 || !entries[index]) { status.textContent='선택한 절에 읽을 NIV 본문이 없습니다. 다른 절을 골라 주세요.'; return; }
    const session = serial, voiceURI = voiceSelect.value;
    const repeat = Number($('narration-repeat').value), rate = Number($('narration-rate').value);
    const oneVerse = $('narration-mode').value === 'verse';
    manualUntil = 0;
    function speak(i, turn) {
      if (session !== serial) return;
      let voice;
      try { voice = synth.getVoices().find(v=>v.voiceURI===voiceURI&&v.localService===true&&/^en(?:[-_]|$)/i.test(v.lang)); } catch {}
      if (!voice) { stop();refreshVoices(true);status.textContent='선택한 기기 음성을 사용할 수 없습니다. 음성 다시 찾기를 눌러 주세요.';return; }
      const entry = entries[i];
      if (!root.contains(entry.marker) || entry.runs.some(r=>!r.node.isConnected)) { stop('본문이 바뀌어 낭독을 멈췄습니다. 다시 눌러 주세요.'); return; }
      const u = new SpeechSynthesisUtterance(entry.text);
      utterance = u; u.voice=voice; u.lang=voice.lang; u.rate=rate;
      const valid = () => session===serial && utterance===u;
      let last=-1, wordSync=true;
      state='playing'; update();
      status.textContent=`${entry.label}절 · ${turn}/${repeat}회 읽기 준비 중`;
      $('narration-current').textContent=`${entry.label}절`;
      u.onstart=()=>{
        if (!valid()) return;
        if (!u.voice || u.voice.voiceURI!==voiceURI || u.voice.localService!==true) { stop('선택한 기기 음성을 확인하지 못해 낭독을 멈췄습니다.'); return; }
        clearTimeout(startTimer);
        try { show(entry); } catch { stop('본문이 바뀌어 낭독을 멈췄습니다.'); return; }
        observer.observe(root,{childList:true,subtree:true,characterData:true});
        status.textContent=`${entry.label}절 · ${turn}/${repeat}회 읽는 중`;
      };
      u.onboundary=event=>{
        if (!valid() || !currentEntry || !wordSync || event.name!=='word') return;
        const pos=event.charIndex;
        // Engines may point at opening punctuation; accept only this word's prefix.
        if (!Number.isInteger(pos)||pos<=last||pos<0||pos>=entry.text.length) {
          wordSync=false;paintOutline([]);if(highlightOK)CSS.highlights.delete('bible-word');return;
        }
        last=pos;
        const word=entry.words.find(w=>pos>=w.start&&pos<w.end)||entry.words.find(w=>w.start>pos&&/^\W*$/.test(entry.text.slice(pos,w.start)));
        if(!word){paintOutline([]);if(highlightOK)CSS.highlights.delete('bible-word');return;}
        try {
          const active=ranges(entry,word.start,word.end);
          if(highlightOK){CSS.highlights.delete('bible-word');const h=new Highlight(...active);h.priority=1;CSS.highlights.set('bible-word',h);}
          if(active[0])follow(active[0]);
          paintOutline(active);
        } catch { stop('본문이 바뀌어 낭독을 멈췄습니다.'); }
      };
      u.onend=()=>{
        if(!valid())return;
        utterance=null; clearTimeout(startTimer);clearTimeout(endTimer);
        paintOutline([]);
        if(highlightOK)CSS.highlights.delete('bible-word');
        const again=turn<repeat, onward=!oneVerse&&i+1<entries.length;
        if(!again&&!onward){stop('낭독을 마쳤습니다.');return;}
        state='waiting';update();
        const gap=repeat>1?Math.max(2500,Math.min(12000,entry.words.length*450/rate)):200;
        status.textContent=repeat>1?`${entry.label}절 · 소리 내어 따라 읽어 보세요. 잠시 뒤 ${again?'한 번 더 읽습니다.':'다음 절을 읽습니다.'}`:`${entry.label}절 · 다음 절로 넘어갑니다.`;
        nextTimer=setTimeout(()=>speak(again?i:i+1,again?turn+1:1),gap);
      };
      u.onerror=()=>{if(valid())stop('낭독이 중단되었습니다. 영어 낭독을 다시 누르거나 다른 기기 음성을 선택해 주세요.');};
      startTimer=setTimeout(()=>{if(valid())stop('음성이 시작되지 않았습니다. 영어 낭독을 다시 눌러 주세요.');},5000);
      endTimer=setTimeout(()=>{if(valid())stop('음성의 완료를 확인하지 못해 멈췄습니다. 다른 기기 음성을 선택해 주세요.');},Math.max(45000,entry.text.length*200/rate));
      try { synth.speak(u); } catch { if(valid())stop('이 브라우저에서 음성을 재생하지 못했습니다.'); }
    }
    if(wasBusy){state='waiting';update();nextTimer=setTimeout(()=>speak(index,1),100);}
    else speak(index,1);
  }
  play.addEventListener('click',start);
  $('narration-preview').addEventListener('click',()=>{
    const wasBusy=state!=='idle';
    stop();
    const token=serial;
    function preview() {
      if(token!==serial)return;
      let voice;try{voice=synth.getVoices().find(v=>v.voiceURI===voiceSelect.value&&v.localService===true&&/^en(?:[-_]|$)/i.test(v.lang));}catch{}
      if(!voice){stop();refreshVoices(true);return;}
      const u=new SpeechSynthesisUtterance("Welcome! Let's read together. Listen closely, then try it yourself.");
      utterance=u;u.voice=voice;u.lang=voice.lang;u.rate=Number($('narration-rate').value);
      const valid=()=>token===serial&&utterance===u;
      state='playing';update();
      u.onstart=()=>{if(valid())clearTimeout(startTimer);};
      u.onend=()=>{if(valid()){utterance=null;stop('음성 미리듣기를 마쳤습니다.');}};
      u.onerror=()=>{if(valid())stop('음성을 재생하지 못했습니다. 다른 기기 음성을 골라 주세요.');};
      startTimer=setTimeout(()=>{if(valid())stop('음성이 시작되지 않았습니다. 음성 미리듣기를 다시 눌러 주세요.');},5000);
      endTimer=setTimeout(()=>{if(valid())stop('음성 재생을 확인하지 못했습니다. 다른 음성을 골라 주세요.');},30000);
      try{synth.speak(u);}catch{stop('음성을 재생하지 못했습니다.');}
    }
    $('narration-current').textContent='음성 미리듣기';status.textContent='선택한 음성으로 자체 영어 예문을 읽습니다.';
    if(wasBusy){state='waiting';update();nextTimer=setTimeout(preview,100);}
    else preview();
  });
  [stopButton,$('narration-stop-floating')].forEach(b=>b.addEventListener('click',()=>stop('낭독을 멈췄습니다.')));
  ['narration-voice','narration-rate','narration-repeat','narration-mode','verse'].forEach(id=>$(id).addEventListener('change',()=>{if(state!=='idle')stop('선택을 바꾸어 낭독을 멈췄습니다. 영어 낭독을 다시 눌러 주세요.');}));
  $('narration-refresh').addEventListener('click',findVoices);
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&state!=='idle')stop('화면을 떠나 낭독을 멈췄습니다.');});
  window.addEventListener('pagehide',()=>{stop('화면을 떠나 낭독을 멈췄습니다.');clearTimeout(voiceTimer);});
  window.addEventListener('pageshow',e=>{if(e.persisted)findVoices();});
  ['wheel','touchstart'].forEach(type=>document.addEventListener(type,()=>{manualUntil=performance.now()+8000;},{passive:true}));
  window.addEventListener('scroll',()=>paintOutline(),{passive:true});window.addEventListener('resize',()=>paintOutline());
  document.addEventListener('keydown',e=>{if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(e.key))manualUntil=performance.now()+8000;});
  const api={setChapter,reset:()=>{stop();entries=[];ready=false;parseFailed=false;update();status.textContent=idleMessage();},refreshKorean:korean};
  if(!synth||typeof window.SpeechSynthesisUtterance!=='function'){
    status.textContent='이 브라우저는 기기 음성 낭독을 지원하지 않습니다. 위의 정식 낭독 링크를 이용해 주세요.';
    panel.querySelectorAll('button,select,input').forEach(el=>el.disabled=true);
    return noop;
  }
  try { synth.cancel(); } catch {}
  synth.addEventListener('voiceschanged',()=>refreshVoices(true));
  findVoices();
  return api;
}

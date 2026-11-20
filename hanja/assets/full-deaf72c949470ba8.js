// 논어 전편. 학습 상태는 이 탭의 메모리에만 둔다.
(() => {
 'use strict';
 const $=s=>document.querySelector(s), src=$('#hanja-src'), pad=$('#pad');
 if(!src||!pad)return;
 const ui={chapter:$('#chapter'),articles:[...document.querySelectorAll('.psg')],board:$('#board'),wrap:$('.board-wrap'),
  canvas:$('#freehand'),trace:$('.trace'),chips:$('.chips'),title:$('.cur-ch'),hun:$('.cur-hun'),note:$('.cur-note'),kind:$('.stroke-kind'),
  status:$('.status'),strip:$('.strip'),result:$('.result'),play:$('#b-play'),quiz:$('#b-quiz'),run:$('#b-run'),stop:$('#b-stop'),
  clear:$('#b-clear'),next:$('#b-free-next'),retry:$('#b-retry'),outline:$('#b-outline'),prev:$('#previous'),following:$('#following')};
 let D,W,chapter=0,current=0,seq=0,running=false,shown=null,chain=Promise.resolve(),freeDone=null,ink=false,drawing=false,lastSize=0,lastRatio=0;
 const cache=new Map(),ctx=ui.canvas.getContext('2d');
 const esc=t=>String(t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
 const say=t=>ui.status.textContent=t;
 const chapterData=()=>D.chapters[chapter];
 const dims=()=>Math.max(120,Math.round(ui.wrap.clientWidth));
 async function getJSON(url){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);try{const r=await fetch(url,{signal:controller.signal});if(!r.ok)throw Error(r.status);return await r.json();}finally{clearTimeout(timer);}}
 function stop(){seq++;running=false;freeDone=null;ui.stop.hidden=true;ui.run.hidden=false;ui.next.hidden=true;ui.board.classList.remove('quiz');if(W)W.cancelQuiz();}
 function clearInk(){ctx.clearRect(0,0,ui.canvas.width,ui.canvas.height);ink=false;drawing=false;ui.next.disabled=true;}
 function resize(){
  const n=dims(),ratio=window.devicePixelRatio||1;if(n===lastSize&&ratio===lastRatio)return;
  const saved=document.createElement('canvas'),hadInk=ink;saved.width=ui.canvas.width;saved.height=ui.canvas.height;
  if(hadInk)saved.getContext('2d').drawImage(ui.canvas,0,0);
  ui.canvas.width=Math.round(n*ratio);ui.canvas.height=Math.round(n*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);
  ctx.strokeStyle='#1c3b2e';ctx.lineWidth=6;ctx.lineCap='round';ctx.lineJoin='round';
  if(hadInk)ctx.drawImage(saved,0,0,saved.width,saved.height,0,0,n,n);
  drawing=false;ink=hadInk;ui.next.disabled=!hadInk;if(W&&n!==lastSize)W.updateDimensions({width:n,height:n});lastSize=n;lastRatio=ratio;
 }
 function busy(flag){ui.play.disabled=flag;ui.quiz.disabled=flag;ui.run.disabled=flag;}
 function chips(){const list=[...new Set(chapterData().chars)];ui.chips.innerHTML=list.map(c=>`<button class="chip" type="button" data-char="${esc(c)}" aria-pressed="${c===chapterData().chars[current]}">${esc(c)}</button>`).join('');}
 function strip(data){ui.strip.innerHTML=data?data.strokes.map((_,i)=>`<li><span>${i+1}</span><svg viewBox="0 0 1024 1024" aria-hidden="true"><g transform="translate(0,900) scale(1,-1)">${data.strokes.slice(0,i+1).map((p,j)=>`<path d="${p}" fill="${i===j?'#b3261e':'#2b2a26'}"/>`).join('')}</g></svg></li>`).join(''):'';}
 function mark(i){[...ui.strip.children].forEach((e,j)=>e.classList.toggle('now',j===i));}
 async function select(index,token){
  current=index;const ch=chapterData().chars[index],meta=D.chars[ch];busy(true);ui.retry.hidden=true;
  ui.title.textContent=ch;ui.hun.textContent=`${meta.hun} · 이 장의 독음 ${chapterData().sounds[index]}`;
  ui.note.textContent=meta.notes.join(' / ');ui.kind.textContent=meta.stroke_status;chips();
  ui.board.hidden=true;ui.canvas.hidden=true;ui.trace.hidden=true;ui.next.hidden=true;ui.clear.hidden=true;strip(null);
  if(!meta.file){
   ui.trace.textContent=ch;ui.trace.hidden=!ui.outline.checked;ui.canvas.hidden=false;ui.clear.hidden=false;clearInk();
   busy(false);ui.play.disabled=true;say('이 글자는 필순 자료가 없어 자유롭게 따라 씁니다. 순서·정확도는 자동 판정하지 않습니다.');return {free:true};
  }
  try{
   let data=cache.get(ch);if(!data){data=await getJSON(meta.file);cache.set(ch,data);}
   if(token!==seq)return null;
   chain=chain.catch(()=>{}).then(async()=>{
    if(token!==seq)return;
    if(!W){
     let resolve;const ready=new Promise(r=>resolve=r);
     W=HanziWriter.create(ui.board,ch,{width:dims(),height:dims(),padding:10,renderer:'svg',strokeColor:'#1a1a17',outlineColor:'#ded7c9',highlightColor:'#9c7d46',drawingColor:'#1c3b2e',drawingWidth:12,strokeAnimationSpeed:1.4,delayBetweenStrokes:220,showHintAfterMisses:1,
      charDataLoader:(c,ok,err)=>cache.has(c)?ok(cache.get(c)):err(Error('Missing prepared data')),
      onLoadCharDataSuccess:()=>resolve()});await ready;shown=ch;
    }else if(shown!==ch){await W.setCharacter(ch);shown=ch;}
   });await chain;if(token!==seq)return null;
   ui.board.hidden=false;W.showCharacter();W.showOutline();strip(data);busy(false);
   const count=data.strokes.length;ui.kind.textContent=`${meta.stroke_status} · 그림 ${count}획${meta.strokes?' / 한국 자전 '+meta.strokes+'획':''}`;
   return {free:false};
  }catch(e){if(token!==seq)return null;busy(true);ui.retry.hidden=false;say('필순 자료를 불러오지 못했습니다. 원문과 PDF는 그대로 볼 수 있습니다. 다시 불러오기를 눌러 주세요.');return null;}
 }
 async function play(){stop();ui.result.hidden=true;const token=seq,loaded=await select(current,token);if(!loaded||loaded.free||token!==seq)return;say('필순을 그리는 중입니다.');W.animateCharacter({onComplete:()=>{if(token===seq)say('필순을 다 그렸습니다. 직접 쓰기로 연습해 보세요.');}});}
 async function quizAt(index,token,done){
  const loaded=await select(index,token);if(!loaded||token!==seq)return;
  if(loaded.free){freeDone=()=>{if(token===seq&&ink){ui.next.hidden=true;freeDone=null;done(null);}};ui.next.textContent=running?'썼어요 · 다음 글자':'썼어요';ui.next.hidden=false;return;}
  W.hideCharacter();if(ui.outline.checked)W.showOutline();else W.hideOutline();ui.board.classList.add('quiz');
  W.quiz({onMistake:d=>{if(token===seq){mark(d.strokeNum);say(`${d.strokeNum+1}번째 획의 순서나 방향을 확인하세요. 맞는 획이 깜빡입니다.`);}},
   onCorrectStroke:d=>{if(token===seq){mark(-1);say(`${d.strokeNum+1}획 맞음 · 남은 획 ${d.strokesRemaining}`);}},
   onComplete:d=>{if(token!==seq)return;ui.board.classList.remove('quiz');queueMicrotask(()=>{if(token===seq)W.cancelQuiz();});done(d.totalMistakes);}});
  say(`${running?`${index+1}/${chapterData().chars.length}자 · `:''}첫 획부터 써 보세요.`);
 }
 function quiz(){stop();ui.result.hidden=true;const token=seq;quizAt(current,token,n=>say(n===null?'자유 필기를 마쳤습니다. 정확도 판정은 하지 않았습니다.':`다 썼습니다 · 틀린 횟수 ${n}번`));}
 function run(){
  stop();running=true;ui.run.hidden=true;ui.stop.hidden=false;ui.result.hidden=true;const token=seq,log=[],list=chapterData().chars;
  const step=i=>{if(token!==seq)return;if(i===list.length){finish(log);return;}quizAt(i,token,n=>{log.push([list[i],n]);setTimeout(()=>step(i+1),350);});};step(0);
 }
 function finish(log){const mistakes=log.reduce((a,[,n])=>a+(n||0),0),free=log.filter(([,n])=>n===null).length;stop();
  ui.result.innerHTML=`<p><strong>${D.name}편 ${chapter+1}장 ${log.length}자 연습 완료</strong></p><p>자동 판정 ${log.length-free}자 · 틀린 횟수 ${mistakes}번${free?` / 자유 필기 ${free}자(판정 없음)`:''}</p><ol>${log.map(([c,n])=>`<li><b>${esc(c)}</b> ${n===null?'자유 필기':n+'번'}</li>`).join('')}</ol>`;ui.result.hidden=false;say('이 장을 끝까지 연습했습니다.');
 }
 function hashIndex(){const s=location.hash;let n=/^#ch-(\d+)$/.exec(s);if(!n&&D.book===1&&/^#p[1-4]$/.test(s))return s==='#p4'?1:0;return n&&+n[1]>=1&&+n[1]<=D.chapters.length?+n[1]-1:0;}
 function renderChapter(){
  stop();chapter=hashIndex();current=0;ui.result.hidden=true;ui.chapter.value=String(chapter+1);
  ui.articles.forEach((a,i)=>a.hidden=i!==chapter);ui.prev.href=chapter?`#ch-${chapter}`:D.previous;
  ui.following.href=chapter+1<D.chapters.length?`#ch-${chapter+2}`:D.next;
  ui.prev.hidden=!ui.prev.getAttribute('href');ui.following.hidden=!ui.following.getAttribute('href');
  $('#pad-title').textContent=`${D.name}편 ${chapter+1}장 쓰기`;
  say('글자를 고르거나 이 장 이어 쓰기를 눌러 보세요.');select(0,seq);
 }
 function point(e){const r=ui.canvas.getBoundingClientRect();return [e.clientX-r.left,e.clientY-r.top];}
 ui.canvas.addEventListener('pointerdown',e=>{e.preventDefault();drawing=true;ui.canvas.setPointerCapture(e.pointerId);const [x,y]=point(e);ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+.1,y+.1);ctx.stroke();ink=true;ui.next.disabled=false;});
 ui.canvas.addEventListener('pointermove',e=>{if(!drawing)return;e.preventDefault();const [x,y]=point(e);ctx.lineTo(x,y);ctx.stroke();});
 ['pointerup','pointercancel','lostpointercapture'].forEach(n=>ui.canvas.addEventListener(n,()=>drawing=false));
 ui.clear.addEventListener('click',clearInk);ui.next.addEventListener('click',()=>freeDone&&freeDone());
 ui.play.addEventListener('click',play);ui.quiz.addEventListener('click',quiz);ui.run.addEventListener('click',run);
 ui.stop.addEventListener('click',()=>{stop();select(current,seq);say('멈췄습니다.');});
 ui.retry.addEventListener('click',()=>{if(running){run();}else{stop();select(current,seq);}});
 ui.outline.addEventListener('change',()=>{ui.trace.hidden=!ui.outline.checked||ui.canvas.hidden;if(W){if(ui.outline.checked)W.showOutline();else W.hideOutline();}});
 ui.chips.addEventListener('click',e=>{if(!D)return;const b=e.target.closest('[data-char]');if(b){current=chapterData().chars.indexOf(b.dataset.char);play();}});
 $('#chapters').addEventListener('click',e=>{if(!D)return;const b=e.target.closest('[data-char]'),runButton=e.target.closest('[data-run]');if(!b&&!runButton)return;const article=e.target.closest('.psg'),n=+article.dataset.chapter-1;
  if(n!==chapter){history.pushState(null,'',`#ch-${n+1}`);renderChapter();}
  if(b){current=+b.dataset.index;play();}else run();pad.scrollIntoView({behavior:'smooth',block:'start'});
 });
 ui.chapter.addEventListener('change',()=>{location.hash=`ch-${ui.chapter.value}`;});
 window.addEventListener('hashchange',()=>{if(D){renderChapter();$('#reading-top').scrollIntoView({block:'start'});}});
 let timer;window.addEventListener('resize',()=>{clearTimeout(timer);timer=setTimeout(resize,150);});
 getJSON(src.dataset.src).then(data=>{if(typeof HanziWriter==='undefined')throw Error('Writer unavailable');D=data;pad.hidden=false;resize();renderChapter();$('#chapter-controls').hidden=false;}).catch(()=>{D=null;$('#pad-fail').hidden=false;pad.hidden=true;ui.articles.forEach(a=>a.hidden=false);document.querySelectorAll('[data-run]').forEach(b=>b.hidden=true);document.querySelectorAll('.psg [data-char]').forEach(b=>b.disabled=true);});
})();

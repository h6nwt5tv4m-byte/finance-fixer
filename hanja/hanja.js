// 논어 쓰기 — 필순 보기·직접 쓰기·구절 이어 쓰기. 데이터는 make.py가 만든 hanja-data.json(정본=~/projects/hanja-practice/make.py).
// 쓴 내용은 어디에도 저장하지 않는다(서버·localStorage 모두 없음).
(() => {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const pad = $('#pad'), fail = $('#pad-fail'), src = $('#hanja-src');
  if (!pad || !src) return;
  const showFail = () => { pad.hidden = true; if (fail) fail.hidden = false; };
  if (typeof HanziWriter === 'undefined') { showFail(); return; }

  const ui = {
    tabs: $('.tabs', pad), chips: $('.chips', pad), board: $('#board'), stage: $('.stage', pad),
    title: $('.cur-ch', pad), hun: $('.cur-hun', pad), note: $('.cur-note', pad),
    status: $('.status', pad), strip: $('.strip', pad), result: $('.result', pad),
    play: $('#b-play'), quiz: $('#b-quiz'), run: $('#b-run'), stop: $('#b-stop'), outline: $('#b-outline'),
  };
  let D, W, cur = null, group = 0, seq = 0, running = null;
  // 글자 불러오기는 한 줄로 세운다: 앞 불러오기가 끝난 뒤에만 다음 setCharacter, 이미 띄운 글자면 건너뜀.
  // (불러오는 중에 setCharacter를 또 부르면 라이브러리가 렌더러를 두 벌 붙여 이전 획이 남는다)
  let shown = null, chain = Promise.resolve();
  const load = (ch) => (chain = chain.then(() => { if (shown === ch) return; shown = ch; return W.setCharacter(ch); }).catch(() => {}));

  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const say = (t) => { ui.status.textContent = t; };
  // 묶음(make.py가 정함): 앞쪽 = 구절마다 하나(0..n-1), 뒤쪽 = 다 들어온 장마다 'N장 전체'
  const groupChars = (g) => D.groups[g].idx.flatMap((i) => D.passages[i - 1].chars);
  const groupName = (g) => D.groups[g].label;
  const uniq = (a) => [...new Set(a)];

  function size() {
    const w = ui.stage.clientWidth;
    return Math.round(Math.max(200, Math.min(320, w >= 640 ? 320 : w - 2)));
  }

  function stopAll() {
    seq++; running = null; ui.stop.hidden = true; ui.run.hidden = false;
    ui.board.classList.remove('quiz');
    if (W) { try { W.cancelQuiz(); } catch (e) { /* 퀴즈 중이 아님 */ } }
  }

  function strip(ch, now = -1) {
    const st = D.chars[ch].data.strokes;
    ui.strip.innerHTML = st.map((_, j) => {
      const paths = st.slice(0, j + 1).map((d, m) => `<path d="${d}" fill="${m === j ? '#b3261e' : '#2b2a26'}"/>`).join('');
      return `<li class="${j === now ? 'now' : ''}"><span>${j + 1}</span><svg viewBox="0 0 1024 1024" aria-hidden="true"><g transform="translate(0,900) scale(1,-1)">${paths}</g></svg></li>`;
    }).join('');
    ui.strip.setAttribute('aria-label', `${ch} 필순 ${st.length}단계`);
  }
  function markStrip(n) {
    [...ui.strip.children].forEach((li, j) => li.classList.toggle('now', j === n));
  }

  function chips() {
    ui.chips.innerHTML = uniq(groupChars(group)).map((c) =>
      `<button type="button" class="chip" data-ch="${esc(c)}" aria-pressed="${c === cur}" lang="zh-Hant">${esc(c)}</button>`).join('');
    [...ui.tabs.children].forEach((b, i) => b.setAttribute('aria-pressed', String(i === group)));
    ui.run.textContent = `${groupName(group)} 이어 쓰기`;
  }

  async function select(ch, { keepStatus = false } = {}) {
    const c = D.chars[ch]; if (!c) return;
    cur = ch;
    ui.title.textContent = ch;
    ui.hun.textContent = `${c.hun} · ${c.strokes}획`;
    ui.note.innerHTML = c.notes.map(esc).join('<br>');
    ui.note.hidden = !c.notes.length;
    [...ui.chips.children].forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.ch === ch)));
    strip(ch);
    if (!keepStatus) say('');
    await load(ch);
    W.showCharacter(); W.showOutline(); // 같은 글자라 다시 안 불러온 경우에도 보는 상태로
  }

  async function play(ch = cur) {
    stopAll(); ui.result.hidden = true;
    const my = seq; await select(ch);
    if (my !== seq) return;
    say(`필순을 그리는 중 — ${D.chars[cur].data.strokes.length}획`);
    W.animateCharacter({ onComplete: () => { if (my === seq) say('다 그렸습니다. 다시 보려면 [필순 보기], 써 보려면 [직접 쓰기].'); } });
  }

  // 한 글자 쓰기. done(틀린 횟수)은 다 썼을 때만 부른다.
  async function quizOne(ch, my, done) {
    await select(ch, { keepStatus: true });
    if (my !== seq) return;
    W.hideCharacter();
    if (ui.outline.checked) W.showOutline(); else W.hideOutline();
    ui.board.classList.add('quiz');
    W.quiz({
      onMistake: (d) => {
        if (my !== seq) return;
        markStrip(d.strokeNum);
        say(`${d.strokeNum + 1}번째 획이 아닙니다 — 순서나 방향을 확인하세요. 깜빡인 획을 따라 쓰면 됩니다.`);
      },
      onCorrectStroke: (d) => {
        if (my !== seq) return;
        markStrip(-1);
        if (d.strokesRemaining > 0) say(`${d.strokeNum + 1}획 맞음 · 남은 획 ${d.strokesRemaining}`);
      },
      onComplete: (s) => {
        if (my !== seq) return;
        ui.board.classList.remove('quiz');
        queueMicrotask(() => { if (my === seq) W.cancelQuiz(); }); // 끝난 퀴즈가 칸의 터치 스크롤을 계속 막지 않게
        done(s.totalMistakes);
      },
    });
  }

  async function quiz() {
    stopAll(); ui.result.hidden = true;
    const my = seq;
    say('칸에 첫 획부터 써 보세요. 틀리면 맞는 획이 깜빡입니다.');
    await quizOne(cur, my, (m) => say(m ? `다 썼습니다 — 틀린 횟수 ${m}번. [직접 쓰기]로 다시.` : '다 썼습니다 — 한 번도 안 틀렸습니다.'));
  }

  async function run() {
    stopAll(); ui.result.hidden = true;
    const my = seq, list = groupChars(group), log = [];
    running = group; ui.run.hidden = true; ui.stop.hidden = false;
    const step = async (i) => {
      if (my !== seq) return;
      if (i >= list.length) { finish(log); return; }
      say(`${groupName(group)} 이어 쓰기 ${i + 1}/${list.length} — 「${list[i]}」`);
      await quizOne(list[i], my, (m) => {
        log.push([list[i], m]);
        setTimeout(() => step(i + 1), 700);
      });
    };
    step(0);
  }

  function finish(log) {
    const total = log.reduce((a, [, m]) => a + m, 0);
    const name = groupName(group);
    stopAll();
    ui.result.innerHTML = `<p><b>${esc(name)}</b> ${log.length}자 다 썼습니다 — 틀린 횟수 합계 ${total}번</p>` +
      `<ol>${log.map(([c, m]) => `<li class="${m ? 'miss' : ''}"><span lang="zh-Hant">${esc(c)}</span><small>${m ? m + '번' : '0'}</small></li>`).join('')}</ol>`;
    ui.result.hidden = false;
    say(total ? '틀린 글자는 칩에서 골라 [필순 보기]로 다시 확인해 보세요.' : '한 번도 안 틀렸습니다.');
  }

  function init(data) {
    D = data;
    ui.tabs.innerHTML = D.groups
      .map((g, i) => `<button type="button" data-g="${i}" aria-pressed="${i === 0}">${esc(g.label)}</button>`).join('');
    cur = D.passages[0].chars[0];
    chips();
    pad.hidden = false; // 크기를 재기 전에 보이게(숨긴 채 재면 0)
    let first; chain = new Promise((res) => { first = res; }); shown = cur;
    W = HanziWriter.create(ui.board, cur, {
      width: size(), height: size(), padding: 10, renderer: 'svg',
      strokeColor: '#1a1a17', outlineColor: '#ddd6c6', highlightColor: '#a8843f', drawingColor: '#1c3b2e',
      drawingWidth: 14, strokeAnimationSpeed: 1, delayBetweenStrokes: 350,
      showHintAfterMisses: 1, highlightOnComplete: true,
      charDataLoader: (c, ok, err) => { const x = D.chars[c]; if (x) ok(x.data); else err(new Error('no data: ' + c)); },
      onLoadCharDataSuccess: () => first(),
      onLoadCharDataError: () => { first(); showFail(); },
    });
    select(cur);

    ui.tabs.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-g]'); if (!b) return;
      stopAll(); group = +b.dataset.g; ui.result.hidden = true;
      cur = groupChars(group)[0]; chips(); select(cur);
    });
    ui.chips.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-ch]'); if (!b) return;
      play(b.dataset.ch);
    });
    ui.play.addEventListener('click', () => play());
    ui.quiz.addEventListener('click', quiz);
    ui.run.addEventListener('click', run);
    ui.stop.addEventListener('click', () => { stopAll(); say('멈췄습니다.'); select(cur, { keepStatus: true }); });
    ui.outline.addEventListener('change', () => { if (ui.outline.checked) W.showOutline(); else W.hideOutline(); });

    // 본문 구절의 글자를 누르면 위 연습 칸에서 그 글자를 연다
    document.querySelectorAll('.psg').forEach((el, i) => el.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-ch]'); const r = e.target.closest('button[data-run]');
      if (!b && !r) return;
      stopAll(); group = i; ui.result.hidden = true;
      cur = b ? b.dataset.ch : D.passages[i].chars[0]; chips();
      pad.scrollIntoView({ behavior: 'smooth', block: 'start' });
      if (r) run(); else play(cur);
    }));

    let rt;
    window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { const s = size(); W.updateDimensions({ width: s, height: s }); }, 150); });
  }

  fetch(src.dataset.src).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }).then(init).catch(showFail);
})();

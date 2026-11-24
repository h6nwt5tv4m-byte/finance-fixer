(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);

  // 읽기·복습·진도는 음성 엔진과 독립적으로 동작한다.
  $('quiz').hidden = false;
  const answers = [ ['q1', 'b', 'messenger는 소식을 전하는 사람입니다.'], ['q2', 'a', 'prepare for는 어떤 일을 대비한다는 뜻입니다.'], ['q3', 'c', '8절은 물 세례와 성령으로 주는 세례를 대비합니다.'] ];
  $('quiz').addEventListener('change', () => $('quiz-result').replaceChildren());
  $('quiz').addEventListener('submit', (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const score = answers.filter(([name, value]) => data.get(name) === value).length;
    $('quiz-result').replaceChildren();
    const title = document.createElement('strong');
    title.textContent = `3문항 중 ${score}문항을 맞혔습니다.`;
    $('quiz-result').append(title);
    answers.forEach(([name, value, explanation], i) => {
      const p = document.createElement('p');
      p.textContent = `${i + 1}번 ${data.get(name) === value ? '정답' : '다시 확인'} · ${explanation}`;
      $('quiz-result').append(p);
    });
  });
  $('progress').hidden = false;
  const key = 'finance-fixer:bible:v1:mark-1-1-8:read';
  let completed = false;
  function showProgress(saved = true, initial = false) {
    $('complete').setAttribute('aria-pressed', String(completed));
    $('progress-status').textContent = saved ? (completed ? '읽음 · 이 브라우저에 저장했습니다. 버튼을 다시 누르면 해제됩니다.' : '진도는 이 브라우저에만 저장됩니다.') : initial ? '이 브라우저에서는 저장을 사용할 수 없습니다. 읽음 표시는 현재 화면에만 남습니다.' : '저장하지 못했습니다. 현재 화면에만 표시되며, 새로 열면 이전 상태가 보일 수 있습니다.';
  }
  try { completed = localStorage.getItem(key) === '1'; showProgress(); }
  catch (_) { showProgress(false, true); }
  $('complete').addEventListener('click', () => {
    completed = !completed;
    try {
      const value = completed ? '1' : '0';
      localStorage.setItem(key, value);
      showProgress(localStorage.getItem(key) === value);
    } catch (_) { showProgress(false); }
  });

  const status = $('speech-status');
  const sayButtons = [...document.querySelectorAll('[data-say]')];
  document.querySelector('.speech-settings').hidden = false;
  function initRecordings() {
    if (typeof window.Audio !== 'function') throw new Error('Audio unavailable');
    const recordings = new Map([
      ["messenger", {file: "messenger", starts: [0.0]}],
      ["The messenger arrived before lunch.", {file: "messenger-line", starts: [0.0, 0.14, 0.48, 0.96, 1.28]}],
      ["prepare", {file: "prepare", starts: [0.0]}],
      ["We prepare for the trip together.", {file: "prepare-line", starts: [0.0, 0.2, 0.44, 0.72, 0.86, 1.08]}],
      ["wilderness", {file: "wilderness", starts: [0.0]}],
      ["They explored the wilderness on foot.", {file: "wilderness-line", starts: [0.0, 0.24, 0.6, 0.8, 1.22, 1.58]}],
      ["confess", {file: "confess", starts: [0.0]}],
      ["I must confess that I forgot your name.", {file: "confess-line", starts: [0.0, 0.22, 0.38, 0.74, 0.96, 1.06, 1.26, 1.5]}],
    ]);
    // Only our original vocabulary examples are eligible; never the Bible text.
    const cues = new Map();
    const prepared = new Map();
    sayButtons.forEach((button) => {
      const article = button.closest('.words article');
      const matches = [...(article?.querySelectorAll('.word-title h3, .example') || [])]
        .filter((el) => el.textContent === button.dataset.say);
      if (matches.length !== 1) return;
      const element = matches[0];
      if (!prepared.has(element)) {
        // Preserve any future nested markup instead of replacing it with spans.
        if (element.childElementCount) return;
        const text = element.textContent;
        const words = [];
        const fragment = document.createDocumentFragment();
        let offset = 0;
        for (const match of text.matchAll(/\S+/gu)) {
          fragment.append(text.slice(offset, match.index));
          const span = document.createElement('span');
          span.textContent = match[0];
          fragment.append(span);
          offset = match.index + match[0].length;
          words.push(span);
        }
        fragment.append(text.slice(offset));
        element.replaceChildren(fragment);
        prepared.set(element, { element, words });
      }
      cues.set(button, prepared.get(element));
    });
    let activeCue;
    function clearCue() {
      if (!activeCue) return;
      activeCue.element.classList.remove('speech-reading', 'speech-practice');
      activeCue.words.forEach(span => span.classList.remove('speech-current-word'));
      activeCue = undefined;
    }
    function showCue(cue, className) {
      clearCue();
      activeCue = cue;
      activeCue?.element.classList.add(className);
    }
    let session = 0;
    let state = 'idle';
    let repeatTimer;
    let startTimer;
    let endTimer;
    let activeAudio;
    let frame;
    const busy = () => state === 'playing' || state === 'waiting';
    function setState(next, message) {
      state = next;
      status.textContent = message;
      $('stop').disabled = !busy();
    }
    function stop(message = '', next = 'idle') {
      session += 1;
      clearTimeout(repeatTimer);
      clearTimeout(startTimer);
      clearTimeout(endTimer);
      repeatTimer = undefined;
      cancelAnimationFrame(frame);
      if (activeAudio) {
        const audio = activeAudio;
        activeAudio = null;
        audio.onplaying = audio.onended = audio.onerror = audio.onpause = null;
        audio.pause();
        audio.removeAttribute('src');
        audio.load();
      }
      clearCue();
      if (message) setState(next, message);
    }
    function playClip(button) {
      document.dispatchEvent(new Event('stop-passage-audio'));
      stop();
      const text = button.dataset.say;
      const cue = cues.get(button);
      const clip = recordings.get(text);
      if (!clip) {
        stop('이 항목의 음원이 없습니다.', 'error');
        return;
      }
      const audio = new Audio(`./audio/lesson-1/${clip.file}.m4a?v=20261121`);
      activeAudio = audio;
      const token = session;
      const count = Number($('repeat').value);
      const rate = Number($('rate').value);
      const gap = Math.max(2500, Math.min(10000, text.split(/\s+/).length * 500 / rate));
      function finished(n) {
        clearTimeout(startTimer);
        clearTimeout(endTimer);
        cancelAnimationFrame(frame);
        clearCue();
        if (n < count) {
          showCue(cue, 'speech-practice');
          setState('waiting', '소리 내어 따라 말해 보세요. 잠시 뒤 한 번 더 읽습니다.');
          repeatTimer = setTimeout(() => play(n + 1), gap);
        } else {
          stop('듣기를 마쳤습니다. 이번에는 혼자 읽어 보세요.');
        }
      }
      function play(n) {
        if (token !== session) return;
        repeatTimer = undefined;
        const current = () => token === session && activeAudio === audio;
        let index = -1;
        function paint() {
          if (!current()) return;
          const time = audio.currentTime;
          const next = clip.starts.findIndex((start, i) => start <= time && time < (clip.starts[i + 1] ?? Infinity));
          if (index !== next) {
            index = next;
            cue?.words.forEach((span, i) => span.classList.toggle('speech-current-word', i === index));
          }
          frame = requestAnimationFrame(paint);
        }
        function failed() {
          if (current()) stop('음원을 재생하지 못했습니다. 듣기 버튼을 눌러 다시 시도해 주세요.', 'error');
        }
        audio.onplaying = () => {
          if (!current()) return;
          clearTimeout(startTimer);
          clearTimeout(endTimer);
          endTimer = setTimeout(failed, 30000);
          showCue(cue, 'speech-reading');
          index = -1;
          setState('playing', `${n}/${count}회 재생 중`);
          cancelAnimationFrame(frame);
          paint();
        };
        audio.onended = () => { if (current()) finished(n); };
        audio.onpause = () => {
          if (current() && audio.paused && !audio.ended) stop('읽기가 일시 중단되었습니다. 듣기 버튼을 누르면 다시 시작합니다.');
        };
        audio.onerror = failed;
        audio.playbackRate = rate;
        if (n > 1) audio.currentTime = 0;
        setState('playing', `${n}/${count}회 듣기 준비 중`);
        startTimer = setTimeout(failed, 10000);
        try { audio.play().catch(failed); } catch (_) { failed(); }
      }
      play(1);
    }
    sayButtons.forEach((button) => {
      button.addEventListener('click', () => playClip(button));
      button.hidden = false;
    });
    document.addEventListener('stop-study-audio', () => { if (busy()) stop('읽기를 멈췄습니다.'); });
    $('study')?.addEventListener('toggle', () => { if (!$('study').open && busy()) stop('읽기를 멈췄습니다.'); });
    $('stop').addEventListener('click', () => { if (busy()) stop('읽기를 멈췄습니다.'); });
    ['rate', 'repeat'].forEach((id) => $(id).addEventListener('change', () => {
      if (busy()) stop('설정을 바꿨습니다. 듣기 버튼을 눌러 다시 시작해 주세요.');
    }));
    document.addEventListener('visibilitychange', () => { if (document.hidden && busy()) stop('화면을 떠나 읽기를 멈췄습니다.'); });
    window.addEventListener('pagehide', () => {
      stop(busy() ? '화면을 떠나 읽기를 멈췄습니다.' : '');
    });
  }
  try { initRecordings(); }
  catch (_) {
    status.textContent = '음원 재생을 준비하지 못했습니다. 페이지를 새로고침해 주세요.';
    [$('rate'), $('repeat'), $('stop'), ...sayButtons].forEach((el) => { el.disabled = true; });
  }
})();

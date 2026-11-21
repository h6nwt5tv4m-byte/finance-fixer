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
  sayButtons.forEach((button) => { button.hidden = false; button.disabled = true; });
  function initSpeech() {
    const synth = window.speechSynthesis;
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
    const recordedVoice = 'chatterbox';
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
          words.push({ span, start: match.index, end: offset });
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
      activeCue.words.forEach(({ span }) => span.classList.remove('speech-current-word'));
      activeCue = undefined;
    }
    function showCue(cue, className) {
      clearCue();
      activeCue = cue;
      activeCue?.element.classList.add(className);
    }
    let voices = [];
    let session = 0;
    let state = 'loading';
    let repeatTimer;
    let voiceTimer;
    let startTimer;
    let endTimer;
    let activeUtterance;
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
      const wasSpeaking = Boolean(activeUtterance);
      activeUtterance = null;
      clearCue();
      try { if (wasSpeaking) synth.cancel(); } catch (_) { /* 음성 오류가 본문·복습에 영향을 주지 않도록 한다. */ }
      if (message) setState(next, message);
    }
    function refreshVoices() {
      const select = $('voice');
      const previous = select.value || recordedVoice;
      voices = [];
      if (typeof window.SpeechSynthesisUtterance === 'function') {
        try { voices = (synth?.getVoices() || []).filter(v => /^en(?:[-_]|$)/i.test(v.lang)); }
        catch (_) { /* The lesson recordings also work without system voices. */ }
      }
      select.replaceChildren(new Option('Chatterbox · 영어 낭독', recordedVoice));
      voices.forEach(v => select.add(new Option(`${v.name} · ${v.lang}`, v.voiceURI)));
      select.value = voices.some(v => v.voiceURI === previous) ? previous : recordedVoice;
      if (busy() && select.value !== previous) stop('선택한 기기 음성이 바뀌어 재생을 멈췄습니다.');
      sayButtons.forEach(b => { b.disabled = false; });
      if (state === 'loading') setState('idle', '단어나 예문의 듣기 버튼을 눌러 보세요.');
    }
    function findVoices() {
      stop('단어나 예문의 듣기 버튼을 눌러 보세요.');
      clearTimeout(voiceTimer);
      refreshVoices();
      if (!voices.length && synth) voiceTimer = setTimeout(refreshVoices, 2500);
    }
    function speak(button) {
      stop();
      const text = button.dataset.say;
      const cue = cues.get(button);
      const recorded = $('voice').value === recordedVoice;
      const clip = recordings.get(text);
      const voice = voices.find(v => v.voiceURI === $('voice').value);
      if ((recorded && !clip) || (!recorded && !voice)) {
        stop('선택한 음성을 준비하지 못했습니다. 다른 영어 음성을 골라 주세요.', 'error');
        return;
      }
      const audio = recorded ? new Audio(`./audio/lesson-1/${clip.file}.m4a?v=20261121`) : null;
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
      function playRecording(n) {
        const current = () => token === session && activeAudio === audio;
        let index = -1;
        function paint() {
          if (!current()) return;
          const time = audio.currentTime;
          const next = clip.starts.findIndex((start, i) => start <= time && time < (clip.starts[i + 1] ?? Infinity));
          if (index !== next) {
            index = next;
            cue?.words.forEach(({span}, i) => span.classList.toggle('speech-current-word', i === index));
          }
          frame = requestAnimationFrame(paint);
        }
        function failed() {
          if (current()) stop('음원을 재생하지 못했습니다. 다시 듣거나 기기 음성을 선택해 주세요.', 'error');
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
      function play(n) {
        if (token !== session) return;
        repeatTimer = undefined;
        if (audio) { playRecording(n); return; }
        const utterance = new SpeechSynthesisUtterance(text);
        activeUtterance = utterance;
        const current = () => token === session && activeUtterance === utterance;
        let lastIndex = -1;
        let wordSync = true;
        utterance.voice = voice;
        utterance.lang = voice.lang;
        utterance.rate = rate;
        setState('playing', `${n}/${count}회 듣기 준비 중`);
        utterance.onstart = () => {
          if (!current()) return;
          clearTimeout(startTimer);
          showCue(cue, 'speech-reading');
          setState('playing', `${n}/${count}회 재생 중`);
        };
        utterance.onboundary = (event) => {
          if (!current() || activeCue !== cue || !cue || !wordSync || event.name !== 'word') return;
          const index = event.charIndex;
          if (!Number.isInteger(index) || index < 0 || index >= text.length || index <= lastIndex) {
            cue.words.forEach(({ span }) => span.classList.remove('speech-current-word'));
            wordSync = false;
            return;
          }
          lastIndex = index;
          // UTF-16 offsets match charIndex; whitespace selects the following word.
          const word = cue.words.find(({ end }) => end > index);
          cue.words.forEach(({ span }) => span.classList.toggle('speech-current-word', span === word?.span));
        };
        utterance.onend = () => {
          if (!current()) return;
          activeUtterance = null;
          finished(n);
        };
        utterance.onerror = (event) => {
          if (!current()) return;
          stop(event.error === 'canceled' || event.error === 'interrupted' ? '읽기가 중단되었습니다. 듣기 버튼을 눌러 다시 시작해 주세요.' : '음성을 재생하지 못했습니다. 다른 영어 음성을 선택하거나 브라우저를 바꿔 주세요.', 'error');
        };
        startTimer = setTimeout(() => {
          if (current()) stop('음성 재생이 시작되지 않았습니다. 듣기 버튼을 다시 누르거나 다른 음성·브라우저를 선택해 주세요.', 'error');
        }, 5000);
        endTimer = setTimeout(() => {
          if (current()) stop('음성 재생의 완료를 확인하지 못했습니다. 다른 음성·브라우저에서 다시 시도해 주세요.', 'error');
        }, Math.max(30000, text.length * 180 / rate));
        try { synth.speak(utterance); }
        catch (_) { stop('음성을 재생하지 못했습니다. 다른 브라우저에서 다시 시도해 주세요.', 'error'); }
      }
      play(1);
    }
    sayButtons.forEach((button) => button.addEventListener('click', () => speak(button)));
    $('stop').addEventListener('click', () => { if (busy()) stop('읽기를 멈췄습니다.'); });
    $('refresh-voices').addEventListener('click', findVoices);
    ['voice', 'rate', 'repeat'].forEach((id) => $(id).addEventListener('change', () => {
      if (busy()) stop('설정을 바꿨습니다. 듣기 버튼을 눌러 다시 시작해 주세요.');
    }));
    if (typeof synth?.addEventListener === 'function') synth.addEventListener('voiceschanged', () => refreshVoices(true));
    else if (synth) synth.onvoiceschanged = () => refreshVoices(true);
    findVoices();
    document.addEventListener('visibilitychange', () => { if (document.hidden && busy()) stop('화면을 떠나 읽기를 멈췄습니다.'); });
    window.addEventListener('pagehide', () => {
      stop(busy() ? '화면을 떠나 읽기를 멈췄습니다.' : '');
      clearTimeout(voiceTimer);
    });
  }
  try { initSpeech(); }
  catch (_) {
    $('voice').replaceChildren(new Option('예문 읽기 사용 불가', ''));
    status.textContent = '이 브라우저는 예문 읽기를 지원하지 않거나 음성을 준비하지 못했습니다. Bible Gateway의 NIV 듣기 링크를 이용해 주세요.';
    [$('voice'), $('rate'), $('repeat'), $('stop'), $('refresh-voices'), ...sayButtons].forEach((el) => { el.disabled = true; });
  }
})();

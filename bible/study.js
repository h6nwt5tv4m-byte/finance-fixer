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
    if (!synth || typeof window.SpeechSynthesisUtterance !== 'function') throw new Error('unsupported');
    let voices = [];
    let session = 0;
    let state = 'loading';
    let repeatTimer;
    let voiceTimer;
    let startTimer;
    let endTimer;
    let activeUtterance;
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
      activeUtterance = null;
      try { synth.cancel(); } catch (_) { /* 음성 오류가 본문·복습에 영향을 주지 않도록 한다. */ }
      if (message) setState(next, message);
    }
    function unavailable(message) {
      stop();
      voices = [];
      $('voice').replaceChildren(new Option('영어 음성 사용 불가', ''));
      sayButtons.forEach((b) => { b.disabled = true; });
      setState('unavailable', message);
    }
    function refreshVoices(settled = false) {
      const previous = voices[Number($('voice').value)]?.voiceURI;
      let available;
      try { available = synth.getVoices().filter((v) => /^en(?:[-_]|$)/i.test(v.lang)); }
      catch (_) { unavailable('영어 음성 목록을 불러오지 못했습니다. 음성 다시 찾기를 눌러 주세요.'); return; }
      if (!available.length) {
        if (busy()) stop();
        voices = [];
        $('voice').replaceChildren(new Option(settled ? '영어 음성 없음' : '음성 불러오는 중', ''));
        sayButtons.forEach((b) => { b.disabled = true; });
        setState(settled ? 'unavailable' : 'loading', settled ? '이 브라우저에서 영어 음성을 찾지 못했습니다. 음성 다시 찾기를 누르거나 다른 브라우저를 사용해 주세요. Bible Gateway의 NIV 듣기 링크도 이용할 수 있습니다.' : '영어 음성을 불러오고 있습니다.');
        return;
      }
      clearTimeout(voiceTimer);
      voices = available;
      $('voice').replaceChildren();
      voices.forEach((v, i) => $('voice').add(new Option(`${v.name} · ${v.lang}`, String(i))));
      const previousIndex = voices.findIndex((v) => v.voiceURI === previous);
      const defaultIndex = voices.findIndex((v) => v.default);
      $('voice').value = String(previousIndex >= 0 ? previousIndex : defaultIndex >= 0 ? defaultIndex : 0);
      sayButtons.forEach((b) => { b.disabled = false; });
      if (state === 'loading' || state === 'unavailable') setState('idle', '단어나 예문의 듣기 버튼을 눌러 보세요.');
    }
    function findVoices() {
      stop();
      clearTimeout(voiceTimer);
      setState('loading', '영어 음성을 불러오고 있습니다.');
      refreshVoices();
      if (state === 'loading') voiceTimer = setTimeout(() => refreshVoices(true), 2500);
    }
    function speak(text) {
      stop();
      const voice = voices[Number($('voice').value)];
      if (!voice) { unavailable('선택할 수 있는 영어 음성이 없습니다. 음성 다시 찾기를 눌러 주세요.'); return; }
      const token = session;
      const count = Number($('repeat').value);
      const rate = Number($('rate').value);
      const gap = Math.max(2500, Math.min(10000, text.split(/\s+/).length * 500 / rate));
      function play(n) {
        if (token !== session) return;
        repeatTimer = undefined;
        const utterance = new SpeechSynthesisUtterance(text);
        activeUtterance = utterance;
        utterance.voice = voice;
        utterance.lang = voice.lang;
        utterance.rate = rate;
        setState('playing', `${n}/${count}회 듣기 준비 중`);
        utterance.onstart = () => {
          if (token !== session) return;
          clearTimeout(startTimer);
          setState('playing', `${n}/${count}회 재생 중`);
        };
        utterance.onend = () => {
          if (token !== session) return;
          clearTimeout(startTimer);
          clearTimeout(endTimer);
          activeUtterance = null;
          if (n < count) {
            setState('waiting', '소리 내어 따라 말해 보세요. 잠시 뒤 한 번 더 읽습니다.');
            repeatTimer = setTimeout(() => play(n + 1), gap);
          } else { setState('idle', '듣기를 마쳤습니다. 이번에는 혼자 읽어 보세요.'); }
        };
        utterance.onerror = (event) => {
          if (token !== session) return;
          stop(event.error === 'canceled' || event.error === 'interrupted' ? '읽기가 중단되었습니다. 듣기 버튼을 눌러 다시 시작해 주세요.' : '음성을 재생하지 못했습니다. 다른 영어 음성을 선택하거나 브라우저를 바꿔 주세요.', 'error');
        };
        startTimer = setTimeout(() => {
          if (token === session) stop('음성 재생이 시작되지 않았습니다. 듣기 버튼을 다시 누르거나 다른 음성·브라우저를 선택해 주세요.', 'error');
        }, 5000);
        endTimer = setTimeout(() => {
          if (token === session) stop('음성 재생의 완료를 확인하지 못했습니다. 다른 음성·브라우저에서 다시 시도해 주세요.', 'error');
        }, Math.max(30000, text.length * 180 / rate));
        try { synth.speak(utterance); }
        catch (_) { stop('음성을 재생하지 못했습니다. 다른 브라우저에서 다시 시도해 주세요.', 'error'); }
      }
      play(1);
    }
    sayButtons.forEach((button) => button.addEventListener('click', () => speak(button.dataset.say)));
    $('stop').addEventListener('click', () => { if (busy()) stop('읽기를 멈췄습니다.'); });
    $('refresh-voices').addEventListener('click', findVoices);
    ['voice', 'rate', 'repeat'].forEach((id) => $(id).addEventListener('change', () => {
      if (busy()) stop('설정을 바꿨습니다. 듣기 버튼을 눌러 다시 시작해 주세요.');
    }));
    if (typeof synth.addEventListener === 'function') synth.addEventListener('voiceschanged', () => refreshVoices(true));
    else synth.onvoiceschanged = () => refreshVoices(true);
    findVoices();
    document.addEventListener('visibilitychange', () => { if (document.hidden && busy()) stop('화면을 떠나 읽기를 멈췄습니다.'); });
    window.addEventListener('pagehide', () => { stop(); clearTimeout(voiceTimer); });
  }
  try { initSpeech(); }
  catch (_) {
    $('voice').replaceChildren(new Option('예문 읽기 사용 불가', ''));
    status.textContent = '이 브라우저는 예문 읽기를 지원하지 않거나 음성을 준비하지 못했습니다. Bible Gateway의 NIV 듣기 링크를 이용해 주세요.';
    [$('voice'), $('rate'), $('repeat'), $('stop'), $('refresh-voices'), ...sayButtons].forEach((el) => { el.disabled = true; });
  }
})();

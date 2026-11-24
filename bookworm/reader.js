(async () => {
  const book = document.documentElement.dataset.book || 'oz';
  const library = window.BookwormProgress;
  const progress = library?.forBook?.(book) || (book === 'oz' ? library : null);
  const visit = new Map();
  let earlyPlayer;
  let earlySeek;
  let earlySelection;
  const captureSeek = e => {
    if (e.target.matches?.('.scene audio')) { earlySeek = e.target; earlySelection = null; }
  };
  const capturePlay = e => {
    if (e.target.matches?.('.scene audio')) { earlyPlayer = e.target; earlySelection = null; }
  };
  function selectEarly(hash) {
    if (!/^#scene-\d+$/.test(hash)) return;
    earlySelection = hash;
    earlyPlayer = null;
    earlySeek = null;
  }
  const captureLink = e => {
    if (e.button === 0 && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey)
      selectEarly(e.target.closest?.('a[href^="#scene-"]')?.hash);
  };
  const captureHash = () => selectEarly(location.hash);
  window.addEventListener('hashchange', captureHash);
  document.addEventListener('click', captureLink, true);
  document.addEventListener('play', capturePlay, true);
  document.addEventListener('seeking', captureSeek, true);
  await progress?.ready;
  window.removeEventListener('hashchange', captureHash);
  document.removeEventListener('click', captureLink, true);
  document.removeEventListener('play', capturePlay, true);
  document.removeEventListener('seeking', captureSeek, true);
  const initialBookmark = progress?.remote();
  let remoteTimeAvailable = true;
  const scenes = Array.from(document.querySelectorAll('.scene'));
  const toc = document.querySelector('.contents details');
  const sceneLinks = Array.from(toc.querySelectorAll('a'));
  const narrow = matchMedia('(max-width: 760px)');
  const chapter = document.documentElement.dataset.chapter || '1';
  const progressPrefix = `bookworm:${book}:ch${chapter}:audio-v1:`;
  // Retain chapter one's existing speed and follow preferences across the book.
  const preferencePrefix = `bookworm:${book}:ch1:audio-v1:`;
  let active;
  let restored = false;
  let interacted = false;
  let lastWrite = 0;
  let lastSavedTime = null;
  let expectedTime = null;
  const restoreTargets = new WeakMap();

  function get(key, prefix = progressPrefix) {
    return progress ? progress.get(prefix + key) : (visit.get(prefix + key) ?? null);
  }
  function set(key, value, prefix = progressPrefix) {
    try {
      if (key === 'rate' || key === 'follow') localStorage.setItem(prefix + key, value);
      else if (progress) progress.set(prefix + key, value);
      else visit.set(prefix + key, String(value));
    } catch { /* Reading works without storage. */ }
  }
  const bookPrefix = `bookworm:${book}:`;
  const resume = document.querySelector('.resume-chapter');

  function readingTime(scene) {
    if (remoteTimeAvailable && initialBookmark?.chapter === Number(chapter) && initialBookmark.scene === Number(scene.id.slice(6))) return initialBookmark.ms / 1000;
    return Number(get(scene.id + ':time')) || 0;
  }
  function rememberScene(scene, publish = true, seconds = readingTime(scene)) {
    set('last-scene', scene.id);
    set('last-chapter', chapter, bookPrefix);
    if (resume) resume.hidden = true;
    if (publish) progress?.save(chapter, scene.id.slice(6), seconds, true, true);
  }
  function installNarration() {
    const template = document.querySelector('#narration-options');
    if (!template) return () => {};
    const options = template.content.firstElementChild.cloneNode(true);
    const speed = options.querySelector('select');
    const follow = options.querySelector('input');
    const header = document.querySelector('.top');
    let player;
    let toolbar;
    let words = [];
    let highlighted;
    let frame = 0;

    function reflectRate(rate) {
      // Native audio controls may offer rates outside the presets.
      if (!Array.from(speed.options).some(option => Number(option.value) === rate)) {
        speed.add(new Option(rate + '배', String(rate)));
      }
      speed.value = String(rate);
    }
    function restorePreferences() {
      let savedFollow;
      let savedRate;
      try {
        savedFollow = localStorage.getItem(preferencePrefix + 'follow');
        savedRate = localStorage.getItem(preferencePrefix + 'rate');
      } catch {
        if (player) return;
      }
      follow.checked = savedFollow == null ? !matchMedia('(prefers-reduced-motion: reduce)').matches : savedFollow === 'on';
      const storedRate = Number(savedRate);
      const rate = storedRate >= .25 && storedRate <= 4 ? storedRate : 1;
      reflectRate(rate);
      if (player) {
        if (player.defaultPlaybackRate !== rate) player.defaultPlaybackRate = rate;
        if (player.playbackRate !== rate) player.playbackRate = rate;
      }
    }
    restorePreferences();

    function setHeaderHeight() {
      document.documentElement.style.setProperty('--bookworm-header-height', header.offsetHeight + 'px');
    }
    setHeaderHeight();
    if ('ResizeObserver' in window) new ResizeObserver(setHeaderHeight).observe(header);
    else window.addEventListener('resize', setHeaderHeight);

    function bringIntoView(word) {
      const viewportBottom = document.documentElement.clientHeight;
      const sticky = getComputedStyle(toolbar).position === 'sticky';
      const top = Math.max(0, header.getBoundingClientRect().bottom) + (sticky ? toolbar.offsetHeight : 0) + 8;
      const room = viewportBottom - top;
      if (room < 40) return;
      const box = word.getBoundingClientRect();
      if (box.top < top || box.bottom > viewportBottom - 12) {
        window.scrollBy(0, box.top - top - room * .25);
      }
    }
    function mark(word) {
      if (word === highlighted) return;
      if (highlighted) highlighted.classList.remove('spoken-word');
      highlighted = word;
      if (!word) return;
      word.classList.add('spoken-word');
      if (follow.checked && !player.paused && !document.hidden) bringIntoView(word);
    }
    function paint() {
      if (!player || player.ended || player.error || player.seeking || !player.readyState) {
        mark(null);
        return;
      }
      const time = player.currentTime * 1000;
      let lo = 0;
      let hi = words.length;
      while (lo < hi) {
        const mid = (lo + hi) >>> 1;
        if (words[mid].start <= time) lo = mid + 1;
        else hi = mid;
      }
      const cue = words[lo - 1];
      mark(cue && time < cue.end ? cue.element : null);
    }
    function stopFrame() {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
    }
    function tick() {
      frame = 0;
      paint();
      if (!document.hidden && !player.paused && !player.ended && !player.error && !player.seeking) {
        frame = requestAnimationFrame(tick);
      }
    }
    function refresh() {
      stopFrame();
      if (player) tick();
    }
    speed.addEventListener('change', () => {
      const rate = Number(speed.value);
      player.defaultPlaybackRate = rate;
      player.playbackRate = rate;
      set('rate', speed.value, preferencePrefix);
    });
    follow.addEventListener('change', () => {
      set('follow', follow.checked ? 'on' : 'off', preferencePrefix);
      if (follow.checked && highlighted && !player.paused) bringIntoView(highlighted);
    });
    for (const scene of scenes) {
      const audio = scene.querySelector('audio');
      audio.addEventListener('ratechange', () => {
        if (audio !== player || Number(speed.value) === audio.playbackRate) return;
        reflectRate(audio.playbackRate);
        audio.defaultPlaybackRate = audio.playbackRate;
        set('rate', speed.value, preferencePrefix);
      });
      for (const event of ['playing', 'pause', 'seeking', 'seeked', 'ended', 'emptied', 'error']) {
        audio.addEventListener(event, () => { if (audio === player) refresh(); });
      }
      audio.addEventListener('timeupdate', () => { if (audio === player && !frame) paint(); });
    }
    window.addEventListener('storage', event => {
      if (event.key === null || event.key === preferencePrefix + 'rate' || event.key === preferencePrefix + 'follow') restorePreferences();
    });
    window.addEventListener('pagehide', stopFrame);
    window.addEventListener('pageshow', () => {
      // Browsers may restore form controls after navigating back to a chapter.
      setTimeout(restorePreferences, 0);
      refresh();
    });
    document.addEventListener('visibilitychange', refresh);
    return scene => {
      stopFrame();
      mark(null);
      if (toolbar) toolbar.classList.remove('with-options');
      toolbar = scene.querySelector('.listen');
      toolbar.append(options);
      toolbar.classList.add('with-options');
      player = toolbar.querySelector('audio');
      player.defaultPlaybackRate = Number(speed.value);
      player.playbackRate = Number(speed.value);
      words = Array.from(scene.querySelectorAll('.passage [data-ms]'), element => {
        const [start, end] = element.dataset.ms.split(' ').map(Number);
        return {start, end, element};
      });
    };
  }

  const activateNarration = installNarration();

  function sceneById(id) {
    return scenes.find(scene => scene.id === id);
  }
  function claimPosition(scene) {
    interacted = true;
    lastSavedTime = null;
    expectedTime = get(scene.id + ':time');
    const audio = scene.querySelector('audio');
    rememberScene(scene, true, restored ? audio.currentTime : readingTime(scene));
    if (restored) {
      set(scene.id + ':time', String(audio.currentTime));
      expectedTime = get(scene.id + ':time');
      if (initialBookmark?.chapter === Number(chapter) && initialBookmark.scene === Number(scene.id.slice(6))) remoteTimeAvailable = false;
    }
  }
  function saveTime(immediate = false) {
    if (!interacted || !restored) return;
    const audio = active.querySelector('audio');
    if (!Number.isFinite(audio.duration)) return;
    const time = audio.ended || audio.duration - audio.currentTime < 2 ? 0 : audio.currentTime;
    const key = active.id + ':time';
    // A late pause or pagehide must not replace a newer seek in another tab.
    if (lastSavedTime === time || get(key) !== expectedTime) return;
    expectedTime = String(time);
    set(key, expectedTime);
    lastSavedTime = time;
    lastWrite = Date.now();
    progress?.save(chapter, active.id.slice(6), time, false, immediate === true);
  }
  function restoreTime() {
    if (restored) return;
    const audio = active.querySelector('audio');
    if (!Number.isFinite(audio.duration) || audio.duration <= 0) return;
    const time = readingTime(active);
    const target = time > 0 && time < audio.duration - 2 ? time : 0;
    if (Math.abs(audio.currentTime - target) >= .0005) {
      restoreTargets.set(audio, target);
      try { audio.currentTime = target; } catch { restoreTargets.delete(audio); return; }
    }
    restored = true;
  }

  function show(scene, selected) {
    if (scene !== active) {
      if (active) {
        saveTime();
        active.querySelector('audio').pause();
      }
      active = scene;
      activateNarration(scene);
      restored = false;
      interacted = false;
      lastWrite = 0;
      lastSavedTime = null;
      for (const item of scenes) item.hidden = item !== scene;
      for (const link of sceneLinks) {
        if (link.hash === '#' + scene.id) link.setAttribute('aria-current', 'location');
        else link.removeAttribute('aria-current');
      }
      const audio = scene.querySelector('audio');
      if (audio.readyState === 0) audio.preload = 'metadata';
      restoreTime();
    }
    if (selected) {
      if (narrow.matches) toc.open = false;
      const title = scene.querySelector('h2');
      title.focus({preventScroll: true});
      scene.scrollIntoView({block: 'start'});
    }
  }

  for (const scene of scenes) {
    const audio = scene.querySelector('audio');
    audio.addEventListener('loadedmetadata', () => { if (scene === active) restoreTime(); });
    audio.addEventListener('play', () => {
      if (scene !== active) { audio.pause(); return; }
      restoreTime();
      claimPosition(scene);
    });
    audio.addEventListener('seeked', () => {
      const target = restoreTargets.get(audio);
      restoreTargets.delete(audio);
      if (target !== undefined && Math.abs(audio.currentTime - target) < .012) return;
      if (scene !== active || !restored) return;
      // A seek made by the reader can take ownership of a previously paused position.
      if (interacted || Math.abs(audio.currentTime - readingTime(scene)) >= .0005) {
        claimPosition(scene);
        saveTime();
      }
    });
    audio.addEventListener('timeupdate', () => {
      if (scene !== active || audio.paused) return;
      const target = restoreTargets.get(audio);
      if (target !== undefined && Math.abs(audio.currentTime - target) >= .012) restoreTargets.delete(audio);
      if (Date.now() - lastWrite > 2000) saveTime();
    });
    for (const event of ['pause', 'ended']) {
      audio.addEventListener(event, () => { if (scene === active) { saveTime(true); progress?.flush(); } });
    }
  }
  if (narrow.matches) toc.open = false;
  const fromHash = () => sceneById(location.hash.slice(1));
  const saved = initialBookmark;
  const bookmarkScene = saved?.chapter === Number(chapter) && sceneById('scene-' + saved.scene);
  const earlyAudio = earlyPlayer || earlySeek;
  const initialScene = earlyAudio?.closest('.scene') || fromHash() || bookmarkScene || sceneById(get('last-scene')) || scenes[0];
  for (const scene of scenes) {
    if (scene !== initialScene) scene.querySelector('audio').pause();
  }
  if (earlyAudio && (bookmarkScene !== initialScene || earlySeek === earlyAudio)) {
    remoteTimeAvailable = false;
    set(initialScene.id + ':time', String(earlyAudio.currentTime));
  }
  show(initialScene, false);
  if (earlyAudio) claimPosition(initialScene);
  // Chapter-choice links signal intent even when opened in a new tab.
  const entry = new URL(location.href);
  const chosen = entry.searchParams.get('read') === '1' || earlySelection === '#' + initialScene.id;
  if (chosen) entry.searchParams.delete('read');
  if (book === 'oz' && !get('last-chapter', bookPrefix) && get('last-scene', preferencePrefix)) {
    set('last-chapter', '1', bookPrefix);
  }
  const explicit = !!earlyAudio || chosen || (!history.state?.bookwormAccountReset &&
    (history.state?.bookwormScene === initialScene.id || !get('last-chapter', bookPrefix)));
  if (explicit && (chosen || !saved || bookmarkScene?.id === initialScene.id)) rememberScene(initialScene, chosen && (!saved || bookmarkScene?.id !== initialScene.id));
  if (!entry.hash || earlyAudio) entry.hash = initialScene.id;
  if (chosen || !location.hash || explicit) {
    const state = explicit ? {...history.state, bookwormScene: initialScene.id} : history.state;
    history.replaceState(state, '', entry);
  }
  document.querySelector('.reading').addEventListener('click', event => {
    const link = event.target.closest('a[href^="#scene-"]');
    if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const scene = sceneById(link.hash.slice(1));
    if (!scene) return;
    event.preventDefault();
    if (location.hash !== link.hash) {
      if (!fromHash()) history.replaceState(null, '', '#' + active.id);
      history.pushState({bookwormScene: scene.id}, '', link.hash);
    } else {
      history.replaceState({...history.state, bookwormScene: scene.id}, '', link.hash);
    }
    show(scene, true);
    rememberScene(scene);
  });
  window.addEventListener('hashchange', () => {
    const scene = fromHash();
    if (!scene) return;
    show(scene, true);
    if (history.state?.bookwormScene === scene.id) rememberScene(scene);
  });
  function finishVisit() { saveTime(true); progress?.flush(); }
  window.addEventListener('pagehide', finishVisit);
  document.addEventListener('visibilitychange', () => { if (document.hidden) finishVisit(); });
})();

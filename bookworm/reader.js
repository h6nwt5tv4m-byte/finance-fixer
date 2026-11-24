(() => {
  const scenes = Array.from(document.querySelectorAll('.scene'));
  const toc = document.querySelector('.contents details');
  const sceneLinks = Array.from(toc.querySelectorAll('a'));
  const narrow = matchMedia('(max-width: 760px)');
  const prefix = 'bookworm:oz:ch1:audio-v1:';
  let active;
  let restored = false;
  let interacted = false;
  let lastWrite = 0;

  function get(key) {
    try { return localStorage.getItem(prefix + key); } catch { return null; }
  }
  function set(key, value) {
    try { localStorage.setItem(prefix + key, value); } catch { /* Reading works without storage. */ }
  }
  function installNarration() {
    const template = document.querySelector('#narration-options');
    if (!template) return () => {};
    const options = template.content.firstElementChild.cloneNode(true);
    const speed = options.querySelector('select');
    const follow = options.querySelector('input');
    const header = document.querySelector('.top');
    const savedFollow = get('follow');
    follow.checked = savedFollow === null ? !matchMedia('(prefers-reduced-motion: reduce)').matches : savedFollow === 'on';
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
    const storedRate = Number(get('rate'));
    reflectRate(storedRate >= .25 && storedRate <= 4 ? storedRate : 1);

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
      set('rate', speed.value);
    });
    follow.addEventListener('change', () => {
      set('follow', follow.checked ? 'on' : 'off');
      if (follow.checked && highlighted && !player.paused) bringIntoView(highlighted);
    });
    for (const scene of scenes) {
      const audio = scene.querySelector('audio');
      audio.addEventListener('ratechange', () => {
        if (audio !== player || Number(speed.value) === audio.playbackRate) return;
        reflectRate(audio.playbackRate);
        audio.defaultPlaybackRate = audio.playbackRate;
        set('rate', speed.value);
      });
      for (const event of ['playing', 'pause', 'seeking', 'seeked', 'ended', 'emptied', 'error']) {
        audio.addEventListener(event, () => { if (audio === player) refresh(); });
      }
      audio.addEventListener('timeupdate', () => { if (audio === player && !frame) paint(); });
    }
    window.addEventListener('pagehide', stopFrame);
    window.addEventListener('pageshow', refresh);
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
  function saveTime() {
    if (!interacted || !restored) return;
    const audio = active.querySelector('audio');
    if (!Number.isFinite(audio.duration)) return;
    const time = audio.ended || audio.duration - audio.currentTime < 2 ? 0 : audio.currentTime;
    set(active.id + ':time', String(time));
    lastWrite = Date.now();
  }
  function restoreTime() {
    if (restored) return;
    const audio = active.querySelector('audio');
    if (!Number.isFinite(audio.duration) || audio.duration <= 0) return;
    const time = Number(get(active.id + ':time'));
    const target = time > 0 && time < audio.duration - 2 ? time : 0;
    if (Math.abs(audio.currentTime - target) > .25) {
      try { audio.currentTime = target; } catch { return; }
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
      set('last-scene', scene.id);
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
      interacted = true;
      set('last-scene', scene.id);
    });
    audio.addEventListener('seeked', () => {
      if (scene !== active || !restored) return;
      // A metadata-only resume can seek before the user starts the player.
      if (interacted || Math.abs(audio.currentTime - Number(get(scene.id + ':time'))) > .3) {
        interacted = true;
        set('last-scene', scene.id);
        saveTime();
      }
    });
    audio.addEventListener('timeupdate', () => {
      if (scene === active && !audio.paused && Date.now() - lastWrite > 2000) saveTime();
    });
    for (const event of ['pause', 'ended']) {
      audio.addEventListener(event, () => { if (scene === active) saveTime(); });
    }
  }
  if (narrow.matches) toc.open = false;
  const fromHash = () => sceneById(location.hash.slice(1));
  const initialScene = fromHash() || sceneById(get('last-scene')) || scenes[0];
  show(initialScene, false);
  if (!location.hash) history.replaceState(null, '', '#' + initialScene.id);
  document.querySelector('.reading').addEventListener('click', event => {
    const link = event.target.closest('a[href^="#scene-"]');
    if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const scene = sceneById(link.hash.slice(1));
    if (!scene) return;
    event.preventDefault();
    if (location.hash !== link.hash) {
      if (!fromHash()) history.replaceState(null, '', '#' + active.id);
      history.pushState(null, '', link.hash);
    }
    show(scene, true);
  });
  window.addEventListener('hashchange', () => {
    const scene = fromHash();
    if (scene) show(scene, true);
  });
  window.addEventListener('pagehide', saveTime);
  document.addEventListener('visibilitychange', () => { if (document.hidden) saveTime(); });
})();

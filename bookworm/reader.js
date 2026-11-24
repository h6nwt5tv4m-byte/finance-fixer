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

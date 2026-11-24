(async () => {
  const progress = window.BookwormProgress;
  if (!progress) return;
  await progress.ready;
  const links = document.querySelectorAll('[data-resume-label]');
  function update() {
    const remote = progress.remote();
    const device = Number(progress.get('bookworm:oz:last-chapter') ||
      (progress.get('bookworm:oz:ch1:audio-v1:last-scene') ? 1 : 0));
    for (const link of links) {
      const counts = (link.dataset.ozScenes || '').split(' ').map(Number);
      const fromAccount = !!counts[remote?.chapter - 1];
      const chapter = fromAccount ? remote.chapter : device;
      const saved = progress.get(`bookworm:oz:ch${chapter}:audio-v1:last-scene`);
      let scene = fromAccount ? remote.scene : Number(saved?.match(/^scene-(\d+)$/)?.[1]);
      if (!(scene >= 1 && scene <= counts[chapter-1])) scene = 1;
      link.hidden = !counts[chapter-1] || String(chapter) === document.documentElement.dataset.chapter;
      if (!link.hidden) {
        link.href = `/bookworm/${chapter}/#scene-${scene}`;
        link.textContent = `오즈의 마법사 ${chapter}장 · 장면 ${scene} 이어 읽기 →`;
      }
    }
  }
  update();
  window.addEventListener('storage', update);
  window.addEventListener('pageshow', update);
  window.addEventListener('bookworm-bookmark', update);
})();

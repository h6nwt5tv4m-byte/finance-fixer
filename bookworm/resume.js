(async () => {
  const progress = window.BookwormProgress;
  if (!progress) return;
  await progress.ready;
  const links = document.querySelectorAll('[data-resume-label]');
  let catalog;
  try {
    const response = await fetch('/bookworm/catalog.json', {cache: 'no-cache'});
    if (!response.ok) return;
    catalog = (await response.json()).find(book => book.slug === 'oz');
  } catch { return; }
  function update() {
    const remote = progress.remote();
    const chapter = remote?.chapter || Number(progress.get('bookworm:oz:last-chapter') ||
      (progress.get('bookworm:oz:ch1:audio-v1:last-scene') ? 1 : 0));
    const entry = catalog?.chapters[chapter-1];
    let scene = remote?.scene || Number((progress.get(`bookworm:oz:ch${chapter}:audio-v1:last-scene`) || '').match(/^scene-(\d+)$/)?.[1]);
    if (!entry || !(scene >= 1 && scene <= entry.scenes)) scene = 1;
    for (const link of links) {
      link.hidden = !entry || String(chapter) === document.documentElement.dataset.chapter;
      if (entry) {
        link.href = entry.path + '#scene-' + scene;
        link.textContent = `오즈의 마법사 ${chapter}장 · 장면 ${scene} 이어 읽기 →`;
      }
    }
  }
  update();
  window.addEventListener('storage', update);
  window.addEventListener('pageshow', update);
  window.addEventListener('bookworm-bookmark', update);
})();

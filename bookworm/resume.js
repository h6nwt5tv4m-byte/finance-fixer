(() => {
  const library = window.BookwormProgress;
  if (!library) return;
  const links = Array.from(document.querySelectorAll('[data-resume-label]'));
  const clients = links.map(link => library.forBook?.(link.dataset.book || 'oz') || library);
  const ready = Promise.all(clients.map(client => client.ready));
  for (const link of links) {
    const book = link.dataset.book || 'oz';
    const progress = library.forBook ? library.forBook(book) : (book === 'oz' ? library : null);
    if (!progress) continue;
    const counts = (link.dataset.scenes || link.dataset.ozScenes || '').split(' ').map(Number);
    const prefix = 'bookworm:' + book + ':';
    const path = book === 'oz' ? '/bookworm/' : '/bookworm/' + book + '/';
    function update() {
      const remote = progress.remote();
      const device = Number(progress.get(prefix + 'last-chapter') ||
        (progress.get(prefix + 'ch1:audio-v1:last-scene') ? 1 : 0));
      const fromAccount = Boolean(counts[remote?.chapter - 1]);
      const chapter = fromAccount ? remote.chapter : device;
      const saved = progress.get(prefix + 'ch' + chapter + ':audio-v1:last-scene');
      let scene = fromAccount ? remote.scene : Number(saved?.match(/^scene-(\d+)$/)?.[1]);
      if (!(scene >= 1 && scene <= counts[chapter - 1])) scene = 1;
      const current = document.documentElement.dataset;
      link.hidden = !counts[chapter - 1] || (book === (current.book || 'oz') && String(chapter) === current.chapter);
      if (!link.hidden) {
        link.href = path + chapter + '/#scene-' + scene;
        link.textContent = (link.dataset.title || '오즈의 마법사') + ' ' + chapter + (link.dataset.unit || '장') + ' · 장면 ' + scene + ' 이어 읽기 →';
      }
    }
    ready.then(update);
    window.addEventListener('storage', () => ready.then(update));
    window.addEventListener('pageshow', () => ready.then(update));
    window.addEventListener('bookworm-bookmark', () => ready.then(update));
  }
})();

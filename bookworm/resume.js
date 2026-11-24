(() => {
  const entries = Array.from(document.querySelectorAll('[data-bookworm-entry]'), link => ({
    link, href: link.getAttribute('href'), hidden: link.hidden,
    label: link.hasAttribute('data-resume-label') ? link.textContent : null
  }));

  function readBookmark() {
    try {
      const chapter = localStorage.getItem('bookworm:oz:last-chapter');
      if (!/^[1-3]$/.test(chapter)) return null;
      const scene = localStorage.getItem(`bookworm:oz:ch${chapter}:audio-v1:last-scene`);
      const number = /^scene-([1-6])$/.exec(scene)?.[1] || '1';
      const path = chapter === '1' ? '/bookworm/' : `/bookworm/${chapter}/`;
      return { chapter, number, href: path + '#scene-' + number };
    } catch { return null; }
  }

  function update() {
    const saved = readBookmark();
    for (const entry of entries) {
      const resume = saved && saved.chapter !== document.documentElement.dataset.chapter;
      entry.link.hidden = entry.hidden && !resume;
      const href = resume ? saved.href : entry.href;
      if (href) entry.link.setAttribute('href', href);
      else entry.link.removeAttribute('href');
      if (entry.label !== null) {
        entry.link.textContent = resume ? `${saved.chapter}장 · 장면 ${saved.number} 이어 읽기 →` : entry.label;
      }
    }
  }
  update();
  window.addEventListener('pageshow', update);
  window.addEventListener('storage', update);
})();

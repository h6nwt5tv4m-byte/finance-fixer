// Original chapter-one URLs used the shelf path before the library opened.
function openLegacyChapter() {
  if (/^#scene-[1-6]$/.test(location.hash) || new URLSearchParams(location.search).get('read') === '1') {
    location.replace('/bookworm/1/' + location.search + location.hash);
  }
}
openLegacyChapter();
window.addEventListener('hashchange', openLegacyChapter);

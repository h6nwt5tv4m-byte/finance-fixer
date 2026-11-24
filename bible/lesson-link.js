// Old lesson bookmarks can point directly to a quiz, notes, or numbered verse.
const target = new URL('./', location.href);
target.search = '?book=MRK&chapter=1';
const anchor = location.hash.slice(1);
target.hash = ['english','context','review','reading'].includes(anchor) ? anchor
  : /^verse-[1-8]$/.test(anchor) ? 'v' + anchor.slice(6) : 'study';
location.replace(target);

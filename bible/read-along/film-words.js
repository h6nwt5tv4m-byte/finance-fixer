import {verseTimings} from './mark-1-film-cues.js?v=1';

const layer = 'lumo-word';
const skip = '.yv-n,.yv-h,.yv-vlbl,.yv-v[v],.yv-r,.r';
let generation = 0;
let cues = [];
let active, activeRow;
let lastTime;
let playing = false;

function clearPaint() {
  CSS.highlights?.delete(layer);
  activeRow?.classList.remove('current');
  activeRow?.removeAttribute('aria-current');
  activeRow = null;
  active = null;
}

export function clearFilmWords() {
  generation++;
  clearPaint();
  cues = [];
  lastTime = undefined;
  playing = false;
  document.getElementById('film-words-status').textContent = '';
}

function wordRanges(cell) {
  const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
  const result = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.parentElement.closest(skip)) continue;
    for (const match of node.data.matchAll(/[\p{L}\p{M}]+(?:['’\-][\p{L}\p{M}]+)*/gu)) {
      const range = new Range();
      range.setStart(node, match.index);
      range.setEnd(node, match.index + match[0].length);
      result.push(range);
    }
  }
  return result;
}

async function bindVerse(passage, verse, marker) {
  const row = passage.querySelector('#v' + verse);
  const cell = row?.querySelector('.en-text');
  if (!cell) return null;
  const ranges = wordRanges(cell);
  if (ranges.length * 2 !== marker.times.length) return null;
  const words = ranges.map(range => range.toString().toLowerCase().replace(/’/g, "'")).join(' ');
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(words));
  const hash = Array.from(new Uint8Array(bytes), n => n.toString(16).padStart(2,'0')).join('');
  if (hash !== marker.hash) return null;
  return ranges.map((range, i) => ({
    range, row, start:marker.times[i*2]/100, end:marker.times[i*2+1]/100
  }));
}

export async function attachFilmWords(passage) {
  const id = ++generation;
  clearPaint();
  cues = [];
  const status = document.getElementById('film-words-status');
  if (!CSS.highlights || !window.Highlight || !window.crypto?.subtle) {
    status.textContent = '이 브라우저에서는 영상과 한영 본문을 함께 볼 수 있습니다. 단어 강조를 사용하려면 브라우저를 업데이트해 주세요.';
    return;
  }
  const verses = await Promise.all(verseTimings.map((marker, i) => bindVerse(passage, i+1, marker))).catch(() => null);
  if (id !== generation) return;
  if (!verses || verses.some(verse => !verse)) {
    status.textContent = '현재 본문과 영상의 단어가 일치하는지 확인할 수 없어 단어 강조를 껐습니다.';
    return;
  }
  cues = verses.flat();
  status.textContent = '';
  paint();
}

function reveal(range) {
  const panel = document.getElementById('lumo');
  if (getComputedStyle(panel).position !== 'sticky') return;
  const rect = range.getBoundingClientRect();
  const panelRect = panel.getBoundingClientRect();
  const overlaps = rect.left < panelRect.right && rect.right > panelRect.left;
  const top = Math.max(overlaps ? panelRect.bottom : 0, document.querySelector('.top').getBoundingClientRect().bottom) + 8;
  const bottom = window.visualViewport ? window.visualViewport.offsetTop + window.visualViewport.height : innerHeight;
  if (bottom - top < 2 * rect.height) return;
  if (rect.top < top || rect.bottom > bottom - 8) {
    window.scrollBy({top:rect.top - top - (bottom - top - rect.height) * .35, behavior:'instant'});
  }
}

function paint() {
  const next = cues.find(cue => cue.start <= lastTime && lastTime < cue.end);
  if (next === active) return;
  if (!next) { clearPaint(); return; }
  if (next.row !== activeRow) {
    activeRow?.classList.remove('current');
    activeRow?.removeAttribute('aria-current');
    activeRow = next.row;
    activeRow.classList.add('current');
    activeRow.setAttribute('aria-current','location');
  }
  active = next;
  CSS.highlights.set(layer, new Highlight(next.range));
  if (playing) reveal(next.range);
}

export function followFilm(time, kind) {
  if (!['play','clock','pause','buffer','ended','idle','error'].includes(kind)) return;
  playing = kind === 'clock' || kind === 'play';
  if (!Number.isFinite(time) || ['ended','error','idle'].includes(kind)) {
    lastTime = undefined;
    clearPaint();
    return;
  }
  lastTime = time;
  paint();
}

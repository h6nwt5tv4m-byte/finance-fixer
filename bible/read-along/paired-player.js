'use strict';
const verses = [
  [["This",0.692,0.915],["is",0.915,1.055],["the",1.055,1.195],["beginning",1.195,1.595],["of",1.595,1.695],["the",1.695,1.795],["gospel",1.795,2.475],["of",2.475,2.675],["Jesus",2.675,3.135],["Christ,",3.135,3.714],["the",3.954,4.075],["Son",4.075,4.315],["of",4.315,4.435],["God.",4.435,4.945]],
  [["As",5.888,6.175],["it",6.175,6.315],["is",6.315,6.435],["written",6.435,6.955],["in",6.955,7.235],["Isaiah",7.235,7.755],["the",7.755,7.915],["prophet:",7.915,8.62],["“Behold,",8.852,9.453],["I",9.6,9.815],["will",9.815,10.095],["send",10.095,10.435],["My",10.435,10.655],["messenger",10.655,11.255],["ahead",11.255,11.535],["of",11.535,11.655],["You,",11.655,11.954],["who",12.276,12.395],["will",12.395,12.635],["prepare",12.635,13.215],["Your",13.215,13.475],["way.”",13.475,13.919]],
  [["“A",14.6,14.745],["voice",14.745,15.125],["of",15.125,15.385],["one",15.385,15.605],["calling",15.605,16.145],["in",16.145,16.245],["the",16.245,16.365],["wilderness,",16.365,17.285],["‘Prepare",17.285,17.845],["the",17.845,18.005],["way",18.005,18.305],["for",18.305,18.505],["the",18.505,18.645],["Lord,",18.645,19.114],["make",19.402,19.765],["straight",19.765,20.185],["paths",20.185,20.685],["for",20.685,20.905],["Him.’”",20.905,21.323]],
  [["John",22.535,22.785],["the",22.785,22.925],["Baptist",22.925,23.505],["appeared",23.505,24.045],["in",24.045,24.165],["the",24.165,24.265],["wilderness,",24.265,24.964],["preaching",25.11,25.545],["a",25.545,25.645],["baptism",25.645,26.445],["of",26.445,26.585],["repentance",26.585,27.245],["for",27.245,27.425],["the",27.425,27.585],["forgiveness",27.585,28.225],["of",28.225,28.405],["sins.",28.405,29.001]],
  [["People",29.909,30.225],["went",30.225,30.525],["out",30.525,30.705],["to",30.705,30.885],["him",30.885,31.185],["from",31.185,31.525],["all",31.525,31.705],["of",31.705,31.805],["Jerusalem",31.805,32.574],["and",32.705,32.865],["the",32.865,32.985],["countryside",32.985,33.725],["of",33.725,33.845],["Judea.",33.845,34.44],["Confessing",35.17,35.805],["their",35.805,36.085],["sins,",36.085,36.885],["they",36.885,37.045],["were",37.045,37.245],["baptized",37.245,37.885],["by",37.885,38.145],["him",38.145,38.605],["in",38.605,38.725],["the",38.725,38.845],["Jordan",38.845,39.265],["River.",39.265,39.65]],
  [["John",40.767,41.105],["was",41.105,41.345],["clothed",41.345,41.945],["in",41.945,42.085],["camel’s",42.085,42.565],["hair,",42.565,42.914],["with",43.255,43.425],["a",43.425,43.505],["leather",43.505,43.845],["belt",43.845,44.325],["around",44.325,44.665],["his",44.665,44.885],["waist.",44.885,45.43],["His",45.865,46.325],["food",46.325,46.785],["was",46.785,47.165],["locusts",47.165,47.845],["and",47.845,48.005],["wild",48.005,48.405],["honey.",48.405,48.8]],
  [["And",49.52,49.685],["he",49.685,49.805],["proclaimed:",49.805,50.44],["“After",50.884,51.265],["me",51.265,51.505],["will",51.505,51.785],["come",51.785,52.225],["One",52.225,52.565],["more",52.565,52.845],["powerful",52.845,53.425],["than",53.425,53.785],["I,",53.785,53.94],["the",54.376,54.505],["straps",54.505,54.945],["of",54.945,55.085],["whose",55.085,55.345],["sandals",55.345,56.205],["I",56.205,56.325],["am",56.325,56.465],["not",56.465,56.745],["worthy",56.745,57.185],["to",57.185,57.425],["stoop",57.425,57.785],["down",57.785,58.305],["and",58.305,58.505],["untie.",58.505,59.098]],
  [["I",59.853,60.095],["baptize",60.095,60.695],["you",60.695,61.035],["with",61.035,61.295],["water,",61.295,61.741],["but",62.327,62.515],["He",62.515,62.675],["will",62.675,62.935],["baptize",62.935,63.535],["you",63.535,63.915],["with",63.915,64.155],["the",64.155,64.335],["Holy",64.335,64.715],["Spirit.”",64.715,65.248]]
];
// Mark 1 is available during the first play gesture, even when other book requests are slow.
const remainder = [
  "In those days Jesus came from Nazareth in Galilee and was baptized by John in the Jordan.",
  "As soon as Jesus came up out of the water, He saw the heavens breaking open and the Spirit descending on Him like a dove.",
  "And a voice came from heaven: “You are My beloved Son; in You I am well pleased.”",
  "At once the Spirit drove Jesus into the wilderness,",
  "and He was there for forty days, being tempted by Satan. He was with the wild animals, and the angels ministered to Him.",
  "After the arrest of John, Jesus went into Galilee and proclaimed the gospel of God.",
  "“The time is fulfilled,” He said, “and the kingdom of God is near. Repent and believe in the gospel!”",
  "As Jesus was walking beside the Sea of Galilee, He saw Simon and his brother Andrew. They were casting a net into the sea, for they were fishermen.",
  "“Come, follow Me,” Jesus said, “and I will make you fishers of men.”",
  "And at once they left their nets and followed Him.",
  "Going on a little farther, He saw James son of Zebedee and his brother John. They were in a boat, mending their nets.",
  "Immediately Jesus called them, and they left their father Zebedee in the boat with the hired men and followed Him.",
  "Then Jesus and His companions went to Capernaum, and right away Jesus entered the synagogue on the Sabbath and began to teach.",
  "The people were astonished at His teaching, because He taught as one who had authority, and not as the scribes.",
  "Suddenly a man with an unclean spirit cried out in the synagogue:",
  "“What do You want with us, Jesus of Nazareth? Have You come to destroy us? I know who You are—the Holy One of God!”",
  "But Jesus rebuked the spirit. “Be silent!” He said. “Come out of him!”",
  "At this, the unclean spirit threw the man into convulsions and came out with a loud shriek.",
  "All the people were amazed and began to ask one another, “What is this? A new teaching with authority! He commands even the unclean spirits, and they obey Him!”",
  "And the news about Jesus spread quickly through the whole region of Galilee.",
  "As soon as Jesus and His companions had left the synagogue, they went with James and John to the home of Simon and Andrew.",
  "Simon’s mother-in-law was sick in bed with a fever, and they promptly told Jesus about her.",
  "So He went to her, took her by the hand, and helped her up. The fever left her, and she began to serve them.",
  "That evening, after sunset, people brought to Jesus all the sick and demon-possessed,",
  "and the whole town gathered at the door.",
  "And He healed many who were ill with various diseases and drove out many demons. But He would not allow the demons to speak, because they knew who He was.",
  "Early in the morning, while it was still dark, Jesus got up and went out to a solitary place to pray.",
  "Simon and his companions went to look for Him,",
  "and when they found Him, they said, “Everyone is looking for You!”",
  "But Jesus answered, “Let us go on to the neighboring towns so I can preach there as well, for that is why I have come.”",
  "So He went throughout Galilee, preaching in their synagogues and driving out demons.",
  "Then a leper came to Jesus, begging on his knees: “If You are willing, You can make me clean.”",
  "Moved with compassion, Jesus reached out His hand and touched the man. “I am willing,” He said. “Be clean!”",
  "And immediately the leprosy left him, and the man was cleansed.",
  "Jesus promptly sent him away with a stern warning:",
  "“See that you don’t tell anyone. But go, show yourself to the priest and present the offering Moses prescribed for your cleansing, as a testimony to them.”",
  "But the man went out and openly began to proclaim and spread the news. Consequently, Jesus could no longer enter a town in plain view, but He stayed out in solitary places. Yet people came to Him from every quarter."
];
export function readAlongChapter() {
  return [...verses.map(words => words.map(([word]) => word).join(' ')), ...remainder];
}
const audio = document.querySelector('#audio');
const toggle = document.querySelector('#toggle');
const seek = document.querySelector('#seek');
const clock = document.querySelector('#clock');
const passage = document.querySelector('#passage');
const error = document.querySelector('#error');
const cues = [];
const rows = [];
let activeWord = null;
let activeRow = null;
let frame = 0;
export function detachReadAlong() {
  cancelAnimationFrame(frame);
  audio.pause();
  if (audio.hasAttribute('src')) {
    audio.removeAttribute('src');
    audio.load();
  }
  cues.length = 0;
  rows.length = 0;
  activeWord = null;
  activeRow = null;
  toggle.disabled = true;
  error.hidden = true;
  document.querySelector('#readalong').hidden = true;
}
export function attachReadAlong() {
  for (const [index, words] of verses.entries()) {
    const row = passage.querySelector('#v' + (index + 1));
    const cell = row?.querySelector('.en-text');
    if (!cell || cell.textContent !== words.map(item => item[0]).join(' ')) return;
  }
  for (const [index, words] of verses.entries()) {
    const row = passage.querySelector('#v' + (index + 1));
    const cell = row.querySelector('.en-text');
    cell.replaceChildren();
    rows.push({start: words[0][1], row});
    for (const [i, [word, start, end]] of words.entries()) {
      const span = document.createElement('span');
      span.className = 'word';
      span.textContent = word;
      if (i) cell.append(' ');
      cell.append(span);
      cues.push({start, end, span});
    }
  }
  rows.reverse();
  audio.preload = 'metadata';
  audio.src = './read-along/mark-1.m4a';
  toggle.disabled = false;
  document.querySelector('#readalong').hidden = false;
  update();
}
function timestamp(seconds) {
  const whole = Math.floor(seconds);
  return Math.floor(whole / 60) + ':' + String(whole % 60).padStart(2, '0');
}
function update(event) {
  const time = audio.currentTime;
  const duration = Number.isFinite(audio.duration) ? audio.duration : 65.52;
  seek.disabled = audio.readyState < HTMLMediaElement.HAVE_METADATA || Boolean(audio.error);
  seek.max = duration;
  seek.value = time;
  const display = timestamp(time) + ' / ' + timestamp(duration);
  if (clock.textContent !== display) {
    clock.textContent = display;
  }
  seek.setAttribute('aria-valuetext', display);
  const label = audio.ended ? '↻ 다시 듣기' : audio.paused ? '▶ 재생' : 'Ⅱ 일시정지';
  if (toggle.textContent !== label) toggle.textContent = label;
  const word = !audio.ended && cues.find(cue => time >= cue.start && time < cue.end);
  const row = !audio.ended && rows.find(item => time >= item.start);
  const wordChanged = activeWord !== (word?.span || null);
  if (wordChanged) {
    activeWord?.classList.remove('current');
    activeWord?.removeAttribute('aria-current');
    activeWord = word?.span || null;
    activeWord?.classList.add('current');
    activeWord?.setAttribute('aria-current', 'location');
  }
  if (activeRow !== (row?.row || null)) {
    activeRow?.classList.remove('current');
    activeRow?.removeAttribute('aria-current');
    activeRow = row?.row || null;
    activeRow?.classList.add('current');
    activeRow?.setAttribute('aria-current', 'location');
  }
  if ((wordChanged || event?.type === 'seeked' || event?.type === 'play') && activeWord && (!audio.paused || event?.type === 'seeked') && !audio.seeking) {
    const rect = activeWord.getBoundingClientRect();
    const bar = toggle.parentElement.getBoundingClientRect();
    const header = document.querySelector('.top').getBoundingClientRect();
    const view = window.visualViewport;
    const top = Math.max(header.bottom, bar.bottom, view?.offsetTop || 0);
    const bottom = view ? view.offsetTop + view.height : window.innerHeight;
    const left = view?.offsetLeft || 0;
    const right = left + (view?.width || window.innerWidth);
    if (rect.top < top || rect.bottom > bottom || rect.left < left || rect.right > right) {
      activeWord.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
    }
  }
}
function tick(event) {
  update(event);
  if (!audio.paused && !audio.ended) frame = requestAnimationFrame(tick);
}
function updatePlayback(event) {
  cancelAnimationFrame(frame);
  tick(event);
}
function showError() {
  update();
  if (!audio.hasAttribute('src')) return;
  error.hidden = false;
  error.textContent = '음원을 열 수 없습니다. 인터넷 연결을 확인한 뒤 재생 버튼을 다시 눌러 주세요.';
}
toggle.addEventListener('click', async () => {
  if (!audio.paused && !audio.ended) {
    audio.pause();
    return;
  }
  document.dispatchEvent(new Event('stop-study-audio'));
  error.hidden = true;
  if (audio.error) audio.load();
  if (audio.ended) {
    audio.pause();
    audio.currentTime = 0;
  }
  try { await audio.play(); }
  catch (reason) { if (reason.name !== 'AbortError') showError(); }
});
seek.addEventListener('keydown', event => {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
  event.preventDefault();
  audio.currentTime = Math.min(audio.duration, Math.max(0, audio.currentTime + (event.key === 'ArrowRight' ? 1 : -1)));
  update();
});
seek.addEventListener('input', () => {
  if (audio.readyState < HTMLMediaElement.HAVE_METADATA) return;
  audio.currentTime = Number(seek.value);
  update();
});
for (const name of ['play', 'pause', 'ended']) audio.addEventListener(name, updatePlayback);
for (const name of ['loadedmetadata', 'timeupdate', 'seeked']) audio.addEventListener(name, update);
audio.addEventListener('error', showError);
window.addEventListener('pagehide', () => audio.pause());
document.addEventListener('stop-passage-audio', () => audio.pause());

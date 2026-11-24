// Keep the official player and its SDK in a separate document.
const origin = location.origin;
const owner = document.referrer || new URLSearchParams(location.search).get('site');
function allowedReader(value) {
  try {
    const url = new URL(value);
    if (['https://finance-fixer.net', 'https://www.finance-fixer.net'].includes(url.origin) ||
        (url.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(url.hostname))) return url.origin;
  } catch {}
  return null;
}
const reader = allowedReader(owner);
const video = document.createElement('iframe');
const url = new URL('https://www.youtube.com/embed/BU4dy36OFEA');
url.search = new URLSearchParams({enablejsapi:'1', origin, playsinline:'1', rel:'0', start:'54'});
video.id = 'film';
video.title = 'LUMO · 마가복음 1장 NIV 공식 영상';
video.referrerPolicy = 'strict-origin-when-cross-origin';
video.allow = 'autoplay; encrypted-media; fullscreen; picture-in-picture';
video.allowFullscreen = true;
video.src = url.href;
video.inert = true;
let player, timer, frame;
function report(kind, time) {
  if (reader) parent.postMessage({type:'lumo', kind, time}, reader);
}
function stopClock() {
  clearInterval(timer);
  cancelAnimationFrame(frame);
}
function onStateChange(event) {
  stopClock();
  const state = event.data;
  const source = event.target;
  const kind = {1:'play', 2:'pause', 3:'buffer', 0:'ended'}[state] || 'idle';
  report(kind, source.getCurrentTime?.());
  let last = source.getCurrentTime?.();
  function sample() {
    const time = source.getCurrentTime();
    if (time !== last) report(state === 1 ? 'clock' : 'pause', time);
    last = time;
  }
  if (state === 1) {
    function tick() {
      sample();
      frame = requestAnimationFrame(tick);
    }
    frame = requestAnimationFrame(tick);
  } else if (state === 2) {
    timer = setInterval(sample, 250);
  }
}
function fail() {
  stopClock();
  video.remove();
  document.getElementById('screen').textContent = '영상 플레이어를 불러올 수 없습니다.';
  report('error');
}
window.onYouTubeIframeAPIReady = () => {
  document.getElementById('screen').append(video);
  player = new YT.Player(video, {events:{
    onReady() { video.inert = false; report('ready'); },
    onStateChange,
    onError:fail
  }});
};
window.addEventListener('message', event => {
  if (reader && event.origin === reader && event.source === parent && event.data?.type === 'lumo-pause') player?.pauseVideo?.();
});
if (reader && parent !== window && location.hostname === 'bible-api.finance-fixer.net') {
  const script = document.createElement('script');
  script.src = 'https://www.youtube.com/iframe_api';
  script.onerror = fail;
  document.head.append(script);
}
window.addEventListener('pagehide', stopClock);

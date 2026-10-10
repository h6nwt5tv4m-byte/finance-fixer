(() => {
  // 도구 메뉴: '도구'를 누르면 홈의 도구 섹션으로 이동하고, 마우스를 올리면 목록 패널이 열린다.
  // 키보드로 '도구'에 들어오면 패널을 열어 Tab으로 항목을 고를 수 있게 한다.
  const wrap = document.querySelector('.nav-drop');
  const btn = wrap.querySelector('.drop-btn');
  const set = (open) => { wrap.classList.toggle('open', open); btn.setAttribute('aria-expanded', open); };
  let t;
  let escaped = false;
  // 패널로 비스듬히 옮겨 가는 동안 닫히지 않게 잠깐 기다린다
  wrap.addEventListener('pointerenter', (e) => { if (e.pointerType === 'mouse') { clearTimeout(t); set(true); } });
  wrap.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse') t = setTimeout(() => set(false), 350); });
  btn.addEventListener('focus', () => { if (!escaped && btn.matches(':focus-visible')) set(true); });
  btn.addEventListener('click', () => set(false));
  wrap.addEventListener('focusout', (e) => { if (!wrap.contains(e.relatedTarget)) { set(false); escaped = false; } });
  document.addEventListener('click', (e) => { if (!wrap.contains(e.target)) set(false); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && wrap.classList.contains('open')) { escaped = true; set(false); btn.focus(); }
  });
  wrap.querySelectorAll('.drop a').forEach((a) => a.addEventListener('click', () => set(false)));

  // 고정 헤더 높이만큼 앵커 위치를 내리고, 스크롤 위치에 맞는 탭을 표시한다
  const header = document.querySelector('.top');
  const fit = () => { document.documentElement.style.scrollPaddingTop = (header.offsetHeight + 16) + 'px'; };
  // 홈에서만: 탭의 #앵커가 이 페이지에 있으면 스크롤 위치에 맞춰 표시
  const path = location.pathname;
  const host = location.hostname;
  const mainSite = host === 'finance-fixer.net' || host === 'www.finance-fixer.net' || host === 'localhost' || host === '';
  const onHome = mainSite && (path === '/' || path === '/index.html' || /\/finance-fixer\/index\.html$/.test(path));
  const tabs = [...document.querySelectorAll('.top nav > a')]
    .map((a) => { const u = new URL(a.href, location.href); return { el: a, sec: onHome && u.hash ? document.getElementById(u.hash.slice(1)) : null }; })
    .concat([{ el: btn, sec: document.getElementById('tools') }])
    .filter((x) => x.sec);
  let raf = 0;
  const spy = () => {
    raf = 0;
    const line = header.offsetHeight + window.innerHeight * 0.25;
    const atEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
    let cur = null;
    for (const x of tabs) {
      const top = x.sec.getBoundingClientRect().top;
      if (top <= line && (!cur || top > cur.sec.getBoundingClientRect().top)) cur = x;
    }
    if (atEnd) cur = tabs.reduce((m, x) => (!m || x.sec.offsetTop > m.sec.offsetTop ? x : m), null);
    tabs.forEach((x) => x.el.classList.toggle('active', x === cur));
  };
  const queue = () => { if (!raf) raf = requestAnimationFrame(spy); };
  if (onHome) addEventListener('scroll', queue, { passive: true });
  addEventListener('resize', () => { fit(); if (onHome) queue(); });
  // 하위 페이지: 지금 페이지에 해당하는 탭을 표시
  if (!onHome) document.querySelectorAll('.top nav > a').forEach((a) => {
    const p = new URL(a.href, location.href).pathname;
    if (mainSite && new URL(a.href, location.href).hostname === host && p !== '/' && path.startsWith(p)) a.classList.add('active');
  });
  // 도구 하위 페이지와 도구 서브도메인(aptfee·sangkwon·jobs)에서는 '도구'를 표시
  if (!onHome && (!mainSite || /^\/(oegam|rates|related-party)\//.test(path))) btn.classList.add('active');
  header.classList.add('stuck');
  fit(); if (onHome) spy();
})();

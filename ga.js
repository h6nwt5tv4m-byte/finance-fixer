// 방문 통계(Google Analytics 4). 정본 1벌 — 홈페이지와 공개 도구 사이트가 모두 이 파일을 읽는다(nav.js가 불러온다).
// 검색어 가리기(주소의 q·query·keyword·search), 사이트 검색·양식·주소 변경 추적 끔은 GA 관리 화면(데이터 스트림)에 설정돼 있다.
// 이 스트림은 페이지 쪽 config 값(page_location·page_title 덮어쓰기 등)을 무시하므로 여기서는 켜기만 한다.
(() => {
  try {
    if (window.__ffGa) return;
    const ID = 'G-F05FV4S36C';
    const HOSTS = ['finance-fixer.net', 'www.finance-fixer.net', 'aptfee.finance-fixer.net', 'sangkwon.finance-fixer.net',
      'jobs.finance-fixer.net', 'jiwon.finance-fixer.net', 'gamsain.finance-fixer.net', 'econ.finance-fixer.net', 'bench.finance-fixer.net'];
    if (!HOSTS.includes(location.hostname)) return; // 로그인 사이트·미리보기·localhost에서는 동작하지 않는다
    window.__ffGa = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = window.gtag || function () { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    window.gtag('config', ID);
    const s = document.createElement('script');
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + ID;
    document.head.appendChild(s);
    // 문의 버튼 누름(블로그→홈페이지 집결 측정, 2026-11-26). 이벤트 이름만 보내고 번호·주소·링크는 보내지 않는다.
    const kinds = [[/^tel:/i, 'contact_tel'], [/^mailto:/i, 'contact_mail'], [/^https?:\/\/pf\.kakao\.com\//i, 'contact_kakao'],
      [/^https:\/\/board\.finance-fixer\.net\/consultation(?:[?#]|$)/, 'contact_consult']];
    // 블로그 안내 링크로 들어온 방문(이 탭 안)은 상담 신청 화면에 출처 표시를 넘긴다 → 게시판이 주간 건수만 센다(신청 내용과 연결 안 함).
    try { if (new URLSearchParams(location.search).get('utm_source') === 'naver_blog') sessionStorage.setItem('ff_src', 'naver_blog'); } catch (e) { /* 저장 불가 브라우저 */ }
    document.addEventListener('click', (ev) => {
      try {
        if (location.pathname.startsWith('/go/')) return; // 이동 페이지는 자체 이벤트(go_*)로 센다 — 이중 계산 방지
        const a = ev.target && ev.target.closest ? ev.target.closest('a[href]') : null;
        const href = a ? a.getAttribute('href') || '' : '';
        const hit = kinds.find(([re]) => re.test(href));
        if (!hit) return;
        window.gtag('event', hit[1], { transport_type: 'beacon' });
        if (hit[1] === 'contact_consult' && sessionStorage.getItem('ff_src') === 'naver_blog') {
          const u = new URL(a.href);
          u.searchParams.set('src', 'naver_blog');
          a.href = u.toString();
        }
      } catch (e) { /* 통계 실패는 화면에 영향 없음 */ }
    }, true);
  } catch (e) { /* 통계 실패는 화면에 영향 없음 */ }
})();

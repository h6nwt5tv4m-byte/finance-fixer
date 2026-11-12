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
  } catch (e) { /* 통계 실패는 화면에 영향 없음 */ }
})();

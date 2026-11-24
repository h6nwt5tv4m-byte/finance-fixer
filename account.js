// Authentication stays on the board host. Only the displayed nickname is shared.
(() => {
  if (window.FinanceAccount) return;
  const board = 'https://board.finance-fixer.net';
  const english = document.documentElement.lang === 'en';
  function accountUrl() {
    const current = new URL(location.href);
    const chapter = /^\/bookworm\/\d+\/$/.test(current.pathname);
    const publicAudit = current.pathname === '/public-audit/' && /^\?id=[A-Z]-[A-Z0-9]{1,24}$/.test(current.search);
    if (!publicAudit && (!chapter || current.search !== '?read=1')) current.search = '';
    if (!chapter || !/^#scene-\d{1,2}$/.test(current.hash)) current.hash = '';
    const target = new URL('/account', board);
    target.searchParams.set('return_to', current.href);
    return target.href;
  }

  function mount() {
    const slot = document.querySelector('[data-site-account]') || document.querySelector('header.top nav');
    if (!slot) return null;
    const link = slot.matches('a') ? slot : document.createElement('a');
    link.href = accountUrl();
    const syncUrl = () => { link.href = accountUrl(); };
    for (const event of ['click', 'focus', 'pointerdown', 'contextmenu']) link.addEventListener(event, syncUrl);
    window.addEventListener('hashchange', syncUrl);
    link.textContent = english ? 'Sign in' : '로그인';
    if (slot !== link) slot.append(link);
    link.dataset.siteAccount = '';
    return link;
  }

  const link = mount();
  let check = 0;
  async function refresh() {
    if (!link) return;
    const ticket = ++check;
    try {
      const r = await fetch(board + '/site/session', {credentials: 'include', cache: 'no-store',
        signal: AbortSignal.timeout(3500)});
      if (!r.ok) return;
      const {label} = await r.json();
      if (ticket !== check) return;
      link.textContent = label || (english ? 'Sign in' : '로그인');
      link.title = label ? (english ? 'My account' : '내 계정') : '';
    } catch { /* The link opens the board even if the status service is unavailable. */ }
  }
  window.FinanceAccount = {refresh};
  refresh();
  window.addEventListener('pageshow', event => { if (event.persisted) refresh(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();

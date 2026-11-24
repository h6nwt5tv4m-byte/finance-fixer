// Authentication stays on the board host. Only the displayed nickname is shared.
(() => {
  if (window.FinanceAccount) return;
  const board = 'https://board.finance-fixer.net';
  const english = document.documentElement.lang === 'en';
  const current = new URL(location.href);
  if (current.search !== '?read=1') current.search = '';
  const account = new URL('/account', board);
  account.searchParams.set('return_to', current.href);

  function mount() {
    const slot = document.querySelector('[data-site-account]') || document.querySelector('header.top nav');
    if (!slot) return null;
    const link = slot.matches('a') ? slot : document.createElement('a');
    link.href = account.href;
    link.textContent = english ? 'Sign in' : '로그인';
    if (slot !== link) slot.append(link);
    link.dataset.siteAccount = '';
    return link;
  }

  const link = mount();
  async function refresh() {
    if (!link) return;
    try {
      const r = await fetch(board + '/site/session', {credentials: 'include', cache: 'no-store',
        signal: AbortSignal.timeout(3500)});
      if (!r.ok) return;
      const {label} = await r.json();
      link.textContent = label || (english ? 'Sign in' : '로그인');
      link.title = label ? (english ? 'My account' : '내 계정') : '';
    } catch { /* The link opens the board even if the status service is unavailable. */ }
  }
  window.FinanceAccount = {refresh};
  refresh();
  window.addEventListener('pageshow', event => { if (event.persisted) refresh(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();

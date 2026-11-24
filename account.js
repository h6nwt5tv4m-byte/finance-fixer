// Authentication stays on the board host. Only the displayed nickname is shared.
(() => {
  if (window.FinanceAccount) return;
  const board = 'https://board.finance-fixer.net';
  const english = document.documentElement.lang === 'en';
  function accountUrl() {
    const current = new URL(location.href);
    const chapter = /^\/bookworm\/(?:holmes\/)?\d+\/$/.test(current.pathname);
    const home = ['finance-fixer.net','www.finance-fixer.net'].includes(current.hostname);
    const safe = new URLSearchParams();
    if (home && chapter && current.searchParams.get('read') === '1') safe.set('read','1');
    if (home && current.pathname === '/public-audit/') {
      const year = current.searchParams.get('year'), id = current.searchParams.get('id');
      if (/^\d{4}$/.test(year || '')) safe.set('year',year);
      if (/^[A-Z]-[A-Z0-9]{1,24}$/.test(id || '')) safe.set('id',id);
    }
    current.search = safe.toString();
    const section = current.pathname === '/' && /^#(services|method|people|tools|contact|videos|db)$/.test(current.hash);
    if (!home || !(section || (chapter && /^#scene-\d{1,2}$/.test(current.hash)))) current.hash = '';
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
    if (slot !== link) {
      const contact = slot.querySelector(':scope > a[href$="/#contact"]');
      if (contact) {
        const pair = document.createElement('span');
        pair.className = 'nav-account-links';
        const contactWasFocused = document.activeElement === contact;
        contact.before(pair);
        pair.append(contact, link);
        if (contactWasFocused) contact.focus({preventScroll: true});
      } else {
        slot.append(link);
      }
    }
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

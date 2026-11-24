// An account keeps one bookmark per book. Guest storage uses the original keys.
(() => {
  const url = 'https://board.finance-fixer.net/site/bookworm/oz';
  let session;
  let pending;
  let writing = false;
  let writable = true;
  let generation = 0;
  const remote = () => session?.bookmark || null;

  async function fetchState() {
    try {
      const r = await fetch(url, {credentials: 'include', cache: 'no-store', signal: AbortSignal.timeout(3500)});
      if (r.status === 401) return {scope: '', guest: true};
      if (r.ok) return await r.json();
    } catch { /* Public books remain readable offline. */ }
    return null;
  }

  function get(key) {
    try { return session && localStorage.getItem(namespace() + key); } catch { return null; }
  }
  function namespace() { return session?.scope ? 'bookworm:account:' + session.scope + ':' : ''; }

  async function flush() {
    if (writing || !pending || !session?.csrf || !writable) return;
    writing = true;
    const value = pending;
    const observed = generation;
    pending = null;
    try {
      const r = await fetch(url, {
        method: 'PUT', credentials: 'include', cache: 'no-store', keepalive: true,
        headers: {'Content-Type': 'application/json', 'X-Bookworm-CSRF': session.csrf},
        body: JSON.stringify({...value, revision: remote()?.revision || 0}), signal: AbortSignal.timeout(6000)
      });
      if (r.ok || r.status === 409) {
        const next = await r.json();
        if (next.scope !== session.scope) return;
        session = next;
        if (r.status === 409 && observed === generation) {
          writable = false;
          pending = null;
        }
      } else if (r.status === 401 || r.status === 403) {
        writable = false;
        pending = null;
      }
    } catch { /* A later action retries with the latest local position. */ }
    finally { writing = false; if (pending) void flush(); }
  }
  let lastPush = 0;
  function save(chapter, scene, seconds, action, immediate) {
    if (!session?.csrf) return;
    if (action) { generation++; writable = true; }
    if (!writable) return;
    pending = {chapter: Number(chapter), scene: Number(scene), ms: Math.round(seconds * 1000)};
    if (action || immediate || Date.now() - lastPush > 10000) {
      lastPush = Date.now();
      void flush();
    }
  }

  const ready = fetchState().then(value => { session = value || {scope: '', offline: true}; });
  window.BookwormProgress = {
    ready, remote, get, save, flush,
    set(key, value) {
      if (session) { try { localStorage.setItem(namespace() + key, value); } catch {} }
    }
  };
  // A cached page can outlive a login or a logout performed in another tab.
  async function recheck() {
    await ready;
    const fresh = await fetchState();
    if (fresh && fresh.scope !== session?.scope) { location.reload(); return; }
    if (fresh?.scope && !writing && fresh.bookmark?.revision !== remote()?.revision) {
      session = fresh;
      writable = false;
      pending = null;
      window.dispatchEvent(new Event('bookworm-bookmark'));
    }
  }
  window.addEventListener('pageshow', e => { if (e.persisted) recheck(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) recheck(); });
})();

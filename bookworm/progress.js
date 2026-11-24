// A confirmed guest uses the original local keys. Each account has its own cache.
(() => {
  const url = 'https://board.finance-fixer.net/site/bookworm/oz';
  const memory = new Map();
  let session = null;
  let pending = null;
  let writing = false;
  let writable = true;
  let generation = 0;
  let confirmedAction = 0;
  let retriedAction = -1;
  let lastPush = 0;
  let lastCheck = 0;
  const revision = () => session?.bookmark?.revision || 0;
  const scopeKey = () => session?.scope ? 'bookworm:account:' + session.scope + ':' : '';
  const outboxKey = () => scopeKey() + 'pending';

  async function fetchState() {
    try {
      const r = await fetch(url, {credentials: 'include', cache: 'no-store', signal: AbortSignal.timeout(3500)});
      if (r.status === 401) return {scope: '', guest: true};
      if (r.ok) return await r.json();
    } catch { /* An unknown identity reads in memory for this visit. */ }
    return null;
  }

  function set(key, value) {
    const id = scopeKey() + key;
    if (session) {
      try { localStorage.setItem(id, value); memory.delete(id); return; } catch {}
    }
    memory.set(id, String(value));
  }
  function get(key) {
    const id = scopeKey() + key;
    if (memory.has(id)) return memory.get(id);
    try { return session && localStorage.getItem(id); } catch { return null; }
  }
  function storePending(value) {
    try {
      if (value) sessionStorage.setItem(outboxKey(), JSON.stringify({...value, revision: revision()}));
      else sessionStorage.removeItem(outboxKey());
    } catch { /* The in-memory queue still retries during this visit. */ }
  }

  async function flush() {
    if (writing || !pending || !session?.csrf || !writable) return;
    writing = true;
    const value = pending;
    const observed = generation;
    let retryLater = false;
    try {
      const r = await fetch(url, {
        method: 'PUT', credentials: 'include', cache: 'no-store', keepalive: true,
        headers: {'Content-Type': 'application/json', 'X-Bookworm-CSRF': session.csrf},
        body: JSON.stringify({...value, revision: revision()}), signal: AbortSignal.timeout(6000)
      });
      if (r.ok || r.status === 409) {
        const next = await r.json();
        if (next.scope !== session.scope) { location.reload(); return; }
        if ((next.bookmark?.revision || 0) >= revision()) session.bookmark = next.bookmark;
        if (r.ok) {
          confirmedAction = Math.max(confirmedAction, observed);
          if (pending === value) pending = null;
        } else if (generation > confirmedAction && retriedAction !== generation) {
          // One deliberate selection may claim the newer revision. A stale timer may not.
          retriedAction = generation;
        } else {
          writable = false;
          pending = null;
        }
        storePending(pending);
      } else if (r.status === 401 || r.status === 403) {
        // A later visibility change renews the current token or detects account changes.
        retryLater = true;
      } else { retryLater = true; }
    } catch { retryLater = true; }
    finally {
      writing = false;
      if (pending && !retryLater) void flush();
    }
  }

  function save(chapter, scene, seconds, action, immediate) {
    if (!session?.csrf || !Number.isFinite(seconds)) return;
    if (action) { generation++; writable = true; }
    if (!writable) return;
    pending = {chapter: Number(chapter), scene: Number(scene), ms: Math.round(seconds * 1000)};
    storePending(pending);
    if (action || immediate || Date.now() - lastPush > 10000) {
      lastPush = Date.now();
      void flush();
    }
  }
  const ready = fetchState().then(value => {
    session = value;
    if (!session?.scope) return;
    try {
      const old = JSON.parse(sessionStorage.getItem(outboxKey()));
      if (old && old.revision === revision()) {
        pending = {chapter: old.chapter, scene: old.scene, ms: old.ms};
        void flush();
      } else { storePending(null); }
    } catch {}
  });

  async function recheck() {
    await ready;
    const ticket = ++lastCheck;
    const fresh = await fetchState();
    if (!fresh || ticket !== lastCheck) return;
    if (fresh.scope !== session?.scope) { location.reload(); return; }
    if (!fresh.scope) return;
    session.csrf = fresh.csrf;
    if ((fresh.bookmark?.revision || 0) > revision() && !writing) {
      session.bookmark = fresh.bookmark;
      writable = false;
      pending = null;
      storePending(null);
      window.dispatchEvent(new Event('bookworm-bookmark'));
    } else if (pending) { void flush(); }
  }
  window.BookwormProgress = {ready, remote: () => pending || session?.bookmark || null, get, set, save, flush};
  window.addEventListener('online', recheck);
  window.addEventListener('pageshow', e => { if (e.persisted) recheck(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) recheck(); });
})();

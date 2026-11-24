// A confirmed guest uses the original local keys. Each account has its own cache.
(() => {
  function openBook(book) {
    const url = 'https://board.finance-fixer.net/site/bookworm/' + book;
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
    const outboxKey = () => scopeKey() + (book === 'oz' ? 'pending' : book + ':pending');
    const writer = crypto.randomUUID();
    let serial = 0;
    let storedId;
    let lastSent;
    function samePosition(a, b) { return !!a && !!b && a.chapter === b.chapter && a.scene === b.scene && a.ms === b.ms; }
    function stored() {
      try { return JSON.parse(localStorage.getItem(outboxKey())); } catch { return null; }
    }

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
        if (value) {
          storedId = writer + ':' + (++serial);
          localStorage.setItem(outboxKey(), JSON.stringify({value, id: storedId, revision: revision(),
            lastSent, intentional: generation > confirmedAction && generation !== retriedAction}));
        } else if (stored()?.id === storedId) { localStorage.removeItem(outboxKey()); }
      } catch { /* The in-memory queue still retries during this visit. */ }
    }

    async function flush() {
      if (writing || !pending || !session?.csrf || !writable) return;
      writing = true;
      const value = pending;
      const observed = generation;
      let retryLater = false;
      const base = revision();
      // Keep the previous attempt until the server acknowledges it. Its response may be lost.
      if (!lastSent || !samePosition(lastSent, value) || lastSent.revision !== base) {
        lastSent = {...value, revision: base};
        storePending(pending);
      }
      try {
        const r = await fetch(url, {
          method: 'PUT', credentials: 'include', cache: 'no-store', keepalive: true,
          headers: {'Content-Type': 'application/json', 'X-Bookworm-CSRF': session.csrf},
          body: JSON.stringify({...value, revision: base}), signal: AbortSignal.timeout(6000)
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
          window.dispatchEvent(new Event('bookworm-bookmark'));
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
        const old = stored();
        if (!old?.value) return;
        storedId = old.id;
        const acknowledged = samePosition(session.bookmark, old.lastSent) && revision() === old.lastSent.revision + 1;
        if (samePosition(session.bookmark, old.value)) { storePending(null); return; }
        if (old.revision === revision() || acknowledged || old.intentional) {
          pending = old.value;
          if (old.intentional) generation++;
          if (old.revision < revision() && !acknowledged) retriedAction = generation;
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
        const acknowledged = samePosition(fresh.bookmark, lastSent) && fresh.bookmark.revision === lastSent.revision + 1;
        session.bookmark = fresh.bookmark;
        if (pending && !samePosition(pending, fresh.bookmark) && (acknowledged || (generation > confirmedAction && retriedAction !== generation))) {
          if (!acknowledged) retriedAction = generation;
          void flush();
        } else {
          writable = false;
          pending = null;
          storePending(null);
        }
        window.dispatchEvent(new Event('bookworm-bookmark'));
      } else if (pending) { void flush(); }
    }
    window.addEventListener('online', recheck);
    window.addEventListener('pageshow', e => { if (e.persisted) recheck(); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) recheck(); });
    return {ready, remote: () => pending || session?.bookmark || null, get, set, save, flush};
  }
  const books = new Map();
  function forBook(book) {
    if (!books.has(book)) books.set(book, openBook(book));
    return books.get(book);
  }
  const current = forBook(document.documentElement.dataset.book || 'oz');
  window.BookwormProgress = Object.assign(current, {forBook});
})();

// A confirmed guest uses the original local keys. Each account has its own cache.
(() => {
  let pageScope;
  let invalidated = false;
  const discardOnSwitch = new Set();
  function invalidate(nextScope, switched = true) {
    if (invalidated) return;
    invalidated = true;
    if (nextScope) for (const discard of discardOnSwitch) discard();
    if (switched && document.documentElement.dataset.chapter && typeof history !== 'undefined') {
      const url = new URL(location.href);
      url.hash = '';
      url.searchParams.delete('read');
      history.replaceState({...history.state, bookwormAccountReset: true, bookwormScene: null}, '', url);
    }
    for (const link of document.querySelectorAll('[data-resume-label]')) link.hidden = true;
    location.reload();
  }
  function openBook(book) {
    const url = 'https://board.finance-fixer.net/site/bookworm/' + book;
    const memory = new Map();
    const changedTimes = new Map();
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
    const choiceKey = () => scopeKey() + book + ':latest-choice';
    let choiceId;
    function choiceSuperseded() {
      try {
        const latest = localStorage.getItem(choiceKey());
        return !!(choiceId && latest && latest !== choiceId);
      } catch { return false; }
    }
    const changedKey = () => scopeKey() + book + ':server-revision';
    const prefix = 'bookworm:' + book + ':';
    const writer = crypto.randomUUID();
    let serial = 0;
    let storedId;
    let lastSent;
    let attempts = [];
    let verifyingReturn = false;
    let offlineWrite = false;
    let checkingConnection = false;
    let returnCheck;
    let deferredChoice;
    function checkReturn() {
      if (!returnCheck) returnCheck = recheck().finally(() => { returnCheck = null; });
      return returnCheck;
    }
    function acknowledged(bookmark) {
      return attempts.some(attempt => samePosition(bookmark, attempt) && bookmark.revision === attempt.revision + 1);
    }
    function acceptScope(next) {
      if (!next || invalidated) return false;
      if (pageScope !== undefined && pageScope !== next.scope) { invalidate(next.scope); return false; }
      pageScope = next.scope;
      return true;
    }
    function advance(bookmark) {
      if (!bookmark || bookmark.revision <= revision()) return;
      session.bookmark = bookmark;
      const chapterKey = scopeKey() + prefix + 'ch' + bookmark.chapter + ':audio-v1:';
      try {
        localStorage.setItem(scopeKey() + prefix + 'last-chapter', String(bookmark.chapter));
        localStorage.setItem(chapterKey + 'last-scene', 'scene-' + bookmark.scene);
        localStorage.setItem(chapterKey + 'scene-' + bookmark.scene + ':time', String(bookmark.ms / 1000));
      } catch { /* The account still has the acknowledged server bookmark. */ }
    }
    function signal() {
      window.dispatchEvent(new Event('bookworm-bookmark'));
    }
    function samePosition(a, b) { return !!a && !!b && a.chapter === b.chapter && a.scene === b.scene && a.ms === b.ms; }
    function stored() {
      try { return JSON.parse(localStorage.getItem(outboxKey())); } catch { return null; }
    }

    async function fetchState() {
      try {
        const r = await fetch(url, {credentials: 'include', cache: 'no-store', signal: AbortSignal.timeout(3500)});
        const next = r.status === 401 ? {scope: '', guest: true} : (r.ok ? await r.json() : null);
        return next;
      } catch { /* An unknown identity reads in memory for this visit. */ }
      return null;
    }

    function set(key, value) {
      if (invalidated || !key.startsWith(prefix)) return;
      const id = scopeKey() + key;
      // Account positions become durable through acknowledged bookmarks and the scoped outbox.
      // A tab with an old login must not put speculative scene choices in that account's cache.
      if (session?.guest) {
        try { localStorage.setItem(id, value); memory.delete(id); return; } catch {}
      }
      memory.set(id, String(value));
      if (session?.scope && key.endsWith(':time')) changedTimes.set(id, String(value));
    }
    function get(key) {
      if (invalidated || verifyingReturn || !key.startsWith(prefix)) return null;
      const id = scopeKey() + key;
      if (memory.has(id)) return memory.get(id);
      try {
        const value = session && localStorage.getItem(id);
        return value;
      } catch { return null; }
    }
    function storePending(value, claim = false, newValue = false) {
      try {
        const disk = stored();
        if (disk && disk.id !== storedId && !claim) return false;
        if (value) {
          const nextId = newValue || !storedId ? writer + ':' + (++serial) : storedId;
          localStorage.setItem(outboxKey(), JSON.stringify({value, id: nextId, revision: revision(),
            lastSent, attempts, choiceId, intentional: generation > confirmedAction && generation !== retriedAction}));
          storedId = nextId;
        } else if (disk && disk.id === storedId) { localStorage.removeItem(outboxKey()); }
      } catch { /* The in-memory queue still retries during this visit. */ }
      return true;
    }
    discardOnSwitch.add(() => {
      if (session?.scope && storedId) storePending(null);
      pending = null;
      memory.clear();
    });

    async function flush() {
      if (invalidated || verifyingReturn || writing || !pending || !session?.csrf || !writable) return;
      if (offlineWrite) {
        // Check whether the lost request arrived before issuing a new write.
        if (!checkingConnection) {
          checkingConnection = true;
          void recheck().finally(() => { checkingConnection = false; });
        }
        return;
      }
      writing = true;
      const value = pending;
      const observed = generation;
      const timesAtSend = new Map(changedTimes);
      let retryLater = false;
      const base = revision();
      const token = session.csrf;
      const disk = stored();
      if (disk && disk.id !== storedId) { writing = false; return; }
      attempts = attempts.filter(attempt => attempt.revision >= base);
      // Keep the previous attempt until the server acknowledges it. Its response may be lost.
      if (!lastSent || !samePosition(lastSent, value) || lastSent.revision !== base) {
        lastSent = {...value, revision: base, generation: observed};
        if (!attempts.some(attempt => samePosition(attempt, lastSent))) attempts.push(lastSent);
        storePending(pending);
      }
      try {
        const r = await fetch(url, {
          method: 'PUT', credentials: 'include', cache: 'no-store', keepalive: true,
          headers: {'Content-Type': 'application/json', 'X-Bookworm-CSRF': token},
          body: JSON.stringify({...value, revision: base}), signal: AbortSignal.timeout(6000)
        });
        if (r.ok || r.status === 409) {
          const next = await r.json();
          if (!acceptScope(next)) return;
          advance(next.bookmark);
          if (choiceSuperseded()) {
            writable = false;
            pending = null;
            storePending(null);
            signal();
            return;
          }
          if (r.ok) {
            // A successful response authorizes device hints captured before that request.
            // A newer remote selection has priority over hints from an older response.
            if (writable && next.bookmark?.revision === revision()) {
              for (const [id, time] of timesAtSend) {
                try { localStorage.setItem(id, time); } catch {}
                if (changedTimes.get(id) === time) {
                  changedTimes.delete(id);
                  if (memory.get(id) === time) memory.delete(id);
                }
              }
            }
            if (next.bookmark.revision < revision() && generation === observed) {
              // Another device advanced after this successful write was committed.
              writable = false;
              pending = null;
            }
            confirmedAction = Math.max(confirmedAction, observed);
            if (pending === value) pending = null;
            try {
              if (revision() > Number(localStorage.getItem(changedKey()))) localStorage.setItem(changedKey(), String(revision()));
            } catch {}
          } else if (acknowledged(session.bookmark)) {
            // The server accepted our preceding write even though its response was lost.
            // The newer pending value can safely advance from the acknowledged revision.
          } else if (generation > confirmedAction && retriedAction !== generation) {
            // One deliberate selection may claim the newer revision. A stale timer may not.
            retriedAction = generation;
          } else {
            writable = false;
            pending = null;
          }
          storePending(pending);
          signal();
        } else if (r.status === 401 || r.status === 403) {
          retryLater = true;
          if (r.status === 401) {
            // A previously authenticated account may resume its own pending work after session expiry.
            // A concurrent successful re-login can already have replaced the rejected token.
            if (session.csrf === token) await recheck();
            if (!invalidated && session.csrf !== token) retryLater = false;
          } else {
            let rejectedScope;
            try { rejectedScope = (await r.json())?.scope; } catch {}
            if (rejectedScope && rejectedScope !== session.scope) {
              invalidate(rejectedScope);
              return;
            }
            const verified = await recheck();
            // Older servers omitted the current scope. An unverified rejection cannot
            // safely be replayed under the previous member when the account comes back.
            if (!verified && !rejectedScope && !invalidated && session.csrf === token) storePending(null);
            retryLater = invalidated || !session.csrf || session.csrf === token;
          }
        } else { retryLater = true; }
      } catch { retryLater = true; offlineWrite = true; }
      finally {
        writing = false;
        if (pending && !retryLater) void flush();
      }
    }

    function save(chapter, scene, seconds, action, immediate) {
      if (invalidated || !session?.csrf) return;
      if (verifyingReturn) {
        deferredChoice = [chapter, scene, seconds, action || !!deferredChoice?.[3], immediate];
        void checkReturn();
        return;
      }
      if (typeof seconds === 'function') seconds = seconds();
      if (!Number.isFinite(seconds)) return;
      if (action) {
        generation++;
        writable = true;
        choiceId = writer + '/' + generation;
        try { localStorage.setItem(choiceKey(), choiceId); } catch {}
      } else if (choiceSuperseded()) {
        writable = false;
      }
      if (!writable) return;
      // Another tab can already be delivering the shared outbox entry we are replacing.
      if (pending && samePosition(stored()?.value, pending) &&
          !attempts.some(attempt => attempt.revision === revision() && samePosition(attempt, pending))) {
        attempts.push({...pending, revision: revision(), generation: confirmedAction});
      }
      pending = {chapter: Number(chapter), scene: Number(scene), ms: Math.round(seconds * 1000)};
      if (!storePending(pending, action, true)) {
        writable = false;
        pending = null;
        return;
      }
      if (action || immediate || Date.now() - lastPush > 10000) {
        lastPush = Date.now();
        void flush();
      }
    }
    const ready = fetchState().then(value => {
      if (!acceptScope(value)) return;
      session = value;
      if (!session?.scope) return;
      try {
        const old = stored();
        if (!old?.value) return;
        storedId = old.id;
        choiceId = old.choiceId;
        if (choiceSuperseded()) { storePending(null); return; }
        lastSent = old.lastSent;
        attempts = Array.isArray(old.attempts) ? old.attempts : (lastSent ? [lastSent] : []);
        const ours = acknowledged(session.bookmark);
        if (samePosition(session.bookmark, old.value)) { storePending(null); return; }
        if (old.revision === revision() || ours || old.intentional) {
          pending = old.value;
          if (old.intentional) generation++;
          if (old.revision < revision() && !ours) retriedAction = generation;
          void flush();
        } else { storePending(null); }
      } catch {}
    });

    async function recheck() {
      await ready;
      const ticket = ++lastCheck;
      const fresh = await fetchState();
      if (ticket !== lastCheck || !acceptScope(fresh)) return;
      if (fresh.scope !== session?.scope) { invalidate(fresh.scope, !!session); return; }
      verifyingReturn = false;
      offlineWrite = false;
      if (!fresh.scope) { signal(); return true; }
      session.csrf = fresh.csrf;
      if ((fresh.bookmark?.revision || 0) > revision()) {
        const ours = acknowledged(fresh.bookmark);
        advance(fresh.bookmark);
        if (!ours && !samePosition(pending, fresh.bookmark)) {
          const remoteTime = scopeKey() + prefix + 'ch' + fresh.bookmark.chapter + ':audio-v1:scene-' + fresh.bookmark.scene + ':time';
          memory.delete(remoteTime);
          changedTimes.delete(remoteTime);
        }
        if (samePosition(pending, fresh.bookmark)) {
          confirmedAction = Math.max(confirmedAction, generation);
          pending = null;
          storePending(null);
        } else if (!writing) {
          if (pending && (ours || (generation > confirmedAction && retriedAction !== generation))) {
            if (!ours) retriedAction = generation;
            void flush();
          } else {
            writable = false;
            pending = null;
            storePending(null);
          }
        }
      } else if (pending && !writing) { void flush(); }
      const choice = deferredChoice;
      deferredChoice = null;
      if (choice) save(...choice);
      signal();
      return true;
    }
    window.addEventListener('storage', event => {
      if (!event.key?.endsWith(':' + book + ':server-revision')) return;
      void ready.then(() => {
        if (session?.scope && event.key === changedKey() && Number(event.newValue) > revision()) void recheck();
      });
    });
    window.addEventListener('online', recheck);
    window.addEventListener('pageshow', e => {
      if (e.persisted) {
        verifyingReturn = true;
        signal();
        void checkReturn();
      }
    });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) recheck(); });
    return {ready, verifying: () => verifyingReturn, remote: () => invalidated || verifyingReturn ? null : (pending || session?.bookmark || null), get, set, save, flush};
  }
  const books = new Map();
  function forBook(book) {
    if (!books.has(book)) books.set(book, openBook(book));
    return books.get(book);
  }
  const current = forBook(document.documentElement.dataset.book || 'oz');
  window.BookwormProgress = Object.assign(current, {forBook});
})();

/* 재무해결사 — AI 상담 채팅 위젯 (vanilla, no build)
   백엔드: https://ai.finance-fixer.net  (hj, Cloudflare Tunnel)
   흐름: Turnstile 토큰 → POST /session (세션토큰) → POST /chat (Bearer).
*/
(function () {
  "use strict";

  var API_BASE = "https://ai.finance-fixer.net";
  var TS_SITEKEY = "0x4AAAAAADhaHYlOduJqFrFB"; // Turnstile 공개 사이트키
  var LS_TOKEN = "ff_chat_token", LS_EXP = "ff_chat_exp", LS_SID = "ff_chat_sid";
  var RM = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ── state ──
  var open = false, sending = false, exchanges = 0, leadShown = false, leadDone = false;
  var tsWidgetId = null, tsToken = null, tsResolver = null;  // Turnstile
  var sessionPromise = null;                    // 세션 발급 직렬화

  var fab, panel, logEl, inputEl, sendBtn, chipsEl, leadForm, lastFocus = null;

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    fab = document.getElementById("ai-fab");
    panel = document.getElementById("ai-panel");
    logEl = document.getElementById("ai-log");
    inputEl = document.getElementById("ai-text");
    sendBtn = document.getElementById("ai-send");
    chipsEl = document.getElementById("ai-chips");
    leadForm = document.getElementById("ai-lead");
    if (!fab || !panel) return;

    fab.addEventListener("click", openPanel);
    document.getElementById("ai-close").addEventListener("click", closePanel);
    var openers = document.querySelectorAll("[data-ai-open]");
    for (var i = 0; i < openers.length; i++) {
      openers[i].addEventListener("click", function (e) { e.preventDefault(); openPanel(); });
    }

    document.getElementById("ai-input").addEventListener("submit", onSend);
    inputEl.addEventListener("input", autosize);
    inputEl.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(e); }
    });
    panel.addEventListener("keydown", onPanelKeydown);

    if (leadForm) {
      leadForm.addEventListener("submit", onLeadSubmit);
      document.getElementById("ai-lead-skip").addEventListener("click", function () {
        leadForm.hidden = true; leadDone = true; inputEl.focus();
      });
    }
    if (chipsEl) {
      chipsEl.addEventListener("click", function (e) {
        var b = e.target.closest("button[data-chip]");
        if (b) { inputEl.value = b.getAttribute("data-chip"); chipsEl.hidden = true; onSend(e); }
      });
    }
  }

  // ── panel open/close (+ 포커스 트랩) ──
  function focusables() {
    return panel.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
  }
  function onPanelKeydown(e) {
    if (e.key === "Escape") { closePanel(); return; }
    if (e.key !== "Tab") return;
    var f = focusables();
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
  function openPanel() {
    if (open) return;
    open = true; lastFocus = document.activeElement;
    panel.hidden = false;
    requestAnimationFrame(function () { panel.classList.add("open"); });
    fab.setAttribute("aria-expanded", "true");
    if (!logEl.dataset.greeted) greet();
    setTimeout(function () { inputEl.focus(); }, 60);
    ensureSession().catch(function () {}); // prewarm(실패해도 전송 때 다시 시도)
  }
  function closePanel() {
    open = false;
    panel.classList.remove("open");
    fab.setAttribute("aria-expanded", "false");
    setTimeout(function () { panel.hidden = true; }, RM ? 0 : 320);
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  function greet() {
    logEl.dataset.greeted = "1";
    addBot("안녕하세요, 재무해결사 AI 상담입니다. 세무·보조금 정산·회계감사·회생 관련해 궁금한 점을 편하게 물어보세요.");
    if (chipsEl) chipsEl.hidden = false;
  }

  // ── 메시지 렌더 ──
  function makeRow(role, ariaHidden) {
    var d = document.createElement("div");
    d.className = "ai-msg ai-msg--" + role;
    if (ariaHidden) d.setAttribute("aria-hidden", "true");
    var b = document.createElement("div");
    b.className = "ai-bubble";
    d.appendChild(b);
    logEl.appendChild(d);
    scroll();
    return d;
  }
  function addUser(t) { makeRow("user").firstChild.textContent = t; }
  function addBot(t) { var r = makeRow("bot"); r.firstChild.textContent = t; return r; }
  function typing() {
    var r = makeRow("bot", true);          // aria-hidden: SR 은 최종답변만 듣게
    var b = r.firstChild;
    b.className = "ai-bubble ai-typing";
    b.innerHTML = "<span></span><span></span><span></span>";
    return r;
  }
  function removeRow(r) { if (r && r.parentNode) r.parentNode.removeChild(r); }
  function scroll() { logEl.scrollTop = logEl.scrollHeight; }
  function autosize() {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + "px";
    sendBtn.disabled = !inputEl.value.trim();
  }

  // ── Turnstile (단일 dispatch + 호출별 타이머) ──
  // 위젯을 보이게 렌더(Managed: 대부분 무동작 통과, 의심스러우면 체크박스). callback이 토큰 제공.
  function tsEnsureRendered() {
    if (tsWidgetId !== null || !window.turnstile) return;
    tsWidgetId = window.turnstile.render("#ai-turnstile", {
      sitekey: TS_SITEKEY,
      callback: function (t) { tsToken = t; if (tsResolver) { var r = tsResolver; tsResolver = null; r(t); } },
      "error-callback": function () { if (tsResolver) { var r = tsResolver; tsResolver = null; r(null); } },
      "expired-callback": function () { tsToken = null; },
    });
  }
  function getTurnstileToken() {
    return new Promise(function (resolve, reject) {
      if (!window.turnstile) { reject(new Error("ts_unloaded")); return; }
      tsEnsureRendered();
      function give(t) {
        if (!t) { reject(new Error("ts_fail")); return; }
        resolve(t);
        try { window.turnstile.reset(tsWidgetId); } catch (e) {}  // 다음 토큰 미리 준비
      }
      if (tsToken) { var cur = tsToken; tsToken = null; give(cur); return; }
      var done = false;
      var timer = setTimeout(function () {
        if (!done) { done = true; tsResolver = null; reject(new Error("ts_timeout")); }
      }, 25000);
      tsResolver = function (tok) { if (done) return; done = true; clearTimeout(timer); tsToken = null; give(tok); };
    });
  }

  // ── 세션 확보 (직렬화, 빈 토큰은 안 보냄) ──
  function validToken() {
    var t = localStorage.getItem(LS_TOKEN), exp = parseInt(localStorage.getItem(LS_EXP) || "0", 10);
    return t && exp > Date.now() / 1000 + 10 ? t : null;
  }
  function ensureSession() {
    var t = validToken();
    if (t) return Promise.resolve(t);
    if (sessionPromise) return sessionPromise;
    sessionPromise = getTurnstileToken().then(function (ts) {
      return fetch(API_BASE + "/session", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ turnstile_token: ts }),
      }).then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (d) {
          localStorage.setItem(LS_TOKEN, d.session_token);
          localStorage.setItem(LS_EXP, String(Math.floor(Date.now() / 1000) + (d.ttl || 1800)));
          localStorage.setItem(LS_SID, d.session_id || "");
          return d.session_token;
        });
    });
    sessionPromise.catch(function () {}).then(function () { sessionPromise = null; });
    return sessionPromise;
  }

  // ── 전송 ──
  function onSend(e) {
    if (e) e.preventDefault();
    var msg = inputEl.value.trim();
    if (!msg || sending) return;
    if (chipsEl) chipsEl.hidden = true;
    addUser(msg);
    inputEl.value = ""; autosize();
    sending = true; sendBtn.disabled = true;
    var bubble = typing();
    doSend({ message: msg }, false).then(function (d) {
      removeRow(bubble);
      addBot(d && d.reply ? d.reply : "답변을 받지 못했어요.");
      exchanges++;
      maybeLead(d);
    }).catch(function () {
      showError(bubble);
    }).finally(function () {
      sending = false; sendBtn.disabled = !inputEl.value.trim();
    });
  }

  // 세션확보 + /chat + 401 1회 재시도. 최종 JSON(reply 포함) 반환.
  function doSend(payload, retried) {
    return ensureSession().then(function (token) {
      return fetch(API_BASE + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token },
        body: JSON.stringify(payload),
      }).then(function (r) {
        if (r.status === 401 && !retried) {
          localStorage.removeItem(LS_TOKEN);
          return doSend(payload, true);   // 같은 체인 — sending 유지됨
        }
        return r.json();
      });
    });
  }

  function showError(bubble) {
    var b = bubble.firstChild;
    b.className = "ai-bubble ai-err"; b.textContent = "연결에 실패했어요. ";
    var tel = document.createElement("a");
    tel.href = "tel:01033395356"; tel.textContent = "전화 010-3339-5356";
    b.appendChild(tel);
    b.appendChild(document.createTextNode(" 또는 "));
    var f = document.createElement("button");
    f.type = "button"; f.className = "ai-link"; f.textContent = "상담폼으로";
    f.addEventListener("click", function () {
      closePanel();
      var c = document.getElementById("contact");
      if (c) c.scrollIntoView({ behavior: RM ? "auto" : "smooth" });
    });
    b.appendChild(f);
    bubble.removeAttribute("aria-hidden");
    scroll();
  }

  // ── 리드 미니폼 ──
  function maybeLead(d) {
    if (leadDone || leadShown || !leadForm) return;
    if (d && d.lead_sent) { leadDone = true; return; }
    if (exchanges >= 2) {
      leadShown = true;
      addBot("전화로 더 정확히 도와드릴까요? 연락처를 남겨주시면 담당 회계사가 연락드립니다.");
      leadForm.hidden = false;
      scroll();
    }
  }
  function onLeadSubmit(e) {
    e.preventDefault();
    var nameEl = document.getElementById("ai-lead-name");
    var phoneEl = document.getElementById("ai-lead-phone");
    if (!nameEl.value.trim() || !phoneEl.value.trim()) return;
    if (!leadForm.checkValidity()) { leadForm.reportValidity(); return; }
    var btn = leadForm.querySelector(".ai-lead-send");
    btn.disabled = true;
    var name = nameEl.value.trim(), phone = phoneEl.value.trim();
    leadForm.hidden = true;
    doSend({ lead: { name: name, phone: phone } }, false).then(function (d) {
      leadDone = true;
      addBot(d && d.reply ? d.reply : "연락처 감사합니다. 곧 연락드릴게요.");
    }).catch(function () {
      leadForm.hidden = false; btn.disabled = false;
      addBot("연락처 전송에 실패했어요. 다시 시도하시거나 전화(010-3339-5356)로 부탁드려요.");
    });
  }
})();

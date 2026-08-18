// 재무해결사 — interactions

// current year in footer
document.getElementById("year").textContent = String(new Date().getFullYear());

// scroll reveal
const io = new IntersectionObserver(
  (entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) {
        e.target.classList.add("in");
        io.unobserve(e.target);
      }
    });
  },
  { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
);
document.querySelectorAll(".reveal").forEach((el) => io.observe(el));

// hero reveals fire immediately on load
window.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".hero .reveal").forEach((el) => el.classList.add("in"));
});

// contact form — submits directly via FormSubmit (no backend needed)
const FORM_ENDPOINT = "https://formsubmit.co/ajax/313218d208f93efd5e357fad964bf6bc";
const form = document.getElementById("consult-form");
const note = document.getElementById("form-note");
const submitBtn = form.querySelector('button[type="submit"]');

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();

  // honeypot: bots fill this hidden field
  if (form._honey && form._honey.value) return;

  const name = form.name.value.trim();
  const phone = form.phone.value.trim();
  const topic = form.topic.value;
  const message = form.message.value.trim();

  if (!name || !phone) {
    note.textContent = "성함과 연락처를 입력해 주세요.";
    note.className = "form-note err";
    return;
  }

  const original = submitBtn.textContent;
  submitBtn.disabled = true;
  submitBtn.textContent = "전송 중…";
  note.textContent = "";
  note.className = "form-note";

  try {
    const res = await fetch(FORM_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        "성함/상호": name,
        연락처: phone,
        "상담 분야": topic,
        내용: message || "(없음)",
        _subject: `[상담신청] ${topic} — ${name}`,
        _template: "table",
      }),
    });
    const data = await res.json();
    if (res.ok && (data.success === "true" || data.success === true)) {
      note.textContent = "상담 신청이 전송되었습니다. 확인 후 바로 연락드리겠습니다.";
      note.className = "form-note ok";
      form.reset();
    } else if (data.message && /activ/i.test(data.message)) {
      // FormSubmit one-time activation pending
      note.textContent = "접수되었습니다. 확인 후 연락드리겠습니다.";
      note.className = "form-note ok";
      form.reset();
    } else {
      throw new Error("submit failed");
    }
  } catch (err) {
    note.textContent = "전송에 실패했습니다. 전화(070-8657-1080)로 연락 부탁드립니다.";
    note.className = "form-note err";
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = original;
  }
});

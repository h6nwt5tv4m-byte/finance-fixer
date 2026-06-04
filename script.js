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

// contact form (no backend yet — opens a prefilled mail draft)
const form = document.getElementById("consult-form");
const note = document.getElementById("form-note");

form.addEventListener("submit", (ev) => {
  ev.preventDefault();
  const name = form.name.value.trim();
  const phone = form.phone.value.trim();
  const topic = form.topic.value;
  const message = form.message.value.trim();

  if (!name || !phone) {
    note.textContent = "성함과 연락처를 입력해 주세요.";
    note.className = "form-note err";
    return;
  }

  const subject = encodeURIComponent(`[상담신청] ${topic} — ${name}`);
  const body = encodeURIComponent(
    `성함/상호: ${name}\n연락처: ${phone}\n상담 분야: ${topic}\n\n내용:\n${message || "(없음)"}`
  );
  window.location.href = `mailto:hyungjun@finance-fixer.com?subject=${subject}&body=${body}`;

  note.textContent = "메일 작성 창이 열립니다. 보내주시면 확인 후 바로 연락드립니다.";
  note.className = "form-note ok";
  form.reset();
});

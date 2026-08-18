// Finance Fixer (EN) — interactions

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
    note.textContent = "Please enter your name and contact number.";
    note.className = "form-note err";
    return;
  }

  const original = submitBtn.textContent;
  submitBtn.disabled = true;
  submitBtn.textContent = "Sending…";
  note.textContent = "";
  note.className = "form-note";

  try {
    const res = await fetch(FORM_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        "Name/Business": name,
        Contact: phone,
        Area: topic,
        Message: message || "(none)",
        _subject: `[Consultation] ${topic} — ${name}`,
        _template: "table",
      }),
    });
    const data = await res.json();
    if (res.ok && (data.success === "true" || data.success === true)) {
      note.textContent = "Your request has been sent. We'll get back to you shortly.";
      note.className = "form-note ok";
      form.reset();
    } else if (data.message && /activ/i.test(data.message)) {
      // FormSubmit one-time activation pending
      note.textContent = "Received. We'll be in touch shortly.";
      note.className = "form-note ok";
      form.reset();
    } else {
      throw new Error("submit failed");
    }
  } catch (err) {
    note.textContent = "Sending failed. Please call us at 070-8657-1080.";
    note.className = "form-note err";
  }
  finally {
    submitBtn.disabled = false;
    submitBtn.textContent = original;
  }
});

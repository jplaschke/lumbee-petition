document.addEventListener("DOMContentLoaded", () => {

  // Animate progress bars
  document.querySelectorAll(".pw-fill[data-pct]").forEach(bar => {
    const pct = parseFloat(bar.dataset.pct) || 0;
    bar.style.width = "0%";
    requestAnimationFrame(() => setTimeout(() => { bar.style.width = pct + "%"; }, 200));
  });

  // Drop zone
  const zone  = document.getElementById("dropZone");
  const input = document.getElementById("id_card");
  const inner = document.getElementById("dzInner");
  if (zone && input) {
    zone.addEventListener("dragover",  e => { e.preventDefault(); zone.classList.add("over"); });
    zone.addEventListener("dragleave", ()  => zone.classList.remove("over"));
    zone.addEventListener("drop", e => {
      e.preventDefault(); zone.classList.remove("over");
      const file = e.dataTransfer.files[0];
      if (file) setFile(file);
    });
    input.addEventListener("change", () => { if (input.files[0]) setFile(input.files[0]); });

    function setFile(file) {
      if (file.size > 16 * 1024 * 1024) { showToast("File too large. Max 16 MB.", "error"); return; }
      if (file.type.startsWith("image/")) {
        const reader = new FileReader();
        reader.onload = e => {
          inner.innerHTML = `<img src="${e.target.result}"
            style="max-height:90px;border-radius:8px;margin-bottom:.5rem">
            <p style="font-size:.82rem;opacity:.7">
              <i class="fas fa-check-circle" style="color:#4caf50"></i> ${file.name}</p>`;
        };
        reader.readAsDataURL(file);
      } else {
        inner.innerHTML = `<i class="fas fa-file-pdf" style="font-size:2.5rem;color:#ef5350"></i>
          <p style="font-size:.82rem;margin-top:.5rem;opacity:.7">${file.name}</p>`;
      }
    }
  }

  // Form submit guard
  const form = document.getElementById("petitionForm");
  if (form) {
    form.addEventListener("submit", e => {
      const expInput = document.getElementById("id_card_expiry");
      if (expInput && expInput.value) {
        const exp = new Date(expInput.value + "T00:00:00");
        const today = new Date(); today.setHours(0,0,0,0);
        if (exp < today) {
          e.preventDefault();
          showToast("Your Member ID card is expired.", "error");
          return;
        }
      }
      const btn = document.getElementById("submitBtn");
      if (btn) { btn.disabled = true; btn.innerHTML = "<i class='fas fa-spinner fa-spin'></i> Submitting…"; }
    });
  }

  // Enrollment ID uppercase
  const eid = document.getElementById("enrollment_id");
  if (eid) {
    eid.addEventListener("input", () => {
      const pos = eid.selectionStart;
      eid.value = eid.value.toUpperCase();
      eid.setSelectionRange(pos, pos);
    });
  }

  // Live counter
  const liveCount = document.getElementById("live-count");
  if (liveCount) {
    setInterval(() => {
      fetch("/api/progress").then(r => r.json()).then(d => {
        animNum(liveCount, parseInt(liveCount.textContent.replace(/,/g,"")) || 0, d.current);
        document.querySelectorAll(".pw-fill").forEach(b => {
          b.style.width = Math.min(d.percent, 100) + "%";
        });
      }).catch(() => {});
    }, 30000);
  }

  function animNum(el, from, to) {
    const dur = 900, t0 = performance.now();
    const step = ts => {
      const frac = Math.min((ts - t0) / dur, 1);
      el.textContent = Math.round(from + (to - from) * frac).toLocaleString();
      if (frac < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // Color pickers sync
  document.querySelectorAll("input[type=color]").forEach(picker => {
    const name = picker.getAttribute("name");
    const hex  = document.querySelector(`.hex-input[data-target="${name}"]`);
    if (!hex) return;
    picker.addEventListener("input", () => { hex.value = picker.value; });
    hex.addEventListener("input", () => {
      if (/^#[0-9a-f]{6}$/i.test(hex.value)) picker.value = hex.value;
    });
  });

  // Toast
  function showToast(msg, type = "info") {
    const colors = { error:"rgba(183,28,28,.95)", info:"rgba(26,35,126,.95)", success:"rgba(46,125,50,.95)" };
    const t = document.createElement("div");
    t.style.cssText = `position:fixed;top:80px;right:20px;z-index:9999;
      background:${colors[type]||colors.info};color:#fff;padding:1rem 1.5rem;
      border-radius:12px;max-width:340px;font-size:.9rem;line-height:1.4;
      box-shadow:0 8px 30px rgba(0,0,0,.4);backdrop-filter:blur(8px);animation:fadeUp .3s ease;`;
    t.innerHTML = `<i class="fas fa-${type==="error"?"exclamation-triangle":"info-circle"}"></i> ${msg}`;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 5000);
  }

});

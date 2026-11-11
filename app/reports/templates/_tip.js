const tip = document.getElementById("tip");
document.addEventListener("pointermove", e => { const t = e.target.closest("[data-tip]"); if (!t) { tip.hidden = true; return; }
  tip.innerHTML = t.dataset.tip; tip.hidden = false; tip.style.left = Math.min(e.clientX+14, innerWidth-tip.offsetWidth-8) + "px"; tip.style.top = (e.clientY+14) + "px"; });

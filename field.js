// A field of synthetic households: each point a record, brightness and size
// scaled by its survey weight. The whole thing drifts slowly, like a nation
// seen from above.
(function () {
  "use strict";
  const canvas = document.getElementById("field");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let w, h, dpr, points, raf;
  const TEAL = [49, 151, 149]; // PolicyEngine teal (--chart-1)

  // Deterministic-ish PRNG so the layout is stable across resizes within a load.
  let seed = 20260610;
  function rnd() {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  }

  function density() {
    const area = window.innerWidth * window.innerHeight;
    return Math.min(240, Math.max(100, Math.round(area / 9000)));
  }

  function build() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.width = Math.floor(window.innerWidth * dpr);
    h = canvas.height = Math.floor(window.innerHeight * dpr);
    canvas.style.width = window.innerWidth + "px";
    canvas.style.height = window.innerHeight + "px";
    seed = 20260610;
    const n = density();
    points = [];
    for (let i = 0; i < n; i++) {
      // weight is heavy-tailed: most households small, a few large (the survey).
      const u = rnd();
      const weight = Math.pow(u, 2.4); // 0..1, skewed low
      points.push({
        x: rnd() * w,
        y: rnd() * h,
        r: (0.6 + weight * 3.1) * dpr,
        base: 0.14 + weight * 0.46,
        tw: rnd() * Math.PI * 2, // twinkle phase
        tws: 0.4 + rnd() * 0.9, // twinkle speed
        vx: (rnd() - 0.5) * 0.04 * dpr,
        vy: (rnd() - 0.5) * 0.04 * dpr,
      });
    }
  }


  function frame(t) {
    ctx.clearRect(0, 0, w, h);
    const px = 0, py = 0;
    const time = t * 0.001;

    for (let i = 0; i < points.length; i++) {
      const p = points[i];
      p.x += p.vx;
      p.y += p.vy;
      if (p.x < -10) p.x = w + 10;
      if (p.x > w + 10) p.x = -10;
      if (p.y < -10) p.y = h + 10;
      if (p.y > h + 10) p.y = -10;

      // larger (heavier) points parallax slightly more — depth.
      const depth = p.r / (3.7 * dpr);
      const x = p.x + px * depth;
      const y = p.y + py * depth;

      const a = p.base;

      ctx.fillStyle = `rgba(${TEAL[0]},${TEAL[1]},${TEAL[2]},${a})`;
      ctx.beginPath();
      ctx.arc(x, y, p.r, 0, Math.PI * 2);
      ctx.fill();
    }
    raf = requestAnimationFrame(frame);
  }

  function staticFrame() {
    ctx.clearRect(0, 0, w, h);
    for (let i = 0; i < points.length; i++) {
      const p = points[i];
      ctx.fillStyle = `rgba(${TEAL[0]},${TEAL[1]},${TEAL[2]},${p.base})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function start() {
    build();
    if (raf) cancelAnimationFrame(raf);
    if (reduce) staticFrame();
    else raf = requestAnimationFrame(frame);
  }

  let rz;
  window.addEventListener("resize", function () {
    clearTimeout(rz);
    rz = setTimeout(start, 180);
  });

  // Pause when the tab is hidden (save battery).
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      if (raf) cancelAnimationFrame(raf);
    } else if (!reduce) {
      raf = requestAnimationFrame(frame);
    }
  });

  start();
})();

// Scroll-reveal for bands lives in reveal.js (shared across every page,
// with or without this hero canvas) — see that file for why it was split
// out.

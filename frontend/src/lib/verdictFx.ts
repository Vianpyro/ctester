import { still } from "./motion";

// What plays once per verdict. app.css draws every state of #out, but CSS animations restart
// whenever the workbench is shown again, and a celebration must never replay for an old result.
const OUT = "cubic-bezier(.16, 1, .3, 1)";
const SPARKS = 14;
// app.css lands the count at about this point (its 120 ms delay plus most of the rise).
const LANDED = 260;

export function play(): void {
  if (still()) return;
  // A frame later, so the verdict is painted and measurable.
  requestAnimationFrame(() => {
    const out = document.getElementById("out");
    // Only a graded run has a count: a compile error or a timeout gets no extra motion.
    const head = out?.querySelector<HTMLElement>(".verdict.count");
    if (!out || !head) return;
    if (out.classList.contains("ok")) setTimeout(() => celebrate(out, head), LANDED);
    else
      head.animate(
        [{ translate: "0" }, { translate: "-6px" }, { translate: "5px" }, { translate: "-3px" }, { translate: "0" }],
        { duration: 380, delay: LANDED + 200, easing: "ease-out" },
      );
  });
}

function celebrate(out: HTMLElement, head: HTMLElement): void {
  head.animate([{ scale: 1 }, { scale: 1.07, offset: 0.35 }, { scale: 1 }], { duration: 620, easing: OUT });

  // Out of #out, which Svelte owns: a fixed layer over the count, removed once it has faded.
  const box = head.getBoundingClientRect();
  const layer = document.createElement("div");
  layer.className = "burst";
  layer.setAttribute("aria-hidden", "true");
  layer.style.left = box.left + Math.min(box.width / 2, 44) + "px";
  layer.style.top = box.top + box.height / 2 + "px";
  const ring = document.createElement("b");
  layer.append(ring);
  ring.animate([{ scale: 0, opacity: 0.7 }, { scale: 5, opacity: 0 }], { duration: 720, easing: OUT, fill: "forwards" });
  for (let n = 0; n < SPARKS; n++) {
    const spark = document.createElement("i");
    const angle = ((n + Math.random() * 0.7) / SPARKS) * 2 * Math.PI;
    const reach = 34 + Math.random() * 52;
    layer.append(spark);
    spark.animate(
      [
        { translate: "0 0", scale: 1, opacity: 1 },
        { translate: `${Math.cos(angle) * reach}px ${Math.sin(angle) * reach}px`, scale: 0.2, opacity: 0 },
      ],
      { duration: 620 + Math.random() * 380, easing: OUT, fill: "forwards" },
    );
  }
  document.body.append(layer);
  setTimeout(() => layer.remove(), 1100);

  out.querySelector(".suite button")?.animate(
    [
      { boxShadow: "0 0 0 0 color-mix(in srgb, var(--ok) 55%, transparent)" },
      { boxShadow: "0 0 0 .7rem transparent" },
    ],
    { duration: 900, delay: 450, easing: OUT },
  );
}

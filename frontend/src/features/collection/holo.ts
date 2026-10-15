import { still } from "../../lib/motion";

const TILT_X = 12;
const TILT_Y = 16;

// A held card leans toward the pointer and its foil follows it. Mouse and pen only: a touch
// has no hover to follow, and nothing moves for a student who asked for less motion.
// An action, not an attachment: the action runtime is already in the eager bundle.
export function holo(card: HTMLElement, held: boolean): { destroy(): void } | void {
  if (!held || still() || !matchMedia("(hover: hover) and (pointer: fine)").matches) return;
  let frame = 0;
  const move = (event: PointerEvent) => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const box = card.getBoundingClientRect();
      const x = (event.clientX - box.left) / box.width;
      const y = (event.clientY - box.top) / box.height;
      card.style.setProperty("--mx", x * 100 + "%");
      card.style.setProperty("--my", y * 100 + "%");
      card.style.setProperty("--rx", (0.5 - y) * TILT_X + "deg");
      card.style.setProperty("--ry", (x - 0.5) * TILT_Y + "deg");
    });
  };
  const rest = () => {
    cancelAnimationFrame(frame);
    for (const name of ["--mx", "--my", "--rx", "--ry"]) card.style.removeProperty(name);
  };
  card.addEventListener("pointermove", move);
  card.addEventListener("pointerleave", rest);
  return {
    destroy() {
      rest();
      card.removeEventListener("pointermove", move);
      card.removeEventListener("pointerleave", rest);
    },
  };
}

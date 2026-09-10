<script lang="ts">
  // THE CARD DRAWINGS. Inline SVG, ONE PATH PER PART, in the vocabulary of a schematic --
  // the same drawing language as the blueprint frames, which is what makes the grid read
  // as one system rather than as eight pieces of clip art.
  //
  // MARKUP, NOT `innerHTML`. These strings are ours and not a student's, so the risk is
  // nil today -- but the forum's message body holds the page's only other `{@html}` on
  // purpose, and adding a second one here would make that sentence false for whoever
  // reads it next.
  //
  // THE FAMILY DECIDES THE DRAWING, not the card id: a new card in an existing family
  // gets a sensible picture with no edit here. An unknown family falls back to the empty
  // frame, which is honest -- better a plain card than a wrong part.

  interface Props {
    id: string;
  }

  const { id }: Props = $props();

  type Shape =
    | { tag: "path"; d: string }
    | { tag: "circle"; cx: number; cy: number; r: number }
    | { tag: "rect"; x: number; y: number; width: number; height: number };

  const path = (d: string): Shape => ({ tag: "path", d });
  const circle = (cx: number, cy: number, r: number): Shape => ({ tag: "circle", cx, cy, r });

  const DRAWINGS: Record<string, Shape[]> = {
    "E-01": [path("M6 32h18l6-12 8 24 8-24 8 24 6-12h18")],
    "M-04": [
      circle(48, 32, 22),
      circle(48, 32, 9),
      circle(48, 16.5, 3.5),
      circle(48, 47.5, 3.5),
      circle(32.5, 32, 3.5),
      circle(63.5, 32, 3.5),
    ],
    "E-07": [
      { tag: "rect", x: 14, y: 14, width: 68, height: 36 },
      path("M26 40V24m8 16V24m8 16V24"),
      path("M56 42l20-14"),
      circle(56, 42, 2.5),
    ],
    "M-02": [
      circle(48, 32, 16),
      circle(48, 32, 5),
      path("M48 8v8m0 32v8M24 32h8m32 0h8M31 15l6 6m22 22l6 6m0-34l-6 6m-22 22l-6 6"),
    ],
    "P-03": [{ tag: "rect", x: 10, y: 20, width: 44, height: 24 }, path("M54 32h30M78 26v12")],
    "E-12": [path("M8 32h24m56 0H64"), path("M32 18l32 14-32 14z"), path("M64 18v28")],
    "M-09": [
      path("M8 32h10m60 0h10"),
      path("M18 32l6-12 8 24 8-24 8 24 8-24 8 24 6-12"),
    ],
    "P-06": [circle(34, 32, 14), path("M34 32l10-9"), path("M54 22h30M54 32h30M54 42h18")],
  };

  const shapes = $derived(DRAWINGS[id] ?? []);
</script>

{#if shapes.length}
  <svg
    viewBox="0 0 96 64"
    width="96"
    height="64"
    fill="none"
    stroke="currentColor"
    stroke-width="1.5"
    stroke-linecap="round"
    aria-hidden="true"
  >
    {#each shapes as s}
      {#if s.tag === "path"}
        <path d={s.d} />
      {:else if s.tag === "circle"}
        <circle cx={s.cx} cy={s.cy} r={s.r} />
      {:else}
        <rect x={s.x} y={s.y} width={s.width} height={s.height} />
      {/if}
    {/each}
  </svg>
{/if}

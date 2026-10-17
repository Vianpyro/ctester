// Whether the bench is in panes is the stylesheet's decision (layout.css, "Panes"): the layout
// is asked here, never a breakpoint copied from it.
export function paned(): boolean {
  const work = document.getElementById("work");
  return !!work && work.scrollWidth > work.clientWidth + 1;
}

// 0 the statement, 1 the code, 2 the result. Nothing happens outside the panes.
export function showPane(index: number): void {
  const work = document.getElementById("work");
  if (!work || !paned()) return;
  const statement = document.getElementById("statement") as HTMLDetailsElement | null;
  if (index === 0 && statement) statement.open = true;
  work.scrollTo?.({ left: index * work.clientWidth });
}

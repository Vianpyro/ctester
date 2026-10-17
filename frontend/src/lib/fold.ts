// The bar never wraps (base.css, "The bar folds"). Its contents are not known here (a name, a
// language, a text size), so it is measured on one row and folded a level at a time until it
// fits: data-fold=" 1 2 3" reads as `[data-fold~="3"]`. Only attributes it never observes change,
// and data-measuring holds transitions still meanwhile: ☰ fading out would keep its tools in the
// bar, grow it, and start the measure over.
export function foldToFit(bar: HTMLElement, levels: number): () => void {
  if (typeof ResizeObserver !== "function") return () => {};
  const fit = () => {
    const wrap = bar.style.flexWrap;
    bar.style.flexWrap = "nowrap";
    bar.dataset.measuring = "";
    bar.dataset.fold = "";
    // Measured first: the last level is laid out while transitions are still held.
    for (let n = 1; bar.scrollWidth > bar.clientWidth && n <= levels; n++) bar.dataset.fold += " " + n;
    bar.style.flexWrap = wrap;
    delete bar.dataset.measuring;
  };
  const size = new ResizeObserver(fit);
  const content = new MutationObserver(fit);
  size.observe(bar);
  content.observe(bar, { subtree: true, childList: true, characterData: true });
  void document.fonts?.ready.then(fit);
  fit();
  return () => {
    size.disconnect();
    content.disconnect();
  };
}

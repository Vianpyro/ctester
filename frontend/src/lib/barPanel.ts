export function barPanel(node: HTMLElement): { destroy(): void } {
  const bar = document.getElementById("top");
  const home = node.parentNode;
  if (bar && bar !== home) bar.appendChild(node);
  return {
    destroy() {
      node.remove();
    },
  };
}

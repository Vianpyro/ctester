// THE THREE FLOATING PANELS HANG OFF THE BAR, AND THE STYLESHEET SAYS SO.
//
// `#consentement`, `#charte` and `#identitepanneau` are each
// `position: absolute; top: 100%; right: .9rem`, and the only positioned ancestor they may
// resolve against is `#top` (`position: relative`). Rendered anywhere else, `top: 100%`
// resolves against the initial containing block -- so the panel is drawn one full viewport
// height down, off-screen, and the button that opened it looks dead. THAT IS THE BUG THIS
// EXISTS TO PREVENT, and it is not hypothetical: it shipped.
//
// WHY AN ACTION RATHER THAN WRITING THEM INSIDE `#top`. Two of the three live in the chat's
// LAZY CHUNK -- the identity form and the charter. Rendering them from the component that
// owns the bar would make the core import that chunk, which is the one thing the whole
// split exists to prevent: the anonymous visitor would download the forum. So the panel
// stays where it belongs in the component tree, and moves itself in the DOM.
//
// It is used by all three, including the one that could have been written into the bar
// directly. One mechanism and one explanation beats two of each.

/**
 * Move the element under the top bar for as long as it is mounted.
 *
 * NO BAR MEANS NO MOVE, not a crash: the element then renders where it was written, which
 * is wrong but visible -- and a panel in the wrong place is easier to notice and fix than a
 * page that failed to start.
 */
export function barPanel(node: HTMLElement): { destroy(): void } {
  const bar = document.getElementById("top");
  const home = node.parentNode;
  if (bar && bar !== home) bar.appendChild(node);
  return {
    destroy() {
      // Svelte removes the node itself; this only matters if it was never moved.
      node.remove();
    },
  };
}

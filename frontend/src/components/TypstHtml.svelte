<script lang="ts">
  import { api } from "../lib/config";
  import { authFetch } from "../lib/auth/session.svelte";
  import { prepareTypstHtml } from "../lib/typstHtml";

  interface Props {
    id: string;
    staff: boolean;
    onfail: () => void;
  }
  const { id, staff, onfail }: Props = $props();

  let html = $state("");

  $effect(() => {
    const path = "statement/" + encodeURIComponent(id) + "/statement.html";
    let cancelled = false;
    let blobs: string[] = [];
    void (async () => {
      const response = await (staff ? authFetch(path) : fetch(api(path))).catch(() => null);
      const text = response?.ok ? await response.text().catch(() => null) : null;
      if (cancelled) return;
      const ready = text === null ? null : prepareTypstHtml(text);
      if (!ready || !ready.html.trim()) {
        onfail();
        return;
      }
      blobs = ready.blobs;
      html = ready.html;
    })();
    return () => {
      cancelled = true;
      for (const url of blobs) URL.revokeObjectURL(url);
    };
  });

  function click(event: MouseEvent) {
    const button = (event.target as HTMLElement).closest("button.copy");
    const pre = button?.closest("pre");
    if (!button || !pre) return;
    const code = pre.querySelector("code")?.textContent ?? "";
    void navigator.clipboard?.writeText(code).then(() => {
      button.textContent = "Copié";
      setTimeout(() => (button.textContent = "Copier"), 1500);
    });
  }

  function inCopyBlock(event: Event): boolean {
    const target = event.target as Node | null;
    const sel = document.getSelection();
    const nodes = [target, sel?.anchorNode, sel?.focusNode];
    return nodes.some((n) => (n instanceof Element ? n : n?.parentElement)?.closest(".typ-recopier"));
  }
  const block = (event: Event) => {
    if (inCopyBlock(event)) event.preventDefault();
  };
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -- clicks are delegated to the real Copy buttons, which keyboard users reach directly -->
  <div
    class="typsthtml"
    onclick={click}
    oncopy={block}
    oncut={block}
    oncontextmenu={block}
    ondragstart={block}
  >
    {@html html}
  </div>

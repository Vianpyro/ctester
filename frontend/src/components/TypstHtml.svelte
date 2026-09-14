<script lang="ts">
  // UN ÉNONCÉ TYPST EN HTML -- l'essai, à côté des pages SVG. Voir
  // `lib/typstHtml.ts` pour ce qui est retiré et réécrit avant l'écriture.
  import { api } from "../lib/config";
  import { authFetch } from "../lib/auth/session.svelte";
  import { prepareTypstHtml } from "../lib/typstHtml";

  interface Props {
    id: string;
    staff: boolean;
    /** Le HTML n'est pas arrivé : le parent retombe sur les pages SVG. */
    onfail: () => void;
  }
  const { id, staff, onfail }: Props = $props();

  let html = $state("");

  $effect(() => {
    const chemin = "statement/" + encodeURIComponent(id) + "/statement.html";
    let annule = false;
    let blobs: string[] = [];
    void (async () => {
      const reponse = await (staff ? authFetch(chemin) : fetch(api(chemin))).catch(() => null);
      const texte = reponse?.ok ? await reponse.text().catch(() => null) : null;
      if (annule) return;
      // UN CORPS SANS CONTENU EST UN ÉCHEC AUSSI : un HTML vide afficherait
      // un panneau blanc au lieu des pages SVG qui, elles, sont là.
      const pret = texte === null ? null : prepareTypstHtml(texte);
      if (!pret || !pret.html.trim()) {
        onfail();
        return;
      }
      blobs = pret.blobs;
      html = pret.html;
    })();
    return () => {
      annule = true;
      for (const url of blobs) URL.revokeObjectURL(url);
    };
  });

  function clic(event: MouseEvent) {
    const bouton = (event.target as HTMLElement).closest("button.copier");
    const pre = bouton?.closest("pre");
    if (!bouton || !pre) return;
    const code = pre.querySelector("code")?.textContent ?? "";
    void navigator.clipboard?.writeText(code).then(() => {
      bouton.textContent = "Copié";
      setTimeout(() => (bouton.textContent = "Copier"), 1500);
    });
  }

  // UNE DISSUASION, PAS UNE PROTECTION : le texte reste dans le document. Le
  // CSS refuse la sélection, ceci refuse la copie et le menu contextuel d'une
  // sélection qui commencerait ailleurs et déborderait dessus.
  function dansRecopier(event: Event): boolean {
    const cible = event.target as Node | null;
    const sel = document.getSelection();
    const noeuds = [cible, sel?.anchorNode, sel?.focusNode];
    return noeuds.some((n) => (n instanceof Element ? n : n?.parentElement)?.closest(".typ-recopier"));
  }
  const bloquer = (event: Event) => {
    if (dansRecopier(event)) event.preventDefault();
  };
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -- le clic est délégué aux vrais <button> « Copier », que le clavier atteint déjà -->
  <div
    class="typsthtml"
    onclick={clic}
    oncopy={bloquer}
    oncut={bloquer}
    oncontextmenu={bloquer}
    ondragstart={bloquer}
  >
    {@html html}
  </div>

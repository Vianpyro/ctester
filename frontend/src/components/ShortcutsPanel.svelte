<script lang="ts">
  // L'AIDE-MÉMOIRE DES RACCOURCIS, et il existe pour une raison précise : les
  // raccourcis de cette page ne doivent JAMAIS être nécessaires. Chacun double
  // un geste faisable à la souris, donc personne n'a à les apprendre -- mais
  // celui qui arrive de CLion et tente Ctrl+/ doit pouvoir vérifier ce que la
  // page connaît, sans deviner.
  //
  // IL DIT AUSSI CE QU'ON NE PREND PAS. La moitié des lignes décrivent le
  // navigateur (Ctrl+Z, Ctrl+F) et ce qui marchait déjà (Tab, les paires). Ce
  // n'est pas du remplissage : « est-ce que Ctrl+Z marche dans cette boîte ? »
  // est la première question qu'on se pose devant un éditeur dans une page web,
  // et la seule réponse rassurante est de l'écrire.
  //
  // PAS DE `role="dialog"`, comme les trois autres panneaux de la barre : sans
  // piège à focus ni `aria-modal`, ce rôle promettrait un comportement que rien
  // ici n'implémente.

  import { barPanel } from "../lib/barPanel";
  import { ALREADY, GROUPS, HELP, NATIVE, type HelpRow } from "../lib/domain/shortcutHelp";

  interface Props {
    open: boolean;
    onClose: () => void;
  }

  let { open, onClose }: Props = $props();

  let title: HTMLHeadingElement | undefined = $state();

  $effect(() => {
    // Le focus atterrit sur le titre quand le panneau s'ouvre, comme chaque
    // écran chargé à la demande le fait déjà avec son `<h2 tabindex="-1">`.
    if (open) title?.focus();
  });

  const SECTIONS: { title: string; rows: HelpRow[] }[] = [
    ...GROUPS.map((group) => ({ title: group.title, rows: group.ids.map((id) => HELP[id]) })),
    { title: "Déjà dans l'éditeur", rows: ALREADY },
    { title: "Ceux du navigateur, intacts", rows: NATIVE },
  ];
</script>

<div id="raccourcis" hidden={!open} use:barPanel>
  <h2 bind:this={title} tabindex="-1">Raccourcis clavier</h2>
  <p class="sous">
    Aucun n'est obligatoire : tout se fait aussi à la souris. Ils sont là pour qui a
    l'habitude d'un éditeur.
  </p>

  {#each SECTIONS as section (section.title)}
    <h3>{section.title}</h3>
    <dl class="touches">
      {#each section.rows as row (row.label)}
        <dt>
          {#each row.caps as cap (cap)}<kbd>{cap}</kbd>{/each}
        </dt>
        <dd>
          {row.label}
          {#if row.note}<span class="apropos">{row.note}</span>{/if}
        </dd>
      {/each}
    </dl>
  {/each}

  <div class="row">
    <button type="button" class="nav" onclick={onClose}>Fermer</button>
  </div>
</div>

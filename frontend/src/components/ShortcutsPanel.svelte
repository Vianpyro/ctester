<script lang="ts">
  import { barPanel } from "../lib/barPanel";
  import { ALREADY, GROUPS, HELP, NATIVE, type HelpRow } from "../lib/domain/shortcutHelp";

  interface Props {
    open: boolean;
    onClose: () => void;
  }

  let { open, onClose }: Props = $props();

  let title: HTMLHeadingElement | undefined = $state();

  $effect(() => {
    if (open) title?.focus();
  });

  const SECTIONS: { title: string; rows: HelpRow[] }[] = [
    ...GROUPS.map((group) => ({ title: group.title, rows: group.ids.map((id) => HELP[id]) })),
    { title: "Déjà dans l'éditeur", rows: ALREADY },
    { title: "Ceux du navigateur, intacts", rows: NATIVE },
  ];
</script>

<div id="shortcuts" hidden={!open} use:barPanel>
  <h2 bind:this={title} tabindex="-1">Raccourcis clavier</h2>
  <p class="sub">
    Aucun n'est obligatoire : tout se fait aussi à la souris. Ils sont là pour qui a
    l'habitude d'un éditeur.
  </p>

  {#each SECTIONS as section (section.title)}
    <h3>{section.title}</h3>
    <dl class="keys">
      {#each section.rows as row (row.label)}
        <dt>
          {#each row.caps as cap (cap)}<kbd>{cap}</kbd>{/each}
        </dt>
        <dd>
          {row.label}
          {#if row.note}<span class="about">{row.note}</span>{/if}
        </dd>
      {/each}
    </dl>
  {/each}

  <div class="row">
    <button type="button" class="nav" onclick={onClose}>Fermer</button>
  </div>
</div>

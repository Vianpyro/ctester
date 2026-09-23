<script lang="ts">
  import { barPanel } from "../lib/barPanel";
  import { t, tOr } from "../lib/i18n.svelte";
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
    { title: "shortcuts.already", rows: ALREADY },
    { title: "shortcuts.native", rows: NATIVE },
  ];

  const cap = (name: string) => tOr("key." + name, name);
</script>

<div id="shortcuts" hidden={!open} use:barPanel>
  <h2 bind:this={title} tabindex="-1">{t("shortcuts.title")}</h2>
  <p class="sub">{t("shortcuts.intro")}</p>

  {#each SECTIONS as section (section.title)}
    <h3>{t(section.title)}</h3>
    <dl class="keys">
      {#each section.rows as row (row.label)}
        <dt>
          {#each row.caps as name (name)}<kbd>{cap(name)}</kbd>{/each}
        </dt>
        <dd>
          {t(row.label)}
          {#if row.note}<span class="about">{t(row.note)}</span>{/if}
        </dd>
      {/each}
    </dl>
  {/each}

  <div class="row">
    <button type="button" class="nav" onclick={onClose}>{t("shortcuts.close")}</button>
  </div>
</div>

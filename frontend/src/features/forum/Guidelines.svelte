<script lang="ts" module>  export const CHARTER_SEEN = "ctester.charter";

  // Locale keys, worded where they are shown.
  export const CHARTER = [1, 2, 3, 4, 5, 6].map((n) => `forum.charter.${n}`);
</script>

<script lang="ts">  import { barPanel } from "../../lib/barPanel";
  import { t } from "../../lib/i18n.svelte";

  interface Props {
    onAccept: () => void;
    onCancel: () => void;
  }

  const { onAccept, onCancel }: Props = $props();
</script>

<div id="charter" use:barPanel>
  <h2>{t("forum.before")}</h2>
  <ul class="rules">
    {#each CHARTER as rule}<li>{t(rule)}</li>{/each}
  </ul>
  <p>{t("forum.human")}</p>
  <div class="row">
    <button type="button" onclick={onAccept}>{t("forum.understood")}</button>
    <button type="button" class="nav" onclick={onCancel}>{t("consent.cancel")}</button>
  </div>
</div>

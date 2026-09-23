<script lang="ts">  import { barPanel } from "../lib/barPanel";
  import { profile } from "../lib/state/profile.svelte";
  import { t } from "../lib/i18n.svelte";
</script>

<div id="consent" use:barPanel hidden={!profile.consentOpen}>
  <p>{t("consent.stored")}</p>
  <p>{t("consent.forum")}</p>
  <p>{t("consent.not_a_grade")}</p>
  <div class="row">
    <button type="button" id="consentok" onclick={() => profile.startSignIn()}>
      {t("consent.continue")}
    </button>
    <button type="button" id="consentno" class="nav" onclick={() => profile.cancelConsent()}>
      {t("consent.cancel")}
    </button>
  </div>
</div>

<script lang="ts">
  import { barPanel } from "../lib/barPanel";
  import { profile } from "../lib/state/profile.svelte";
  import { t } from "../lib/i18n.svelte";

  let title: HTMLHeadingElement | undefined = $state();

  $effect(() => {
    if (profile.consentOpen) title?.focus();
  });

  function cancel() {
    profile.cancelConsent();
    document.getElementById("login")?.focus();
  }
</script>

<div id="consent" role="dialog" aria-labelledby="consenttitle" use:barPanel hidden={!profile.consentOpen}>
  <h2 id="consenttitle" tabindex="-1" bind:this={title}>{t("consent.title")}</h2>
  <p class="lead">{t("topbar.login_title")}</p>
  <p>{t("consent.stored")}</p>
  <p>{t("consent.forum")}</p>
  <p>{t("consent.not_a_grade")}</p>
  <div class="row">
    <button type="button" id="consentok" onclick={() => profile.startSignIn()}>
      {t("consent.continue")}
    </button>
    <button type="button" id="consentno" class="nav" onclick={cancel}>
      {t("consent.cancel")}
    </button>
  </div>
</div>

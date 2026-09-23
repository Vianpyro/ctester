<script lang="ts">
  import { profile } from "../lib/state/profile.svelte";
  import { t } from "../lib/i18n.svelte";
  import { session } from "../lib/auth/session.svelte";

  interface Props {
    openView: (name: "progress" | "leaderboard" | "collection" | "scratch") => void;
  }

  const { openView }: Props = $props();

  async function openIdentity() {
    profile.menuOpen = false;
    const { identity } = await import("../features/forum/identity.svelte");
    await identity.toggle();
  }

  function go(name: "leaderboard" | "collection") {
    profile.menuOpen = false;
    openView(name);
  }
</script>

{#if session.forumOffered}
  <button type="button" id="identity" class="nav" onclick={openIdentity}>{t("account.identity")}</button>
{/if}
<span class="menutitle">{t("account.optional")}</span>
<button type="button" id="leaderboard" class="nav" onclick={() => go("leaderboard")}>
  {t("leaderboard.title")}
</button>
<button type="button" id="collection" class="nav" onclick={() => go("collection")}>
  {t("account.collection")}
</button>
<span class="menutitle">{t("account.this_account")}</span>
<button type="button" id="logout" class="nav" onclick={() => profile.signOut()}>
  {t("account.sign_out")}
</button>
<button type="button" id="forget" class="nav" onclick={() => profile.deleteAccount()}>
  {t("account.delete")}
</button>

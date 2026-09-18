<script lang="ts">
  import { profile } from "../lib/state/profile.svelte";
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
  <button type="button" id="identity" class="nav" onclick={openIdentity}>Mon identité</button>
{/if}
<span class="menutitle">Facultatif</span>
<button type="button" id="leaderboard" class="nav" onclick={() => go("leaderboard")}>
  Classement
</button>
<button type="button" id="collection" class="nav" onclick={() => go("collection")}>
  Collection
</button>
<span class="menutitle">Ce compte</span>
<button type="button" id="logout" class="nav" onclick={() => profile.signOut()}>
  Se déconnecter
</button>
<button type="button" id="forget" class="nav" onclick={() => profile.deleteAccount()}>
  Supprimer mes données
</button>

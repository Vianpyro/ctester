<script lang="ts">
  import { profile } from "../lib/state/profile.svelte";
  import { session } from "../lib/auth/session.svelte";

  interface Props {
    openView: (name: "progres" | "leaderboard" | "collection" | "scratch") => void;
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
  <button type="button" id="identite" class="nav" onclick={openIdentity}>Mon identité</button>
{/if}
<span class="menutitre">Facultatif</span>
<button type="button" id="leaderboard" class="nav" onclick={() => go("leaderboard")}>
  Classement
</button>
<button type="button" id="collection" class="nav" onclick={() => go("collection")}>
  Collection
</button>
<span class="menutitre">Ce compte</span>
<button type="button" id="deconnexion" class="nav" onclick={() => profile.signOut()}>
  Se déconnecter
</button>
<button type="button" id="oublier" class="nav" onclick={() => profile.deleteAccount()}>
  Supprimer mes données
</button>

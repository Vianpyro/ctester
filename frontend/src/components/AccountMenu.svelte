<script lang="ts">
  // WHAT IS IN THE COMPTE MENU. Three buttons, and the identity form is a SHORTCUT to
  // it -- not a second form: one place, so one place where visibility can differ from
  // what the database says.

  import { profile } from "../lib/state/profile.svelte";
  import { session } from "../lib/auth/session.svelte";

  async function openIdentity() {
    profile.menuOpen = false;
    // SAME CONTRACT AS EVERY OTHER DESTINATION: the chunk comes down on the click.
    const { identity } = await import("../features/forum/identity.svelte");
    await identity.toggle();
  }
</script>

{#if session.forumOffered}
  <button type="button" id="identite" class="nav" onclick={openIdentity}>Mon identité</button>
{/if}
<button type="button" id="deconnexion" class="nav" onclick={() => profile.signOut()}>
  Se déconnecter
</button>
<button type="button" id="oublier" class="nav" onclick={() => profile.deleteAccount()}>
  Supprimer mes données
</button>

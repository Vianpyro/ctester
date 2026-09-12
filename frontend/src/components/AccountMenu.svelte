<script lang="ts">
  // CE QU'IL Y A DANS LE MENU COMPTE. Le formulaire d'identité y est un RACCOURCI
  // vers le panneau -- pas un second formulaire : un seul endroit, donc un seul
  // endroit où la visibilité peut diverger de ce que la base dit.
  //
  // ET DEPUIS QUE LA BARRE EST DESCENDUE DE CINQ DESTINATIONS À TROIS, il porte aussi
  // « Classement » et « Collection ». Les deux sont facultatives, privées, et leur nom
  // ne dit rien à quelqu'un de première session : elles occupaient deux des cinq mots
  // d'une barre où « Mes progrès », « Chat » et « Console » sont, eux, ce qu'on vient
  // faire. Elles vivent maintenant là où vivent les autres réglages du compte.
  //
  // `openView` ARRIVE EN PROP, il n'est pas importé ici : les deux écrans sont des
  // morceaux à la demande que la coquille va chercher au clic, et un import statique
  // depuis ce fichier-ci -- qui est eager -- les ferait descendre chez tout le monde,
  // y compris chez qui ne les ouvre jamais. `bundle.test.ts` monte la garde.

  import { profile } from "../lib/state/profile.svelte";
  import { session } from "../lib/auth/session.svelte";

  interface Props {
    openView: (name: "progres" | "leaderboard" | "collection" | "scratch") => void;
  }

  const { openView }: Props = $props();

  async function openIdentity() {
    profile.menuOpen = false;
    // MÊME CONTRAT QUE TOUTE AUTRE DESTINATION : le morceau arrive au clic.
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
<!-- UNE LIGNE QUI NOMME LE GROUPE, et ce n'est pas de la décoration : le résumé de ce
     menu est le NOM D'AFFICHAGE de l'étudiant, qui ne laisse pas deviner que des
     écrans vivent dedans. Sans cette ligne, « Collection » -- la seule surface de
     récompense de la page -- devient quelque chose qu'on trouve par accident. -->
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

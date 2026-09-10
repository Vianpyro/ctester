<script lang="ts">
  // WHAT SIGNING IN KEEPS, SAID BEFORE THE REDIRECT AND NOT AFTER. The sentence about
  // "Supprimer mes données" is a promise, so that button exists -- see
  // `profile.deleteAccount()` and `DELETE /moi`, which erases every table of the
  // schema.

  import { profile } from "../lib/state/profile.svelte";
</script>

<div id="consentement" hidden={!profile.consentOpen}>
  <p>
    Te connecter fait conserver, sur le serveur de ce site&nbsp;: un identifiant de
    compte opaque (ni ton nom, ni ton courriel), le code que tu écris pour chaque
    exercice, l'historique de tes tentatives et de leurs résultats, et tes préférences
    d'affichage (le thème clair ou sombre, pour le retrouver sur tes autres appareils).
  </p>
  <p>
    Si les discussions sont ouvertes sur ce site&nbsp;: les messages que tu y publies
    sont visibles des autres comptes connectés, et ils sont lus par des personnes, pas
    par un automate. Tu y apparais comme «&nbsp;Participant&nbsp;» — ni ton nom, ni un
    pseudonyme stable.
  </p>
  <p>
    Ce n'est pas une note, et rien n'est transmis à ton enseignant. Tu peux tout effacer
    quand tu veux avec «&nbsp;Supprimer mes données&nbsp;», messages compris. Sans
    connexion, la page continue de fonctionner exactement pareil.
  </p>
  <div class="row">
    <button type="button" id="consentok" onclick={() => profile.startSignIn()}>
      Continuer vers la connexion
    </button>
    <button type="button" id="consentnon" class="nav" onclick={() => profile.cancelConsent()}>
      Annuler
    </button>
  </div>
</div>

<script lang="ts" module>
  // THE CHARTER, IN ONE PLACE. It displays in the view AND before the session's first
  // post; two copies of the text would eventually contradict each other, and it is the
  // forgotten copy that would get read at the moment it matters.
  //
  // MODERATION IS HUMAN, AND THE PAGE SAYS SO. Nothing here promises a shared solution
  // would be detected automatically: it would not be. That is what makes "Signaler"
  // useful rather than decorative.

  export const CHARTER_SEEN = "ctester.charte";

  export const CHARTER = [
    "Entraide conceptuelle : une question, une idée, ce que tu observes, ce que tu as déjà essayé.",
    "Pas de solution complète, pas d'extrait de code, aucun fichier déposé.",
    "Pas de capture d'écran.",
    "Pas de lien vers une solution — un lien vers un corrigé sera masqué.",
    "Respect mutuel : on parle du problème, jamais de la personne.",
    "Tu vois passer une solution ? Signale-la plutôt que d'y répondre.",
  ];
</script>

<script lang="ts">
  import { barPanel } from "../../lib/barPanel";

  interface Props {
    onAccept: () => void;
    onCancel: () => void;
  }

  const { onAccept, onCancel }: Props = $props();
</script>

<!-- Under the bar, like the two other floating panels: see `lib/barPanel.ts`. -->
<div id="charte" use:barPanel>
  <h2>Avant de publier</h2>
  <ul class="regles">
    {#each CHARTER as rule}<li>{rule}</li>{/each}
  </ul>
  <p>
    Les messages sont lus et modérés par des personnes, pas par un automate. Un message
    qui contient une solution peut être masqué.
  </p>
  <div class="row">
    <button type="button" onclick={onAccept}>J'ai compris — publier</button>
    <button type="button" class="nav" onclick={onCancel}>Annuler</button>
  </div>
</div>

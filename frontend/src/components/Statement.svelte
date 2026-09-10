<script lang="ts">
  // THE STATEMENT, AND IT HAS THREE STATES, NOT TWO. "No statement online" and "the
  // statement has not arrived" used to display identically: the student believed it
  // was a property of the exercise, so they never retried -- when a reload would have
  // been enough. The retry is a BUTTON and not an invitation to reload the page:
  // reloading would lose the not-yet-saved code of somebody who just pasted a file.
  //
  // `textContent`, always: a statement is full of asterisks and angle brackets.

  import { exercise } from "../lib/state/exercise.svelte";

  const state = $derived(exercise.statement);
</script>

<details id="consigne" open>
  <summary class="phead">Consigne</summary>
  {#if state.kind === "loading"}
    <pre id="consignetexte" class="vide">Chargement…</pre>
  {:else if state.kind === "text"}
    <pre id="consignetexte">{state.text}</pre>
  {:else if state.kind === "none"}
    <pre id="consignetexte" class="vide">Cet exercice n'a pas de consigne en ligne. Reporte-toi à l'énoncé du TP sur Moodle : les noms de fichiers et de fonctions attendus y sont.</pre>
  {:else}
    <pre id="consignetexte" class="vide">La consigne n'a pas pu être chargée. Tu peux quand même écrire et tester : les noms de fichiers attendus, eux, sont déjà là.<button
        type="button"
        class="nav"
        onclick={() => exercise.retryStatement()}>Réessayer</button
      ></pre>
  {/if}
</details>

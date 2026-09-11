<script lang="ts">
  // THE STATEMENT, AND IT HAS THREE STATES, NOT TWO. "No statement online" and "the
  // statement has not arrived" used to display identically: the student believed it
  // was a property of the exercise, so they never retried -- when a reload would have
  // been enough. The retry is a BUTTON and not an invitation to reload the page:
  // reloading would lose the not-yet-saved code of somebody who just pasted a file.
  //
  // THE TEXT IS MARKDOWN, AND IT IS RENDERED. The files are called `statement.md` and
  // 56 of the 77 carry an indented C block; they used to be shown raw, backticks and
  // setext underlines included. `renderStatement` escapes every slice before placing
  // it between tags it writes itself, so this `{@html}` is safe for the same reason
  // `highlight()`'s output is -- see `lib/domain/statement.ts`. No `marked`, no
  // DOMPurify: those two are 74 KB and the statement is on the ANONYMOUS path.

  import { exercise } from "../lib/state/exercise.svelte";
  import { catalog } from "../lib/state/catalog.svelte";
  import { lockNote } from "../lib/domain/catalog";
  import { renderStatement } from "../lib/domain/statement";

  const state = $derived(exercise.statement);
  // ONLY A MODERATOR CAN REACH THIS STATE, so there is no role to test here:
  // `catalog.selected` reads the flat list, and a locked exercise is only in it
  // when the server said this account is staff. Said HERE, above the statement,
  // because that is where the instructor is looking when they check the render.
  const ferme = $derived(lockNote(catalog.selected));
</script>

{#if ferme}
  <p class="apercu">🔒 Invisible pour les étudiants — {ferme}.</p>
{/if}

<details id="consigne" open>
  <summary class="phead">Consigne</summary>
  {#if state.kind === "loading"}
    <pre id="consignetexte" class="vide">Chargement…</pre>
  {:else if state.kind === "text"}
    <div id="consignetexte" class="md">{@html renderStatement(state.text)}</div>
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

<style>
  /* Not a warning and not an error: a statement of fact about who can see this.
     `--wait` is already the page's "not yet" colour (the syntax checker's hints,
     the queued verdict), so it costs no new token. */
  .apercu {
    margin: 0 0 0.6rem;
    padding: 0.35rem 0.6rem;
    border: 1px solid var(--wait);
    border-radius: var(--coin);
    color: var(--wait);
    font-size: 0.9em;
  }
</style>

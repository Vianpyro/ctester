<script lang="ts">
  import { exercise } from "../lib/state/exercise.svelte";
  import { catalog } from "../lib/state/catalog.svelte";
  import { lockNote } from "../lib/domain/catalog";
  import { renderStatement } from "../lib/domain/statement";
  import TypstStatement from "./TypstStatement.svelte";
  import TypstHtml from "./TypstHtml.svelte";

  const current = $derived(exercise.statement);
  const closed = $derived(lockNote(catalog.selected));

  let htmlFailedFor = $state<string | null>(null);
</script>

<details id="statement" open>
  <summary class="phead">Consigne</summary>
  {#if closed}
    <p class="preview">🔒 Invisible pour les étudiants — {closed}.</p>
  {/if}
  {#if current.kind === "loading"}
    <pre id="statementtext" class="empty">Chargement…</pre>
  {:else if current.kind === "text"}
    <div id="statementtext" class="md">{@html renderStatement(current.text)}</div>
  {:else if current.kind === "typst" && current.html && htmlFailedFor !== current.id}
    {@const id = current.id}
    <div id="statementtext" class="md">
      <TypstHtml {id} staff={current.staff} onfail={() => (htmlFailedFor = id)} />
    </div>
  {:else if current.kind === "typst"}
    <div id="statementtext" class="typstpages">
      <TypstStatement
        id={current.id}
        pages={current.pages}
        staff={current.staff}
        title={current.title}
      />
    </div>
  {:else if current.kind === "none"}
    <pre id="statementtext" class="empty">Cet exercice n'a pas de consigne en ligne. Reporte-toi à l'énoncé remis par ton enseignant : les noms de fichiers et de fonctions attendus y sont.</pre>
  {:else}
    <pre id="statementtext" class="empty">La consigne n'a pas pu être chargée. Tu peux quand même écrire et tester : les noms de fichiers attendus, eux, sont déjà là.<button
        type="button"
        class="nav"
        onclick={() => exercise.retryStatement()}>Réessayer</button
      ></pre>
  {/if}
</details>

<style>
  .preview {
    margin: 0.6rem 0.6rem 0;
    padding: 0.35rem 0.6rem;
    border: 1px solid var(--wait);
    border-radius: var(--coin);
    color: var(--wait);
    font-size: 0.9em;
  }
</style>

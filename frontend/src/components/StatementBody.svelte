<script lang="ts">
  import { exercise, type StatementState } from "../lib/state/exercise.svelte";
  import { renderStatement } from "../lib/domain/statement";
  import TypstStatement from "./TypstStatement.svelte";
  import TypstHtml from "./TypstHtml.svelte";

  const { current }: { current: StatementState } = $props();

  let htmlFailedFor = $state<string | null>(null);
</script>

{#if current.kind === "loading"}
  <pre class="statementtext empty">Chargement…</pre>
{:else if current.kind === "text"}
  <div class="statementtext md">{@html renderStatement(current.text)}</div>
{:else if current.kind === "typst" && current.html && htmlFailedFor !== current.id}
  {@const id = current.id}
  <div class="statementtext md">
    <TypstHtml {id} staff={current.staff} onfail={() => (htmlFailedFor = id)} />
  </div>
{:else if current.kind === "typst"}
  <div class="statementtext typstpages">
    <TypstStatement
      id={current.id}
      pages={current.pages}
      staff={current.staff}
      title={current.title}
    />
  </div>
{:else if current.kind === "none"}
  <pre class="statementtext empty">Cet exercice n'a pas de consigne en ligne. Reporte-toi à l'énoncé du TP sur Moodle : les noms de fichiers et de fonctions attendus y sont.</pre>
{:else}
  <pre class="statementtext empty">La consigne n'a pas pu être chargée. Tu peux quand même écrire et tester : les noms de fichiers attendus, eux, sont déjà là.<button
      type="button"
      class="nav"
      onclick={() => exercise.retryStatement()}>Réessayer</button
    ></pre>
{/if}

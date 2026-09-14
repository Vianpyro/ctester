<script lang="ts">
  import { exercise } from "../lib/state/exercise.svelte";
  import { catalog } from "../lib/state/catalog.svelte";
  import { lockNote } from "../lib/domain/catalog";
  import { renderStatement } from "../lib/domain/statement";
  import TypstStatement from "./TypstStatement.svelte";
  import TypstHtml from "./TypstHtml.svelte";

  const etat = $derived(exercise.statement);
  const ferme = $derived(lockNote(catalog.selected));

  let htmlRate = $state<string | null>(null);
</script>

<details id="consigne" open>
  <summary class="phead">Consigne</summary>
  {#if ferme}
    <p class="apercu">🔒 Invisible pour les étudiants — {ferme}.</p>
  {/if}
  {#if etat.kind === "loading"}
    <pre id="consignetexte" class="vide">Chargement…</pre>
  {:else if etat.kind === "text"}
    <div id="consignetexte" class="md">{@html renderStatement(etat.text)}</div>
  {:else if etat.kind === "typst" && etat.html && htmlRate !== etat.id}
    {@const id = etat.id}
    <div id="consignetexte" class="md">
      <TypstHtml {id} staff={etat.staff} onfail={() => (htmlRate = id)} />
    </div>
  {:else if etat.kind === "typst"}
    <div id="consignetexte" class="typstpages">
      <TypstStatement
        id={etat.id}
        pages={etat.pages}
        staff={etat.staff}
        title={etat.title}
      />
    </div>
  {:else if etat.kind === "none"}
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
  .apercu {
    margin: 0.6rem 0.6rem 0;
    padding: 0.35rem 0.6rem;
    border: 1px solid var(--wait);
    border-radius: var(--coin);
    color: var(--wait);
    font-size: 0.9em;
  }
</style>

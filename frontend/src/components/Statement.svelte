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
  //
  // AND SINCE A STATEMENT CAN ALSO BE TYPST, there is a fifth branch. It is a
  // FORMAT, not a fetch state: the pages were rendered to SVG at publish time
  // and arrive as images. Nothing about the Markdown path changed -- the 77
  // existing statements take exactly the branch they always took, and
  // `statement.test.ts` proves it.

  import { exercise } from "../lib/state/exercise.svelte";
  import { catalog } from "../lib/state/catalog.svelte";
  import { lockNote } from "../lib/domain/catalog";
  import { renderStatement } from "../lib/domain/statement";
  import TypstStatement from "./TypstStatement.svelte";
  import TypstHtml from "./TypstHtml.svelte";

  const etat = $derived(exercise.statement);
  // ONLY A MODERATOR CAN REACH THIS STATE, so there is no role to test here:
  // `catalog.selected` reads the flat list, and a locked exercise is only in it
  // when the server said this account is staff. Said HERE, above the statement,
  // because that is where the instructor is looking when they check the render.
  const ferme = $derived(lockNote(catalog.selected));

  // SVG OU HTML, POUR UN ÉNONCÉ TYPST QUI A LES DEUX. Un réglage d'affichage
  // par appareil : `localStorage`, et l'échec de celui-ci ne change que le
  // souvenir, jamais l'affichage. Le SVG reste le défaut pendant l'essai.
  const CLE = "ctester.typst.vue";
  let vue = $state<"svg" | "html">(
    (() => {
      try {
        return localStorage.getItem(CLE) === "html" ? "html" : "svg";
      } catch {
        return "svg";
      }
    })(),
  );
  function choisir(v: "svg" | "html") {
    vue = v;
    try {
      localStorage.setItem(CLE, v);
    } catch {
      /* le choix vaut pour cette visite */
    }
  }
</script>

<details id="consigne" open>
  <summary class="phead">Consigne</summary>
  <!-- DEDANS, PAS À CÔTÉ. `#travail` est une grille dont les enfants DIRECTS sont
       les colonnes : un second élément racine ici prend la première colonne et
       pousse tout le reste d'un cran. Même piège que `#chatdock`. -->
  {#if ferme}
    <p class="apercu">🔒 Invisible pour les étudiants — {ferme}.</p>
  {/if}
  {#if etat.kind === "loading"}
    <pre id="consignetexte" class="vide">Chargement…</pre>
  {:else if etat.kind === "text"}
    <div id="consignetexte" class="md">{@html renderStatement(etat.text)}</div>
  {:else if etat.kind === "typst" && etat.html && vue === "html"}
    {@render bascule()}
    <div id="consignetexte" class="md">
      <TypstHtml id={etat.id} staff={etat.staff} />
    </div>
  {:else if etat.kind === "typst"}
    {#if etat.html}{@render bascule()}{/if}
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

{#snippet bascule()}
  <div class="bascule" role="group" aria-label="Affichage de la consigne">
    <button type="button" class="nav" aria-pressed={vue === "svg"} onclick={() => choisir("svg")}>SVG</button>
    <button type="button" class="nav" aria-pressed={vue === "html"} onclick={() => choisir("html")}>HTML</button>
  </div>
{/snippet}

<style>
  .bascule {
    display: flex;
    gap: 0.3rem;
    justify-content: flex-end;
    margin: 0.4rem 0.6rem 0;
  }
  .bascule [aria-pressed="true"] {
    border-color: var(--ink);
    color: var(--ink);
  }
  /* Not a warning and not an error: a statement of fact about who can see this.
     `--wait` is already the page's "not yet" colour (the syntax checker's hints,
     the queued verdict), so it costs no new token. */
  .apercu {
    margin: 0.6rem 0.6rem 0;
    padding: 0.35rem 0.6rem;
    border: 1px solid var(--wait);
    border-radius: var(--coin);
    color: var(--wait);
    font-size: 0.9em;
  }
</style>

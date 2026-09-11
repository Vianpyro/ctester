<script lang="ts">
  // THE LAB STRIP AND THE LINE ABOVE IT.
  //
  // THE STRIP IS THE NAVIGATION A STUDENT DOES TWENTY TIMES A SESSION -- going from
  // ex.2 to ex.3 of the same lab -- and it used to require opening a menu that covers
  // the screen for a target one step away. It DOES NOT REPLACE THE MENU: that one
  // stays the switch between collections, which is rare.
  //
  // FEWER THAN TWO EXERCISES, NO STRIP: a strip of one item helps nothing and steals
  // a line from the statement.
  //
  // LOCKED EXERCISES ARE IN IT TOO, with their date: making them vanish the day
  // before they open looked like an outage, which is exactly what the menu's lock
  // exists to avoid.

  import { catalog } from "../lib/state/catalog.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { statuses } from "../lib/state/statuses.svelte";
  import { isBonus, lockNote, stripLabel, tileState } from "../lib/domain/catalog";
  import { STATUS_MARK, plural } from "../lib/domain/labels";

  interface Props {
    /** Opens the exercise menu -- one function, so three entry points cannot end up
     *  doing three slightly different things. */
    openMenu: (focusSearch?: boolean) => void;
  }

  const { openMenu }: Props = $props();

  const here = $derived(catalog.selected);
  const neighbors = $derived(catalog.neighbors);
  const shown = $derived(neighbors.length >= 2);
  const solved = $derived(neighbors.filter((e) => statuses.of(e.id) === "solved").length);

  /**
   * THE FIVE LEGENDS, in the strip's own order. Written once and rendered once: two
   * copies would drift, and the copy that drifted would be the one explaining a
   * border that no longer exists. A border nobody can name is decoration.
   */
  const LEGEND: [string, string][] = [
    ["reussi", "fond bleuté = réussi"],
    ["courant", "trait épais = ouvert dans l'éditeur"],
    ["verif", "trait bleu = vérification (compte pour la maîtrise)"],
    ["afaire", "trait simple = à faire"],
    ["bonus", "tirets = bonus facultatif"],
  ];
</script>

{#if shown && here}
  <!-- WHERE I AM AND WHAT IS LEFT. One line: the lab, how many exercises it holds
       and how many are solved -- the last of which used to require opening
       "Mes progrès". ZERO SOLVED SAYS SO rather than disappearing: "0 réussi" is a
       starting point, an absent line is a page that forgot to load. -->
  <div id="labcontext">
    <span class="labo">{here.group}</span>
    <span class="tag">{plural(neighbors.length, "exercice")}</span>
    <span class={"tag" + (solved ? " accent" : "")}>
      {solved} réussi{solved > 1 ? "s" : ""}
    </span>
    <span class="grow"></span>
    <!-- IT OPENS THE MENU THAT ALREADY EXISTS. A second collection picker would be a
         second place where "which labs are there" is answered, and the two would
         eventually disagree about a lock. -->
    <button type="button" class="nav" onclick={() => openMenu()}>Changer de labo</button>
    <button type="button" class="nav" onclick={() => openMenu(true)}>
      Rechercher<span class="shortcut">Ctrl+K</span>
    </button>
  </div>
{/if}

<nav id="bandelabo" aria-label="Exercices de ce laboratoire" hidden={!shown}>
  {#if shown}
    {#each neighbors as ex (ex.id)}
      {@const note = lockNote(ex)}
      <!-- SAME RULE AS THE MENU: the lock and its date are shown to everyone, they
           only BLOCK a student. A moderator navigates the whole lab, locked
           exercises included, which is how one checks a lab before the class. -->
      {@const bloque = !!note && !catalog.staff}
      {@const state = tileState(ex, !!note, statuses.byExercise)}
      {@const current = ex.id === catalog.selectedId}
      {@const said = (note || state.word) + (current ? ", ouvert dans l'éditeur" : "")}
      <!-- `aria-disabled` AND NOT `disabled`: a `disabled` button drops out of the
           tab order, and the opening date is the whole reason the tile is still
           displayed. Reachable, announced as unavailable, no listener.
           `aria-current` RATHER THAN A COLOUR: that is what says "you are here" to a
           screen reader, and `courant` means nothing to anyone else. -->
      <button
        type="button"
        class={"tile " + (isBonus(ex) ? "bonus" : state.cls) + (current ? " courant" : "")}
        title={ex.short + " — " + said}
        aria-disabled={bloque ? "true" : undefined}
        aria-current={current ? "true" : undefined}
        onclick={() => {
          if (!bloque && !current) exercise.open(ex.id);
        }}
      >
        {stripLabel(ex)}
        <span class="horsecran"> — {said}</span>
        {#if statuses.of(ex.id)}
          <!-- THE SIGN IN ADDITION TO THE WORD, never instead of it. -->
          <i class="marque">{STATUS_MARK[statuses.of(ex.id)!] ?? ""}</i>
        {/if}
        {#if note}<span class="cadenas">🔒</span>{/if}
      </button>
    {/each}
  {/if}
</nav>

<div id="striplegend" hidden={!shown}>
  {#if shown}
    <span class="quoi">Légende :</span>
    {#each LEGEND as [cls, text]}
      <span class="item"><i class={"tile " + cls}></i><span>{text}</span></span>
    {/each}
  {/if}
</div>

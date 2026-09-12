<script lang="ts">
  // LA BANDE DU LABO, ET C'EST MAINTENANT LA SEULE BANDE.
  //
  // C'est la navigation qu'un étudiant fait vingt fois par séance -- aller de ex.2 à
  // ex.3 du même labo -- et elle demandait autrefois d'ouvrir un menu qui couvre
  // l'écran pour une cible située à un pas. ELLE NE REMPLACE PAS LE MENU : celui-ci
  // reste le passage d'une collection à l'autre, ce qui est rare.
  //
  // MOINS DE DEUX EXERCICES, PAS DE BANDE : une bande d'un seul élément n'aide
  // personne et vole une ligne à la consigne.
  //
  // LES EXERCICES VERROUILLÉS Y SONT AUSSI, avec leur date : les faire disparaître la
  // veille de leur ouverture ressemblait à une panne.
  //
  // ─────────────────────────────────────────────────────────────────────────────
  // CE QUI A FONDU ICI, ET POURQUOI. Il y avait TROIS bandes empilées -- `#labcontext`
  // (le nom du labo, deux décomptes, deux boutons), la bande elle-même, et
  // `#striplegend` (cinq items de légende). Sur un 13", avec `#now` au-dessus et
  // l'en-tête de l'éditeur en dessous, ça faisait ~150 px de chrome avant la première
  // ligne de code, et l'éditeur tombait à ~185 px.
  //
  // * `#labcontext` a disparu : son nom de labo était DÉJÀ dans `#now` (« TP2 : ex.1 »),
  //   et ses deux boutons posaient deux fois la même question -- « Changer de labo » et
  //   « Rechercher » ouvrent le même menu. Un seul bouton, en fin de bande.
  // * `#striplegend` A DISPARU, ÉLÉMENT COMPRIS, et c'est le vrai changement : une
  //   interface qui a besoin d'une légende est une interface ratée. Cinq styles de
  //   bordure à mémoriser, en permanence à l'écran, pour lire une rangée de boutons.
  //   Ce qui les remplace se lit sans clé : `✓` et fond teinté = réussi, `🔒` + date =
  //   verrouillé, bordure épaisse = ouvert ici. Restaient `bonus` et `verif`, qui ne
  //   sont pas des états mais des CATÉGORIES, et rares : elles portent maintenant leur
  //   MOT sur la tuile. C'est ce mot qui rend la suppression possible plutôt que d'en
  //   faire une perte.

  import { catalog } from "../lib/state/catalog.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { statuses } from "../lib/state/statuses.svelte";
  import { lockNote, stripLabel, tileState } from "../lib/domain/catalog";
  import { STATUS_MARK, plural } from "../lib/domain/labels";

  interface Props {
    /** Ouvre le menu des exercices -- une seule fonction, pour que deux points
     *  d'entrée ne finissent pas par faire deux choses légèrement différentes. */
    openMenu: (focusSearch?: boolean) => void;
  }

  const { openMenu }: Props = $props();

  const neighbors = $derived(catalog.neighbors);
  const shown = $derived(neighbors.length >= 2);
  const solved = $derived(neighbors.filter((e) => statuses.of(e.id) === "solved").length);
</script>

<!-- `aria-label` RÉÉCRIT : la bande ne porte plus seulement des exercices depuis que
     le bouton du catalogue y a fondu, et un libellé qui ment à un lecteur d'écran est
     pire qu'un libellé absent. -->
<nav id="bandelabo" aria-label="Exercices de ce laboratoire, et accès au catalogue" hidden={!shown}>
  {#if shown}
    {#each neighbors as ex (ex.id)}
      {@const note = lockNote(ex)}
      <!-- MÊME RÈGLE QUE LE MENU : le cadenas et sa date sont montrés à tout le monde,
           ils ne BLOQUENT qu'un étudiant. Un modérateur navigue tout le labo, exercices
           verrouillés compris -- c'est comme ça qu'on vérifie un labo avant le cours. -->
      {@const bloque = !!note && !catalog.staff}
      {@const state = tileState(ex, !!note, statuses.byExercise)}
      {@const current = ex.id === catalog.selectedId}
      <!-- LE MOT VOYAGE AVEC LA BORDURE, et c'est ce qui a permis de supprimer la
           légende. Il était déjà dans le `title` et dans le texte hors écran ; il est
           maintenant aussi VISIBLE pour les deux catégories qu'aucun symbole ne dit. -->
      {@const said =
        (note || state.word) +
        (ex.bonus ? ", bonus facultatif" : "") +
        (current ? ", ouvert dans l'éditeur" : "")}
      <!-- `aria-disabled` ET PAS `disabled` : un bouton `disabled` sort de l'ordre de
           tabulation, et la date d'ouverture est toute la raison pour laquelle la tuile
           est encore affichée. Atteignable, annoncée indisponible, sans écouteur.
           `aria-current` PLUTÔT QU'UNE COULEUR : c'est ce qui dit « tu es ici » à un
           lecteur d'écran, et `courant` ne veut rien dire pour personne d'autre.
           TROIS AXES, TROIS CLASSES, et `bonus` est le drapeau du catalogue -- jamais un
           mot lu dans le titre. Il se SUPERPOSE comme `courant` au lieu de remplacer la
           classe de progression : un bonus réussi gardait ses tirets et perdait son fond
           teinté, exactement le repli que `tileState` existe pour éviter. Aucun des trois
           ne pose la même propriété. -->
      <button
        type="button"
        class={"tile " + state.cls + (ex.bonus ? " bonus" : "") + (current ? " courant" : "")}
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
          <!-- LE SIGNE EN PLUS DU MOT, jamais à sa place. -->
          <i class="marque">{STATUS_MARK[statuses.of(ex.id)!] ?? ""}</i>
        {/if}
        <!-- LES DEUX SEULES CATÉGORIES QUI DEMANDAIENT UNE LÉGENDE, écrites. Elles
             sont rares -- c'est ce qui rend le mot abordable en place : un labo
             ordinaire n'en porte aucune. -->
        {#if ex.verification}<i class="quoi">vérif</i>{/if}
        {#if ex.bonus}<i class="quoi">bonus</i>{/if}
        {#if note}<span class="cadenas">🔒</span>{/if}
      </button>
    {/each}

    <span class="grow"></span>
    <!-- LES DEUX DÉCOMPTES, VENUS DE `#labcontext` : « combien il en reste » se lisait
         une bande plus haut, et c'est la question qu'on se pose EN REGARDANT la bande.
         ZÉRO RÉUSSI LE DIT plutôt que de disparaître : « 0 réussi » est un point de
         départ, une ligne absente est une page qui a oublié de charger. -->
    <span class="tag">{plural(neighbors.length, "exercice")}</span>
    <span class={"tag" + (solved ? " accent" : "")}>
      {solved} réussi{solved > 1 ? "s" : ""}
    </span>
    <!-- UN SEUL BOUTON LÀ OÙ IL Y EN AVAIT DEUX. « Changer de labo » et « Rechercher »
         ouvraient le MÊME menu : deux mots à apprendre pour une porte. Il ouvre sur le
         champ de filtre, qui sert les deux intentions.
         `class="nav"` ET PAS `tile` : ce n'est pas un exercice, et un test de la bande
         compte les `.tile`. -->
    <button type="button" class="nav" onclick={() => openMenu(true)}>
      Tous les exercices<span class="shortcut">Ctrl+K</span>
    </button>
  {/if}
</nav>

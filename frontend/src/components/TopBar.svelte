<script lang="ts">
  // THE BAR. The exercise menu, the two step buttons, the destinations, the theme, and
  // the account plate.
  //
  // EVERY DESTINATION BUTTON IS GATED BY THE SERVER, and by being signed in. Without
  // either the button does not exist, so its chunk is NEVER requested -- that is what
  // makes "the anonymous path downloads nothing account-related" true rather than
  // aspirational. A deployment with no configured moderator does not open a channel
  // nobody rereads.

  import { catalog } from "../lib/state/catalog.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { presence } from "../lib/state/presence.svelte";
  import { profile } from "../lib/state/profile.svelte";
  import { session } from "../lib/auth/session.svelte";
  import { theme } from "../lib/state/theme.svelte";
  import { view } from "../lib/state/view.svelte";
  import { initialsOf } from "../lib/domain/labels";
  import ExerciseMenu from "./ExerciseMenu.svelte";
  import AccountMenu from "./AccountMenu.svelte";

  interface Props {
    menuOpen: boolean;
    focusSearch: boolean;
    onMenu: (open: boolean, focusSearch?: boolean) => void;
    /** Each destination is a lazy chunk; the shell owns the loading. */
    openView: (name: "progres" | "leaderboard" | "collection" | "scratch") => void;
    openChat: () => void;
    helpOpen: boolean;
    openHelp: () => void;
  }

  const { menuOpen, focusSearch, onMenu, openView, openChat, helpOpen, openHelp }: Props = $props();

  const signedIn = $derived(session.signedIn);
  const plate = $derived(profile.plate);
  const light = $derived(theme.current === "light");

  const step = (by: number) => {
    const target = catalog.step(by);
    if (target) exercise.open(target.id);
  };
  const index = $derived(catalog.catalog.findIndex((t) => t.id === catalog.selectedId));
</script>

<div id="top">
  <!-- LE TITRE RAMÈNE À L'EXERCICE, et c'est le geste que tout le monde essaie déjà :
       cliquer le nom du site pour rentrer. Il n'y avait aucun retour depuis « Mes
       progrès » ou le classement sauf recliquer le bouton par lequel on était venu --
       c'est-à-dire se souvenir d'où on venait, ce qui est exactement ce qu'on ne fait
       pas quand on s'est perdu.
       LE COMPTEUR DE PRÉSENCE RESTE DEHORS : c'est une information qui change toute
       seule, pas une commande, et l'avaler dans la cible de clic ferait un bouton dont
       le libellé bouge. -->
  <h1>
    <button
      type="button"
      id="accueil"
      title="Revenir à l'exercice"
      onclick={() => view.show("")}
    >
      TCH009<span class="tagline">Tester mon code</span>
    </button>
  </h1>
  <!-- A FAILURE OF THE COUNTER IS INVISIBLE: it stays hidden. It must never get in
       the way of an exercise. -->
  <span id="live" class="tagline" aria-live="polite" hidden={presence.count === null}>
    {presence.label}
  </span>
  <span class="sep"></span>

  <ExerciseMenu open={menuOpen} {focusSearch} onOpenChange={(o) => onMenu(o)} />

  <span class="field">
    <button
      type="button"
      id="prev"
      class="nav"
      aria-label="Exercice précédent"
      title="Exercice précédent"
      disabled={index <= 0}
      onclick={() => step(-1)}>‹</button
    >
    <button
      type="button"
      id="next"
      class="nav"
      aria-label="Exercice suivant"
      title="Exercice suivant"
      disabled={index < 0 || index >= catalog.catalog.length - 1}
      onclick={() => step(1)}>›</button
    >
  </span>
  <span class="grow"></span>

  <span class="groupe">
    {#if signedIn}
      <button type="button" id="mesprogres" class="nav" onclick={() => openView("progres")}>
        {view.label("progres", "Mes progrès")}
      </button>
      {#if session.forumOffered}
        <!-- THE BUTTON TOGGLES THE DOCK, not a fifth screen. The wide view (search,
             permalinks, the moderation door) opens FROM the dock, by "⤢": two buttons
             in the bar for two sizes of the same thing were two words to learn for one
             idea. -->
        <button type="button" id="discussions" class="nav" onclick={openChat}>
          {view.current === "forum" || view.current === "moderation"
            ? "Retour à l'exercice"
            : "Chat"}
        </button>
      {/if}
      <!-- « CLASSEMENT » ET « COLLECTION » SONT DESCENDUS DANS LE MENU COMPTE, et
           c'est la moitié la plus visible de l'allègement de cette barre. Les deux
           sont facultatives, privées, et leur nom ne dit rien à quelqu'un de
           première session -- elles prenaient deux des cinq mots d'une barre où
           « Mes progrès », « Chat » et « Console » sont ce qu'on vient faire. Leurs
           BOUTONS n'ont jamais eu besoin que d'un compte, ce qui reste vrai : le
           menu Compte est lui aussi derrière `signedIn`, et l'écran du classement
           reste celui qui explique ce que s'y inscrire veut dire. -->
      {#if session.scratchOffered}
        <button type="button" id="scratch" class="nav" onclick={() => openView("scratch")}>
          {view.label("scratch", "Console")}
        </button>
      {/if}
    {/if}
  </span>
  <span class="sep"></span>

  <!-- LE SEUL ENDROIT QUI ANNONCE LES RACCOURCIS, avec la touche écrite dessus --
       le motif de `LabStrip`. Un lot de raccourcis que personne ne découvre est un
       lot de raccourcis qui n'existe pas. -->
  <button
    type="button"
    id="raccourcisbouton"
    class="nav"
    aria-expanded={helpOpen}
    aria-controls="raccourcis"
    title="Les raccourcis clavier de la page"
    onclick={openHelp}
  >
    Raccourcis<span class="shortcut">F1</span>
  </button>
  <button
    type="button"
    id="theme"
    class="nav"
    title={light ? "Passer au thème sombre" : "Passer au thème clair"}
    aria-label={light ? "Passer au thème sombre" : "Passer au thème clair"}
    onclick={() => theme.toggle(signedIn)}>{light ? "☾" : "☀"}</button
  >

  {#if !signedIn && session.oidcOffered}
    <!-- "Se connecter" STAYS OUTSIDE THE MENU: burying the entry in a menu makes it
         disappear. -->
    <button type="button" id="connexion" class="nav" onclick={() => profile.askConsent()}>
      Se connecter
    </button>
  {/if}

  {#if signedIn}
    <!-- THE PLATE, and it is what others see in the discussions. Initials, the chosen
         name, the group -- all three from what the account actually chose, never from
         a token claim. Empty until a name is chosen: "Compte" is the fallback, not a
         placeholder identity. -->
    <details class="menu" id="menucompte" bind:open={profile.menuOpen}>
      <summary class="nav plate" id="plate">
        <span class="initials" id="initials" aria-hidden="true">
          {initialsOf(plate?.display_name ?? "")}
        </span>
        <span id="whoami">{plate?.display_name || "Compte"}</span>
        {#if plate?.group_number}
          <span class="groupe" id="mygroup">
            g.{String(plate.group_number).padStart(2, "0")}
          </span>
        {/if}
      </summary>
      <div class="menupanneau">
        <span id="moi">connecté</span>
        <AccountMenu {openView} />
      </div>
    </details>
  {/if}
</div>

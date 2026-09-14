<script lang="ts">
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
  <span class="tagline credit">par <a href="https://www.linkedin.com/in/vianney-veremme-1b88a5177" target="_blank">Vianney Veremme</a></span>
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
        <button type="button" id="discussions" class="nav" onclick={openChat}>
          {view.current === "forum" || view.current === "moderation"
            ? "Retour à l'exercice"
            : "Chat"}
        </button>
      {/if}
      {#if session.scratchOffered}
        <button type="button" id="scratch" class="nav" onclick={() => openView("scratch")}>
          {view.label("scratch", "Console")}
        </button>
      {/if}
    {/if}
  </span>
  <span class="sep"></span>

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
    <button type="button" id="connexion" class="nav" onclick={() => profile.askConsent()}>
      Se connecter
    </button>
  {/if}

  {#if signedIn}
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

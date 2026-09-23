<script lang="ts">
  import { TITLE } from "../lib/config";
  import { i18n, languageName, LANGUAGES, t } from "../lib/i18n.svelte";
  import { savePreferences } from "../lib/api/account";
  import { catalog } from "../lib/state/catalog.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { presence } from "../lib/state/presence.svelte";
  import { profile } from "../lib/state/profile.svelte";
  import { session } from "../lib/auth/session.svelte";
  import { dock } from "../lib/state/dock.svelte";
  import { theme } from "../lib/state/theme.svelte";
  import { view } from "../lib/state/view.svelte";
  import { initialsOf } from "../lib/domain/labels";
  import ExerciseMenu from "./ExerciseMenu.svelte";
  import AccountMenu from "./AccountMenu.svelte";

  interface Props {
    menuOpen: boolean;
    focusSearch: boolean;
    onMenu: (open: boolean, focusSearch?: boolean) => void;
    openView: (name: "progress" | "leaderboard" | "collection" | "scratch") => void;
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

  $effect(() => {
    document.title = TITLE + " — " + t("app.tagline");
  });

  const chooseLanguage = async (lang: string) => {
    if ((await i18n.choose(lang)) && signedIn) void savePreferences({ lang });
  };
</script>

<div id="top">
  <h1>
    <button
      type="button"
      id="home"
      title={t("topbar.home")}
      onclick={() => view.show("")}
    >
      {TITLE}<span class="tagline">{t("app.tagline")}</span>
    </button>
  </h1>
  <span class="tagline credit">{t("topbar.by")} <a href="https://www.linkedin.com/in/vianney-veremme-1b88a5177" target="_blank">Vianney Veremme</a></span>
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
      aria-label={t("topbar.prev")}
      title={t("topbar.prev")}
      disabled={index <= 0}
      onclick={() => step(-1)}>‹</button
    >
    <button
      type="button"
      id="next"
      class="nav"
      aria-label={t("topbar.next")}
      title={t("topbar.next")}
      disabled={index < 0 || index >= catalog.catalog.length - 1}
      onclick={() => step(1)}>›</button
    >
  </span>
  <span class="grow"></span>

  <span class="group">
    {#if signedIn}
      <button type="button" id="myprogress" class="nav" onclick={() => openView("progress")}>
        {view.label("progress", t("topbar.progress"))}
      </button>
      {#if session.forumOffered}
        <button type="button" id="discussions" class="nav" onclick={openChat}>
          {view.current === "forum" || view.current === "moderation"
            ? t("view.back")
            : t("topbar.chat")}
          {#if dock.unread}<span class="pill" aria-label={t("topbar.unread")}></span>{/if}
        </button>
      {/if}
      {#if session.scratchOffered}
        <button type="button" id="scratch" class="nav" onclick={() => openView("scratch")}>
          {view.label("scratch", t("topbar.console"))}
        </button>
      {/if}
    {/if}
  </span>
  <span class="sep"></span>

  <button
    type="button"
    id="shortcutsbutton"
    class="nav"
    aria-expanded={helpOpen}
    aria-controls="shortcuts"
    title={t("topbar.shortcuts_title")}
    onclick={openHelp}
  >
    {t("topbar.shortcuts")}<span class="shortcut">F1</span>
  </button>
  <button
    type="button"
    id="theme"
    class="nav"
    title={light ? t("topbar.to_dark") : t("topbar.to_light")}
    aria-label={light ? t("topbar.to_dark") : t("topbar.to_light")}
    onclick={() => theme.toggle(signedIn)}>{light ? "☾" : "☀"}</button
  >
  {#if LANGUAGES.length > 1}
    <select
      id="language"
      class="nav"
      aria-label={t("topbar.language")}
      title={t("topbar.language")}
      value={i18n.lang}
      onchange={(e) => chooseLanguage(e.currentTarget.value)}
    >
      {#each LANGUAGES as lang (lang)}
        <option value={lang}>{languageName(lang)}</option>
      {/each}
    </select>
  {/if}

  {#if !signedIn && session.oidcOffered}
    <button
      type="button"
      id="login"
      class="nav"
      title={t("topbar.login_title")}
      onclick={() => profile.askConsent()}
    >
      {t("topbar.login")}
    </button>
  {/if}

  {#if signedIn}
    <details class="menu" id="accountmenu" bind:open={profile.menuOpen}>
      <summary class="nav plate" id="plate">
        <span class="initials" id="initials" aria-hidden="true">
          {initialsOf(plate?.display_name ?? "")}
        </span>
        <span id="whoami">{plate?.display_name || t("topbar.account")}</span>
        {#if plate?.group_number}
          <span class="group" id="mygroup">
            g.{String(plate.group_number).padStart(2, "0")}
          </span>
        {/if}
      </summary>
      <div class="menupanel">
        <span id="me">{t("topbar.signed_in")}</span>
        <AccountMenu {openView} />
      </div>
    </details>
  {/if}
</div>

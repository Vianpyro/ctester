<script lang="ts">
  import { onMount, type Component } from "svelte";
  import { captureAccessKey, sessionKey } from "./lib/state/accesskey";
  import { t } from "./lib/i18n.svelte";
  import { catalog } from "./lib/state/catalog.svelte";
  import { dock } from "./lib/state/dock.svelte";
  import { lastExercise, exercise } from "./lib/state/exercise.svelte";
  import { maintenance } from "./lib/state/maintenance.svelte";
  import { presence } from "./lib/state/presence.svelte";
  import { profile } from "./lib/state/profile.svelte";
  import { statuses } from "./lib/state/statuses.svelte";
  import { system } from "./lib/state/system.svelte";
  import { theme } from "./lib/state/theme.svelte";
  import { view } from "./lib/state/view.svelte";
  import { runTest } from "./lib/state/run";
  import { drafts } from "./lib/state/drafts.svelte";
  import { editor } from "./lib/state/editor.svelte";
  import { matchShortcut } from "./lib/domain/shortcuts";
  import { fetchDeployment } from "./lib/api/public";
  import type { Deployment } from "./lib/api/types";
  import { RETURN_KEY } from "./lib/auth/keys";
  import { ensureValid, session, whenSessionLost } from "./lib/auth/session.svelte";
  import { sessionGet } from "./lib/storage";
  import { expectedOf } from "./lib/domain/labels";

  import ActionBar from "./components/ActionBar.svelte";
  import CodeEditor from "./components/CodeEditor.svelte";
  import ConsentPanel from "./components/ConsentPanel.svelte";
  import LabStrip from "./components/LabStrip.svelte";
  import Statement from "./components/Statement.svelte";
  import TopBar from "./components/TopBar.svelte";
  import VerdictPanel from "./components/VerdictPanel.svelte";

  let menuOpen = $state(false);
  let focusSearch = $state(false);
  let helpOpen = $state(false);

  let Progress = $state<Component | null>(null);
  let Leaderboard = $state<Component | null>(null);
  let CollectionView = $state<Component | null>(null);
  let ConsoleView = $state<Component | null>(null);
  let ForumView = $state<Component | null>(null);
  let ModerationView = $state<Component | null>(null);
  let ChatDock = $state<Component | null>(null);
  let IdentityPanel = $state<Component | null>(null);
  let TeamBand = $state<Component | null>(null);
  let ShortcutsPanel = $state<Component<{ open: boolean; onClose: () => void }> | null>(null);
  let QuizPanel = $state<Component | null>(null);

  async function bring<T>(what: string, load: () => Promise<T>): Promise<T | null> {
    try {
      return await load();
    } catch {
      system.say(t("app.load_failed", { what: t(`app.load.${what}`) }), true);
      return null;
    }
  }

  async function openDestination(name: "progress" | "leaderboard" | "collection" | "scratch") {
    if (view.current === name) {
      view.show("");
      return;
    }
    if (name === "progress") {
      const parts = await bring("progress", () =>
        Promise.all([
          import("./features/progress/Progress.svelte"),
          import("./features/progress/projection.svelte"),
        ]),
      );
      if (!parts) return;
      const [mod, { projection }] = parts;
      await projection.load();
      Progress = mod.default as Component;
    } else if (name === "leaderboard") {
      const mod = await bring("leaderboard", () => import("./features/leaderboard/Leaderboard.svelte"));
      if (!mod) return;
      Leaderboard = mod.default as Component;
    } else if (name === "collection") {
      const mod = await bring("collection", () => import("./features/collection/Collection.svelte"));
      if (!mod) return;
      CollectionView = mod.default as Component;
    } else {
      const mod = await bring("console", () => import("./features/scratch/Console.svelte"));
      if (!mod) return;
      ConsoleView = mod.default as Component;
    }
    view.show(name);
  }

  async function tryInConsole() {
    const mod = await bring("console", () => import("./features/scratch/session.svelte"));
    if (mod && catalog.selected && (await mod.scratch.adopt(catalog.selected.files, editor.sources)))
      await openDestination("scratch");
  }

  async function bringChat(): Promise<boolean> {
    if (ChatDock) return true;
    const parts = await bring("chat", () =>
      Promise.all([
        import("./features/forum/ChatDock.svelte"),
        import("./features/forum/ForumView.svelte"),
        import("./features/forum/ModerationView.svelte"),
        import("./features/forum/IdentityPanel.svelte"),
      ]),
    );
    if (!parts) return false;
    ChatDock = parts[0].default as Component;
    ForumView = parts[1].default as Component;
    ModerationView = parts[2].default as Component;
    IdentityPanel = parts[3].default as Component;
    return true;
  }

  async function toggleChat() {
    if (!(await bringChat())) return;
    const { chat } = await import("./features/forum/chat.svelte");
    await chat.toggleDock();
  }

  $effect(() => {
    const wanted =
      profile.identityOpen || view.current === "forum" || view.current === "moderation";
    if (wanted && !ChatDock) void bringChat();
  });

  $effect(() => {
    if (!showTeamBand || TeamBand) return;
    void bring("team", () => import("./features/team/TeamBand.svelte")).then((mod) => {
      if (mod) TeamBand = mod.default as Component;
    });
  });

  onMount(() => {
    const params = new URLSearchParams(location.search);
    const authCode = params.get("code");
    const authState = params.get("state");
    if (authCode) history.replaceState({}, "", location.pathname + sessionGet(RETURN_KEY));
    captureAccessKey(location.search);
    if (!sessionKey()) system.say(t("access.missing_key"));
    theme.apply(theme.current);
    const stopBeating = presence.start();
    const stopListening = maintenance.start();
    whenSessionLost(() => system.say(t("app.session_lost"), true));
    void start(params.get("tp") ?? "", authCode, authState);
    return () => {
      stopBeating();
      stopListening();
    };
  });

  async function start(deepLink: string, authCode: string | null, authState: string | null) {
    await boot(deepLink, authCode, authState);
    // Nothing is going to open the chat any more, so give the reserved column back.
    if (!dock.open) dock.reserved = false;
  }

  // Right after a deployment the API may still be starting: a stored session waits for it
  // rather than being left without the issuer it needs to renew.
  async function deploymentWhenUp(): Promise<Deployment | null> {
    let delay = 1000;
    for (;;) {
      const deployment = await fetchDeployment();
      if (deployment || !session.token) return deployment;
      await new Promise((done) => setTimeout(done, delay));
      delay = Math.min(delay * 2, 15_000);
    }
  }

  async function boot(deepLink: string, authCode: string | null, authState: string | null) {
    const deploymentSoon = deploymentWhenUp();
    const toOpen = await catalog.load(deepLink, lastExercise());
    if (catalog.spotlighted) menuOpen = true;
    if (toOpen) await exercise.open(toOpen);
    else if (catalog.collections.length) menuOpen = true;

    const deployment = await deploymentSoon;
    if (!deployment || !deployment.issuer || !deployment.client_id) return;
    session.deployment = deployment;
    if (!session.token && !authCode) return;

    if (authCode) {
      const { finishSignIn } = await import("./lib/auth/oidc");
      const ok = await finishSignIn(authCode, authState ?? "");
      if (!ok && !session.token) {
        system.say(t("app.signin_failed"), true);
      }
    }
    if (!session.token) return;
    await ensureValid();
    if (!session.token) return;
    await Promise.all([theme.loadFromAccount(), statuses.load()]);
    if (catalog.selectedId) await exercise.open(catalog.selectedId);
    if (!deployment.forum) return;
    void import("./lib/state/unread.svelte").then(({ unread }) => unread.start());
    if (!dock.remembered()) return;
    if (!(await bringChat())) return;
    const { chat } = await import("./features/forum/chat.svelte");
    await chat.restoreDock();
  }

  function onKeydown(event: KeyboardEvent) {
    // The editor claims its keys with preventDefault().
    if (event.defaultPrevented) return;
    const id = matchShortcut(event);
    if (!id) return;

    if (id === "escape") {
      onEscape(event);
      return;
    }
    if (id === "catalog") {
      event.preventDefault();
      openMenu(true);
      return;
    }
    if (id === "help") {
      event.preventDefault();
      void toggleHelp();
      return;
    }
    if (view.current !== "") return;
    if (id === "run") {
      event.preventDefault();
      // On a quiz the blue button tests the page you are on; the shortcut must agree with
      // it, or Ctrl+Enter quietly grades the whole quiz instead.
      void runTest(isQuiz);
      return;
    }
    if (id === "save") {
      event.preventDefault();
      saveNow();
    }
  }

  function saveNow() {
    drafts.cancel();
    exercise.saveNow();
    system.flash(t("app.autosaved"));
  }

  async function toggleHelp() {
    if (helpOpen) {
      helpOpen = false;
      return;
    }
    ShortcutsPanel ??= await bring(
      "shortcuts",
      async () => (await import("./components/ShortcutsPanel.svelte")).default,
    );
    if (ShortcutsPanel) helpOpen = true;
  }

  function onEscape(event: KeyboardEvent) {
    const active = document.activeElement as HTMLElement | null;
    const typing =
      !!active &&
      (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable);

    if (helpOpen) return close(event, () => (helpOpen = false), "shortcutsbutton");
    if (profile.identityOpen && !typing) {
      return close(event, () => (profile.identityOpen = false), "plate");
    }
    if (profile.consentOpen) return close(event, () => profile.cancelConsent(), "login");
    if (menuOpen) return close(event, () => ((menuOpen = false), (focusSearch = false)), "excurrent");
    if (profile.menuOpen) return close(event, () => (profile.menuOpen = false), "plate");

    if (view.current !== "" || typing) return;
    const zone = document.getElementById("code") as HTMLTextAreaElement | null;
    if (!zone) return;
    event.preventDefault();
    zone.focus();
  }

  function close(event: KeyboardEvent, shut: () => void, opener: string) {
    event.preventDefault();
    document.getElementById(opener)?.focus();
    shut();
  }

  function openMenu(search = false) {
    menuOpen = true;
    focusSearch = search;
  }

  const here = $derived(catalog.selected);
  const isQuiz = $derived(here?.mode === "quiz");
  const showWorkbench = $derived(view.current === "");
  const showTeamBand = $derived(!!here?.assignment && session.signedIn);

  $effect(() => {
    if (!isQuiz || QuizPanel) return;
    void bring("quiz", () => import("./components/QuizPanel.svelte")).then((mod) => {
      if (mod) QuizPanel = mod.default as Component;
    });
  });
</script>

<svelte:window onkeydown={onKeydown} />

<TopBar
  {menuOpen}
  {focusSearch}
  onMenu={(open) => {
    menuOpen = open;
    if (!open) focusSearch = false;
  }}
  openView={openDestination}
  openChat={toggleChat}
  {helpOpen}
  openHelp={() => void toggleHelp()}
/>
<ConsentPanel />
{#if ShortcutsPanel}
  <ShortcutsPanel open={helpOpen} onClose={() => (helpOpen = false)} />
{/if}
{#if IdentityPanel}
  <IdentityPanel />
{/if}

<main>
  <!-- Its own banner: every submission rewrites #system, which would erase the notice. -->
  <div id="maintenance" role="status" class={maintenance.phase} hidden={maintenance.phase === "idle"}>
    {maintenance.phase === "back" ? t("maintenance.over") : t("maintenance.started")}
  </div>
  <div id="system"class={system.failed ? "outage" : ""} hidden={!system.text}>{system.text}</div>

  <div id="work" class={dock.open || dock.reserved ? "withchat" : ""} hidden={!showWorkbench}>
    <Statement />

    <div id="right">
      <div id="now" class="phead" aria-live="polite">
        {#if here}
          <b>{here.label}</b>
          <span class="badge">{expectedOf(here.mode)}</span>
          {#if here.verification}
            <span class="badge verification">{t("app.verification")}</span>
          {/if}
        {/if}
      </div>

      {#if showTeamBand}
        <div id="teamband">
          {#if TeamBand}<TeamBand />{/if}
        </div>
      {/if}

      <LabStrip openMenu={(search) => openMenu(search)} />

      {#if isQuiz}
        <!-- The placeholder holds the same flex slot, so the chunk arriving shifts nothing. -->
        {#if QuizPanel}<QuizPanel />{:else}<div id="quizwrap" aria-hidden="true"></div>{/if}
      {:else}
        <CodeEditor />
      {/if}

      <ActionBar openConsole={tryInConsole} />
      <VerdictPanel />
    </div>

    <aside id="chatdock" aria-label={t("app.course_chat")} hidden={!dock.open}>
      {#if ChatDock && dock.open}<ChatDock />{/if}
    </aside>
  </div>

  <section id="viewprogress" aria-labelledby="progresstitle" hidden={view.current !== "progress"}>
    {#if Progress && view.current === "progress"}<Progress openView={openDestination} />{/if}
  </section>
  <section
    id="viewleaderboard"
    aria-labelledby="leaderboardtitle"
    hidden={view.current !== "leaderboard"}
  >
    {#if Leaderboard && view.current === "leaderboard"}<Leaderboard />{/if}
  </section>
  <section
    id="viewcollection"
    aria-labelledby="collectiontitle"
    hidden={view.current !== "collection"}
  >
    {#if CollectionView && view.current === "collection"}<CollectionView />{/if}
  </section>
  <section id="viewscratch" aria-labelledby="scratchtitle" hidden={view.current !== "scratch"}>
    {#if ConsoleView && view.current === "scratch"}<ConsoleView />{/if}
  </section>
  <section id="viewforum" aria-labelledby="forumtitle" hidden={view.current !== "forum"}>
    {#if ForumView && view.current === "forum"}<ForumView />{/if}
  </section>
  <section
    id="viewmoderation"
    aria-labelledby="moderationtitle"
    hidden={view.current !== "moderation"}
  >
    {#if ModerationView && view.current === "moderation"}<ModerationView />{/if}
  </section>

  <div id="notice" role="status" class="offscreen">{system.announcement}</div>
</main>

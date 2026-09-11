<script lang="ts">
  // THE SHELL. It owns three things and nothing more: the startup sequence, which
  // destination is on screen, and the LAZY LOADING of the destinations.
  //
  // EVERY DESTINATION IS A DYNAMIC IMPORT, and that is what makes "the anonymous path
  // downloads nothing account-related" true rather than aspirational. The chunk arrives on
  // the click, exactly as the injected `<script>` used to -- with types, and without a
  // global object. The shell resolves the module first and renders the component once it is
  // there, so a failure can be SAID rather than leaving a button inert.

  import { onMount, type Component } from "svelte";
  import { MISSING_KEY_MESSAGE, captureAccessKey, sessionKey } from "./lib/state/accesskey";
  import { catalog } from "./lib/state/catalog.svelte";
  import { dock } from "./lib/state/dock.svelte";
  import { exercise } from "./lib/state/exercise.svelte";
  import { presence } from "./lib/state/presence.svelte";
  import { profile } from "./lib/state/profile.svelte";
  import { statuses } from "./lib/state/statuses.svelte";
  import { system } from "./lib/state/system.svelte";
  import { theme } from "./lib/state/theme.svelte";
  import { view } from "./lib/state/view.svelte";
  import { runTest } from "./lib/state/run";
  import { drafts } from "./lib/state/drafts.svelte";
  import { matchShortcut } from "./lib/domain/shortcuts";
  import { fetchDeployment } from "./lib/api/public";
  import { RETURN_KEY } from "./lib/auth/keys";
  import { ensureValid, session } from "./lib/auth/session.svelte";
  import { sessionGet } from "./lib/storage";
  import {
    CONTEXT_LABELS,
    DIFFICULTY_LABELS,
    EXPECTED,
    skillLabel,
  } from "./lib/domain/labels";
  import type { Exercise } from "./lib/domain/catalog";

  import ActionBar from "./components/ActionBar.svelte";
  import CodeEditor from "./components/CodeEditor.svelte";
  import ConsentPanel from "./components/ConsentPanel.svelte";
  import LabStrip from "./components/LabStrip.svelte";
  import QuizPanel from "./components/QuizPanel.svelte";
  import Statement from "./components/Statement.svelte";
  import TopBar from "./components/TopBar.svelte";
  import VerdictPanel from "./components/VerdictPanel.svelte";

  let menuOpen = $state(false);
  let focusSearch = $state(false);
  /** L'aide-mémoire. Même forme et même propriétaire que `menuOpen` juste
   *  au-dessus : un module d'état pour un booléen de composant n'en serait
   *  pas un. */
  let helpOpen = $state(false);

  // --- The lazily loaded destinations ------------------------------------------
  // One holder per chunk. `null` means "not fetched"; a component means "here".

  let Progress = $state<Component | null>(null);
  let Leaderboard = $state<Component | null>(null);
  let CollectionView = $state<Component | null>(null);
  let ConsoleView = $state<Component | null>(null);
  let ForumView = $state<Component | null>(null);
  let ModerationView = $state<Component | null>(null);
  let ChatDock = $state<Component | null>(null);
  let IdentityPanel = $state<Component | null>(null);
  let TeamBand = $state<Component | null>(null);
  /** Typé, contrairement aux autres : c'est le seul morceau à la demande qui
   *  prenne des props. */
  let ShortcutsPanel = $state<Component<{ open: boolean; onClose: () => void }> | null>(null);

  /**
   * A FAILURE IS SAID, NOT SWALLOWED: a chunk that does not come down would otherwise
   * leave a button inert without a word. THE REJECTION IS NOT REMEMBERED -- a one-second
   * outage must not condemn the feature for the whole visit, so the next click retries.
   */
  async function bring<T>(what: string, load: () => Promise<T>): Promise<T | null> {
    try {
      return await load();
    } catch {
      system.say(
        "Impossible de charger " + what + ". Vérifie ta connexion, puis recharge la page.",
        true,
      );
      return null;
    }
  }

  async function openDestination(name: "progres" | "leaderboard" | "collection" | "scratch") {
    // A destination's own button doubles as "Retour à l'exercice" when it is open.
    if (view.current === name) {
      view.show("");
      return;
    }
    if (name === "progres") {
      const mod = await bring("« Mes progrès »", () => import("./features/progres/Progress.svelte"));
      if (!mod) return;
      const { projection } = await import("./features/progres/projection.svelte");
      await projection.load();
      Progress = mod.default as Component;
    } else if (name === "leaderboard") {
      const mod = await bring("le classement", () => import("./features/leaderboard/Leaderboard.svelte"));
      if (!mod) return;
      Leaderboard = mod.default as Component;
    } else if (name === "collection") {
      const mod = await bring("la collection", () => import("./features/collection/Collection.svelte"));
      if (!mod) return;
      CollectionView = mod.default as Component;
    } else {
      const mod = await bring("la console", () => import("./features/scratch/Console.svelte"));
      if (!mod) return;
      ConsoleView = mod.default as Component;
    }
    view.show(name);
  }

  /** THE CHAT'S CHUNK carries the dock, the wide view, the moderation screen and the
   *  identity panel -- one feature, one chunk, and its two rendering libraries with it. */
  async function bringChat(): Promise<boolean> {
    if (ChatDock) return true;
    const parts = await bring("le chat", () =>
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

  // The identity panel and the wide view can be opened from elsewhere -- the Compte menu, a
  // failing verdict. Bringing the chunk in on those state changes keeps the shell the only
  // place that decides what is mounted.
  $effect(() => {
    const wanted =
      profile.identityOpen || view.current === "forum" || view.current === "moderation";
    if (wanted && !ChatDock) void bringChat();
  });

  /** THE TEAM WORKSPACE'S BAND. The room itself is entered by `exercise.open()`; this only
   *  brings the band down once there is something to draw. */
  $effect(() => {
    if (!showTeamBand || TeamBand) return;
    void bring("l'espace d'équipe", () => import("./features/team/TeamBand.svelte")).then((mod) => {
      if (mod) TeamBand = mod.default as Component;
    });
  });

  // --- Startup -----------------------------------------------------------------

  onMount(() => {
    const params = new URLSearchParams(location.search);
    const authCode = params.get("code");
    const authState = params.get("state");
    // THE OIDC CALLBACK'S QUERY STRING IS PUT BACK FIRST, so a reload does not re-exchange
    // a spent code and the deep link the student arrived with survives.
    if (authCode) history.replaceState({}, "", location.pathname + sessionGet(RETURN_KEY));
    captureAccessKey(location.search);
    if (!sessionKey()) system.say(MISSING_KEY_MESSAGE);
    // The theme is already on screen (see `public/theme.js`); this mirrors it into state.
    theme.apply(theme.current);
    const stopBeating = presence.start();
    void start(params.get("tp") ?? "", authCode, authState);
    return stopBeating;
  });

  async function start(deepLink: string, authCode: string | null, authState: string | null) {
    // THE CATALOG FIRST: it is what the anonymous path needs, and that is the default path.
    const toOpen = await catalog.load(deepLink);
    if (catalog.spotlighted) menuOpen = true;
    if (toOpen) await exercise.open(toOpen);
    // EVERYTHING PUBLISHED, NOTHING OPEN YET: the normal state at the start of a term, not
    // an outage, and the menu carries the dates -- so it opens.
    else if (catalog.collections.length) menuOpen = true;

    // THE ANONYMOUS PATH STOPS HERE. `oidc.json` is anonymous, but nothing beyond it is
    // fetched without a session in progress or a sign-in return.
    const deployment = await fetchDeployment();
    if (!deployment || !deployment.issuer || !deployment.client_id) return;
    session.deployment = deployment;
    if (!session.token && !authCode) return;

    if (authCode) {
      const { finishSignIn } = await import("./lib/auth/oidc");
      const ok = await finishSignIn(authCode, authState ?? "");
      if (!ok && !session.token) {
        system.say(
          "La connexion a échoué. Tu peux continuer sans compte : la page fonctionne " +
            "exactement pareil.",
          true,
        );
      }
    }
    if (!session.token) return;
    // A TAB REOPENED AFTER A BREAK carries a token that died in the meantime. Renewing it
    // here, once, is what keeps the reads below from all failing at the same moment and
    // signing the student out on arrival.
    await ensureValid();
    if (!session.token) return;
    // BEFORE the projections: the theme is the screen this fixes, so it happens as early
    // as possible in the session.
    await theme.loadFromAccount();
    await statuses.load();
    // The editor may need the account's draft now that there is one.
    if (catalog.selectedId) await exercise.open(catalog.selectedId);
    // THE CHAT COMES BACK IF IT WAS OPEN, and only then: three conditions, all necessary --
    // a session, a deployment offering it, and somebody who opened it with their own hand.
    if (!deployment.forum || !dock.remembered()) return;
    if (!(await bringChat())) return;
    const { chat } = await import("./features/forum/chat.svelte");
    await chat.restoreDock();
  }

  /**
   * LES RACCOURCIS DE LA PAGE. Captés sur le document et pas sur un champ, parce
   * que le curseur de l'étudiant est dans l'éditeur -- c'est de là qu'il faut
   * pouvoir les atteindre.
   *
   * ⚠ LE CONTRAT AVEC `CodeSurface`, ET IL EST INVISIBLE DANS L'UN OU L'AUTRE
   * PRIS SEUL : un `keydown` remonte jusqu'à `window` que `preventDefault()` ait
   * été appelé ou non, donc la surface ne peut pas « consommer » une frappe en
   * la prévenant. C'est `defaultPrevented` qui le dit, et c'est la première
   * ligne ici. Jamais de `stopPropagation` en face -- ça cacherait l'événement à
   * tout futur écouteur et rendrait le contrat positionnel au lieu qu'il soit
   * écrit.
   */
  function onKeydown(event: KeyboardEvent) {
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
    // LES DEUX SEULS GARDÉS SUR LA VUE. La barre d'actions est `hidden` et non
    // démontée quand « Mes progrès » est ouvert : sans cette garde, Ctrl+Entrée
    // soumettrait depuis un écran où il n'y a pas d'éditeur, et Ctrl+S viderait
    // le débounce d'un brouillon que personne ne regarde.
    if (view.current !== "") return;
    if (id === "run") {
      event.preventDefault();
      void runTest(false);
      return;
    }
    if (id === "save") {
      event.preventDefault();
      saveNow();
    }
  }

  /**
   * Ctrl+S N'ENREGISTRE PAS UN FICHIER, IL RÉPOND À LA QUESTION. Le brouillon
   * part tout seul 1,5 s après la dernière frappe ; ce que le geste achète, c'est
   * de ne pas attendre -- et surtout de le DIRE, parce que quelqu'un qui presse
   * Ctrl+S demande une confirmation, pas un enregistrement.
   *
   * Les deux moitiés comptent : `#sauvegarde` affiche « enregistré sur ton
   * compte · 14:32 », la réponse durable, dans le créneau que l'étudiant regarde
   * déjà ; le flash, lui, accuse réception de la FRAPPE et s'efface tout seul.
   */
  function saveNow() {
    drafts.cancel();
    exercise.saveNow();
    system.flash("Pas besoin d'enregistrer : ton code est sauvegardé tout seul.");
  }

  async function toggleHelp() {
    if (helpOpen) {
      helpOpen = false;
      return;
    }
    ShortcutsPanel ??= await bring(
      "l'aide-mémoire des raccourcis",
      async () => (await import("./components/ShortcutsPanel.svelte")).default,
    );
    if (ShortcutsPanel) helpOpen = true;
  }

  /**
   * ÉCHAP FERME UN PANNEAU, SINON REVIENT AU CODE -- et l'ordre des cas est ce
   * qui l'empêche de nuire.
   *
   * L'ASYMÉTRIE ENTRE LE CATALOGUE ET « MON IDENTITÉ » EST VOULUE : un filtre de
   * recherche est jetable, et « Échap efface la recherche » est universel ; un
   * nom d'affichage à moitié tapé est du TRAVAIL, et cette page n'a aucune
   * annulation pour lui. Échap depuis un champ d'identité ne ferme donc rien --
   * le panneau a un bouton « Annuler » pour ça.
   *
   * ET LE DERNIER CAS EST CE QUI GARDE ÉCHAP-PUIS-TAB VIVANT : le curseur dans
   * le textarea rend `typing` vrai, donc on n'atteint jamais le retour au code,
   * donc on ne prévient jamais -- et le drapeau `escaped` de `CodeSurface`
   * survit pour le Tab suivant.
   */
  function onEscape(event: KeyboardEvent) {
    const active = document.activeElement as HTMLElement | null;
    const typing =
      !!active &&
      (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable);

    // UN SEUL À LA FOIS, pour qu'un second Échap atteigne le suivant. Et le focus
    // part AVANT le masquage : masquer un élément qui contient le focus le laisse
    // tomber sur `<body>`, et le Tab d'après repart du haut de la page.
    if (helpOpen) return close(event, () => (helpOpen = false), "raccourcisbouton");
    if (profile.identityOpen && !typing) {
      return close(event, () => (profile.identityOpen = false), "plate");
    }
    if (profile.consentOpen) return close(event, () => profile.cancelConsent(), "connexion");
    if (menuOpen) return close(event, () => ((menuOpen = false), (focusSearch = false)), "excourant");
    if (profile.menuOpen) return close(event, () => (profile.menuOpen = false), "plate");

    // Rien n'était ouvert : on ramène au code, et SEULEMENT si on n'y est pas
    // déjà -- depuis un bouton `.diag`, une tuile de la bande, ou le verdict.
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

  /** The learning objective line, from the catalog's own fields. */
  function objective(ex: Exercise): string {
    const details: string[] = [];
    if (ex.learning.skills?.length) {
      details.push("objectif : " + ex.learning.skills.map(skillLabel).join(", "));
    }
    const context = ex.learning.context;
    if (context && CONTEXT_LABELS[context]) details.push(CONTEXT_LABELS[context]);
    const difficulty = ex.learning.difficulty;
    if (difficulty && DIFFICULTY_LABELS[difficulty]) details.push(DIFFICULTY_LABELS[difficulty]);
    return details.join(" — ");
  }

  const here = $derived(catalog.selected);
  const isQuiz = $derived(here?.mode === "quiz");
  const showWorkbench = $derived(view.current === "");
  const showTeamBand = $derived(!!here?.assignment && session.signedIn);
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
  <!-- THE SERVICE STATE CHANNEL, never the student's code channel. Network, quota, a full
       queue, the session key, a missing module: everything they are not responsible for
       goes here, and never into the verdict. -->
  <div id="systeme" class={system.failed ? "panne" : ""} hidden={!system.text}>{system.text}</div>

  <div id="travail" class={dock.open ? "avecchat" : ""} hidden={!showWorkbench}>
    <Statement />

    <div id="droite">
      <div id="now" class="phead" aria-live="polite">
        {#if here}
          <b>{here.label}</b>
          <span class="badge">{EXPECTED[here.mode] ?? ""}</span>
          <!-- MARKED HERE TOO, not only in the menu: a verification must stay recognizable
               once OPENED, since this is where one decides to start it. -->
          {#if here.verification}
            <span class="badge verif">vérification — sans XP</span>
          {/if}
          {#if objective(here)}
            <span class="learning">{objective(here)}</span>
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
        <QuizPanel />
      {:else}
        <CodeEditor />
      {/if}

      <ActionBar />
      <VerdictPanel />
    </div>

    <!-- THE CHAT, BESIDE THE CODE AND NOT INSTEAD OF IT. Third column of the grid, folded
         into a bottom sheet under 900 px. Empty until the chunk has come down -- the
         anonymous visitor does not even see the button. -->
    <aside id="chatdock" aria-label="Chat du cours" hidden={!dock.open}>
      {#if ChatDock && dock.open}<ChatDock />{/if}
    </aside>
  </div>

  <section id="vueprogres" aria-labelledby="progrestitre" hidden={view.current !== "progres"}>
    {#if Progress && view.current === "progres"}<Progress />{/if}
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
  <section id="vueforum" aria-labelledby="forumtitre" hidden={view.current !== "forum"}>
    {#if ForumView && view.current === "forum"}<ForumView />{/if}
  </section>
  <!-- MODERATION IS A SEPARATE DESTINATION, not one more block in the student view. -->
  <section
    id="vuemoderation"
    aria-labelledby="moderationtitre"
    hidden={view.current !== "moderation"}
  >
    {#if ModerationView && view.current === "moderation"}<ModerationView />{/if}
  </section>

  <!-- WHAT GETS ANNOUNCED, AND NOTHING ELSE. One short line. Off-screen, never hidden: a
       hidden element is not announced. -->
  <div id="annonce" role="status" class="horsecran">{system.announcement}</div>
</main>

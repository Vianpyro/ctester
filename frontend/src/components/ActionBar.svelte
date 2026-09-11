<script lang="ts">
  // THE ACTION BAR: import a file, the draft's own message slot, clear the drafts,
  // export the lab, and the one or two "Tester" buttons.
  //
  // IT IS A SEPARATE GRID ROW, and never inside the editor or the quiz: those two take
  // turns, but submitting applies to both -- so hiding a panel can never take the
  // button down with it.

  import { catalog } from "../lib/state/catalog.svelte";
  import { drafts } from "../lib/state/drafts.svelte";
  import { editor } from "../lib/state/editor.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { submission } from "../lib/state/submission.svelte";
  import { runTest } from "../lib/state/run";
  import { isGroupExportable } from "../lib/domain/catalog";
  import { decodeImported } from "../lib/domain/source";
  import { exportGroup } from "../lib/state/export";

  const here = $derived(catalog.selected);
  const isQuiz = $derived(here?.mode === "quiz");
  const exportable = $derived(!!here && isGroupExportable(catalog.catalog, here.group));

  /** The idle labels. `submission.busy` replaces them with what is happening. */
  const goLabel = $derived(isQuiz ? "Tester tout le quiz" : "Tester");
  const busyLabel = $derived(
    submission.phase.kind === "cooldown"
      ? "Nouveau test dans " + submission.phase.seconds + " s"
      : "Test en cours…",
  );

  /**
   * `aria-busy` ONLY WHEN IT IS ACTUALLY WORKING: during a quota countdown nothing is
   * running, and announcing busy would be false.
   */
  const working = $derived(
    submission.phase.kind === "sending" ||
      submission.phase.kind === "queued" ||
      submission.phase.kind === "running",
  );

  /**
   * IMPORT USED TO LOSE THE IMPORTED FILE. `input` DOES NOT FIRE when a script writes
   * into a `<textarea>`: the file only existed in the DOM, and a reload -- or a tab
   * closed by mistake -- took it away without a word. It is the easiest way to lose
   * code on the whole page, so the save is explicit here.
   */
  async function onFile(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    // LE BOM ET LES CRLF NE PASSENT PAS LA PORTE. C'est le seul endroit du
    // système où des octets étrangers entrent, et une fois dans le `Y.Doc`
    // d'une équipe le serveur ne peut plus les reprendre.
    const text = decodeImported(await file.text());
    // THE FILE GOES INTO THE TAB CARRYING ITS NAME, when there is one. Importing
    // `calendrier.c` over `calendrier.h` just because that is the open tab is a
    // silent overwrite, at the exact moment the student is looking elsewhere.
    const target = Object.prototype.hasOwnProperty.call(editor.sources, file.name)
      ? file.name
      : editor.activeFile;
    if (target === null) return;
    if (target !== editor.activeFile) editor.activate(target);
    // WE ASK BEFORE OVERWRITING WORK: there is no undo in this editor. An empty tab,
    // or one still at its template, is not worth a question.
    const replaced = (editor.read(target) || "").trim();
    if (
      replaced &&
      typeof confirm === "function" &&
      !confirm(
        "Remplacer le contenu de « " +
          target +
          " » par « " +
          file.name +
          " » ? Ce qui est écrit dans cet onglet sera perdu.",
      )
    ) {
      input.value = "";
      return;
    }
    editor.write(target, text);
    drafts.cancel();
    exercise.saveNow();
    // RESET THE FIELD: without this, re-importing the SAME file after fixing it on
    // disk does not fire `change`, and the button looks dead.
    input.value = "";
  }

  async function doExport() {
    if (!here) return;
    await exportGroup(catalog.catalog, here.group, (text, failed) =>
      drafts.sayExport(text, failed),
    );
  }
</script>

<div id="actions">
  <span id="filewrap" hidden={isQuiz}>
    <input type="file" id="file" accept=".c,.txt" onchange={onFile} />
    <label for="file" class="btn">Importer un fichier</label>
  </span>
  <span id="brouillon" class={drafts.exportFailed ? "rate" : ""} aria-live="polite"
    >{drafts.exportNote}</span
  >
  <button type="button" id="purger" class="nav" hidden={!drafts.hasAny} onclick={() => drafts.clearAll()}>
    Effacer mes brouillons
  </button>
  <button
    type="button"
    id="exporttp"
    class="nav"
    hidden={!exportable}
    title="Assemble tous les exercices de ce TP dans un seul main.c"
    onclick={doExport}
  >
    Exporter le TP en main.c
  </button>
  <span class="grow"></span>
  <!-- NOT `disabled`, AND THAT IS DELIBERATE. Disabling the focused button drops
       focus onto `<body>`: with a keyboard one had to tab through the whole page
       again after EVERY submission. It stays focusable, it SAYS what it is doing, and
       it stays clickable -- a poll that never completes used to leave the student in
       front of a dead button with no way out. The real safeguard against hammering is
       the server's quota, and it is already there. -->
  <button
    id="go"
    class={(isQuiz ? "secondaire" : "") + (submission.busy ? " occupe" : "")}
    aria-busy={working ? "true" : "false"}
    onclick={() => runTest(false)}
  >
    {submission.busy ? busyLabel : goLabel}
  </button>
  <!-- Outside a quiz there is one button and it is primary. In a quiz, the current
       action is the DISPLAYED exercise: testing all 40 questions stays possible but
       stops being the default landing action. -->
  <button
    type="button"
    id="goex"
    hidden={!isQuiz}
    class={submission.busy ? "occupe" : ""}
    aria-busy={working ? "true" : "false"}
    onclick={() => runTest(true)}
  >
    {submission.busy ? busyLabel : "Tester l'exercice"}
  </button>
</div>

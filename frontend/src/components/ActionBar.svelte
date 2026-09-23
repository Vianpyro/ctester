<script lang="ts">
  import { catalog } from "../lib/state/catalog.svelte";
  import { drafts } from "../lib/state/drafts.svelte";
  import { editor } from "../lib/state/editor.svelte";
  import { exercise } from "../lib/state/exercise.svelte";
  import { submission } from "../lib/state/submission.svelte";
  import { runTest } from "../lib/state/run";
  import { isGroupExportable } from "../lib/domain/catalog";
  import { decodeImported } from "../lib/domain/source";
  import { exportGroup } from "../lib/state/export";
  import { session } from "../lib/auth/session.svelte";
  import { t } from "../lib/i18n.svelte";

  let { openConsole }: { openConsole: () => void } = $props();

  const here = $derived(catalog.selected);
  const isQuiz = $derived(here?.mode === "quiz");
  const exportable = $derived(!!here && isGroupExportable(catalog.catalog, here.group));

  const goLabel = $derived(isQuiz ? t("actions.test_quiz") : t("actions.test"));
  const busyLabel = $derived(
    submission.phase.kind === "cooldown"
      ? t("actions.cooldown", { seconds: submission.phase.seconds })
      : t("actions.running"),
  );

  const working = $derived(
    submission.phase.kind === "sending" ||
      submission.phase.kind === "queued" ||
      submission.phase.kind === "running",
  );

  async function onFile(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    const text = decodeImported(await file.text());
    const target = Object.prototype.hasOwnProperty.call(editor.sources, file.name)
      ? file.name
      : editor.activeFile;
    if (target === null) return;
    if (target !== editor.activeFile) editor.activate(target);
    const replaced = (editor.read(target) || "").trim();
    if (
      replaced &&
      typeof confirm === "function" &&
      !confirm(t("actions.replace_confirm", { target, file: file.name }))
    ) {
      input.value = "";
      return;
    }
    editor.write(target, text);
    drafts.cancel();
    exercise.saveNow();
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
    <label for="file" class="btn">{t("actions.import")}</label>
  </span>
  <span id="draft" class={drafts.exportFailed ? "failed" : ""} aria-live="polite"
    >{drafts.exportNote}</span
  >
  <button type="button" id="purge" class="nav" hidden={!drafts.hasAny} onclick={() => drafts.clearAll()}>
    {t("actions.clear_drafts")}
  </button>
  <button
    type="button"
    id="exporttp"
    class="nav"
    hidden={!exportable}
    title={t("actions.export_title")}
    onclick={doExport}
  >
    {t("actions.export")}
  </button>
  <span class="grow"></span>
  {#if !isQuiz && session.signedIn && session.scratchOffered}
    <button
      type="button"
      id="toconsole"
      class="nav"
      title={t("actions.console_title")}
      onclick={openConsole}
    >
      {t("actions.console")}
    </button>
  {/if}
  <button
    id="go"
    class={(isQuiz ? "secondary" : "") + (submission.busy ? " busy" : "")}
    aria-busy={working ? "true" : "false"}
    onclick={() => runTest(false)}
  >
    {submission.busy ? busyLabel : goLabel}
    {#if !submission.busy && !isQuiz}<span class="shortcut">Ctrl+↵</span>{/if}
  </button>
  <button
    type="button"
    id="goex"
    hidden={!isQuiz}
    class={submission.busy ? "busy" : ""}
    aria-busy={working ? "true" : "false"}
    onclick={() => runTest(true)}
  >
    {submission.busy ? busyLabel : t("actions.test_exercise")}
    {#if !submission.busy}<span class="shortcut">Ctrl+↵</span>{/if}
  </button>
</div>

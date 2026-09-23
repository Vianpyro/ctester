<script lang="ts">
  import { catalog } from "../../lib/state/catalog.svelte";
  import { t } from "../../lib/i18n.svelte";
  import { sessionGet, sessionSet } from "../../lib/storage";
  import { thread } from "./thread.svelte";
  import Guidelines, { CHARTER_SEEN } from "./Guidelines.svelte";
  import Markdown from "./Markdown.svelte";
  import SearchResults from "./SearchResults.svelte";

  interface Props {
    compact?: boolean;
  }

  const { compact = false }: Props = $props();

  const prefix = $derived(compact ? "chat" : "forum");

  let composeMode = $state<"question" | "bloque">("question");
  let askPrivately = $state(false);
  let step = $state("");
  let blockedKind = $state("");
  let visibility = $state<"private" | "group">("private");
  let showGuidelines = $state(false);
  let pending: (() => void) | null = null;

  const stuck = $derived(composeMode === "bloque" && !thread.isChat && !thread.replyTo);
  const modes = $derived(
    thread.isChat || thread.replyTo
      ? []
      : ([
          ["question", t("composer.ask")],
          ["bloque", t("composer.stuck")],
        ] as const),
  );

  const label = $derived(
    (stuck
      ? t("composer.tried")
      : thread.replyTo
        ? t("composer.reply")
        : thread.isChat
          ? t("composer.chat_question")
          : t("composer.question")) + (thread.max ? t("composer.max", { max: thread.max }) : ""),
  );

  const hint = $derived(
    !thread.renderable
      ? t("composer.plain")
      : compact
        ? t("composer.enter")
        : t("composer.markdown"),
  );

  let duplicateTimer: ReturnType<typeof setTimeout> | null = null;

  function watchForDuplicates() {
    if (thread.replyTo || compact) return;
    if (duplicateTimer) clearTimeout(duplicateTimer);
    const text = thread.typing;
    if (text.trim().length < 8) {
      thread.duplicates = null;
      return;
    }
    duplicateTimer = setTimeout(async () => {
      thread.duplicates = (await thread.search(text)).slice(0, 3);
    }, 400);
  }

  function send() {
    const text = thread.typing;
    let extra: Parameters<typeof thread.post>[1];
    if (thread.replyTo) {
      extra = { reply_to: thread.replyTo };
    } else if (askPrivately && thread.canAskPrivately) {
      extra = {
        exercise_id: thread.currentExercise,
        step: step || "statement",
        blocked_kind: blockedKind || undefined,
        visibility: "private",
      };
    } else if (stuck) {
      extra = {
        step: step || "statement",
        blocked_kind: blockedKind || undefined,
        visibility,
      };
    } else {
      extra = {};
    }
    const go = async () => {
      const ok = await thread.post(text, extra);
      if (ok) {
        askPrivately = false;
        thread.replyTo = null;
      }
    };
    if (sessionGet(CHARTER_SEEN)) void go();
    else {
      pending = () => void go();
      showGuidelines = true;
    }
  }

  function acceptGuidelines() {
    sessionSet(CHARTER_SEEN, "1");
    showGuidelines = false;
    pending?.();
    pending = null;
  }

  function onKeydown(event: KeyboardEvent) {
    if (!compact || event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    send();
  }

  const exerciseTitle = $derived(
    catalog.catalog.find((ex) => ex.id === thread.currentExercise)?.short ?? "",
  );
</script>

{#if showGuidelines}
  <Guidelines onAccept={acceptGuidelines} onCancel={() => (showGuidelines = false)} />
{/if}

<div class={compact ? "chatsaisie" : "block"}>
  {#if thread.replyTo}
    <div class="row">
      <span class="tag accent">{t("composer.replying")}</span>
      <button type="button" class="nav" onclick={() => (thread.replyTo = null)}>
        {t("composer.cancel_reply")}
      </button>
    </div>
  {/if}

  <div class="tabs">
    {#each modes as [id, title]}
      <button
        type="button"
        class={"nav" + (composeMode === id ? " on" : "")}
        aria-pressed={composeMode === id}
        onclick={() => (composeMode = id)}>{title}</button
      >
    {/each}
  </div>

  {#if stuck}
    <p class="help">{t("composer.context")}</p>
    <div class="choice">
      <label for={prefix + "etape"}>{t("composer.where")}</label>
      {#each thread.steps as s (s.id)}
        <label class="check">
          <input
            type="radio"
            name={prefix + "etape"}
            checked={step ? step === s.id : s === thread.steps[0]}
            onchange={() => (step = s.id)}
          /><span>{t(`forum.step.${s.id}`)}</span>
        </label>
      {/each}
    </div>
    <div class="choice">
      <label for={prefix + "blocage"}>{t("composer.what")}</label>
      {#each thread.blockedKinds as k (k.id)}
        <label class="check">
          <input
            type="radio"
            name={prefix + "blocage"}
            checked={blockedKind ? blockedKind === k.id : k === thread.blockedKinds[0]}
            onchange={() => (blockedKind = k.id)}
          /><span>{t(`forum.blocked.${k.id}`)}</span>
        </label>
      {/each}
    </div>
  {/if}

  <label for={prefix + "text"}>{label}</label>
  <textarea
    id={prefix + "text"}
    rows="4"
    bind:value={thread.typing}
    placeholder={stuck ? t("composer.placeholder") : undefined}
    oninput={watchForDuplicates}
    onkeydown={onKeydown}
  ></textarea>

  <p class="help">{hint}</p>

  {#if thread.renderable && !compact}
    <h4 class="subtitle" id="forumpreviewtitle">{t("identity.preview")}</h4>
    <div role="region" aria-labelledby="forumpreviewtitle">
      <Markdown source={thread.typing} class="md preview" />
    </div>
  {/if}

  {#if !thread.replyTo && !compact && thread.duplicates?.length}
    <div class="block second">
      <h4 class="subtitle">{t("composer.maybe_asked")}</h4>
      <SearchResults rows={thread.duplicates} empty="" />
      <p class="help">{t("composer.post_yours")}</p>
    </div>
  {/if}

  {#if stuck}
    <div class="choice">
      <label for={prefix + "visibilite"}>{t("composer.who")}</label>
      <label class="check">
        <input
          type="radio"
          name={prefix + "visibilite"}
          checked={visibility === "private"}
          onchange={() => (visibility = "private")}
        /><span>{t("composer.lab_only")}</span><span class="help">{t("composer.default")}</span>
      </label>
      <label class="check">
        <input
          type="radio"
          name={prefix + "visibilite"}
          checked={visibility === "group"}
          onchange={() => (visibility = "group")}
        /><span>{t("composer.group_too")}</span><span class="help">{t("composer.group_help")}</span>
      </label>
      <p class="help">{t("composer.later")}</p>
    </div>
  {/if}

  {#if thread.canAskPrivately}
    <div class="chatprive">
      <label class="check" for={prefix + "prive"}>
        <input id={prefix + "prive"} type="checkbox" bind:checked={askPrivately} />
        <span>{t("composer.private")}</span>
      </label>
      {#if askPrivately}
        <p class="help">{t("composer.private_help")}</p>
        <div class="choice">
          <label for={prefix + "etapeprive"}>{t("composer.where")}</label>
          {#each thread.steps as s (s.id)}
            <label class="check">
              <input
                type="radio"
                name={prefix + "etapeprive"}
                checked={step ? step === s.id : s === thread.steps[0]}
                onchange={() => (step = s.id)}
              /><span>{t(`forum.step.${s.id}`)}</span>
            </label>
          {/each}
        </div>
      {/if}
    </div>
  {/if}

  <button type="button" onclick={send}>
    {thread.replyTo ? t("composer.answer") : t("composer.post")}
  </button>
  {#if !compact && exerciseTitle}
    <span class="offscreen">{t("composer.channel", { name: exerciseTitle })}</span>
  {/if}
</div>

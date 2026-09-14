<script lang="ts">
  import { catalog } from "../../lib/state/catalog.svelte";
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
          ["question", "Poser une question"],
          ["bloque", "Je suis bloqué ici"],
        ] as const),
  );

  const label = $derived(
    (stuck
      ? "Ce que tu as déjà essayé"
      : thread.replyTo
        ? "Ta réponse"
        : thread.isChat
          ? "Ta question — personne ne juge, et tu es masqué"
          : "Ta question ou ton explication") +
      (thread.max ? " (" + thread.max + " caractères au plus)" : ""),
  );

  const hint = $derived(
    !thread.renderable
      ? "Le rendu enrichi n'a pas pu être chargé : ton message part quand même, et il s'affiche en texte brut."
      : compact
        ? "Entrée pour envoyer, Maj+Entrée pour un saut de ligne."
        : "Mise en forme simple : **gras**, *italique*, listes, > citation, `code court`. Le HTML n'est jamais interprété.",
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
    catalog.catalog.find((t) => t.id === thread.currentExercise)?.short ?? "",
  );
</script>

{#if showGuidelines}
  <Guidelines onAccept={acceptGuidelines} onCancel={() => (showGuidelines = false)} />
{/if}

<div class={compact ? "chatsaisie" : "bloc"}>
  {#if thread.replyTo}
    <div class="row">
      <span class="tag accent">Réponse à un message</span>
      <button type="button" class="nav" onclick={() => (thread.replyTo = null)}>
        Annuler la réponse
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
    <p class="aide">
      Ta question partira avec l'exercice et l'étape. Ton code, lui, ne part pas — décris
      ce que tu observes.
    </p>
    <div class="choix">
      <label for={prefix + "etape"}>Où ça coince</label>
      {#each thread.steps as s (s.id)}
        <label class="coche">
          <input
            type="radio"
            name={prefix + "etape"}
            checked={step ? step === s.id : s === thread.steps[0]}
            onchange={() => (step = s.id)}
          /><span>{s.title}</span>
        </label>
      {/each}
    </div>
    <div class="choix">
      <label for={prefix + "blocage"}>Ce qui bloque</label>
      {#each thread.blockedKinds as k (k.id)}
        <label class="coche">
          <input
            type="radio"
            name={prefix + "blocage"}
            checked={blockedKind ? blockedKind === k.id : k === thread.blockedKinds[0]}
            onchange={() => (blockedKind = k.id)}
          /><span>{k.title}</span>
        </label>
      {/each}
    </div>
  {/if}

  <label for={prefix + "texte"}>{label}</label>
  <textarea
    id={prefix + "texte"}
    rows="4"
    bind:value={thread.typing}
    placeholder={stuck ? "J'ai vérifié le type de ma variable, mais…" : undefined}
    oninput={watchForDuplicates}
    onkeydown={onKeydown}
  ></textarea>

  <p class="aide">{hint}</p>

  {#if thread.renderable && !compact}
    <h4 class="soustitre" id="forumapercutitre">Aperçu</h4>
    <div role="region" aria-labelledby="forumapercutitre">
      <Markdown source={thread.typing} class="md apercu" />
    </div>
  {/if}

  {#if !thread.replyTo && !compact && thread.duplicates?.length}
    <div class="bloc second">
      <h4 class="soustitre">Peut-être déjà demandé</h4>
      <SearchResults rows={thread.duplicates} empty="" />
      <p class="aide">Si ce n'est pas ta question, publie la tienne : c'est fait pour.</p>
    </div>
  {/if}

  {#if stuck}
    <div class="choix">
      <label for={prefix + "visibilite"}>Qui la voit</label>
      <label class="coche">
        <input
          type="radio"
          name={prefix + "visibilite"}
          checked={visibility === "private"}
          onchange={() => (visibility = "private")}
        /><span>Seulement le chargé de lab</span><span class="aide">— par défaut</span>
      </label>
      <label class="coche">
        <input
          type="radio"
          name={prefix + "visibilite"}
          checked={visibility === "group"}
          onchange={() => (visibility = "group")}
        /><span>Aussi les autres de mon groupe</span><span class="aide"
          >— quelqu'un peut répondre tout de suite</span
        >
      </label>
      <p class="aide">
        Tu pourras la rendre visible au groupe plus tard, en un clic, sans la republier.
      </p>
    </div>
  {/if}

  {#if thread.canAskPrivately}
    <div class="chatprive">
      <label class="coche" for={prefix + "prive"}>
        <input id={prefix + "prive"} type="checkbox" bind:checked={askPrivately} />
        <span>Demander en privé à l'enseignant</span>
      </label>
      {#if askPrivately}
        <p class="aide">
          Ton message n'ira pas dans le chat : seul l'enseignant le lira. Ton code, lui, ne
          part pas — décris ce que tu observes.
        </p>
        <div class="choix">
          <label for={prefix + "etapeprive"}>Où ça coince</label>
          {#each thread.steps as s (s.id)}
            <label class="coche">
              <input
                type="radio"
                name={prefix + "etapeprive"}
                checked={step ? step === s.id : s === thread.steps[0]}
                onchange={() => (step = s.id)}
              /><span>{s.title}</span>
            </label>
          {/each}
        </div>
      {/if}
    </div>
  {/if}

  <button type="button" onclick={send}>
    {thread.replyTo ? "Répondre" : "Publier"}
  </button>
  {#if !compact && exerciseTitle}
    <span class="horsecran">Canal : {exerciseTitle}</span>
  {/if}
</div>

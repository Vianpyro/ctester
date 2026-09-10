<script lang="ts">
  // THE COMPOSER, IN TWO SIZES. `compact` is the dock's: a 22 rem column has no room for
  // the Markdown preview or the tabs, the wide view does.
  //
  // THE IDS ARE PREFIXED, BECAUSE BOTH SURFACES COEXIST IN THE DOCUMENT. The dock keeps
  // its DOM while the wide view is open: without the prefix there would be two
  // `id="forumtexte"`, a `<label for>` pointing at the wrong field and a lookup returning
  // whichever came first.
  //
  // ENTER SENDS, SHIFT+ENTER BREAKS A LINE, AND ONLY IN THE DOCK. It is the one gesture
  // nobody has to be taught. Not in the wide view: there one writes a ten-line question,
  // and a key that sent it half-written would be worse than the click.
  //
  // THE PRIVATE BOX REPLACED A PLACE WITH A CHOICE. One no longer decides where to go
  // before writing; one decides who reads once one has written. It clears on every send
  // -- a box that stayed ticked would make the NEXT message private without saying so,
  // and that one nobody reads.

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

  /** WHICH FORM IS OPEN. "question" is the ordinary public post; "bloque" is the help
   *  request, PRIVATE by default and carrying a step. One value, so the two can never be
   *  half-open at once. */
  let composeMode = $state<"question" | "bloque">("question");
  let askPrivately = $state(false);
  let step = $state("");
  let blockedKind = $state("");
  let visibility = $state<"private" | "group">("private");
  let showGuidelines = $state(false);
  let pending: (() => void) | null = null;

  // In a chat there is only one way to write, because there is nothing private to choose.
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

  /**
   * THE DEBOUNCE IS THIS FUNCTION'S WHOLE LOAD MANAGEMENT. The route is an indexed read
   * with no quota (a ten-second cooldown would make it useless while typing, which is
   * the only moment it helps): what bounds it is not leaving on every keystroke.
   *
   * NOT FROM THE DOCK: it draws no duplicate panel (no room in 22 rem), so the request
   * would leave for a result nobody displays -- one request per keystroke, for nothing.
   */
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

  /** THE SEND IS IN ONE PLACE, because it now leaves from TWO gestures: the button and
   *  the Enter key. Two copies would have diverged, and the one that drifts is always the
   *  one that forgets the box. */
  function send() {
    const text = thread.typing;
    // A REPLY CARRIES NEITHER STEP NOR VISIBILITY: it inherits the conversation it joins,
    // and the server REFUSES one that carries either. Sending them anyway would be a 400
    // nobody could act on.
    let extra: Parameters<typeof thread.post>[1];
    if (thread.replyTo) {
      extra = { reply_to: thread.replyTo };
    } else if (askPrivately && thread.canAskPrivately) {
      // THE BOX DOES NOT CHANGE THE VISIBILITY IN THE CHANNEL, IT CHANGES THE THREAD.
      // `est_chat()` forces public server-side and we ask it for NO exception: we simply
      // write into the exercise's forum thread, a key `threadKey()` already produces.
      // "In the chat everything is public" stays true to the letter.
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
    // THE CHARTER BEFORE THE SESSION'S FIRST POST. Once read it does not reappear on
    // every message -- it stays in view, further up the page.
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
  <!-- REPLYING TO SOMEBODY IS SAID BEFORE WRITING. Without this band one types a reply
       believing one is opening a new question -- and the other way round. -->
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
    <!-- WHAT GOES WITH THE QUESTION, SAID BEFORE IT IS WRITTEN. The exercise and the step
         travel; THE CODE DOES NOT, and that is what keeps the charter tenable -- there is
         no field here that could carry a source file, and the sentence says so where it
         will be read. -->
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
    <!-- THE PREVIEW IS NOT `aria-live`. Announcing every keystroke to a screen reader
         would make the field unusable; it is a labelled region, to be read whenever one
         wants. -->
    <h4 class="soustitre" id="forumapercutitre">Aperçu</h4>
    <div role="region" aria-labelledby="forumapercutitre">
      <Markdown source={thread.typing} class="md apercu" />
    </div>
  {/if}

  <!-- "SOMEBODY ALREADY ASKED THIS", AND WE ONLY PROPOSE IT. Never blocking: deciding
       for somebody that their question is a duplicate is exactly how to make them stop
       asking, which is what all of this exists to avoid. -->
  {#if !thread.replyTo && !compact && thread.duplicates?.length}
    <div class="bloc second">
      <h4 class="soustitre">Peut-être déjà demandé</h4>
      <SearchResults rows={thread.duplicates} empty="" />
      <p class="aide">Si ce n'est pas ta question, publie la tienne : c'est fait pour.</p>
    </div>
  {/if}

  {#if stuck}
    <!-- PRIVATE IS THE DEFAULT, AND IT IS THE FIRST OPTION. Asking for help should not
         require deciding, in the same breath, to say so publicly -- and the second option
         says what one gains by choosing it, since that is the whole reason to. -->
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
        <!-- THE STEP IS NOT DECORATIVE: it is what groups the aggregate the instructor
             reads in "qui a besoin d'aide". Labelling everything "énoncé" by default would
             make it mute on the morning it counts. -->
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

<script lang="ts">
  // THE CONSOLE'S SCREEN. Its editor IS the exercise editor's -- `CodeSurface`, the same
  // component -- and that is what it took to stop it falling behind: it used to restate
  // the three elements itself, so the Tab key, the auto-closing pairs and the syntax
  // checker were each written next door and never arrived here.
  //
  // `textContent`, NEVER `{@html}`, FOR THE OUTPUT: what arrives is a program written by a
  // student, that is to say an arbitrary string. The colouring layer is the one exception
  // and it receives `highlight()`'s output, which escapes every slice.

  import { onDestroy, onMount } from "svelte";
  import CodeSurface from "../../components/CodeSurface.svelte";
  import { scratch, TEMPLATE } from "./session.svelte";

  let title: HTMLHeadingElement | undefined = $state();
  let terminal: HTMLPreElement | undefined = $state();
  let typed = $state("");

  onMount(() => {
    title?.focus();
    if (!scratch.loaded) void scratch.load();
    else if (!scratch.code) scratch.code = TEMPLATE;
  });

  // LEAVING THE VIEW CLOSES THE SESSION. Without this, a container would survive a screen
  // change and hold a core of the server while the student does something else.
  onDestroy(() => scratch.stop());

  // The terminal follows the bottom, as every terminal does.
  $effect(() => {
    void scratch.output.length;
    if (terminal) terminal.scrollTop = terminal.scrollHeight;
  });

  function submitInput() {
    scratch.send(typed);
    typed = "";
  }
</script>

<h2 bind:this={title} id="scratchtitle" tabindex="-1">Console</h2>
<p class="explique">Écris un programme C, lance-le, c'est un brouillon pour essayer.</p>

<div class="plan scratchpan">
  <div class="phead">Ton programme</div>
  <CodeSurface
    value={scratch.code}
    onInput={(text) => {
      scratch.code = text;
      scratch.scheduleSave();
    }}
    label="Programme de la Console"
    placeholder="// Écris ton programme C ici"
    idPrefix="scratch"
    wrapClass="scratchedit"
  />
</div>

<div class="scratchbarre">
  <button type="button" id="scratchgo" disabled={scratch.running} onclick={() => scratch.start()}>
    {scratch.running ? "En cours…" : "Lancer"}
  </button>
  {#if scratch.running}
    <button type="button" id="scratchstop" class="nav" onclick={() => scratch.stop()}>
      Arrêter
    </button>
  {/if}
  <span id="scratchetat" class={"scratchetat" + (scratch.noteFailed ? " rate" : "")}>
    {scratch.note}
  </span>
</div>

<div class="plan scratchpan">
  <div class="phead">Sortie</div>
  <pre bind:this={terminal} id="scratchout" class="scratchterm">{#each scratch.output as chunk, i (i)}<span
        class={chunk.kind}>{chunk.text}</span
      >{/each}</pre>
  <div class="scratchsaisiebarre">
    <label class="horsecran" for="scratchsaisie">Entrée pour ton programme</label>
    <input
      id="scratchsaisie"
      type="text"
      bind:value={typed}
      disabled={!scratch.running}
      placeholder="Réponds à ton programme, puis Entrée"
      onkeydown={(e) => {
        if (e.key === "Enter") submitInput();
      }}
    />
    <button
      type="button"
      id="scratchenvoi"
      class="nav"
      disabled={!scratch.running}
      onclick={submitInput}>Envoyer</button
    >
    <button
      type="button"
      id="scratcheof"
      class="nav"
      disabled={!scratch.running}
      onclick={() => scratch.endInput()}>Fin d'entrée</button
    >
  </div>
</div>

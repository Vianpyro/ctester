<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import CodeSurface from "../../components/CodeSurface.svelte";
  import { scratch, TEMPLATE } from "./session.svelte";

  let title: HTMLHeadingElement | undefined = $state();
  let terminal: HTMLPreElement | undefined = $state();
  let prompt: HTMLInputElement | undefined = $state();
  let typed = $state("");
  // "add" and "rename" ask for a name; "remove" asks to confirm, since the text is lost.
  let asking = $state<"" | "add" | "rename" | "remove">("");
  let proposed = $state("");
  let refusal = $state("");

  onMount(() => {
    title?.focus();
    if (!scratch.loaded) void scratch.load();
    else if (!scratch.code) scratch.code = TEMPLATE;
  });

  onDestroy(() => scratch.stop());

  $effect(() => {
    void scratch.output.length;
    if (terminal) terminal.scrollTop = terminal.scrollHeight;
  });

  $effect(() => {
    if (scratch.running) prompt?.focus();
  });

  function onPromptKeydown(event: KeyboardEvent) {
    if (event.key === "Enter") {
      scratch.send(typed);
      typed = "";
    } else if (event.ctrlKey && event.key.toLowerCase() === "d") {
      event.preventDefault();
      if (typed) scratch.send(typed);
      typed = "";
      scratch.endInput();
    } else if (event.ctrlKey && event.key.toLowerCase() === "c" && !getSelection()?.toString()) {
      event.preventDefault();
      scratch.stop();
    }
  }

  function ask(what: "add" | "rename" | "remove") {
    asking = what;
    proposed = what === "rename" ? scratch.headerName : "";
    refusal = "";
  }

  function confirmName() {
    const name = proposed.trim();
    refusal = asking === "rename" ? scratch.renameHeader(name) : scratch.addHeader(name);
    if (!refusal) asking = "";
  }

  function onTabsKeydown(event: KeyboardEvent) {
    if ((event.key === "ArrowRight" || event.key === "ArrowLeft") && scratch.headerName) {
      scratch.active = scratch.active === "main" ? "header" : "main";
      document.getElementById(scratch.active === "main" ? "scratchtabmain" : "scratchtabheader")?.focus();
    }
  }
</script>

<h2 bind:this={title} id="scratchtitle" tabindex="-1">Console</h2>
<p class="explain">Écris un programme C, lance-le, c'est un brouillon pour essayer.</p>

<div class="plan scratchpan">
  <div class="phead">
    <span>Ton programme</span>
    <!-- svelte-ignore a11y_interactive_supports_focus -->
    <div class="scratchtabs" role="tablist" aria-label="Fichiers de la Console" onkeydown={onTabsKeydown}>
      <button
        type="button"
        id="scratchtabmain"
        class={scratch.active === "main" ? "tab on" : "tab"}
        role="tab"
        aria-controls="scratchedwrap"
        aria-selected={scratch.active === "main"}
        tabindex={scratch.active === "main" ? 0 : -1}
        onclick={() => (scratch.active = "main")}>main.c</button
      >
      {#if scratch.headerName}
        <button
          type="button"
          id="scratchtabheader"
          class={scratch.active === "header" ? "tab on" : "tab"}
          role="tab"
          aria-controls="scratchedwrap"
          aria-selected={scratch.active === "header"}
          tabindex={scratch.active === "header" ? 0 : -1}
          onclick={() => (scratch.active = "header")}>{scratch.headerName}</button
        >
      {/if}
    </div>
    <span class="grow"></span>
    {#if !asking}
      {#if scratch.headerName}
        <button type="button" id="scratchrename" class="nav" onclick={() => ask("rename")}>
          Renommer l'en-tête
        </button>
        <button type="button" id="scratchremove" class="nav" onclick={() => ask("remove")}>
          Retirer l'en-tête
        </button>
      {:else}
        <button type="button" id="scratchadd" class="nav" onclick={() => ask("add")}>
          Ajouter un en-tête .h
        </button>
      {/if}
    {/if}
  </div>
  {#if asking === "add" || asking === "rename"}
    <form
      class="scratchname"
      onsubmit={(e) => {
        e.preventDefault();
        confirmName();
      }}
    >
      <label for="scratchheadername">
        {asking === "rename" ? "Nouveau nom de l'en-tête" : "Nom de l'en-tête"}
      </label>
      <!-- svelte-ignore a11y_autofocus -->
      <input
        id="scratchheadername"
        type="text"
        bind:value={proposed}
        placeholder="pile.h"
        autocomplete="off"
        spellcheck="false"
        autofocus
        aria-invalid={!!refusal}
        aria-describedby={refusal ? "scratchnamerefusal" : undefined}
        onkeydown={(e) => {
          if (e.key === "Escape") asking = "";
        }}
      />
      <button type="submit">{asking === "rename" ? "Renommer" : "Ajouter"}</button>
      <button type="button" class="nav" onclick={() => (asking = "")}>Annuler</button>
      {#if refusal}<span id="scratchnamerefusal" class="scratchstate failed">{refusal}</span>{/if}
    </form>
  {:else if asking === "remove"}
    <div class="scratchname" role="group" aria-label="Retirer l'en-tête">
      <span>Retirer {scratch.headerName} ? Son contenu sera perdu.</span>
      <button
        type="button"
        id="scratchremoveconfirm"
        onclick={() => {
          scratch.removeHeader();
          asking = "";
        }}>Retirer</button
      >
      <button type="button" class="nav" onclick={() => (asking = "")}>Garder</button>
    </div>
  {/if}
  {#key scratch.active}
    <CodeSurface
      value={scratch.activeText}
      onInput={(text) => scratch.typed(text)}
      label={(scratch.active === "main" ? "Fichier " : "En-tête ") + scratch.activeName + " de la Console"}
      placeholder={scratch.active === "main" ? "// Écris ton programme C ici" : "// Écris ton en-tête ici"}
      idPrefix="scratch"
      wrapClass="scratchedit"
      wrapRole="tabpanel"
    />
  {/key}
</div>

<div class="plan scratchpan">
  <div class="phead">
    <span>Terminal</span>
    <button type="button" id="scratchgo" disabled={scratch.running} onclick={() => scratch.start()}>
      {scratch.running ? "En cours…" : "Lancer"}
    </button>
    {#if scratch.running}
      <button type="button" id="scratchstop" class="nav" onclick={() => scratch.stop()}>
        Arrêter
      </button>
    {/if}
    <span class="grow"></span>
    <span id="scratchstate" class={"scratchstate" + (scratch.noteFailed ? " failed" : "")}>
      {scratch.note}
    </span>
  </div>
  <!-- The prompt sits right after the output, where the program asked its question. -->
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
  <pre
    bind:this={terminal}
    id="scratchout"
    class="scratchterm"
    role="log"
    aria-label="Terminal de ton programme"
    onclick={() => {
      if (!getSelection()?.toString()) prompt?.focus();
    }}>{#each scratch.output as chunk, i (i)}<span class={chunk.kind}>{chunk.text}</span
      >{/each}{#if scratch.running}<label class="offscreen" for="scratchinput"
        >Entrée pour ton programme</label
      ><input
        bind:this={prompt}
        id="scratchinput"
        class="scratchprompt"
        type="text"
        bind:value={typed}
        autocomplete="off"
        spellcheck="false"
        onkeydown={onPromptKeydown}
      />{:else if !scratch.output.length}<span class="scratchecho"
        >Appuie sur Lancer pour exécuter ton programme.</span
      >{/if}</pre>
  <div class="scratchhint">
    <span>Entrée envoie la ligne · Ctrl+D termine l'entrée · Ctrl+C arrête le programme</span>
    <button
      type="button"
      id="scratcheof"
      class="nav"
      disabled={!scratch.running}
      onclick={() => scratch.endInput()}>Fin d'entrée</button
    >
  </div>
</div>

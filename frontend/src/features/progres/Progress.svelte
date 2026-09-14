<script lang="ts">  import { onMount } from "svelte";
  import { catalog } from "../../lib/state/catalog.svelte";
  import { exercise } from "../../lib/state/exercise.svelte";
  import { statuses } from "../../lib/state/statuses.svelte";
  import { view } from "../../lib/state/view.svelte";
  import { exportGroup } from "../../lib/state/export";
  import {
    gridLabel,
    isGroupExportable,
    lockNote,
    tileState,
    type Collection,
    type Exercise,
  } from "../../lib/domain/catalog";
  import { STATUS_WORD, plural, skillLabel } from "../../lib/domain/labels";
  import { projection } from "./projection.svelte";

  let title: HTMLHeadingElement | undefined = $state();
  onMount(() => title?.focus());

  const p = $derived(projection.payload);

  const CALENDAR_DAYS = 91;

  function calendarStep(attempts: number): string {
    if (!attempts) return "";
    if (attempts >= 8) return "n4";
    if (attempts >= 4) return "n3";
    if (attempts >= 2) return "n2";
    return "n1";
  }

  const calendar = $derived.by(() => {
    const counts: Record<string, number> = {};
    for (const row of p?.practice_days ?? []) {
      if (row && typeof row.date === "string") counts[row.date] = row.attempts | 0;
    }
    const today = new Date();
    const cells: { key: string; step: string; title: string }[] = [];
    for (let back = CALENDAR_DAYS - 1; back >= 0; back--) {
      const day = new Date(today.getTime() - back * 86400000);
      const key = day.toISOString().slice(0, 10);
      const n = counts[key] ?? 0;
      cells.push({
        key,
        step: calendarStep(n),
        title:
          day.toLocaleDateString(undefined, { day: "numeric", month: "long" }) +
          " — " +
          (n ? plural(n, "test") : "aucune pratique"),
      });
    }
    return { cells, active: Object.keys(counts).length };
  });

  const bandTitles = $derived.by(() => {
    const out: Record<string, { title: string; description: string }> = {};
    for (const b of p?.mastery.bands ?? []) out[b.id] = b;
    return out;
  });

  const BAND_ORDER = ["verifie", "en-progression", "a-consolider", "non-verifie"] as const;

  const exerciseLabel = (id: string) => {
    const found = catalog.catalog.find((t) => t.id === id);
    return found ? found.label || found.short || id : id;
  };

  function open(id: string) {
    if (!catalog.catalog.some((t) => t.id === id)) return;
    exercise.open(id);
    view.show("");
  }

  function labTheme(col: Collection): string {
    const skills: string[] = [];
    for (const ex of col.items) {
      for (const skill of ex.learning.skills ?? []) {
        const word = skillLabel(skill);
        if (!skills.includes(word)) skills.push(word);
      }
    }
    return skills.slice(0, 4).join(", ");
  }

  function tile(ex: Exercise) {
    const note = lockNote(ex);
    let state = tileState(ex, !!note, statuses.byExercise);
    const count = statuses.practice[ex.id];
    if (!note && count && count.successes) state = { cls: "reussi", word: "réussi" };
    const tries = count?.attempts
      ? ", " + count.attempts + " tentative" + (count.attempts > 1 ? "s" : "")
      : "";
    const done = statuses.of(ex.id);
    const word = (note || (done ? STATUS_WORD[done] : "") || state.word) + tries;
    return { note, state, word };
  }

  function levelProgress(view: NonNullable<typeof p>): number {
    const span = (view.level.next === null ? view.xp : view.level.next) - view.level.since;
    return span ? Math.round(((view.xp - view.level.since) / span) * 100) : 0;
  }

  const exportNotes = $state<Record<string, { text: string; failed: boolean }>>({});

  async function exportLab(group: string) {
    await exportGroup(catalog.catalog, group, (text, failed) => {
      exportNotes[group] = { text, failed: !!failed };
    });
  }
</script>

<h2 bind:this={title} id="progrestitre" tabindex="-1">Mes progrès</h2>
<p class="aide">
  Cette page n'est visible que par toi. Rien n'est transmis à ton enseignant, et ce n'est
  pas une note.
</p>

{#if !p}
  <p class="rate">{projection.error}</p>
{:else}
  <div class="tableau">
    <div class="bloc plan">
      <div class="kicker">Action suivante</div>
      {#if !p.next}
        <p>
          {p.exercises.total
            ? "Tu as réussi tous les exercices publiés. Rien de neuf à proposer pour l'instant."
            : "Aucun exercice n'est publié pour l'instant."}
        </p>
      {:else}
        {@const what = exerciseLabel(p.next.exercise_id)}
        <p>
          {p.next.skill
            ? "Tu as déjà pratiqué « " +
              skillLabel(p.next.skill) +
              " » : continue avec « " +
              what +
              " »."
            : "Commence par « " + what + " »."}
        </p>
        <button type="button" onclick={() => open(p.next!.exercise_id)}>
          Ouvrir « {what} »
        </button>
      {/if}
    </div>

    <div class="bloc plan">
      <div class="kicker">Maîtrise vérifiée</div>
      {#if !p.mastery.skills.length}
        <p class="aide">Aucune vérification n'est ouverte pour l'instant.</p>
      {:else}
        {@const verified = p.mastery.skills.filter((r) => r.band === "verifie").length}
        <p class="gros">
          {verified} compétence{verified > 1 ? "s" : ""} sur {p.mastery.skills.length}
        </p>
        {#each BAND_ORDER as id}
          {@const named = p.mastery.skills.filter((r) => r.band === id)}
          {#if named.length}
            <p class="bandeligne">
              <span class={"tag" + (id === "verifie" ? " accent" : "")}>
                {bandTitles[id]?.title ?? id}
              </span>
              <span>{named.map((r) => skillLabel(r.id)).join(", ")}</span>
            </p>
          {/if}
        {/each}
      {/if}
    </div>

    <div class="bloc plan">
      <div class="kicker">Ce que tu as pratiqué</div>
      <div class="calendar">
        {#each calendar.cells as cell (cell.key)}
          <span class={cell.step} title={cell.title}></span>
        {/each}
      </div>
      <p>{plural(calendar.active, "jour")} de pratique sur les treize dernières semaines.</p>
      <p class="aide">
        Une case foncée = un jour où tu as testé du code. Il n'y a pas de série à maintenir
        : un trou ne retire rien.
      </p>
    </div>
  </div>
{/if}

<div class="bloc">
  <h3 class="soustitre">Par laboratoire</h3>
  {#if !catalog.collections.some((c) => c.items.length)}
    <p class="aide">Aucun exercice n'est publié pour l'instant.</p>
  {:else}
    <div class="grille">
      {#each catalog.collections.filter((c) => c.items.length) as col (col.titre)}
        {@const openItems = col.items.filter((ex) => !lockNote(ex))}
        {@const done = openItems.filter((ex) => statuses.of(ex.id) === "solved").length}
        <div class="labo">
          <div class="quoi">
            <span class="name">{col.titre}</span>
            {#if labTheme(col)}<span class="theme">{labTheme(col)}</span>{/if}
          </div>
          <div class="tiles">
            {#each col.items as ex (ex.id)}
              {@const t = tile(ex)}
              <button
                type="button"
                class={"tile " + t.state.cls}
                title={ex.short + " — " + t.word}
                aria-disabled={t.note ? "true" : undefined}
                onclick={() => {
                  if (!t.note) open(ex.id);
                }}
              >
                {gridLabel(ex)}
                <span class="horsecran"> — {t.word}</span>
                {#if t.note}<span class="cadenas">🔒</span>{/if}
              </button>
            {/each}
          </div>
          <div class="compte">
            <span>
              {openItems.length
                ? done + " sur " + openItems.length + " réussi" + (done > 1 ? "s" : "")
                : "pas encore ouvert"}
            </span>
            {#if isGroupExportable(catalog.catalog, col.titre)}
              <span class="exportligne">
                <button type="button" class="nav" onclick={() => exportLab(col.titre)}>
                  Exporter le {col.titre} en main.c
                </button>
                <span
                  class={"exportetat" + (exportNotes[col.titre]?.failed ? " rate" : "")}
                  aria-live="polite">{exportNotes[col.titre]?.text ?? ""}</span
                >
              </span>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

{#if p}
  <div class="bloc">
    <h3 class="soustitre">Maîtrise vérifiée</h3>
    {#if !p.mastery.skills.length}
      <p class="aide">
        Aucune vérification n'est ouverte pour l'instant. Ce sont les activités marquées
        « vérification » dans le menu des exercices.
      </p>
    {:else}
      <ul class="competences">
        {#each p.mastery.skills as c (c.id)}
          <li>
            <span class="nom">{skillLabel(c.id)}</span>
            <span class={"bande " + c.band}>{bandTitles[c.band]?.title ?? c.band}</span>
            <span class="chiffres">
              {c.passed} vérification{c.passed > 1 ? "s" : ""} réussie{c.passed > 1 ? "s" : ""}
              sur {c.total}{c.attempted
                ? ", " + c.attempted + " tentée" + (c.attempted > 1 ? "s" : "")
                : ", aucune tentée"}
            </span>
            <span class="jauge" aria-hidden="true">
              <i style={"width:" + (c.total ? Math.round((c.passed / c.total) * 100) : 0) + "%"}></i>
            </span>
          </li>
        {/each}
      </ul>
      <dl class="bandes">
        {#each p.mastery.bands as b (b.id)}
          <dt>{b.title}</dt>
          <dd>{b.description}</dd>
        {/each}
      </dl>
      <p class="aide">
        Une vérification ne rapporte aucun XP : elle dit ce que tu sais refaire, pas
        combien tu as travaillé. Une bande basse ne retire rien et n'est pas une note —
        elle indique où revenir pratiquer.
      </p>
    {/if}
  </div>

  <div class="bloc">
    <h3 class="soustitre">Ce que tu as pratiqué</h3>
    <p>
      {plural(p.exercises.practiced, "exercice")} pratiqué{p.exercises.practiced > 1 ? "s" : ""}
      sur {p.exercises.total} publié{p.exercises.total > 1 ? "s" : ""}, dont
      {p.exercises.solved} réussi{p.exercises.solved > 1 ? "s" : ""}.
    </p>
    {#if !p.skills.length}
      <p class="aide">
        Les exercices que tu as ouverts n'annoncent pas encore de compétence.
      </p>
    {:else}
      <ul class="competences">
        {#each p.skills as c (c.id)}
          <li>
            <span class="nom">{skillLabel(c.id)}</span>
            <span class="chiffres">
              {c.practiced} exercice{c.practiced > 1 ? "s" : ""} pratiqué{c.practiced > 1
                ? "s"
                : ""} sur {c.total}, dont {c.solved} réussi{c.solved > 1 ? "s" : ""}
            </span>
            <span class="jauge" aria-hidden="true">
              <i
                style={"width:" + (c.total ? Math.round((c.practiced / c.total) * 100) : 0) + "%"}
              ></i>
            </span>
          </li>
        {/each}
      </ul>
      <p class="aide">
        « Pratiquée » veut dire que tu as soumis un exercice qui porte cette compétence.
        Ce n'est pas une maîtrise vérifiée.
      </p>
    {/if}
  </div>

  <div class="bloc second">
    <h3 class="soustitre">Niveau et XP</h3>
    <p>
      Niveau {p.level.rank} — {p.xp} XP.{p.level.next === null
        ? " C'est le dernier niveau de la politique en cours."
        : " Encore " + p.level.remaining + " XP avant le niveau " + (p.level.rank + 1) + "."}
    </p>
    <span class="jauge" aria-hidden="true">
      <i style={"width:" + levelProgress(p) + "%"}></i>
    </span>
    <p class="aide">
      Les XP reflètent l'activité de pratique ; ce ne sont ni une note ni une maîtrise
      vérifiée.
    </p>
  </div>

  <div class="bloc">
    <h3 class="soustitre">Accomplissements</h3>
    {#if !p.achievements.length}
      <p class="aide">
        Aucun pour l'instant. Ils arrivent en pratiquant ; aucun n'est obligatoire.
      </p>
    {:else}
      <dl class="succes">
        {#each p.achievements as s (s.id)}
          <dt>{s.title}</dt>
          <dd>
            <span class="quoi">{s.description}</span>
            <time class="quand" datetime={s.unlocked_at}>obtenu le {s.unlocked_at}</time>
          </dd>
        {/each}
      </dl>
    {/if}
  </div>
{/if}

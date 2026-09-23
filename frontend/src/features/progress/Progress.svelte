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
  import { skillLabel, statusWord } from "../../lib/domain/labels";
  import { i18n, t } from "../../lib/i18n.svelte";
  import { projection } from "./projection.svelte";

  const { openView }: { openView: (name: "leaderboard" | "collection") => void } = $props();

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

  const labs = $derived(catalog.collections.filter((c) => c.items.length));

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
          day.toLocaleDateString(i18n.lang, { day: "numeric", month: "long" }) +
          " — " +
          (n ? t("progress.tests", { count: n }) : t("progress.no_practice")),
      });
    }
    return { cells, active: Object.keys(counts).length };
  });


  // The payload's order is the policy's: listing the ids here would hide any band
  // the server adds.
  const bandOrder = $derived((p?.mastery.bands ?? []).map((b) => b.id));

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
    if (!note && count && count.successes) state = { cls: "solved", word: t("status.solved") };
    const tries = count?.attempts ? t("progress.tries", { count: count.attempts }) : "";
    const done = statuses.of(ex.id);
    const word = (note || (done ? statusWord(done) : "") || state.word) + tries;
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

<h2 bind:this={title} id="progresstitle" tabindex="-1">{t("progress.title")}</h2>
<p class="help">{t("progress.private")}</p>

{#if !p}
  <p class="failed">{projection.error}</p>
{:else}
  <div class="board">
    <div class="block plan">
      <div class="kicker">{t("progress.next")}</div>
      {#if !p.next}
        <p>
          {p.exercises.total ? t("progress.all_solved") : t("progress.none_published")}
        </p>
      {:else}
        {@const what = catalog.labelOf(p.next.exercise_id)}
        <p>
          {p.next.skill
            ? t("progress.continue_with", { skill: skillLabel(p.next.skill), exercise: what })
            : t("progress.start_with", { exercise: what })}
        </p>
        <button type="button" onclick={() => open(p.next!.exercise_id)}>
          {t("progress.open", { exercise: what })}
        </button>
      {/if}
    </div>

    <div class="block plan">
      <div class="kicker">{t("progress.mastery")}</div>
      {#if !p.mastery.skills.length}
        <p class="help">{t("progress.no_verification")}</p>
      {:else}
        {@const verified = p.mastery.skills.filter((r) => r.band === "verifie").length}
        <p class="big">
          {t("progress.skills_verified", { count: verified, total: p.mastery.skills.length })}
        </p>
        {#each bandOrder as id}
          {@const named = p.mastery.skills.filter((r) => r.band === id)}
          {#if named.length}
            <p class="bandline">
              <span class={"tag" + (id === "verifie" ? " accent" : "")}>
                {t(`band.${id}.title`)}
              </span>
              <span>{named.map((r) => skillLabel(r.id)).join(", ")}</span>
            </p>
          {/if}
        {/each}
      {/if}
    </div>

    <div class="block plan">
      <div class="kicker">{t("progress.practiced")}</div>
      <div class="calendar">
        {#each calendar.cells as cell (cell.key)}
          <span class={cell.step} title={cell.title}></span>
        {/each}
      </div>
      <p>{t("progress.days", { count: calendar.active })}</p>
      <p class="help">{t("progress.calendar_help")}</p>
    </div>
  </div>
{/if}

<div class="block">
  <h3 class="subtitle">{t("progress.by_lab")}</h3>
  {#if !labs.length}
    <p class="help">{t("progress.none_published")}</p>
  {:else}
    <div class="grid">
      {#each labs as col (col.title)}
        {@const openItems = col.items.filter((ex) => !lockNote(ex))}
        {@const done = openItems.filter((ex) => statuses.of(ex.id) === "solved").length}
        <div class="lab">
          <div class="what">
            <span class="name">{col.title}</span>
            {#if labTheme(col)}<span class="theme">{labTheme(col)}</span>{/if}
          </div>
          <div class="tiles">
            {#each col.items as ex (ex.id)}
              {@const cell = tile(ex)}
              <button
                type="button"
                class={"tile " + cell.state.cls}
                title={ex.short + " — " + cell.word}
                aria-disabled={cell.note ? "true" : undefined}
                onclick={() => {
                  if (!cell.note) open(ex.id);
                }}
              >
                {gridLabel(ex)}
                <span class="offscreen"> — {cell.word}</span>
                {#if cell.note}<span class="padlock">🔒</span>{/if}
              </button>
            {/each}
          </div>
          <div class="count">
            <span>
              {openItems.length
                ? t("progress.lab_solved", { count: done, total: openItems.length })
                : t("catalog.not_open")}
            </span>
            {#if isGroupExportable(catalog.catalog, col.title)}
              <span class="exportline">
                <button type="button" class="nav" onclick={() => exportLab(col.title)}>
                  {t("progress.export", { lab: col.title })}
                </button>
                <span
                  class={"exportstate" + (exportNotes[col.title]?.failed ? " failed" : "")}
                  aria-live="polite">{exportNotes[col.title]?.text ?? ""}</span
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
  <div class="block">
    <h3 class="subtitle">{t("progress.mastery")}</h3>
    {#if !p.mastery.skills.length}
      <p class="help">{t("progress.no_verification_long")}</p>
    {:else}
      <ul class="skills">
        {#each p.mastery.skills as c (c.id)}
          <li>
            <span class="name">{skillLabel(c.id)}</span>
            <span class={"band " + c.band}>{t(`band.${c.band}.title`)}</span>
            <span class="figures">
              {t("progress.checks_passed", { count: c.passed, total: c.total }) +
                (c.attempted
                  ? t("progress.checks_tried", { count: c.attempted })
                  : t("progress.checks_none_tried"))}
            </span>
            <span class="gauge" aria-hidden="true">
              <i style={"width:" + (c.total ? Math.round((c.passed / c.total) * 100) : 0) + "%"}></i>
            </span>
          </li>
        {/each}
      </ul>
      <dl class="bands">
        {#each p.mastery.bands as b (b.id)}
          <dt>{t(`band.${b.id}.title`)}</dt>
          <dd>{t(`band.${b.id}.description`)}</dd>
        {/each}
      </dl>
      <p class="help">{t("progress.mastery_help")}</p>
    {/if}
  </div>

  <div class="block">
    <h3 class="subtitle">{t("progress.practiced")}</h3>
    <p>
      {t("progress.exercises_practiced", {
        count: p.exercises.practiced,
        total: p.exercises.total,
        solved: p.exercises.solved,
      })}
    </p>
    {#if !p.skills.length}
      <p class="help">{t("progress.no_skills")}</p>
    {:else}
      <ul class="skills">
        {#each p.skills as c (c.id)}
          <li>
            <span class="name">{skillLabel(c.id)}</span>
            <span class="figures">
              {t("progress.skill_practiced", { count: c.practiced, total: c.total, solved: c.solved })}
            </span>
            <span class="gauge" aria-hidden="true">
              <i
                style={"width:" + (c.total ? Math.round((c.practiced / c.total) * 100) : 0) + "%"}
              ></i>
            </span>
          </li>
        {/each}
      </ul>
      <p class="help">{t("progress.practiced_help")}</p>
    {/if}
  </div>

  <div class="block second">
    <h3 class="subtitle">{t("progress.level")}</h3>
    <p>
      {t("progress.level_line", { rank: p.level.rank, xp: p.xp }) +
        (p.level.next === null
          ? t("progress.level_last")
          : t("progress.level_next", { remaining: p.level.remaining, next: p.level.rank + 1 }))}
    </p>
    <span class="gauge" aria-hidden="true">
      <i style={"width:" + levelProgress(p) + "%"}></i>
    </span>
    <p class="help">{t("progress.level_help")}</p>
  </div>

  <div class="block">
    <h3 class="subtitle">{t("progress.achievements")}</h3>
    {#if !p.achievements.length}
      <p class="help">{t("progress.no_achievements")}</p>
    {:else}
      <dl class="achievements">
        {#each p.achievements as s (s.id)}
          <dt>{t(`achievement.${s.id}.title`)}</dt>
          <dd>
            <span class="what">{t(`achievement.${s.id}.description`)}</span>
            <time class="when" datetime={s.unlocked_at}>{t("progress.unlocked_on", { date: s.unlocked_at })}</time>
          </dd>
        {/each}
      </dl>
    {/if}
  </div>

  <div class="block second">
    <h3 class="subtitle">{t("progress.elsewhere")}</h3>
    <p class="help">{t("progress.elsewhere_help")}</p>
    <div class="elsewhere">
      <button type="button" class="nav" onclick={() => openView("collection")}>
        {t("progress.my_collection")}
      </button>
      <button type="button" class="nav" onclick={() => openView("leaderboard")}>
        {t("leaderboard.title")}
      </button>
    </div>
  </div>
{/if}

<style>
  .elsewhere {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
  }
</style>

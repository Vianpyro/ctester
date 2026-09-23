<script lang="ts">  import { onMount } from "svelte";
  import { fetchLeaderboard } from "../../lib/api/leaderboard";
  import { redrawAlias } from "../../lib/api/forum";
  import { whenSignedOut } from "../../lib/auth/session.svelte";
  import { t } from "../../lib/i18n.svelte";
  import type { LeaderboardPayload } from "../../lib/api/types";

  let title: HTMLHeadingElement | undefined = $state();
  let payload = $state<LeaderboardPayload | null>(null);
  let error = $state("");
  let said = $state("");
  let scope = $state<"group" | "course">("group");
  let targetGroup = $state<number | null>(null);

  async function load() {
    const answer = await fetchLeaderboard(scope, targetGroup);
    if (!answer || typeof answer.participating !== "boolean") {
      payload = null;
      error = t("leaderboard.unavailable");
      return;
    }
    payload = answer;
    error = "";
  }

  onMount(() => {
    void load();
    title?.focus();
  });

  whenSignedOut(() => {
    payload = null;
    error = "";
    said = "";
  });

  async function openIdentity() {
    const { identity } = await import("../forum/identity.svelte");
    await identity.toggle();
  }

  async function newAlias() {
    const answer = await redrawAlias();
    said = answer.ok ? t("leaderboard.new_alias") : t("leaderboard.alias_failed");
    await load();
  }

  async function pick(next: "group" | "course", group: number | null) {
    scope = next;
    targetGroup = group;
    await load();
  }
</script>

<h2 bind:this={title} id="leaderboardtitle" tabindex="-1">{t("leaderboard.title")}</h2>
<p class="help">{t("leaderboard.intro")}</p>

{#if said}<p class="notice" aria-live="polite">{said}</p>{/if}

{#if !payload}
  <p class="failed">{error}</p>
{:else if !payload.participating && !payload.moderator}
  <div class="block plan">
    <div class="kicker">{t("leaderboard.out.kicker")}</div>
    <p>{t("leaderboard.out.body")}</p>
    <p class="help">{t("leaderboard.out.help")}</p>
    <button type="button" onclick={openIdentity}>{t("leaderboard.open_identity")}</button>
  </div>
{:else}
  {#if payload.moderator && (payload.groups ?? []).length}
    <div class="tabs">
      <button
        type="button"
        class={"nav" + (targetGroup === null ? " on" : "")}
        aria-pressed={targetGroup === null}
        onclick={() => pick("course", null)}>{t("leaderboard.all_groups")}</button
      >
      {#each payload.groups ?? [] as g (g)}
        <button
          type="button"
          class={"nav" + (targetGroup === g ? " on" : "")}
          aria-pressed={targetGroup === g}
          onclick={() => pick("group", g)}
          >{t("leaderboard.group", { n: String(g).padStart(2, "0") })}</button
        >
      {/each}
    </div>
  {:else}
    <div class="tabs">
      {#each [["group", t("leaderboard.my_group")], ["course", t("leaderboard.whole_course")]] as const as [id, label]}
        <button
          type="button"
          class={"nav" + (scope === id ? " on" : "")}
          aria-pressed={scope === id}
          onclick={() => pick(id, targetGroup)}>{label}</button
        >
      {/each}
    </div>
  {/if}

  <div class="block">
    {#if payload.moderator}
      <p>{t("leaderboard.moderator")}</p>
    {:else}
      <p class="aliasrow">
        <span>{t("leaderboard.you_appear_as")}</span>
        <b class="alias-value">{payload.alias || "—"}</b>
        <button type="button" class="nav" onclick={newAlias}>{t("leaderboard.another_name")}</button>
      </p>
      <p class="help">{t("leaderboard.alias_help")}</p>
    {/if}
  </div>

  {#if payload.me}
    <div class="block plan rank">
      <span class="figure">{payload.me.rank}</span>
      <div>
        <p>
          {t(payload.scope === "course" ? "leaderboard.out_of_course" : "leaderboard.out_of_group", {
            count: payload.cohort,
            days: payload.window_days,
          })}
        </p>
        {#if payload.gap}
          <p class="help">
            {payload.gap.solved > 0
              ? t(payload.gap.rank === 1 ? "leaderboard.gap_first" : "leaderboard.gap", {
                  count: payload.gap.solved,
                  rank: payload.gap.rank,
                })
              : t("leaderboard.tied")}
          </p>
        {:else}
          <p class="help">{t("leaderboard.nobody_ahead")}</p>
        {/if}
      </div>
    </div>
  {/if}

  {#if payload.rows.length}
    <div class="block">
      <table class="rank-table">
        <thead>
          <tr>
            <th>#</th><th>{t("leaderboard.col.account")}</th><th>{t("leaderboard.col.solved")}</th>
          </tr>
        </thead>
        <tbody>
          {#each payload.rows as row (row.rank)}
            <tr class={row.mine ? "mine" : ""}>
              <td class="num">{row.rank}</td>
              <td>
                {row.mine
                  ? t("leaderboard.you", { alias: row.alias || t("identity.participant") })
                  : row.alias || t("identity.participant")}
              </td>
              <td class="num">{row.solved}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      <p class="help">{t("leaderboard.table_help")}</p>
    </div>
  {:else}
    <div class="block">
      <p>{t("leaderboard.too_few", { count: payload.cohort, minimum: payload.minimum })}</p>
      <p class="help">{t("leaderboard.too_few_help")}</p>
    </div>
  {/if}

  {#if (payload.divisions ?? []).length}
    <div class="block">
      <h3 class="subtitle">{t("leaderboard.divisions")}</h3>
      <div class="divisions">
        {#each payload.divisions ?? [] as d (d.id)}
          <div class={"division" + (d.id === payload.division?.id ? " on" : "")}>
            <span class="name">{t(`division.${d.id}`)}</span>
            <span class="what">
              {(d.id === payload.division?.id ? t("leaderboard.you_are_here") : "") +
                t("leaderboard.accounts", { count: d.accounts })}
            </span>
          </div>
        {/each}
      </div>
      <p class="help">{t("leaderboard.divisions_help")}</p>
    </div>
  {/if}
{/if}

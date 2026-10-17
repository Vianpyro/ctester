<script lang="ts">
  import "./forum.css";
  import { untrack } from "svelte";
  import { catalog } from "../../lib/state/catalog.svelte";
  import { profile as bar } from "../../lib/state/profile.svelte";
  import { groupNumber, initialsOf, memberName, teamLabel } from "../../lib/domain/labels";
  import { i18n, t } from "../../lib/i18n.svelte";
  import { identity } from "./identity.svelte";
  import type { ForumProfile, ForumProfileIn } from "../../lib/api/types";

  const held = $derived(identity.profile);

  let name = $state("");
  let group = $state("");
  let showName = $state(false);
  let showGroup = $state(false);
  let showBadges = $state(false);
  let joinLeaderboard = $state(false);
  let frame = $state("");

  // What the server holds, in the form's own terms: the measure of what is not saved yet.
  function formOf(p: ForumProfile): ForumProfileIn {
    return {
      display_name: p.display_name || p.suggestion || "",
      group_number: p.group_number === null || p.group_number === undefined ? "" : String(p.group_number),
      display_name_public: p.display_name_public,
      group_number_public: p.group_number_public,
      badges_public: p.badges_public,
      leaderboard_opt_in: p.leaderboard_opt_in,
      plate_frame: p.plate_frame ?? "",
    };
  }

  function seed(p: ForumProfile) {
    const f = formOf(p);
    name = f.display_name;
    group = f.group_number;
    showName = f.display_name_public;
    showGroup = f.group_number_public;
    showBadges = f.badges_public;
    joinLeaderboard = f.leaderboard_opt_in;
    frame = f.plate_frame;
  }

  const form = $derived<ForumProfileIn>({
    display_name: name,
    group_number: group,
    display_name_public: showName,
    group_number_public: showGroup,
    badges_public: showBadges,
    leaderboard_opt_in: joinLeaderboard,
    plate_frame: frame,
  });
  const dirty = $derived(!!held && JSON.stringify(form) !== JSON.stringify(formOf(held)));

  const maskedName = $derived(held?.alias || t("identity.participant"));
  const previewName = $derived(showName ? name.trim() : "");
  const previewGroup = $derived(showGroup ? group.trim() : "");

  const frames = $derived(held?.frames ?? []);

  const assignments = $derived(catalog.assignments.filter((a) => a && a.team));
  // A team still to join is the reason to be here: it comes first. Otherwise it waits at the end.
  const teamFirst = $derived(assignments.some((a) => !identity.teamFor(a.id)));

  let dialog: HTMLDialogElement | undefined = $state();
  let title: HTMLHeadingElement | undefined = $state();

  // Filled when it opens, and only then: drawing a name or joining a team reloads the profile,
  // which must not wipe what the student is typing.
  $effect(() => {
    if (!dialog) return;
    if (bar.identityOpen && !dialog.open) {
      untrack(() => held && seed(held));
      if (dialog.showModal) dialog.showModal();
      else dialog.open = true;
      title?.focus();
    } else if (!bar.identityOpen && dialog.open) {
      if (dialog.close) dialog.close();
      else dialog.open = false;
      document.getElementById("plate")?.focus();
    }
  });

  function requestClose() {
    if (dirty && typeof confirm === "function" && !confirm(t("identity.discard"))) return;
    identity.close();
  }

  async function save() {
    // The server may tidy what it stores (a trimmed name): the form takes its word for it.
    if ((await identity.save(form)) && identity.profile) seed(identity.profile);
  }

  // A click that starts and ends on the backdrop closes; a selection dragged out of a field
  // and released outside does not.
  let pressedOutside = false;
</script>

{#snippet teams()}
  <div class="myteams">
    <h3 class="subtitle">{assignments.length > 1 ? t("identity.my_teams") : t("identity.my_team")}</h3>
    {#if identity.teamWord}<p class="failed">{identity.teamWord}</p>{/if}
    {#if identity.teams === null}
      <p class="failed">{t("identity.teams_unreadable")}</p>
      <p class="help">{t("identity.teams_retry")}</p>
    {:else}
      {#each assignments as assignment (assignment.id)}
        {@const mine = identity.teamFor(assignment.id)}
        {#if mine}
          <div class="team">
            <div class="teamtitle">
              <b>{teamLabel(mine.number)}</b>
              <span class="tag">{groupNumber(mine.group_number)}</span>
              <span class="tag">{mine.assignment_title}</span>
              {#if mine.access !== "available"}
                {@const when = new Date(mine.available_from ?? "")}
                <span class="tag">
                  {isNaN(when.getTime())
                    ? t("catalog.upcoming")
                    : t("catalog.opens_on", {
                        date: when.toLocaleDateString(i18n.lang, {
                          day: "numeric",
                          month: "long",
                        }),
                      })}
                </span>
              {:else}
                <span class="tag ok">{t("identity.frozen")}</span>
              {/if}
            </div>
            <div class="teammembers">
              {#each mine.members as member (member.id)}
                <span class="mate on">
                  <i class="dot" style={"background:" + member.color}></i>
                  <span>{memberName(member)}{member.you ? t("team.you") : ""}</span>
                </span>
              {/each}
            </div>
            {#if !mine.joinable}
              <p class="help">{t("identity.teams_frozen")}</p>
            {/if}
          </div>
        {/if}
        {#if !mine || mine.joinable}
          <div class="teams">
            {#if !identity.available}
              <p class="help">
                {identity.teamWord || t("identity.teams_unavailable")}
              </p>
            {:else}
              <p class="help">
                {t("identity.pick_team", {
                  size:
                    assignment.team!.max > assignment.team!.min
                      ? t("identity.size_range", {
                          min: assignment.team!.min,
                          max: assignment.team!.max,
                        })
                      : assignment.team!.min,
                })}
              </p>
              {#each identity.available.teams as team (team.number)}
                <div class={"teamline" + (team.number === mine?.number ? " on" : "")}>
                  <b class="name">{teamLabel(team.number)}</b>
                  <span class="places">{team.members} / {team.max}</span>
                  <span class="grow"></span>
                  {#if team.number === mine?.number}
                    <span class="tag ok">{t("identity.yours")}</span>
                    <button
                      type="button"
                      class="nav"
                      onclick={() => identity.leave(assignment.id)}>{t("identity.leave")}</button
                    >
                  {:else if team.full}
                    <span class="tag">{t("identity.full")}</span>
                  {:else}
                    <button
                      type="button"
                      class={mine ? "nav" : ""}
                      onclick={() => identity.join(assignment.id, team.number)}
                      >{t("identity.join")}</button
                    >
                  {/if}
                </div>
              {/each}
            {/if}
          </div>
        {/if}
      {/each}
    {/if}
  </div>
{/snippet}

<!-- The dialog itself is the backdrop's only target: its form fills it edge to edge. -->
<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
<dialog
  id="identitypanel"
  aria-labelledby="identitytitle"
  bind:this={dialog}
  oncancel={(e) => {
    e.preventDefault();
    requestClose();
  }}
  onclose={() => {
    if (bar.identityOpen) identity.close();
  }}
  onpointerdown={(e) => (pressedOutside = e.target === dialog)}
  onclick={(e) => {
    if (pressedOutside && e.target === dialog) requestClose();
  }}
>
  <form
    class="idsheet"
    onsubmit={(e) => {
      e.preventDefault();
      if (dirty) void save();
    }}
  >
    <header class="idhead">
      <h2 id="identitytitle" tabindex="-1" bind:this={title}>{t("identity.title")}</h2>
      <button
        type="button"
        id="identityclose"
        class="nav"
        aria-label={t("shortcuts.close")}
        title={t("shortcuts.close")}
        onclick={requestClose}
      ></button>
    </header>

    <div class="idbody">
      {#if !held}
        <p class="failed">{t("identity.unreadable")}</p>
      {:else}
        {#if assignments.length && teamFirst}{@render teams()}{/if}

        <aside class="idpreview" aria-labelledby="idpreviewtitle">
          <h3 class="subtitle" id="idpreviewtitle">{t("identity.preview")}</h3>
          <div class="previewplate">
            <div class={"plate plan" + (frame ? " frame-" + frame : "")}>
              <div class="row">
                <span class="initials">{initialsOf(previewName || maskedName)}</span>
                <span class="name">{previewName || maskedName}</span>
              </div>
              {#if previewGroup || showBadges}
                <div class="tags">
                  {#if previewGroup}<span class="tag">{groupNumber(previewGroup)}</span>{/if}
                  {#if showBadges}<span class="tag accent">{t("identity.badges_visible")}</span>{/if}
                </div>
              {/if}
            </div>
          </div>
          <p class="help">{t("identity.exactly")}</p>
        </aside>

        <div class="idfields">
          <section class="idcard" aria-labelledby="aliaslabel">
            <p class="idlabel" id="aliaslabel">{t("identity.alias")}</p>
            <p class="aliasrow">
              <b class="alias-value">{held.alias || t("identity.not_drawn")}</b>
              <button type="button" class="nav" onclick={() => identity.redraw()}>
                {held.alias ? t("leaderboard.another_name") : t("identity.draw")}
              </button>
            </p>
            <p class="help">{t("identity.alias_help")}</p>
            <p class="help">{t("identity.alias_everywhere")}</p>
          </section>

          <section class="idcard">
            <label class="idlabel" for="forumpseudo">{t("identity.display_name")}</label>
            <input
              id="forumpseudo"
              type="text"
              autocomplete="off"
              maxlength={held.max_display_name || 24}
              placeholder={t("identity.participant")}
              bind:value={name}
            />
            <label class="check" for="forumshowname">
              <input id="forumshowname" type="checkbox" bind:checked={showName} />
              <span>{t("identity.show_name")}</span>
            </label>
            {#if !held.display_name && held.suggestion}
              <p class="help">{t("identity.suggested")}</p>
            {/if}
            <p class="help">{t("identity.unticked")}</p>
          </section>

          <section class="idcard">
            <label class="idlabel" for="forumgroup">{t("identity.group")}</label>
            {#if held.group_numbers.length}
              <select id="forumgroup" bind:value={group}>
                <option value="">{t("identity.none")}</option>
                {#each held.group_numbers as g (g)}
                  <option value={String(g)}>{groupNumber(g)}</option>
                {/each}
              </select>
            {:else}
              <input id="forumgroup" type="number" min="1" max="99" bind:value={group} />
            {/if}
            <label class="check" for="forumshowgroup">
              <input id="forumshowgroup" type="checkbox" bind:checked={showGroup} />
              <span>{t("identity.show_group")}</span>
            </label>
          </section>

          <section class="idcard">
            {#if frames.length >= 2}
              <label class="idlabel" for="forumframe">{t("identity.frame")}</label>
              <select id="forumframe" bind:value={frame}>
                <option value="">{t("identity.none")}</option>
                {#each frames as f (f.id)}<option value={f.id}>{t(`frame.${f.id}`)}</option>{/each}
              </select>
            {/if}
            <label class="check" for="forumshowplate">
              <input id="forumshowplate" type="checkbox" bind:checked={showBadges} />
              <span>{t("identity.show_badges")}</span>
            </label>
          </section>

          <section class="idcard">
            <label class="check" for="forumleaderboard">
              <input id="forumleaderboard" type="checkbox" bind:checked={joinLeaderboard} />
              <span>{t("identity.join_leaderboard")}</span>
            </label>
          </section>
        </div>

        {#if assignments.length && !teamFirst}{@render teams()}{/if}
      {/if}
    </div>

    <footer class="idfoot">
      <p class="idstate" aria-live="polite">{dirty ? t("identity.unsaved") : identity.said}</p>
      <button type="submit" id="identitysave" disabled={!dirty}>{t("identity.save")}</button>
      <button type="button" class="nav" onclick={requestClose}>{t("shortcuts.close")}</button>
    </footer>
  </form>
</dialog>

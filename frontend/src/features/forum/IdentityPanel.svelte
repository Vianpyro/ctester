<script lang="ts">  import { barPanel } from "../../lib/barPanel";
  import { catalog } from "../../lib/state/catalog.svelte";
  import { profile as bar } from "../../lib/state/profile.svelte";
  import { groupNumber, initialsOf, memberName, teamLabel } from "../../lib/domain/labels";
  import { i18n, t } from "../../lib/i18n.svelte";
  import { identity } from "./identity.svelte";
  import type { ForumProfileIn } from "../../lib/api/types";

  const held = $derived(identity.profile);

  let name = $state("");
  let group = $state("");
  let showName = $state(false);
  let showGroup = $state(false);
  let showBadges = $state(false);
  let joinLeaderboard = $state(false);
  let frame = $state("");
  let seeded = $state("");

  $effect(() => {
    const p = identity.profile;
    if (!p || seeded === (p.alias ?? "") + "|" + (p.display_name ?? "")) return;
    seeded = (p.alias ?? "") + "|" + (p.display_name ?? "");
    name = p.display_name || p.suggestion || "";
    group = p.group_number === null || p.group_number === undefined ? "" : String(p.group_number);
    showName = p.display_name_public;
    showGroup = p.group_number_public;
    showBadges = p.badges_public;
    joinLeaderboard = p.leaderboard_opt_in;
    frame = p.plate_frame ?? "";
  });

  const form = $derived<ForumProfileIn>({
    display_name: name,
    group_number: group,
    display_name_public: showName,
    group_number_public: showGroup,
    badges_public: showBadges,
    leaderboard_opt_in: joinLeaderboard,
    plate_frame: frame,
  });

  const maskedName = $derived(held?.alias || t("identity.participant"));
  const previewName = $derived(showName ? name.trim() : "");
  const previewGroup = $derived(showGroup ? group.trim() : "");

  const frames = $derived(held?.frames ?? []);

  const assignments = $derived(catalog.assignments.filter((a) => a && a.team));
</script>

<div id="identitypanel" use:barPanel hidden={!bar.identityOpen}>
  <div>
    <h2>{t("identity.title")}</h2>
    {#if identity.said}<p class="notice">{identity.said}</p>{/if}

    {#if !held}
      <p class="failed">{t("identity.unreadable")}</p>
      <div class="row">
        <button type="button" class="nav" onclick={() => identity.close()}>{t("shortcuts.close")}</button>
      </div>
    {:else}
      {#if assignments.length}
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
      {/if}

      <label for="forumpseudo">{t("identity.display_name")}</label>
      <input
        id="forumpseudo"
        type="text"
        autocomplete="off"
        maxlength={held.max_display_name || 24}
        placeholder={t("identity.participant")}
        bind:value={name}
      />

      <label for="forumgroup">{t("identity.group")}</label>
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

      {#if frames.length >= 2}
        <label for="forumframe">{t("identity.frame")}</label>
        <select id="forumframe" bind:value={frame}>
          <option value="">{t("identity.none")}</option>
          {#each frames as f (f.id)}<option value={f.id}>{t(`frame.${f.id}`)}</option>{/each}
        </select>
      {/if}

      <div>
        <label for="alias-value">{t("identity.alias")}</label>
        <p class="aliasrow">
          <b class="alias-value" id="alias-value">{held.alias || t("identity.not_drawn")}</b>
          <button type="button" class="nav" onclick={() => identity.redraw()}>
            {held.alias ? t("leaderboard.another_name") : t("identity.draw")}
          </button>
        </p>
        <p class="help">{t("identity.alias_help")}</p>
        <p class="help">{t("identity.alias_everywhere")}</p>
      </div>

      <label class="check" for="forumshowname">
        <input id="forumshowname" type="checkbox" bind:checked={showName} />
        <span>{t("identity.show_name")}</span>
      </label>
      <label class="check" for="forumshowgroup">
        <input id="forumshowgroup" type="checkbox" bind:checked={showGroup} />
        <span>{t("identity.show_group")}</span>
      </label>
      <label class="check" for="forumshowplate">
        <input id="forumshowplate" type="checkbox" bind:checked={showBadges} />
        <span>{t("identity.show_badges")}</span>
      </label>
      <label class="check" for="forumleaderboard">
        <input id="forumleaderboard" type="checkbox" bind:checked={joinLeaderboard} />
        <span>{t("identity.join_leaderboard")}</span>
      </label>

      {#if !held.display_name && held.suggestion}
        <p class="help">{t("identity.suggested")}</p>
      {/if}
      <p class="help">{t("identity.unticked")}</p>

      <h3 class="subtitle">{t("identity.preview")}</h3>
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

      <div class="row">
        <button type="button" onclick={() => identity.save(form)}>{t("identity.save")}</button>
        <button type="button" class="nav" onclick={() => identity.close()}>{t("shortcuts.close")}</button>
      </div>
    {/if}
  </div>
</div>

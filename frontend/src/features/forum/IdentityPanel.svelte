<script lang="ts">  import { barPanel } from "../../lib/barPanel";
  import { catalog } from "../../lib/state/catalog.svelte";
  import { profile as bar } from "../../lib/state/profile.svelte";
  import { groupNumber, initialsOf } from "../../lib/domain/labels";
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

  const maskedName = $derived(held?.alias || "Participant");
  const previewName = $derived(showName ? name.trim() : "");
  const previewGroup = $derived(showGroup ? group.trim() : "");

  const frames = $derived(held?.frames ?? []);

  const assignments = $derived(catalog.assignments.filter((a) => a && a.team));
</script>

<div id="identitepanneau" use:barPanel hidden={!bar.identityOpen}>
  <div>
    <h2>Mon identité</h2>
    {#if identity.said}<p class="annonce">{identity.said}</p>{/if}

    {#if !held}
      <p class="rate">Ton identité n'a pas pu être lue.</p>
      <div class="row">
        <button type="button" class="nav" onclick={() => identity.close()}>Fermer</button>
      </div>
    {:else}
      {#if assignments.length}
        <div class="mesequipes">
          <h3 class="soustitre">{assignments.length > 1 ? "Mes équipes" : "Mon équipe"}</h3>
          {#if identity.teamWord}<p class="rate">{identity.teamWord}</p>{/if}
          {#if identity.teams === null}
            <p class="rate">La liste de tes équipes n'a pas pu être lue.</p>
            <p class="aide">
              Réessaie dans un instant. Si ça persiste, préviens ton enseignant : ce n'est
              pas toi, c'est le service.
            </p>
          {:else}
            {#each assignments as assignment (assignment.id)}
              {@const mine = identity.teamFor(assignment.id)}
              {#if mine}
                <div class="equipe">
                  <div class="equipetitre">
                    <b>{mine.label}</b>
                    <span class="tag">{groupNumber(mine.group_number)}</span>
                    <span class="tag">{mine.assignment_title}</span>
                    {#if mine.access !== "available"}
                      {@const when = new Date(mine.available_from ?? "")}
                      <span class="tag">
                        {isNaN(when.getTime())
                          ? "à venir"
                          : "ouvre le " +
                            when.toLocaleDateString(undefined, { day: "numeric", month: "long" })}
                      </span>
                    {:else}
                      <span class="tag ok">figée</span>
                    {/if}
                  </div>
                  <div class="equipegens">
                    {#each mine.members as member (member.id)}
                      <span class="mate on">
                        <i class="dot" style={"background:" + member.color}></i>
                        <span>{member.name}{member.you ? " (toi)" : ""}</span>
                      </span>
                    {/each}
                  </div>
                  {#if !mine.joinable}
                    <p class="aide">
                      Le devoir est ouvert : les équipes sont figées. Si la tienne est
                      fausse, vois avec ton enseignant.
                    </p>
                  {/if}
                </div>
              {/if}
              {#if !mine || mine.joinable}
                <div class="equipes">
                  {#if !identity.available}
                    <p class="aide">
                      {identity.teamWord ||
                        "La liste des équipes n'est pas disponible pour l'instant."}
                    </p>
                  {:else}
                    <p class="aide">
                      Choisis ton équipe, la même que sur Moodle. Vous serez {assignment.team!
                        .min}{assignment.team!.max > assignment.team!.min
                        ? " à " + assignment.team!.max
                        : ""} ; tu peux en changer tant que le devoir n'est pas ouvert.
                    </p>
                    {#each identity.available.teams as team (team.number)}
                      <div class={"equipeligne" + (team.number === mine?.number ? " on" : "")}>
                        <b class="nom">{team.name}</b>
                        <span class="places">{team.members} / {team.max}</span>
                        <span class="grow"></span>
                        {#if team.number === mine?.number}
                          <span class="tag ok">la tienne</span>
                          <button
                            type="button"
                            class="nav"
                            onclick={() => identity.leave(assignment.id)}>Quitter</button
                          >
                        {:else if team.full}
                          <span class="tag">complète</span>
                        {:else}
                          <button
                            type="button"
                            class={mine ? "nav" : ""}
                            onclick={() => identity.join(assignment.id, team.number)}
                            >Rejoindre</button
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

      <label for="forumpseudo">Nom affiché (facultatif)</label>
      <input
        id="forumpseudo"
        type="text"
        autocomplete="off"
        maxlength={held.max_display_name || 24}
        placeholder="Participant"
        bind:value={name}
      />

      <label for="forumgroupe">Groupe (facultatif)</label>
      {#if held.group_numbers.length}
        <select id="forumgroupe" bind:value={group}>
          <option value="">— aucun —</option>
          {#each held.group_numbers as g}
            <option value={String(g)}>{groupNumber(g)}</option>
          {/each}
        </select>
      {:else}
        <input id="forumgroupe" type="number" min="1" max="99" bind:value={group} />
      {/if}

      {#if frames.length >= 2}
        <label for="forumcadre">Cadre de plaque</label>
        <select id="forumcadre" bind:value={frame}>
          <option value="">— aucun —</option>
          {#each frames as f (f.id)}<option value={f.id}>{f.title}</option>{/each}
        </select>
      {/if}

      <div>
        <label for="alias-value">Mon nom masqué (tiré au hasard)</label>
        <p class="aliasrow">
          <b class="alias-value" id="alias-value">{held.alias || "pas encore tiré"}</b>
          <button type="button" class="nav" onclick={() => identity.redraw()}>
            {held.alias ? "Un autre nom" : "Tirer un nom"}
          </button>
        </p>
        <p class="aide">
          C'est sous ce nom que tu apparais dans le chat et au classement tant que tu
          n'affiches pas le tien. Il est tiré d'une liste fermée — personne ne peut écrire
          ce qu'il veut.
        </p>
        <p class="aide">
          Le changer remplace ton nom partout, y compris sur tes messages déjà publiés.
        </p>
      </div>

      <label class="coche" for="forumvoirnom">
        <input id="forumvoirnom" type="checkbox" bind:checked={showName} />
        <span>Afficher mon nom dans les discussions</span>
      </label>
      <label class="coche" for="forumvoirgroupe">
        <input id="forumvoirgroupe" type="checkbox" bind:checked={showGroup} />
        <span>Afficher mon numéro de groupe</span>
      </label>
      <label class="coche" for="forumshowplate">
        <input id="forumshowplate" type="checkbox" bind:checked={showBadges} />
        <span>Afficher ma plaque et mes écussons</span>
      </label>
      <label class="coche" for="forumleaderboard">
        <input id="forumleaderboard" type="checkbox" bind:checked={joinLeaderboard} />
        <span>Participer au classement de mon groupe</span>
      </label>

      {#if !held.display_name && held.suggestion}
        <p class="aide">
          Nom proposé par ta connexion — modifie-le si tu veux, il ne s'affiche qu'une fois
          enregistré et coché.
        </p>
      {/if}
      <p class="aide">
        Décoché, ton vrai nom n'apparaît nulle part : tu écris sous ton nom masqué
        ci-dessus. L'enseignant, lui, voit toujours ton numéro de groupe — jamais ton nom
        si tu ne l'affiches pas.
      </p>

      <h3 class="soustitre">Aperçu</h3>
      <div class="previewplate">
        <div class={"plate plan" + (frame ? " frame-" + frame : "")}>
          <div class="row">
            <span class="initials">{initialsOf(previewName || maskedName)}</span>
            <span class="name">{previewName || maskedName}</span>
          </div>
          {#if previewGroup || showBadges}
            <div class="tags">
              {#if previewGroup}<span class="tag">{groupNumber(previewGroup)}</span>{/if}
              {#if showBadges}<span class="tag accent">écussons visibles</span>{/if}
            </div>
          {/if}
        </div>
      </div>
      <p class="aide">Voilà exactement ce que les autres verront.</p>

      <div class="row">
        <button type="button" onclick={() => identity.save(form)}>Enregistrer</button>
        <button type="button" class="nav" onclick={() => identity.close()}>Fermer</button>
      </div>
    {/if}
  </div>
</div>

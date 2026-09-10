// "MON IDENTITÉ": the name, the group, what is shown, the masked name, and the team.
//
// IT LIVES IN THE COMPTE MENU, NOT IN THE THREAD. It is a SETTING: in the thread's
// column it pushed the charter and the post form further down on every visit. One
// place, so one place where visibility can differ from what the database says.
//
// THE IDENTITY IS CHOSEN, OPTIONAL, AND INVISIBLE BY DEFAULT. Nothing appears without
// its owner having ticked a box -- with one exception, written into the form: THE
// INSTRUCTOR SEES THE GROUP NUMBER AT ALL TIMES, never the name if it is not shown.
//
// WRITING A PROFILE REWRITES IT IN FULL. The last row IS the profile: a partial write
// would reset the fields it omits, and the one it would reset most often is a
// visibility checkbox.
//
// THE MASKED NAME IS DRAWN FROM A CLOSED VOCABULARY SERVER-SIDE, so nothing anyone
// typed can reach it -- which is why there is no pseudonym to moderate. It is
// RETROACTIVE, and that is a property: the profile is append-only and the last row
// wins, so changing it renames the displayed author of one's whole history. The form
// says so before the click.

import { fetchProfile, redrawAlias, saveProfile } from "../../lib/api/forum";
import {
  fetchAvailable,
  fetchMyTeams,
  joinTeam,
  leaveTeam,
} from "../../lib/api/team";
import { refusal } from "../../lib/api/client";
import { session, whenSignedOut } from "../../lib/auth/session.svelte";
import { catalog } from "../../lib/state/catalog.svelte";
import { profile as bar } from "../../lib/state/profile.svelte";
import type { AvailableTeams, ForumProfile, ForumProfileIn, MyTeam } from "../../lib/api/types";

class Identity {
  /** `null` until read -- we do not invent an empty profile, which would amount to
   *  announcing "you have no name" during an outage. */
  profile = $state<ForumProfile | null>(null);
  said = $state("");

  /**
   * THE TEAMS ARE READ HERE BECAUSE THIS IS THE "WHO AM I" SCREEN. They are NOT a
   * setting: nothing in this panel can change one after the assignment opens, and that
   * is the point -- a student who could pick their team would pick the one whose work is
   * furthest along. What they can do is notice they are in the wrong one and say so,
   * BEFORE the assignment opens.
   *
   * `null` means "not read" and `[]` means "no team": the two do not read the same, and
   * confusing them would announce "you have no team" to somebody who has one, during an
   * outage.
   */
  teams = $state<MyTeam[] | null>(null);
  /** `GET /team/available`, or null with the reason in `teamWord`. */
  available = $state<AvailableTeams | null>(null);
  teamWord = $state("");

  async load(): Promise<void> {
    if (!session.signedIn) return;
    const mine = await fetchProfile();
    this.profile = mine ?? null;
    // The bar's plate reads what was actually saved, so what one sees in one's own bar
    // is what others see in a thread.
    bar.set(this.profile);
    const teams = await fetchMyTeams();
    this.teams = teams && Array.isArray(teams.teams) ? teams.teams : null;
    this.available = null;
    // ONE EXTRA REQUEST, AND ONLY IF THERE IS A TEAM ASSIGNMENT: a deployment without
    // one pays nothing for this.
    const assignment = catalog.assignments.find((a) => a && a.team);
    const held = assignment ? (this.teams ?? []).find((e) => e.assignment_id === assignment.id) : null;
    if (assignment && (!held || held.joinable)) await this.loadAvailable(assignment.id);
  }

  async loadAvailable(assignmentId: string): Promise<void> {
    const answer = await fetchAvailable(assignmentId);
    if (answer.ok && answer.body) {
      this.available = answer.body;
      return;
    }
    this.available = null;
    // THE SERVER'S MESSAGE, NOT OURS: only it knows whether the assignment is open,
    // whether the group is missing, or whether the database is silent.
    this.teamWord = (answer.body as { error?: string } | null)?.error ?? "";
  }

  teamFor(assignmentId: string): MyTeam | null {
    return (this.teams ?? []).find((e) => e.assignment_id === assignmentId) ?? null;
  }

  async join(assignmentId: string, number: number): Promise<void> {
    await this.#teamAction(() => joinTeam(assignmentId, number));
  }

  async leave(assignmentId: string): Promise<void> {
    await this.#teamAction(() => leaveTeam(assignmentId));
  }

  async #teamAction(call: () => ReturnType<typeof joinTeam>): Promise<void> {
    const answer = await call();
    if (answer.status === 0) {
      this.teamWord = "Le serveur ne répond pas. Réessaie dans un instant.";
    } else if (!answer.ok) {
      this.teamWord =
        (answer.body as { error?: string } | null)?.error ??
        "Ça n'a pas marché. Réessaie dans un instant.";
    } else {
      this.teamWord = "";
      this.available = answer.body;
    }
    await this.load();
  }

  async save(form: ForumProfileIn): Promise<boolean> {
    const answer = await saveProfile(form);
    const ok = answer.ok;
    this.said = ok
      ? "Identité enregistrée."
      : "Identité non enregistrée : " + refusal(answer, "refusé");
    await this.load();
    return ok;
  }

  async redraw(): Promise<void> {
    const answer = await redrawAlias();
    this.said = answer.ok ? "Nouveau pseudonyme." : "Le pseudonyme n'a pas pu être changé.";
    await this.load();
  }

  async toggle(): Promise<void> {
    if (bar.identityOpen) {
      this.close();
      return;
    }
    this.said = "";
    await this.load();
    bar.identityOpen = true;
  }

  close(): void {
    this.said = "";
    bar.identityOpen = false;
  }

  forget(): void {
    this.profile = null;
    this.teams = null;
    this.available = null;
    this.said = "";
    this.teamWord = "";
    this.close();
  }
}

export const identity = new Identity();

whenSignedOut(() => identity.forget());

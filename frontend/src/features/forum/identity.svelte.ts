import { fetchProfile, redrawAlias, saveProfile } from "../../lib/api/forum";
import { t } from "../../lib/i18n.svelte";
import {
  fetchAvailable,
  fetchMyTeams,
  joinTeam,
  leaveTeam,
} from "../../lib/api/team";
import { refusal, serverMessage } from "../../lib/api/client";
import { session, whenSignedOut } from "../../lib/auth/session.svelte";
import { catalog } from "../../lib/state/catalog.svelte";
import { profile as bar } from "../../lib/state/profile.svelte";
import type { AvailableTeams, ForumProfile, ForumProfileIn, MyTeam } from "../../lib/api/types";

class Identity {
  profile = $state<ForumProfile | null>(null);
  said = $state("");

  teams = $state<MyTeam[] | null>(null);
  available = $state<AvailableTeams | null>(null);
  teamWord = $state("");

  async load(): Promise<void> {
    if (!session.signedIn) return;
    const mine = await fetchProfile();
    this.profile = mine ?? null;
    bar.set(this.profile);
    const teams = await fetchMyTeams();
    this.teams = teams && Array.isArray(teams.teams) ? teams.teams : null;
    this.available = null;
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
    this.teamWord = serverMessage(answer.body);
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
      this.teamWord = t("identity.server_down");
    } else if (!answer.ok) {
      this.teamWord = serverMessage(answer.body) || t("identity.failed");
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
      ? t("identity.saved")
      : t("identity.not_saved", { reason: refusal(answer, t("identity.refused")) });
    await this.load();
    return ok;
  }

  async redraw(): Promise<void> {
    const answer = await redrawAlias();
    this.said = answer.ok ? t("leaderboard.new_alias") : t("leaderboard.alias_failed");
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

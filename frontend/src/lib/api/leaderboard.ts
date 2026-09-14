import { authGet } from "../auth/session.svelte";
import type { LeaderboardPayload } from "./types";

export function fetchLeaderboard(
  scope: "group" | "course",
  group: number | null,
): Promise<LeaderboardPayload | null> {
  const targeted = group === null ? "" : "&group=" + encodeURIComponent(String(group));
  return authGet<LeaderboardPayload>("leaderboard?scope=" + encodeURIComponent(scope) + targeted);
}

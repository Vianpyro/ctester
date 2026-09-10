// THE OPTIONAL LEADERBOARD. NOTHING IS COMPUTED CLIENT-SIDE: ranks, the gap to
// the row above, the cohort threshold and the divisions all arrive decided. A
// page that ranked itself would be a page where one ranks oneself from the
// console, and this is the one screen where that would be worth doing.
//
// `?group=` IS ONLY HONOURED FOR A MODERATOR, and the role is recomputed
// server-side. For a student it is IGNORED, not refused: it is a convenience
// parameter, and a 403 would make a shared link look like an outage.
//
// The opt-in lives on the PROFILE (`POST /forum/profil`), not here: joining a
// ranking is an identity setting, next to "show my name" and "show my group".

import { authGet } from "../auth/session.svelte";
import type { LeaderboardPayload } from "./types";

export function fetchLeaderboard(
  scope: "group" | "course",
  group: number | null,
): Promise<LeaderboardPayload | null> {
  const targeted = group === null ? "" : "&group=" + encodeURIComponent(String(group));
  return authGet<LeaderboardPayload>("leaderboard?scope=" + encodeURIComponent(scope) + targeted);
}

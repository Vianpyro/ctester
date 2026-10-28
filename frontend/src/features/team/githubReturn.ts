import { linkGitHub } from "../../lib/api/github";
import { serverMessage } from "../../lib/api/client";
import { GITHUB_STATE_KEY, RETURN_KEY } from "../../lib/auth/keys";
import { system } from "../../lib/state/system.svelte";
import { sessionDrop } from "../../lib/storage";
import { t } from "../../lib/i18n.svelte";

export async function finishGitHubLink(code: string): Promise<void> {
  sessionDrop(GITHUB_STATE_KEY);
  sessionDrop(RETURN_KEY);
  const answer = await linkGitHub(code);
  if (answer.ok) system.say(t("github.linked"));
  else system.say(serverMessage(answer.body) || t("github.link_failed"), true);
}

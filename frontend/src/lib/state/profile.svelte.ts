import { forgetMe } from "../api/account";
import { t } from "../i18n.svelte";
import { session, signOut, whenSignedOut } from "../auth/session.svelte";
import { system } from "./system.svelte";
import type { ForumProfile } from "../api/types";

class ProfileState {
  plate = $state<ForumProfile | null>(null);
  consentOpen = $state(false);
  menuOpen = $state(false);
  identityOpen = $state(false);

  set(profile: ForumProfile | null): void {
    this.plate = profile;
  }

  askConsent(): void {
    this.consentOpen = true;
  }

  cancelConsent(): void {
    this.consentOpen = false;
  }

  async startSignIn(): Promise<void> {
    this.consentOpen = false;
    try {
      const { startSignIn } = await import("../auth/oidc");
      await startSignIn();
    } catch (e) {
      system.say(
        t("profile.signin_failed", { reason: e instanceof Error ? e.message : String(e) }),
        true,
      );
    }
  }

  signOut(): void {
    this.menuOpen = false;
    signOut();
  }

  async deleteAccount(): Promise<void> {
    if (!session.signedIn) return;
    this.menuOpen = false;
    const answer = await forgetMe();
    if (answer.ok) signOut();
    system.say(
      answer.ok
        ? t("profile.deleted")
        : t("profile.delete_failed"),
      !answer.ok,
    );
  }
}

export const profile = new ProfileState();

whenSignedOut(() => {
  profile.plate = null;
  profile.identityOpen = false;
  profile.menuOpen = false;
});

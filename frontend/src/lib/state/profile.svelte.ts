import { forgetMe } from "../api/account";
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
        "La connexion n'a pas pu démarrer : " +
          (e instanceof Error ? e.message : String(e)) +
          ". Tu peux continuer sans compte : tout fonctionne pareil.",
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
        ? "Tes données ont été supprimées du serveur."
        : "Suppression impossible pour l'instant : réessaie plus tard.",
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

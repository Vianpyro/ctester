// THE ACCOUNT AS THE BAR SEES IT: the plate, the consent panel, and the two
// destructive actions.
//
// THE PLATE IS PUSHED HERE, NEVER PULLED FROM HERE. The identity form owns the
// profile and writes what it saved into this module, so what one sees in one's own
// bar is exactly what others see in a thread -- one place where visibility can differ
// from what the database says, not two. The direction stays one-way, and the anonymous
// visitor triggers nothing.
//
// EVERY PIECE OF THE PLATE IS OPTIONAL, and empty is the default: an account that
// chose nothing reads "Compte", not a name guessed from a token claim.

import { forgetMe } from "../api/account";
import { session, signOut, whenSignedOut } from "../auth/session.svelte";
import { system } from "./system.svelte";
import type { ForumProfile } from "../api/types";

class ProfileState {
  plate = $state<ForumProfile | null>(null);
  /** The consent panel shown before redirecting to the issuer. */
  consentOpen = $state(false);
  menuOpen = $state(false);
  /** The identity panel -- a floating card in the Compte menu, not in the thread. */
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

  /**
   * AWAITED, NOT FIRED INTO THE VOID. Signing in does a network discovery then a PKCE
   * challenge: without the await, a failure becomes a rejected promise nobody reads
   * and the button does NOTHING -- no redirect, no message. That is the failure that
   * was actually observed.
   */
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

  /**
   * SIGN OUT FIRST, ANNOUNCE AFTER. Signing out goes back through the exercise view,
   * which rewrites the result area with its waiting message: announced before, the
   * deletion confirmation used to be erased within a millisecond and the student never
   * saw that their request had gone through.
   */
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

// THE PLATE AND THE PANELS LEAVE WITH THE SESSION: they carry somebody's name, and
// signing out must not leave either on screen.
whenSignedOut(() => {
  profile.plate = null;
  profile.identityOpen = false;
  profile.menuOpen = false;
});

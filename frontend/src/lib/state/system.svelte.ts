// TWO CHANNELS, AND THEY MUST NEVER BE CONFUSED AGAIN.
//
// THE VERDICT TALKS ABOUT THE STUDENT'S CODE. THE SYSTEM BANNER TALKS ABOUT THE
// SERVICE. A single red box used to serve both: "your file does not compile" and
// "the server is unreachable" displayed identically, in the same place, in the
// same title typography. A beginner concludes they broke something -- a false
// attribution of blame, in exactly the situations where it is not their fault.
//
// Network, quota, a full queue, the session key, a module that did not arrive,
// signing in: everything the student is not responsible for goes here. Neutral
// tone, never in the verdict's spot, and always a sentence saying what is NOT
// lost.

class SystemChannel {
  text = $state("");
  /** True paints it as a failure. A quota countdown is not a failure. */
  failed = $state(false);

  /**
   * WHAT IS ANNOUNCED TO SCREEN READERS, AND NOTHING ELSE: one short line. The
   * verdict box deliberately has NO `aria-live` -- it carries the compiler's
   * output, and announcing all of it would be worse than silence.
   */
  announcement = $state("");

  /**
   * LE BANDEAU EST EMPRUNTÉ, PAS PRIS. `flash()` garde ce qu'il a trouvé et le
   * remet en place à l'expiration -- un message de quota ou de panne posé avant
   * n'est donc jamais effacé par un accusé de réception.
   */
  #held: { text: string; failed: boolean } | null = null;
  #timer: ReturnType<typeof setTimeout> | null = null;
  /** Ce qui rend un minuteur déjà parti inopérant. Voir `say()`. */
  #token = 0;

  /**
   * Un message bref, qui s'efface tout seul.
   *
   * IL N'Y A PAS DE TOAST DANS CETTE PAGE, ET IL N'EN FAUT PAS. Le bandeau
   * `#systeme` est déjà rendu, déjà stylé, déjà annoncé aux lecteurs d'écran et
   * déjà à sa place sous la barre. Un composant flottant de plus, ce serait un
   * `z-index` de plus à arbitrer contre le dock du chat, pour dire une phrase.
   */
  flash(text: string, ms = 2500): void {
    // CAPTURÉ UNE SEULE FOIS, ET C'EST L'INVARIANT QUI TIENT TOUT LE RESTE.
    // Sans cette garde, un second flash sauvegarderait le texte du PREMIER et
    // le restaurerait pour de bon : le bandeau resterait coincé sur
    // « déjà enregistré » jusqu'au rechargement de la page.
    if (!this.#held) this.#held = { text: this.text, failed: this.failed };
    if (this.#timer) clearTimeout(this.#timer);
    const mine = ++this.#token;
    this.text = text;
    this.failed = false;
    this.announce(text);
    this.#timer = setTimeout(() => {
      if (this.#token !== mine) return;
      this.text = this.#held!.text;
      this.failed = this.#held!.failed;
      this.#held = null;
      this.#timer = null;
      // REMIS À VIDE POUR QUE LE PROCHAIN FLASH SOIT UN VRAI CHANGEMENT :
      // `aria-live` ne relit pas une chaîne identique, donc un second Ctrl+S
      // quelques secondes plus tard resterait muet.
      this.announcement = "";
    }, ms);
  }

  /**
   * UN VRAI MESSAGE GAGNE SUR UN FLASH, TOUT DE SUITE ET POUR DE BON. Le jeton
   * incrémenté rend le minuteur en vol inopérant : sans lui, un message de
   * quota posé 200 ms après un « déjà enregistré » serait balayé deux secondes
   * plus tard, et l'étudiant n'en verrait qu'un éclair.
   */
  say(text: string, failed = false): void {
    this.#abandon();
    this.text = text || "";
    this.failed = !!failed;
    if (text) this.announce(text);
  }

  clear(): void {
    this.#abandon();
    this.text = "";
    this.failed = false;
  }

  /** Le flash en vol, s'il y en a un, n'a plus rien à restaurer. */
  #abandon(): void {
    this.#token++;
    if (this.#timer) clearTimeout(this.#timer);
    this.#timer = null;
    this.#held = null;
  }

  announce(text: string): void {
    this.announcement = text;
  }
}

export const system = new SystemChannel();

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

  say(text: string, failed = false): void {
    this.text = text || "";
    this.failed = !!failed;
    if (text) this.announce(text);
  }

  clear(): void {
    this.text = "";
    this.failed = false;
  }

  announce(text: string): void {
    this.announcement = text;
  }
}

export const system = new SystemChannel();

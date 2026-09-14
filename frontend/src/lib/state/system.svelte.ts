class SystemChannel {
  text = $state("");
  failed = $state(false);

  announcement = $state("");

  #held: { text: string; failed: boolean } | null = null;
  #timer: ReturnType<typeof setTimeout> | null = null;
  #token = 0;

  flash(text: string, ms = 2500): void {
    // The banner shown before a flash comes back afterwards, even across overlapping flashes.
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
      this.announcement = "";
    }, ms);
  }

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

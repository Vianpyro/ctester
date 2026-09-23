<script lang="ts">
  import { api } from "../lib/config";
  import { t } from "../lib/i18n.svelte";
  import { authFetch } from "../lib/auth/session.svelte";
  import { theme } from "../lib/state/theme.svelte";

  interface Props {
    id: string;
    pages: number;
    staff: boolean;
    title: string;
  }

  const { id, pages, staff, title }: Props = $props();

  const numbers = $derived(Array.from({ length: pages }, (_, i) => i + 1));
  const path = (number: number, name: string) =>
    api("statement/" + encodeURIComponent(id) + "/" + name + "-" + number + ".svg");

  let missing = $state<Set<number>>(new Set());
  const markFailed = (number: number) => {
    missing = new Set(missing).add(number);
  };

  let blobs = $state<Record<number, string>>({});
  $effect(() => {
    if (!staff) return;
    const name = theme.current;
    const alive: string[] = [];
    let cancelled = false;
    void (async () => {
      for (const number of numbers) {
        const response = await authFetch(
          "statement/" + encodeURIComponent(id) + "/" + name + "-" + number + ".svg",
        ).catch(() => null);
        if (cancelled) return;
        if (!response?.ok) {
          markFailed(number);
          continue;
        }
        const url = URL.createObjectURL(await response.blob());
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        alive.push(url);
        blobs = { ...blobs, [number]: url };
      }
    })();
    return () => {
      cancelled = true;
      for (const url of alive) URL.revokeObjectURL(url);
    };
  });

  const source = (number: number): string =>
    staff ? (blobs[number] ?? "") : path(number, theme.current);
</script>

<figure class="typst" aria-label={t("statement.typst_label", { title, count: pages })}>
  {#each numbers as number (number)}
    {#if missing.has(number)}
      <p class="loadfailed">{t("statement.page_failed", { n: number })}</p>
    {:else if source(number)}
      <img
        src={source(number)}
        alt={t("statement.page_alt", { n: number, total: pages })}
        loading={number === 1 ? "eager" : "lazy"}
        decoding="async"
        onerror={() => markFailed(number)}
      />
    {/if}
  {/each}
</figure>

<style>
  .typst {
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .typst img {
    display: block;
    width: 100%;
    max-width: 100%;
    height: auto;
    /* A rendered page is A4. Claiming its height before the bytes arrive keeps the
       statement from growing under the reader, one jump per page. */
    aspect-ratio: 1 / 1.414;
  }
  .loadfailed {
    margin: 0;
    padding: 0.5rem 0.9rem;
    color: var(--muted);
    font-size: 0.9em;
  }
</style>

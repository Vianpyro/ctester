<script lang="ts">
  import { api } from "../lib/config";
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
  const rate = (number: number) => {
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
          rate(number);
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

<figure class="typst" aria-label={"Consigne de " + title + ", " + pages + " page(s)"}>
  {#each numbers as number (number)}
    {#if missing.has(number)}
      <p class="loadfailed">La page {number} de la consigne n'a pas pu être chargée.</p>
    {:else if source(number)}
      <img
        src={source(number)}
        alt={"Consigne, page " + number + " sur " + pages}
        loading={number === 1 ? "eager" : "lazy"}
        decoding="async"
        onerror={() => rate(number)}
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
    width: auto;
    max-width: 100%;
    height: auto;
  }
  .loadfailed {
    margin: 0;
    padding: 0.5rem 0.9rem;
    color: var(--muted);
    font-size: 0.9em;
  }
</style>

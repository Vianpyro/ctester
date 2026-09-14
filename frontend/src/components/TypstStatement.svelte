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

  const numeros = $derived(Array.from({ length: pages }, (_, i) => i + 1));
  const chemin = (numero: number, nom: string) =>
    api("statement/" + encodeURIComponent(id) + "/" + nom + "-" + numero + ".svg");

  let manquantes = $state<Set<number>>(new Set());
  const rate = (numero: number) => {
    manquantes = new Set(manquantes).add(numero);
  };

  let blobs = $state<Record<number, string>>({});
  $effect(() => {
    if (!staff) return;
    const nom = theme.current;
    const vivants: string[] = [];
    let annule = false;
    void (async () => {
      for (const numero of numeros) {
        const reponse = await authFetch(
          "statement/" + encodeURIComponent(id) + "/" + nom + "-" + numero + ".svg",
        ).catch(() => null);
        if (annule) return;
        if (!reponse?.ok) {
          rate(numero);
          continue;
        }
        const url = URL.createObjectURL(await reponse.blob());
        if (annule) {
          URL.revokeObjectURL(url);
          return;
        }
        vivants.push(url);
        blobs = { ...blobs, [numero]: url };
      }
    })();
    return () => {
      annule = true;
      for (const url of vivants) URL.revokeObjectURL(url);
    };
  });

  const source = (numero: number): string =>
    staff ? (blobs[numero] ?? "") : chemin(numero, theme.current);
</script>

<figure class="typst" aria-label={"Consigne de " + title + ", " + pages + " page(s)"}>
  {#each numeros as numero (numero)}
    {#if manquantes.has(numero)}
      <p class="ratee">La page {numero} de la consigne n'a pas pu être chargée.</p>
    {:else if source(numero)}
      <img
        src={source(numero)}
        alt={"Consigne, page " + numero + " sur " + pages}
        loading={numero === 1 ? "eager" : "lazy"}
        decoding="async"
        onerror={() => rate(numero)}
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
  .ratee {
    margin: 0;
    padding: 0.5rem 0.9rem;
    color: var(--muted);
    font-size: 0.9em;
  }
</style>

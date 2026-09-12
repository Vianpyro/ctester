<script lang="ts">
  // UN ÉNONCÉ TYPST : DES PAGES DÉJÀ RENDUES, POSÉES DANS DES `<img>`.
  //
  // RIEN NE COMPILE ICI, ET RIEN N'EN APPROCHE. Pas de WebAssembly, pas de
  // Typst dans le navigateur, aucune dépendance npm : les SVG ont été écrits au
  // build par `typst_build.py` et vivent dans la release. Ce composant fait
  // trois choses -- choisir le thème, poser les images, dire ce qui manque.
  //
  // POURQUOI `<img>` ET PAS DU SVG EN LIGNE. Un SVG injecté dans le document
  // partage son espace d'identifiants et ses styles avec la page, et il
  // faudrait l'assainir avant de l'écrire ; une `<img>` est un bac à sable que
  // le navigateur tient tout seul, elle se met en cache, elle se revalide, et
  // elle ne touche jamais `innerHTML`. Ce fichier n'est donc PAS l'une des
  // sorties dangereuses de l'application.
  //
  // DEUX CHEMINS DE CHARGEMENT, ET LE SECOND N'EST PAS UN LUXE. Un exercice
  // ouvert est un fichier public : `<img src>` direct, que Cloudflare et le
  // navigateur mettent en cache. Un exercice pas encore ouvert n'existe que
  // sous `staff/` et n'est servi qu'à un modérateur authentifié -- or un `<img>`
  // ne porte pas d'en-tête `Authorization`. On le récupère donc par `authFetch`
  // et on le pose en `blob:`, révoqué au démontage. Sans ce second chemin,
  // l'enseignant verrait une image cassée exactement là où il vient vérifier
  // son rendu.

  import { api } from "../lib/config";
  import { authFetch } from "../lib/auth/session.svelte";
  import { theme } from "../lib/state/theme.svelte";

  interface Props {
    id: string;
    pages: number;
    /** Un exercice pas encore ouvert : servi `no-store`, derrière un jeton. */
    staff: boolean;
    title: string;
  }

  const { id, pages, staff, title }: Props = $props();

  const numeros = $derived(Array.from({ length: pages }, (_, i) => i + 1));
  const chemin = (numero: number, nom: string) =>
    api("statement/" + encodeURIComponent(id) + "/" + nom + "-" + numero + ".svg");

  /** Les pages qui n'ont pas pu être chargées. Dites, jamais laissées en trou. */
  let manquantes = $state<Set<number>>(new Set());
  const rate = (numero: number) => {
    manquantes = new Set(manquantes).add(numero);
  };

  // LE CHEMIN AUTHENTIFIÉ. `blob:` par page, refait quand le thème change, et
  // révoqué à chaque fois -- une URL d'objet non révoquée retient ses octets
  // pour toute la visite, et un enseignant qui parcourt vingt exercices en
  // garderait quarante.
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

<!-- UN `<figure>` ET PAS UNE PILE DE `<img>` NUES : le document garde une
     structure, et le lecteur d'écran annonce un bloc au lieu de N images. Ce
     que ça NE fait PAS, c'est rendre l'énoncé accessible -- voir
     `docs/content/typst.md` : Typst vectorise ses glyphes, donc le texte de la
     consigne n'est ni sélectionnable ni lisible par une synthèse vocale, et un
     `alt` de quinze mots ne remplace pas un énoncé. C'est la raison pour
     laquelle `statement.md` reste le défaut. -->
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
  /* LA LARGEUR EST CELLE DE LA COLONNE, et la hauteur suit le viewBox du SVG.
     Rien n'est imposé : le document a été rendu à 320 pt de large, donc il
     s'adapte sans déformation et sans reflow une fois arrivé. */
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
    height: auto;
  }
  .ratee {
    margin: 0;
    padding: 0.5rem 0.9rem;
    color: var(--muted);
    font-size: 0.9em;
  }
</style>

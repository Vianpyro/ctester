import { i18n } from "../i18n.svelte";

// The server sends ISO instants; a student reads a day, in their own language. Anything that
// is not a date (a held card says "held") reads as nothing rather than as itself.
export function dayOf(iso: string | null | undefined): string {
  const when = new Date(iso ?? "");
  if (Number.isNaN(when.getTime())) return "";
  return new Intl.DateTimeFormat(i18n.lang, { dateStyle: "long" }).format(when);
}

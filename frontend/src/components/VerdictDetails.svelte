<script lang="ts">
  import { quiz } from "../lib/state/quiz.svelte";
  import { t } from "../lib/i18n.svelte";
  import {
    caseClass,
    caseInputs,
    caseNumbers,
    caseReason,
    quizHint,
    showsContract,
  } from "../lib/domain/verdict";
  import type { Verdict } from "../lib/api/types";

  let { r, complete }: { r: Verdict; complete: boolean } = $props();

  const partial = $derived(r.status === "ok" && !complete);
  const quizGroup = (id: string): string => quiz.groupOf[id] ?? "";
</script>

{#if partial && r.kind === "io"}
  <div class="cases">
    {#each r.cases ?? [] as c, i}
      {@const kind = caseClass(c.reason)}
      {@const inputs = caseInputs(c.stdin)}
      {@const numbers = caseNumbers(c)}
      <details class={"case " + kind} open={i === 0}>
        <summary>{t("verdict.case", { n: c.case, kind: t(`verdict.case.${kind}`) })}</summary>
        <div class="body">
          <div class="case-field">
            <span class="what">{t("verdict.receives", { count: inputs.length })}</span>
            <pre class="value">{inputs.length ? inputs.join(t("verdict.then")) : t("verdict.no_input")}</pre>
          </div>
          <div class="case-field">
            <span class="what">{t("verdict.printed")}</span>
            <pre class="value">{c.stdout || t("verdict.nothing")}</pre>
          </div>
          {#if numbers}
            <div class="case-field">
              <span class="what">{t("verdict.numbers_read")}</span>
              <pre class="value">{numbers.length ? numbers.join(", ") : t("verdict.no_numbers")}</pre>
            </div>
          {/if}
          {#if c.stderr}
            <div class="case-field">
              <span class="what">{t("verdict.stderr")}</span>
              <pre class="value">{c.stderr}</pre>
            </div>
          {/if}
          <p class="why">{caseReason(c)}</p>
          {#if showsContract(c)}
            <p class="contract">{t("verdict.contract")}</p>
          {/if}
        </div>
      </details>
    {/each}
  </div>
{/if}

{#if partial && r.kind === "unity" && r.failed?.length}
  <div class="failures">
    <p class="what">{t("verdict.failed_checks", { count: r.failed.length })}</p>
    <ul>
      {#each r.failed as name (name)}<li>{name}</li>{/each}
    </ul>
    <p class="contract">{t("verdict.hidden_values")}</p>
  </div>
{/if}

{#if partial && r.kind === "quiz"}
  <ul class="wrong">
    {#each r.wrong ?? [] as w}
      {@const group = quizGroup(w.id)}
      {@const empty = !(w.given && w.given.trim())}
      <li class={empty ? "nothing" : ""}>
        {(group ? group + " — " : "") +
          w.label +
          (empty ? "" : t("verdict.you_answered", { given: w.given ?? "" })) +
          (w.hint ? " — " + quizHint(w.hint) : "")}
      </li>
    {/each}
  </ul>
{/if}

{#if r.warnings || r.long_source}
  <div class="warn">
    <div class="title">{t("verdict.warnings")}</div>
    <div class="what">{t("verdict.warnings_explain")}</div>
    <pre>{[r.warnings ?? "", r.long_source ? t("verdict.long_source", r.long_source) : ""]
        .filter(Boolean)
        .join("\n")}</pre>
  </div>
{/if}

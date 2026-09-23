import { t } from "../i18n.svelte";

/**
 * Whether an answer has the shape its question asks for, never whether it is right: a
 * right/wrong hint per field would let an 8-bit answer be found in 256 tries.
 * The rules replay the judge's `norm_bin`, `norm_hex` and `norm_int`, bound by
 * `tests/vectors/answer_shape.json`.
 */

/** Spaces and underscores are not part of an answer, exactly as `without_separators` says. */
const bare = (given: string): string => given.replace(/[\s_]/g, "");

const NUMBER = /^[-+]?[0-9]+(?:[.,][0-9]+)?(?:[eE][-+]?[0-9]+)?$/;

function bits(given: string): string {
  const s = bare(given).toLowerCase();
  return s.startsWith("0b") ? s.slice(2) : s;
}

export function shapeNote(type: string, given: string): string {
  const text = given.trim();
  if (!text) return "";
  switch (type) {
    case "bin8": {
      const s = bits(text);
      if (!s || !/^[01]+$/.test(s)) return t("shape.bits_only");
      // Same rule as the judge's needs_8_bits hint, shown before the answer is sent.
      return s.length === 8 ? "" : t("shape.bits_of_8", { count: s.length });
    }
    case "bin": {
      const s = bits(text);
      return !s || !/^[01]+$/.test(s) ? t("shape.bits_only") : "";
    }
    case "hex8": {
      let s = bare(text).toLowerCase();
      if (s.startsWith("0x")) s = s.slice(2);
      if (s.endsWith("h")) s = s.slice(0, -1);
      s = s.replace(/^[-+]/, "");
      // No length here: the judge compares magnitudes, so "00C8" is as good as "C8".
      return !s || !/^[0-9a-f]+$/.test(s) ? t("shape.hex") : "";
    }
    case "int": {
      const s = bare(text).replace("−", "-").replace(/^[-+]/, "");
      return !s || !/^[0-9]+$/.test(s) ? t("shape.int") : "";
    }
    case "number":
      return NUMBER.test(bare(text).replace("−", "-")) ? "" : t("shape.number");
    default:
      return "";
  }
}

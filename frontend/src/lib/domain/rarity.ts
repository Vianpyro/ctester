// Colour bands read the measured share of holders, never a decreed rarity: 0 until the
// cohort is large enough to publish one, then 1 (common) to 4 (held by a tenth or fewer).
export function tier(rarity: number | null | undefined): 0 | 1 | 2 | 3 | 4 {
  if (rarity === null || rarity === undefined) return 0;
  if (rarity <= 10) return 4;
  if (rarity <= 25) return 3;
  if (rarity <= 50) return 2;
  return 1;
}

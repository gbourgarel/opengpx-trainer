/* What the rider answered after a ride ("How was it?"), as stored in its summary. */

/** How the rider felt (FIT `workout_feel`, 0-100 in five levels, as the Edge records it). */
export const FEELS: [number, string][] = [
  [0, 'Very weak'],
  [25, 'Weak'],
  [50, 'Normal'],
  [75, 'Strong'],
  [100, 'Very strong'],
]

/** "RPE 7 · Strong · 60 g · 750 ml": only the parts answered; null when nothing was. */
export function feedbackText(summary: Record<string, number | null | undefined>): string | null {
  const parts: string[] = []
  const { rpe, feel, carbs_g: carbs, water_ml: water } = summary
  if (rpe != null) parts.push(`RPE ${rpe}`)
  if (feel != null) parts.push(FEELS.find(([v]) => v === feel)?.[1] ?? `feel ${feel}`)
  if (carbs != null) parts.push(`${carbs} g`)
  if (water != null) parts.push(`${water} ml`)
  return parts.length ? parts.join(' · ') : null
}

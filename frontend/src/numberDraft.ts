/* Number fields edited as text: what the rider is typing ("-", "-0", "", "1.") is kept as is
 * until it is a number, instead of being replaced by 0 at the first key (a "-" typed first
 * used to turn into 0). Pure helpers of components/NumberInput.tsx. */

/** The number a field's text stands for, or null while it is not one yet. A number input
 * reports "" for an unfinished entry such as "-" (the browser keeps showing it). */
export function parseDraft(text: string): number | null {
  if (text.trim() === '') return null
  const n = Number(text)
  return Number.isFinite(n) ? n : null
}

/** The text to show once the value changed from outside (or was clamped by the owner): the
 * text being typed when it already stands for that value, else the value itself. */
export function draftFor(value: number, draft: string): string {
  return parseDraft(draft) === value ? draft : String(value)
}

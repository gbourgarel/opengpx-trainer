import { useState, type InputHTMLAttributes } from 'react'
import { draftFor, parseDraft } from '../numberDraft'

/** A number field that lets the rider type freely (a leading minus, an emptied field):
 * ``onChange`` only gets finite numbers; on leaving the field it shows ``value`` again. */
export function NumberInput({
  value,
  onChange,
  ...rest
}: { value: number; onChange: (n: number) => void } & Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'type'>) {
  const [draft, setDraft] = useState(String(value))
  const [seen, setSeen] = useState(value)
  if (value !== seen) {
    // changed from outside, or clamped by the owner: follow it unless the text already says so
    setSeen(value)
    setDraft(draftFor(value, draft))
  }
  return (
    <input
      type="number"
      {...rest}
      value={draft}
      onChange={(e) => {
        setDraft(e.target.value)
        const n = parseDraft(e.target.value)
        if (n != null) onChange(n)
      }}
      onBlur={(e) => {
        setDraft(String(value))
        rest.onBlur?.(e)
      }}
    />
  )
}

import assert from 'node:assert/strict'
import { draftFor, parseDraft } from '../src/numberDraft'

export const checks = {
  'unfinished entries are not numbers yet (never 0)': () => {
    for (const t of ['', ' ', '-', '.', '-.', 'e']) assert.equal(parseDraft(t), null, JSON.stringify(t))
  },
  'numbers, negative ones included': () => {
    assert.equal(parseDraft('-5'), -5)
    assert.equal(parseDraft('-0.5'), -0.5)
    assert.equal(parseDraft('12'), 12)
    assert.equal(parseDraft('0'), 0)
  },
  'the text being typed is kept while it says the value': () => {
    assert.equal(draftFor(-0, '-0'), '-0') // "-0" on the way to "-05"
    assert.equal(draftFor(1, '1.'), '1.') // "1." on the way to "1.5"
    assert.equal(draftFor(-5, '-5'), '-5')
  },
  'a value changed from outside or clamped replaces the text': () => {
    assert.equal(draftFor(-30, '-35'), '-30') // clamped by the owner
    assert.equal(draftFor(12, '-3'), '12')
    assert.equal(draftFor(4, ''), '4')
  },
}

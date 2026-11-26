import assert from 'node:assert/strict'
import { withAsked } from '../src/feedbackAsked'

export const checks = {
  'a ride is added once, last': () => {
    assert.deepEqual(withAsked([], 7), [7])
    assert.deepEqual(withAsked([3, 7, 9], 7), [3, 9, 7])
  },
  'only the latest are kept, the new one always': () => {
    const ids = Array.from({ length: 5 }, (_, i) => i)
    assert.deepEqual(withAsked(ids, 99, 3), [3, 4, 99])
  },
}

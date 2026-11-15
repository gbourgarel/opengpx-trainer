import assert from 'node:assert/strict'
import type { Profile } from '../src/api'
import { profileChanged } from '../src/profileDiff'

const saved = { ftp_w: 250, rider_mass_kg: 73, max_hr_bpm: null, grade_curve: [[0, 0.7], [5, 0.9]], intervals_api_key: '', intervals_api_key_set: true } as unknown as Profile

export const checks = {
  'the loaded profile is not a change': () => {
    assert.equal(profileChanged({ ...saved }, saved), false)
  },
  'an edited field, curve point or typed key is a change': () => {
    assert.equal(profileChanged({ ...saved, ftp_w: 260 }, saved), true)
    assert.equal(profileChanged({ ...saved, grade_curve: [[0, 0.7], [5, 0.95]] }, saved), true)
    assert.equal(profileChanged({ ...saved, intervals_api_key: 'abc' }, saved), true)
  },
  'server-only fields and null / missing optional fields are not changes': () => {
    assert.equal(profileChanged({ ...saved, devices_note: 'Reconnected' } as Profile, saved), false)
    const { max_hr_bpm: _drop, ...noHr } = saved
    assert.equal(profileChanged(noHr as Profile, saved), false)
  },
}

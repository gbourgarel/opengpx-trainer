import assert from 'node:assert/strict'
import { feedbackText } from '../src/feedback'

export const checks = {
  'nothing answered (or skipped): no text': () => {
    assert.equal(feedbackText({}), null)
    assert.equal(feedbackText({ rpe: null, feel: null, carbs_g: null, water_ml: null, normalized_power_w: 210 }), null)
  },
  'all answered, in the dialog order': () => {
    assert.equal(feedbackText({ rpe: 7, feel: 75, carbs_g: 60, water_ml: 750 }), 'RPE 7 · Strong · 60 g · 750 ml')
  },
  'only the parts answered; 0 is an answer': () => {
    assert.equal(feedbackText({ feel: 0 }), 'Very weak')
    assert.equal(feedbackText({ carbs_g: 0, water_ml: null }), '0 g')
  },
}

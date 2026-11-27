/* Frontend checks: clear invariants of the pure logic (no test runner, no dependency).
 * `npm run check`. Each module exports `checks`: named functions that throw on failure. */
import { checks as battery } from './battery.check.ts'
import { checks as calibration } from './calibration.check.ts'
import { checks as feedback } from './feedback.check.ts'
import { checks as feedbackAsked } from './feedbackAsked.check.ts'
import { checks as fileDrop } from './fileDrop.check.ts'
import { checks as help } from './help.check.ts'
import { checks as mapTiles } from './mapTiles.check.ts'
import { checks as numberDraft } from './numberDraft.check.ts'
import { checks as nudge } from './nudge.check.ts'
import { checks as profile } from './profile.check.ts'
import { checks as route3d } from './route3d.check.ts'
import { checks as routeStart } from './routeStart.check.ts'
import { checks as stepCues } from './stepCues.check.ts'
import { checks as targetSource } from './targetSource.check.ts'
import { checks as tiles } from './tiles.check.ts'
import { checks as zones } from './zones.check.ts'

type Check = Record<string, () => void | Promise<void>>
const groups: Record<string, Check> = { battery, calibration, feedback, feedbackAsked, fileDrop, help, mapTiles, numberDraft, nudge, profile, route3d, routeStart, stepCues, targetSource, tiles, zones }

let failed = 0
for (const [group, checks] of Object.entries(groups)) {
  for (const [name, fn] of Object.entries(checks)) {
    try {
      await fn()
      console.log(`  ok    ${group}: ${name}`)
    } catch (e) {
      failed++
      console.log(`  FAIL  ${group}: ${name}\n        ${e instanceof Error ? e.message : String(e)}`)
    }
  }
}
console.log(failed ? `${failed} check(s) failed` : 'all checks passed')
process.exit(failed ? 1 : 0)

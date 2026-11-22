import assert from 'node:assert/strict'
import { carriesFiles, splitByExtension } from '../src/fileDrop'

const f = (name: string) => ({ name })

export const checks = {
  'only drags carrying files count': () => {
    assert.equal(carriesFiles(['Files']), true)
    assert.equal(carriesFiles(['text/plain', 'Files']), true)
    assert.equal(carriesFiles(['text/uri-list', 'text/plain']), false)
    assert.equal(carriesFiles(undefined), false)
  },
  'files are split by extension, case-insensitive, order kept': () => {
    const { accepted, refused } = splitByExtension([f('a.GPX'), f('b.fit'), f('c.gpx'), f('noext'), f('d.gpx.zip')], ['.gpx'])
    assert.deepEqual(
      accepted.map((x) => x.name),
      ['a.GPX', 'c.gpx'],
    )
    assert.deepEqual(refused, ['b.fit', 'noext', 'd.gpx.zip'])
  },
}

// `node --import ./checks/register.mjs`: lets Node (built-in TypeScript stripping) load the
// app's modules, whose relative imports are written without extension (as Vite wants).
import { register } from 'node:module'

register('./ts-resolve.mjs', import.meta.url)

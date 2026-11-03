import { useEffect, useRef, useState } from 'react'
import type { Telemetry } from './api'

/** Audio cues of a structured workout: 3-2-1 beeps before each step change, then a cue at
 * the change — a rising two-tone when the target goes up, a single long beep otherwise —
 * and a final chime when the workout ends. Synthesised with Web Audio (no sound files). */

export type Cue = 'tick' | 'change' | 'rise' | 'end'

export interface CueState {
  session?: string
  state: string
  step?: number
  remaining?: number
  target?: number | null
  next?: number | null
}

export function cueState(t: Telemetry): CueState {
  return {
    session: t.session_id,
    state: t.state,
    step: t.step_index,
    remaining: t.step_remaining_s,
    target: t.target_w,
    next: t.next_target_w,
  }
}

/** Cues to play between two consecutive telemetry samples (pure, ~4 Hz). */
export function cuesBetween(prev: CueState | null, cur: CueState): Cue[] {
  if (!prev || prev.session !== cur.session || cur.session == null || prev.step == null) return []
  if (prev.state === 'running' && cur.state === 'finished') return ['end']
  if (cur.state !== 'running' || cur.step == null) return []
  if (cur.step !== prev.step) {
    if (cur.step < prev.step) return [] // not a step change (e.g. time going back)
    const rises = prev.next != null && prev.target != null && prev.next > prev.target + 1
    return [rises ? 'rise' : 'change']
  }
  if (prev.remaining == null || cur.remaining == null) return []
  // one beep per whole second crossed: 3, 2, 1 s before the change
  return [3, 2, 1].filter((n) => prev.remaining! > n && cur.remaining! <= n).map(() => 'tick')
}

// -- sound ---------------------------------------------------------------------------------
let ctx: AudioContext | null = null

/** Browsers only start audio after a user gesture: create / resume the context on the first
 * click or key press (the rider clicks to start the ride anyway). */
function unlockAudio() {
  try {
    ctx ??= new AudioContext()
    if (ctx.state === 'suspended') void ctx.resume()
  } catch {
    ctx = null // no Web Audio: cues stay silent
  }
}

function tone(freq: number, start: number, dur: number, vol = 0.25) {
  if (!ctx) return
  const t0 = ctx.currentTime + start
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.type = 'sine'
  osc.frequency.value = freq
  // short attack / release: no clicks
  gain.gain.setValueAtTime(0, t0)
  gain.gain.linearRampToValueAtTime(vol, t0 + 0.01)
  gain.gain.setValueAtTime(vol, t0 + dur - 0.03)
  gain.gain.linearRampToValueAtTime(0, t0 + dur)
  osc.connect(gain).connect(ctx.destination)
  osc.start(t0)
  osc.stop(t0 + dur + 0.02)
}

export function playCue(c: Cue) {
  if (!ctx || ctx.state !== 'running') return
  if (c === 'tick') tone(880, 0, 0.12)
  else if (c === 'change') tone(880, 0, 0.45)
  else if (c === 'rise') {
    tone(660, 0, 0.18)
    tone(990, 0.2, 0.4, 0.3)
  } else {
    tone(660, 0, 0.18)
    tone(880, 0.2, 0.18)
    tone(1320, 0.4, 0.5)
  }
}

const STORAGE_KEY = 'hometrainer.sound'

function loadSound(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== 'off'
  } catch {
    return true
  }
}

/** Plays the step cues of the live ride; returns the sound on/off switch (remembered). */
export function useStepCues(tel: Telemetry): [boolean, (on: boolean) => void] {
  const [sound, setSound] = useState(loadSound)
  const prev = useRef<CueState | null>(null)

  useEffect(() => {
    window.addEventListener('pointerdown', unlockAudio)
    window.addEventListener('keydown', unlockAudio)
    return () => {
      window.removeEventListener('pointerdown', unlockAudio)
      window.removeEventListener('keydown', unlockAudio)
    }
  }, [])

  useEffect(() => {
    const cur = cueState(tel)
    const cues = cuesBetween(prev.current, cur)
    prev.current = cur
    if (sound) cues.forEach(playCue)
  }, [tel, sound])

  const toggle = (on: boolean) => {
    setSound(on)
    if (on) unlockAudio()
    try {
      localStorage.setItem(STORAGE_KEY, on ? 'on' : 'off')
    } catch {
      /* private mode: not remembered */
    }
  }
  return [sound, toggle]
}

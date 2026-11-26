# OpenGPX Trainer

Free, open-source indoor-cycling app: ride **any GPX route** (or a structured workout, or both)
on a smart trainer driven over ANT+ (FE-C, USB stick) or Bluetooth LE (FTMS), with power meter
and heart-rate sensors on either protocol. Formerly called *Home Trainer*.

* **ERG workouts**: planned workouts fetched from intervals.icu (or imported `.zwo` / `.erg` / `.mrc`,
  with the button or by dropping files onto the Workouts tab), with a live intensity % adjustment. The current step can be skipped or extended by 1 min, and
  3-2-1 beeps announce each step change (a rising tone when the target goes up).
* **GPX routes** (**Slope ERG**): the trainer target power follows a configurable *grade → %FTP*
  curve on the look-ahead grade, held by the trainer in ERG, so you never shift (unlike a classic
  simulation mode, where the grade sets the resistance); or a target set by hand; or **Sim**,
  that classic mode: the route's smoothed grade under the wheel × a *trainer effect* (50 % the
  first time, ↑ / ↓ by 10 %, remembered per browser) is sent to the trainer (FE-C page 51 /
  FTMS indoor bike simulation, grade only), changing by at most 1 % per second; you shift and
  choose your power, which drives the virtual bike as in the other modes (no target, no
  `target_power` in the FIT). A GPX + workout ride keeps the workout's targets until it is
  over, then Sim applies. Routes are
  imported with *Import GPX* or by dropping one or more `.gpx` files anywhere on the Routes
  tab. Virtual speed and position on the trace come
  from a dynamic physics model fed with the measured power (see the *speed-model power scale*
  below), with the **conditions of the ride** set when starting the route: **wind** (speed and
  direction) and **air** (temperature, humidity: the air density), remembered per browser for
  the next ride. ERG rides (no route) use standard air, 15 °C / 50 %. Climb rate (VAM) and
  elevation gain are shown. **Weather now** (next to them) fills in the current wind,
  temperature and humidity from Open-Meteo (free, no key): points every ~10 km along the route (3 to 10),
  averaged into one weather for the ride (wind as a vector mean), the 10 m wind brought down to
  rider height with a log profile (`u(1 m) = u(10 m)·ln(1/z0)/ln(10/z0)`, z0 = 0.1 m,
  countryside with hedges: × 0.50), all editable before starting; the route's time estimate follows them. A
  route can be **started part-way**: click the map or the elevation profile (or type a km
  value under it) to choose the start point; the part before it is greyed, the estimate
  covers the rest, the ride ends at the route's end and its recorded distance starts at 0
  (with a workout, the route loops back through its start as usual). A
  route can be ridden **in reverse** (*Reverse*, next to the wind when
  starting it): a climb becomes its descent; the map and profile follow the direction chosen.
* **Workout on a route**: a GPX ride can follow a workout. The workout sets the target, the route
  gives speed and position, and the route loops while the workout lasts; its free-ride steps
  are in Slope ERG. The ride controls name what sets the target (*Workout* or *Slope ERG*, or
  *Manual*: watts set by hand, which override the workout while its steps keep running) and
  show only the value that acts now (intensity, effort or watts), also under the power dial.
  Once the workout is over, the ride carries on as a plain GPX ride until the end of the
  current lap.
* Power is also shown in **W/kg** (rider mass).
* **Power source**: the power meter if one is detected (or forced), else the trainer. With a
  power meter, *power match* corrects the ERG target so the meter reads the requested power.
* Rides are recorded to `.fit` (cycling / virtual activity, one lap per workout step). Once a
  ride is saved, the app **asks** whether to upload it to intervals.icu (never automatic).
* A ride in progress is checkpointed every 30 s: after a crash it is recovered into the history
  at the next start.
* During a ride the screen is kept on, and the keyboard drives the main controls (see
  [Ride screen](#ride-screen)).

```
backend/   Python 3.12 · FastAPI · openant · bleak · numpy · SQLite   (uv)
frontend/  React · Vite · TypeScript · Leaflet · MapLibre GL
samples/   sample GPX route and ZWO workout
```

## Installing (macOS, Windows)

No Node or Python needed beforehand: [uv](https://docs.astral.sh/uv/) installs Python for the
app, and the release wheel contains the UI and libusb.

1. Install uv, once. macOS (Terminal):
   `curl -LsSf https://astral.sh/uv/install.sh | sh`; Windows (PowerShell):
   `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
   Then open a new terminal.
2. Install the app from the latest release:
   `uv tool install <URL of the opengpx_trainer-….whl from the Releases page>`.
   An update is the same command with the newer wheel. (Coming from the former `hometrainer`
   wheel: `uv tool uninstall hometrainer` first; the data is moved over at the first start.)
3. Run `opengpx-trainer`. The UI opens in the browser at http://127.0.0.1:8000 (`--no-browser`
   to skip, `--port` to use another port). Stop it with Ctrl+C.

**Tablet or second device on the LAN**: start with `--host 0.0.0.0` and open
`http://<computer's IP>:8000`. There is **no authentication**: anyone on the network can use
the app (stop a ride, change the profile, upload to intervals.icu). Use it on a trusted
private network only. Requests sent by other web sites open in the browser are refused (the
`Origin` must be the app's own address), but DNS rebinding is not guarded against.

Bluetooth sensors need nothing else (on macOS, allow Bluetooth for Terminal, see below). An
ANT+ stick works as is on macOS. On Windows it needs the WinUSB driver once: plug the stick in,
run [Zadig](https://zadig.akeo.ie/), pick the stick (*ANT USBStick2* or *ANT USB-m Stick*) and
install *WinUSB*. Garmin Express then no longer sees the stick.

A release is made by pushing a tag: `git tag v0.2.0 && git push origin v0.2.0`. The
`release` workflow builds the UI and the wheel and attaches it to a GitHub release. By hand:
`cd frontend && npm run build`, then `cd backend && uv build --wheel` (the wheel lands in
`backend/dist/`).

## Running (development)

Prerequisites: [uv](https://docs.astral.sh/uv/) and Node ≥ 20. The ANT+ stick uses the libusb
of the `libusb-package` wheel (a system libusb is used where the wheel has none).
Quit Garmin Express (and Zwift/TrainerRoad…) so that nothing else holds the stick.
For Bluetooth on macOS, allow Bluetooth for the app that runs the server (Terminal, iTerm, VS Code…)
in System Settings → Privacy & Security → Bluetooth. Without it, scans never answer. A Bluetooth
sensor also usually accepts a single connection, so disconnect it from other apps.

Sensors are chosen in **Profile → Devices**. For each role (trainer, power meter, heart rate),
pick ANT+ or Bluetooth and the device, from a **Scan** that lists both protocols. Then click
**Connect sensors**.

```bash
# one-off
cd frontend && npm install && npm run build && cd ..
cd backend && uv sync

# run (serves the built UI too) → http://127.0.0.1:8000
cd backend && uv run opengpx-trainer
```

Development, with hot reload on both sides:

```bash
cd backend && uv run opengpx-trainer --reload  # :8000
cd frontend && npm run dev                     # :5173, proxies /api and /ws to :8000
```

### Testing without hardware (fake power input)

Start the app with `--simulator` (or `OPENGPX_TRAINER_SIMULATOR=1`), then click **Simulator**
instead of **Connect sensors** (the button is hidden otherwise). A simulator panel appears on
the Ride page:

* **Follow target**: behaves like an ERG trainer, so power tracks the target with a 1.5 s lag.
* **Manual power**: you set the rider's power with the slider or ±10/±50 buttons, or from the
  keyboard (←/→ ±10 W, Shift ±50 W). Use it to probe the speed model on a GPX route.
* **P** toggles pedaling, so you can watch the virtual bike coast and auto-pause. (Space and
  ↑/↓ are the ride shortcuts.)
* Switches for power meter / HR strap presence (turn the power meter off to see the *auto*
  source fall back to the trainer), sensor noise, and power-meter bias (default −3 %, which
  exercises power match).

The same controls are available over the API: `PUT /api/simulator` with e.g.
`{"mode": "manual", "manual_power_w": 300}`.

Tests: `cd backend && uv run pytest`, lint: `uv run ruff check src tests`. Frontend:
`cd frontend && npm run build` (type-check + bundle) and `npm run lint` (oxlint).

Data lives in `~/.opengpx-trainer`: the SQLite DB, `rides/*.fit`, and `checkpoints/` (rides
in progress). Environment variables:

| Variable                   | Effect                                                    |
|----------------------------|-----------------------------------------------------------|
| `OPENGPX_TRAINER_DATA`     | data directory instead of `~/.opengpx-trainer`            |
| `OPENGPX_TRAINER_ANT_LOG`  | CSV file where every raw ANT+ page and every command sent is logged; also requests the trainer's command status (page 71) every 5 s (debugging) |
| `OPENGPX_TRAINER_FRONTEND` | built UI to serve instead of the packaged one / `frontend/dist` |
| `OPENGPX_TRAINER_SIMULATOR` | `1`: show the Simulator button (same as `--simulator`)   |

From the former name (*Home Trainer*): at the first start, `~/.hometrainer` is moved to
`~/.opengpx-trainer` (when the new one does not exist yet) and `hometrainer.db` renamed;
the former `HOMETRAINER_*` variables are still read when the new ones are not set, and the
settings remembered in the browser (sound, wind, air) are kept.

## Ride screen

* Auto start when you pedal, auto pause after 3 s without power or cadence, auto resume. On
  a GPX route the virtual bike coasts on when you stop pedalling: the ride pauses once it has
  stopped, or after 15 s without pedalling. Those 15 s do not count down a real descent
  (look-ahead grade of −3 % or steeper, where freewheeling is legitimate), nor while the power
  source sends nothing (a dropout is not a stop).
* Workout: **+1 min** and **Skip step** for the current step; *Sound on/off* for the 3-2-1
  beeps (Web Audio, enabled by the first click or key press, remembered in the browser).
* GPX: the wind badge in the map corner shows where the wind blows; hover it for the head /
  tail / cross components on the current heading.
* Zones: the training zone of the 3 s power (Coggan, % of FTP: Z1 < 55, Z2 < 75, Z3 < 90,
  Z4 < 105, Z5 < 120, Z6 < 150, Z7) is shown in its colour after the W/kg; the heart rate is
  coloured by its zone when the threshold heart rate is set in the Profile (Friel, % of LTHR:
  Z1 < 81, Z2 < 90, Z3 < 94, Z4 < 100, Z5 ≥ 100); workout profiles use the same 7 colours.
* A sensor that sent data during the ride and goes silent for 5 s (trainer, power meter, heart
  rate) raises a red banner, also over the immersive view, until it comes back: "no data
  since …", and for the power meter whether the trainer's power is used instead (power source
  *Auto*) or no power is recorded (*Power meter only*).
* **Low sensor batteries** are shown in the Ride tab before a ride (no ride yet, or waiting
  for the first pedal stroke) and once it is finished, never while riding: "Power meter:
  battery low (3.77 V)". Low = ANT+ battery status *low* / *critical* (common page 82,
  heart-rate page 7), or a Bluetooth Battery Level of 20 % or less (critical: 5 %). The last
  report is kept while the sensor is silent (a dead battery stops it).
* Calibration of the power source (ANT+ sensors): **trainer spin-down** and **power-meter zero
  offset**, from Profile → Devices or from the Ride tab before a ride (no ride yet, or
  waiting for the first pedal stroke) or while it is paused, e.g. after the warm-up the
  trainer wants: the ride stays paused during the calibration and resumes on the first pedal
  stroke after it (once the pedals have stopped, so a failed spin-down can be tried again
  without the ride carrying on). A guided dialog shows the steps live: for a
  spin-down, pedal up to the speed the trainer asks for (bar with the live speed), then stop
  and let the wheel coast; the result is the spin-down time when the trainer gives one (the
  Tacx Flux does not: "Spin-down done"), or the zero offset value. ERG is off during a
  spin-down and a ride waiting to start does not start meanwhile. A trainer that stops
  sending calibration data for 4 s (it may have restarted) ends the spin-down with a
  message and *Try again*. When the trainer itself flags "calibration required" (FE-C page
  25), the Ride tab highlights the spin-down and Devices shows "calibration requested",
  unless the last calibration of that sensor succeeded (the Tacx raises the flag at every
  power-up). Results are kept while the app runs, across reconnections (not stored). The
  rider configuration (weight, wheel size) is sent again whenever the trainer asks for it.
* The screen is kept on with the Screen Wake Lock API, which needs `localhost` or HTTPS: a
  tablet opening the app over plain `http://` on the LAN shows "screen may sleep".
* Keyboard (ignored while typing in a field or while a dialog is open; Esc closes the Stop
  dialog without stopping):

  | Key            | Action                                                              |
  |----------------|---------------------------------------------------------------------|
  | Space          | pause / resume                                                      |
  | ↑ / ↓ (+ / −)  | the value of what sets the target now: workout intensity ±1 %; effort ±2 % in Slope ERG (also in a workout's free-ride steps); target ±5 W in manual mode |
  | M              | sound on / off                                                      |
  | V / Esc        | immersive 3D view on / off (GPX rides)                              |
  | F              | browser full screen (immersive view)                                |

* GPX: **Immersive** (or V) shows the route in 3D over the whole window: terrain draped with
  aerial imagery, a camera following the rider, wide angle. The camera is automatic: on flat,
  straight roads it rides low (3 m up) looking at the horizon, backing away until the rider is
  in view; on climbs, descents and in turns it follows from higher up (5 s behind, at least
  70 m), looks at the road ahead and swings to the outside of the bends; it stays above the
  terrain and keeps the rider in the frame. Imagery: IGN orthophotos where IGN
  has data (France: Géoplateforme, Licence Ouverte Etalab 2.0, no key), Esri World Imagery
  elsewhere, chosen per tile; the finest IGN level (~30 cm/px) is used where IGN has it and
  the network keeps up (prefetched last), otherwise the view stays one level coarser rather
  than switching source; terrain: AWS Terrain Tiles (Terrarium). Needs an internet
  connection; MapLibre GL (WebGL) is only downloaded when the view is opened. On high-density
  (Retina) screens the 3D scene is drawn at 1.5x rather than 2x, for the frame rate (the
  panels over it stay sharp). The tiles of the
  next kilometre are downloaded ahead (a corridor along the route, wider for the coarse levels)
  so fast descents do not outrun the network; they are kept **in memory only**, dropped once
  behind, and the cache is emptied when the view closes or the ride ends. Expect a few tens of
  MB per minute at descent speed. Over the view: 3 s power in its zone colour with a zone bar
  (target ± 25 %) and, with a workout, the step left, next target, interval average and a band
  of the workout (top left); speed, time, HR, cadence, average / NP (top right); the road
  ahead (bottom left); the whole route and a small fixed map (bottom right). The controls
  (pause, stop, step, effort or manual target) sit at the top centre and hide after 3 s without
  moving the mouse; pressing Space or ↑ / ↓ shows them again, so the change can be seen. The
  view closes by itself when the ride ends.

* When a ride ends (end of the workout or route, or *Stop* → *Save*) the trainer goes back to
  free ride, the FIT file is written in the background, and the upload to intervals.icu is
  offered if an API key is set. *Stop* asks *Save* / *Discard* / *Keep riding*; *Discard*
  asks once more and records nothing.
* History: *Delete* removes a ride (history row and FIT file) after a confirmation. It never
  touches intervals.icu: an uploaded copy stays there.

## Recording

* 1 Hz samples (power, cadence, HR, speed, distance, position, altitude, grade, target).
* FIT activity: one lap per workout step (avg / max power, NP, HR, cadence,
  `workout_step_index`), the target power as a `target_power` developer field on records and
  laps.
* The sensors are declared like a Garmin head unit does: `product_name` "OpenGPX Trainer" in
  `file_id`, a `device_info` for the app (index 0) and one per sensor that sent data during
  the ride (ANT+ device type 17 / 11 / 120, device number, and what the sensor broadcasts
  about itself: manufacturer, model, serial number, hardware / software version, battery from
  the ANT+ common pages 80-82 and the heart-rate pages 2 / 3 / 7; over Bluetooth only the
  advertised name and the Battery Level, in %). Simulated sensors are not declared.
* The workout **as ridden** embedded in the activity (`workout` + one `workout_step` per
  workout lap: ridden duration, so skips / extensions are reflected; power target = range of
  the targets held, in watts; free-ride steps without target), like a Garmin head unit:
  intervals.icu extracts it to show the targets (it ignores the developer field).
* The totals a head unit writes, on laps and session: work (kJ), calories (work / 21.3 % gross
  efficiency, fitted on Edge 540 files), crank revolutions, max cadence / HR, average / max
  speed, ascent / descent (GPX); on the session the FTP, IF = NP / FTP and TSS = t·NP·IF /
  (FTP·3600)·100. Also: accumulated power on records, timer stop / start events at pauses,
  the rider's weight, max HR and FTP (`user_profile`, `zones_target`) and the local time of
  day.
* Dual-sided power meter (ANT+), the same fields as a Garmin head unit: L/R balance, torque
  effectiveness and pedal smoothness (left / right), power phase and peak power phase (start
  / end angles), platform centre offset (only when the meter says it supports it), seated /
  standing (`rider_position_change` events, time standing, power and cadence per position).
  Records carry the per-second values; laps and the session the averages, computed like an
  Edge: over the pedalling seconds, balance weighted by power, angles averaged on the circle,
  transitions attributed to the following position (checked on a real ride against an Edge 540
  with the same pedals).
* HRV: beat-to-beat (R-R) intervals as FIT `hrv` messages, unless they are just 60 / HR (some
  straps over ANT+, e.g. a Polar, compute the beat times from their averaged heart rate).
* **How was it?** Once the ride is saved, a dialog asks for the perceived effort (RPE 1–10),
  the feel (very weak … very strong), the carbohydrates eaten (g) and the water drunk (ml), all
  optional, before the intervals.icu upload prompt. They are written into the FIT session like
  a Garmin Edge 540 does (`workout_rpe` = RPE × 10, `workout_feel` 0 / 25 / 50 / 75 / 100, and
  two undocumented fields read from an original Edge file: 177 = energy eaten in kcal, i.e.
  4 × the grams of carbohydrates, which intervals.icu shows as carbohydrates ingested; 179 =
  water in ml, shown in intervals.icu through a custom "Fluids in" field) and kept with the
  ride in the history (its *Feel* column). Asked once per ride in a browser, even after a page
  reload; Skip counts as an answer.
* Checkpoint: every 30 s the new samples are appended (and fsync'd) to
  `checkpoints/<session>.jsonl`; the file is deleted once the ride is saved or discarded. At
  startup, a leftover file becomes a ride named "… (recovered)".

## Speed model

Power balance at the wheel, ground speed `v`, road angle `θ` (`tanθ` = grade), wind components
relative to the direction of travel `v_w` (headwind, negative = tailwind) and `v_c` (crosswind):

```
η·P = m·g·v·(Crr·cosθ + sinθ) + ½·ρ·CdA·|V_a|·(v+v_w)·v + m_eff·(dv/dt)·v
|V_a| = √((v+v_w)² + v_c²)
```

* `m` = rider + bike, `m_eff = m + I_wheels / r²` (rotational inertia of the wheels).
* `ρ` comes from the route altitude (ISA barometric pressure), air temperature and humidity (Tetens).
* The equation of motion is **integrated in time** (midpoint method, 50 ms sub-steps, with the
  grade re-evaluated every sub-step). Momentum therefore carries through the foot of a climb or
  the start of a descent, instead of speed jumping to the steady-state solution.
* The drive force `ηP/v` is regularised as `ηP/max(v, 1 m/s)`, a finite starting torque. A
  stopped bike stays stopped when the static resistive force wins (no rolling backwards).
* Descents are capped by a virtual braking speed (default 70 km/h).
* Route distance is **horizontal** (map distance): position advances by `v·cosθ·dt`. The road
  distance `∫v dt` is also tracked.
* GPX processing: haversine distances, uniform resampling (~5 m), Gaussian smoothing of
  elevation in the distance domain (σ = 25 m, odd-reflected edges so end slopes are preserved),
  then `grade = d(ele)/d(dist)` clipped to ±30 %.
* The **speed-model power scale** `x %` (Profile, default 0) scales only the power fed to the
  speed model, in every mode: `P_model = P_measured·(1+x)`. The trainer target and the recorded
  power are unchanged; the virtual speed and distance (also in the FIT file) follow. Like the
  other model parameters, a change applies from the next ride.
* Wind (GPX rides, chosen when starting the route: speed `W` and the direction `φ` it blows
  from) is projected on the route heading `ψ` at each sub-step: `v_w = W·cos(φ−ψ)`,
  `v_c = W·sin(φ−ψ)`. The drag acts along the apparent wind, so a crosswind adds drag (CdA is
  taken independent of yaw). The heading is smoothed (unit vectors, σ = 25 m) so GPS zig-zags
  do not make the wind flicker. ERG rides (flat virtual road, no heading) have no wind.

The rider and bike parameters (CdA, Crr, η, wheel inertia, braking cap, curve points,
look-ahead, target ramp rate) are edited on the Profile page, which also previews
steady-state speeds. Edits apply once saved: the page shows "Unsaved changes" until then, and
leaving the tab asks Save / Discard / Stay (closing the page, the browser's own question).

**Estimated time of a route.** The routes list and the route detail show the time to ride it
(Slope ERG at 100 % effort, the rider holding the targets; in the list: no wind, standard
air), updated in the detail with the wind, the air, the direction and, with a workout, the
distance covered during it (the route loops). Same
equation of motion as the ride (`VirtualBike.accel`), integrated along the distance in 10 m
steps with an energy balance, `v_out² = v_in² + 2·a(v_mid)·L` (`L`: road length of the step),
so momentum carries over grade changes; the target goes through the same ramp limiter.
**During a GPX ride** the same estimate runs from the ride's state (position, speed, wind, air)
with its current settings: Slope ERG at the current effort, the manual target, or in Sim the
mean power of the last 30 s (held constant), gives the time left to the end of the route (`≈ 20:51` after "Left" in the progress block); a workout
running gives the distance left before it ends, its steps at the current intensity
(`≈ 20.8 km to go` under the workout profile). Recomputed off the engine loop every 10 s of
riding and at once on any settings change, counted down in between. It
stays within 0.4 % of the ride's own time integration on the sample route (both directions)
and a 15 km descent, in ~2 ms per km instead of ~50 ms. Not modelled: a rider missing the
targets, pauses.

**Bike & position presets.** The Profile offers typical bikes and positions instead of the
five bike parameters; *Custom* shows the fields (starting from the preset's values) to set
exact ones. The bike weight stays a separate field. Values (speeds: steady state, 73 kg rider
+ 10 kg bike, no wind, ρ = 1.2):

| Preset                 | CdA (m²) | Crr    | η     | I wheels (kg·m²) | Ø (m) | 200 W flat | 250 W flat | 250 W at 5 % |
|------------------------|----------|--------|-------|------------------|-------|------------|------------|--------------|
| Road bike, hoods       | 0.32     | 0.0045 | 0.976 | 0.14             | 0.670 | 33.9 km/h  | 36.9 km/h  | 17.9 km/h    |
| Road bike, drops       | 0.29     | 0.0045 | 0.976 | 0.14             | 0.670 | 35.0 km/h  | 38.0 km/h  | 18.0 km/h    |
| Time trial / triathlon | 0.28     | 0.0040 | 0.977 | 0.16             | 0.670 | 35.7 km/h  | 38.7 km/h  | 18.2 km/h    |
| Gravel (40 mm tyres)   | 0.35     | 0.0060 | 0.970 | 0.18             | 0.700 | 32.2 km/h  | 35.1 km/h  | 17.3 km/h    |
| Mountain bike 29"      | 0.45     | 0.0090 | 0.960 | 0.25             | 0.740 | 28.5 km/h  | 31.2 km/h  | 16.2 km/h    |
| City bike              | 0.55     | 0.0080 | 0.950 | 0.20             | 0.690 | 27.1 km/h  | 29.6 km/h  | 15.9 km/h    |

These are **orders of magnitude, not measurements**. CdA: the usual ranges are hoods
0.30–0.40, drops 0.27–0.35, time trial 0.22–0.26 for elite amateurs and 0.26–0.32 for
recreational riders (the preset takes a recreational value); methods in Debraux et al.,
*Aerodynamic drag in cycling: methods of assessment*, Sports Biomechanics 10(3), 2011. Crr:
real-road values, higher than drum measurements (bicyclerollingresistance.com), which rank
tyres well but read lower than real asphalt. The speed-model power scale is the knob to adjust
the result to how a ride feels. A profile saved before presets existed opens as *Custom*, with
its values unchanged.

## ANT+

One ANT node, three slave channels with wildcard pairing (the first device found). They are
plain channels searching in low priority only, with no timeout, so a channel looking for a
sensor never takes the radio from the others. (Background-scanning channels froze when the app
sent a command to a device on any channel but the first.)

| Device        | Type | Period | Pages used                                                  |
|---------------|------|--------|-------------------------------------------------------------|
| FE-C trainer  | 17   | 8192   | rx 16, 25, 71, 2 / 1 (calibration progress / result) · tx 49 (target power), 48 (free ride), 55 (user config), 1 (spin-down request) |
| Power meter   | 11   | 8182   | rx 18 (crank torque: power and cadence per crank revolution), else rx 16 (power-only; event-averaged power) · rx 16 byte 2 (L/R balance), 19 (torque effectiveness, pedal smoothness), 0xE0–0xE2 (Cycling Dynamics), 2 / 0xFE (capabilities), 1 / 0xAC–0xAF (calibration result) · tx 1 / 0xAA (zero offset request) |
| Heart rate    | 120  | 8070   | rx byte 7 (HR), bytes 4–6 (beat time and count → R-R), page 4 (previous beat time) |

Commands go out as acknowledged messages from a single sender thread, which coalesces requests
and re-sends the target every 2 s.

A watchdog closes and reopens the channel of a sensor that was heard and has then been silent
for 10 s (same pairing), at most once a minute: a channel can stay deaf while the device keeps
broadcasting, and a sensor that was switched off or fell asleep comes back on its own when it
wakes.

Cycling Dynamics (power phase, rider position, PCO) are only sent once a display enables them.
The app records them when a head unit (e.g. a Garmin Edge) has enabled them. Enabling them
from the app (Bicycle Power profile §4.5.2) is implemented but switched off: the test pedals
(Favero Assioma) refuse the 8 Hz rate the dynamics pages need. L/R balance,
torque effectiveness and pedal smoothness need no set-up.

## Bluetooth LE

Handled in the backend with [bleak](https://github.com/hbldh/bleak), in its own thread and
asyncio loop. Each device gets one connection that reconnects by itself. Standard services:

| Role        | Service           | Characteristics used                                               |
|-------------|-------------------|--------------------------------------------------------------------|
| Trainer     | FTMS (0x1826)     | Indoor Bike Data 0x2AD2 (power, cadence, speed) · Control Point 0x2AD9: request control, start, set target power (ERG, bounded by the Supported Power Range 0x2AD8 when the trainer has one), indoor-bike simulation at 0 % for free ride and at the route's grade in Sim |
| Power meter | Cycling Power (0x1818) | Measurement 0x2A63 (power; cadence from crank revolutions, 0 after 3 s without a new crank event; L/R balance) |
| Heart rate  | Heart Rate (0x180D) | Measurement 0x2A37 (heart rate; R-R intervals for the FIT HRV) |

FTMS has no rider-weight command (the User Data Service would need a consent procedure that
few trainers implement), so the user configuration is only sent over ANT+. Bluetooth speed /
cadence sensors (0x1816) are not supported.

## intervals.icu

On the Profile page, set your athlete id (`0` = owner of the key) and API key (intervals.icu →
Settings → Developer settings). The app uses:

* `GET /api/v1/athlete/{id}/events?category=WORKOUT` to list planned workouts (cycling
  types only: Ride, VirtualRide, GravelRide, MountainBikeRide, TrackRide, …),
* `GET /api/v1/athlete/{id}/events/{eventId}/download.zwo` to import one,
* `POST /api/v1/athlete/{id}/activities` (multipart `file`) to upload a ride: from the prompt
  shown when a ride is saved, or from History. A ride already uploaded is never sent twice.

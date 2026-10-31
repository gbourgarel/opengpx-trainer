# Home Trainer

Personal indoor-cycling app that drives a smart trainer over ANT+ (FE-C, USB stick) or
Bluetooth LE (FTMS), with power meter and heart-rate sensors on either protocol.

* **ERG workouts**: planned workouts fetched from intervals.icu (or imported `.zwo` / `.erg` / `.mrc`),
  with a live intensity % adjustment.
* **GPX routes** (pseudo-ERG): the trainer target power follows a configurable *grade → %FTP* curve
  on the look-ahead grade, or a target set by hand. Virtual speed and position on the trace come
  from a dynamic physics model fed with the measured power × (1 + difficulty %). Climb rate (VAM)
  and elevation gain are shown.
* **Workout on a route**: a GPX ride can follow a workout. The workout sets the target, the route
  gives speed and position, and the route loops while the workout lasts.
* Power is also shown in **W/kg** (rider mass).
* **Power source**: the power meter if one is detected (or forced), else the trainer. With a
  power meter, *power match* corrects the ERG target so the meter reads the requested power.
* Rides are recorded to `.fit` (cycling / virtual activity) and can be uploaded to intervals.icu.

```
backend/   Python 3.12 · FastAPI · openant · bleak · numpy · SQLite   (uv)
frontend/  React · Vite · TypeScript · Leaflet · uPlot
samples/   sample GPX route and ZWO workout
```

## Running

Prerequisites: [uv](https://docs.astral.sh/uv/), Node ≥ 20, and `brew install libusb` for the ANT+ stick.
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
cd backend && uv run hometrainer
```

Development, with hot reload on both sides:

```bash
cd backend && uv run hometrainer --reload      # :8000
cd frontend && npm run dev                     # :5173, proxies /api and /ws to :8000
```

### Testing without hardware (fake power input)

Click **Simulator** instead of **Connect sensors**. A simulator panel appears on the Ride page:

* **Follow target**: behaves like an ERG trainer, so power tracks the target with a 1.5 s lag.
* **Manual power**: you set the rider's power with the slider or ±10/±50 buttons, or from the
  keyboard (↑/↓ ±10 W, Shift ±50 W). Use it to probe the speed model on a GPX route.
* **Space** toggles pedaling, so you can watch the virtual bike coast and auto-pause.
* Switches for power meter / HR strap presence (turn the power meter off to see the *auto*
  source fall back to the trainer), sensor noise, and power-meter bias (default −3 %, which
  exercises power match).

The same controls are available over the API: `PUT /api/simulator` with e.g.
`{"mode": "manual", "manual_power_w": 300}`.

Tests: `cd backend && uv run pytest`, lint: `uv run ruff check src tests`.

Data (SQLite DB and `.fit` files) lives in `~/.hometrainer` (override with `HOMETRAINER_DATA`).

## Speed model

Power balance at the wheel, ground speed `v`, headwind `v_w`, road angle `θ` (`tanθ` = grade):

```
η·P = m·g·v·(Crr·cosθ + sinθ) + ½·ρ·CdA·(v+v_w)·|v+v_w|·v + m_eff·(dv/dt)·v
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
* Difficulty `x %` scales only the power fed to the speed model: `P_model = P_measured·(1+x)`.
  The trainer target is unchanged.

All parameters (CdA, Crr, η, wheel inertia, temperature, humidity, wind, braking cap, curve
points, look-ahead, target ramp rate) can be edited on the Profile page, which also previews
steady-state speeds.

## ANT+

One ANT node, three slave channels with wildcard pairing (the first device found):

| Device        | Type | Period | Pages used                                                  |
|---------------|------|--------|-------------------------------------------------------------|
| FE-C trainer  | 17   | 8192   | rx 16, 25, 71 · tx 49 (target power), 48 (free ride), 55 (user config) |
| Power meter   | 11   | 8182   | rx 16 (power-only; event-averaged power)                    |
| Heart rate    | 120  | 8070   | rx byte 7                                                   |

Commands go out as acknowledged messages from a single sender thread, which coalesces requests
and re-sends the target every 2 s.

## Bluetooth LE

Handled in the backend with [bleak](https://github.com/hbldh/bleak), in its own thread and
asyncio loop. Each device gets one connection that reconnects by itself. Standard services:

| Role        | Service           | Characteristics used                                               |
|-------------|-------------------|--------------------------------------------------------------------|
| Trainer     | FTMS (0x1826)     | Indoor Bike Data 0x2AD2 (power, cadence, speed) · Control Point 0x2AD9: request control, start, set target power (ERG), indoor-bike simulation at 0 % for free ride |
| Power meter | Cycling Power (0x1818) | Measurement 0x2A63 (power; cadence from crank revolutions, 0 after 3 s without a new crank event) |
| Heart rate  | Heart Rate (0x180D) | Measurement 0x2A37                                                |

FTMS has no rider-weight command, so the user configuration is only sent over ANT+.

## intervals.icu

On the Profile page, set your athlete id (`0` = owner of the key) and API key (intervals.icu →
Settings → Developer settings). The app uses:

* `GET /api/v1/athlete/{id}/events?category=WORKOUT` to list planned workouts,
* `GET /api/v1/athlete/{id}/events/{eventId}/download.zwo` to import one,
* `POST /api/v1/athlete/{id}/activities` (multipart `file`) to upload a ride.

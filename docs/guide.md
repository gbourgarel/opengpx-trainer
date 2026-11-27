# Using OpenGPX Trainer

This guide takes you through the first setup, in order, then your first rides. Not installed
yet? See the [install guide](https://github.com/gbourgarel/opengpx-trainer/blob/main/docs/install.md).

## First setup

Do these steps once, in this order. All of them are in the **Profile** tab, and nothing is
used until you click **Save profile** (bottom of the page).

### 1. Rider & bike

Fill in **Rider weight**, **Bike weight** and your **FTP** (the power you can hold for about an
hour; a guess is fine to begin with). Workout targets and the Slope ERG power are percentages
of your FTP, and the virtual speed depends on the weights.

Optional: **Threshold HR** colours your heart rate by zone during the ride.

### 2. Speed model

Pick the **Bike & position** that matches yours (road bike on the hoods, on the drops, TT…).
It sets how fast the virtual bike goes for a given power. The line below shows a few examples
(200 W on the flat → … km/h).

### 3. Devices

1. Wake the sensors up: a few pedal strokes, the heart-rate strap on.
2. Quit the other apps that may hold them (Zwift, Garmin Express, TrainerRoad…): a sensor
   often accepts a single connection.
3. Click **Scan for devices** (about 6 s). The list shows ANT+ and Bluetooth sensors.
4. Click **Use as trainer** next to your smart trainer, then **Use as power meter** and
   **Use as heart rate** if you have them. A trainer alone is enough: it measures the power.
5. Click **Save profile**.
6. Click **Connect sensors** at the top of the page. The dots next to *Trainer*, *Power* and
   *HR* turn green once each sensor is connected.

The app connects to the same sensors next time: only **Connect sensors** is needed.

### 4. Power source

With a power meter on the bike, keep **Auto**: its power is used for the speed and the
recording, the trainer's otherwise. **Power match** corrects the trainer so that the power
meter reads the target power.

### 5. intervals.icu (optional)

To fetch the workouts planned in [intervals.icu](https://intervals.icu) and upload your rides
there: your **Athlete ID** and **API key**, both in intervals.icu under *Settings →
Developer settings*.

### 6. Calibration (if the trainer asks for it)

Some trainers want a **spin-down** after a warm-up. When the trainer asks for it, the Ride tab
says so before the ride; it can also be done from Profile → Devices, or with the ride paused.
A dialog guides you: pedal up to the speed shown, then stop pedalling and let the wheel coast.
A power meter can likewise get its **zero offset**: unclip, cranks still.

## Riding a route (GPX)

1. **Routes (GPX)** tab: **Import GPX** (or drop `.gpx` files onto the page). To try, a
   [sample climb](https://github.com/gbourgarel/opengpx-trainer/raw/main/samples/sample_climb.gpx).
2. Choose the route. Before starting you can set:
   * the **wind** and the **air** (temperature, humidity), or **Weather now** for the current
     weather along the route;
   * **Reverse**, to ride it the other way;
   * a start point part-way: click the map or the elevation profile;
   * a **Workout** to follow on the route (it sets the target while the route loops).
3. Click **Ride this route** (**Ride with workout**), then pedal: the ride starts on its own.

On a route, what sets the trainer is chosen in the ride controls:

* **Slope ERG** (default): the trainer holds a target power that follows the grade ahead (more
  on climbs, less downhill), from your FTP. No need to shift. The curve is in Profile → *Slope
  ERG*; **Effort** (↑ / ↓) raises or lowers it during the ride.
* **Sim**: the classic mode. The trainer simulates the grade (× the **trainer effect**, 50 %
  to begin with), you shift and choose your power as on the road.
* **Manual**: a target in watts that you set.

## Riding a workout (ERG)

1. **Workouts (ERG)** tab: **Import .zwo / .erg / .mrc** (or drop the file onto the page), or
   **Load planned from intervals.icu**. To try, a
   [sweet-spot workout](https://github.com/gbourgarel/opengpx-trainer/raw/main/samples/sweet_spot.zwo).
2. Click **Ride (ERG)** and pedal. The trainer holds each step's power: pedal at the cadence
   you like, no need to shift.

During the workout: **Intensity** (↑ / ↓) scales every target, **+1 min** lengthens the current
step, **Skip step** goes to the next one. Beeps 3-2-1 announce each step change (**Sound
on / off**, or M).

## During the ride

* The ride **pauses on its own** when you stop pedalling and resumes when you pedal again.
* Keyboard: **Space** pause / resume, **↑ / ↓** (or + / −) the value of what sets the target
  (intensity, effort or watts), **M** sound, **V** the immersive 3D view of a route (**F**
  full screen in it, **Esc** to leave).
* The screen stays on during the ride.
* A red banner says when a sensor stops sending data.

## After the ride

1. Click **Stop**, then **Save** (or **Discard**). A route ride ends on its own at the finish.
2. **How was it?**: how hard it felt, and optionally what you ate and drank. It is written into
   the FIT file; **Skip** is fine.
3. With intervals.icu set up, the app offers to upload the ride (never without asking).
4. **History** tab: every ride, with its **.fit** button to download the file and upload it to
   Strava, Garmin Connect, etc.

## If something goes wrong

* **A sensor is not found**: wake it up, quit the other apps, scan again. On a Mac, Bluetooth
  must be allowed for Terminal (System Settings → Privacy & Security → Bluetooth). On
  Windows, an ANT+ stick needs the WinUSB driver (see the install guide).
* **The page shows "backend offline"**: the terminal window running the app was closed or
  stopped; start `opengpx-trainer` again.
* **The app or the computer crashed during a ride**: the ride is saved every 30 s and shows up
  in the History at the next start.
* **The virtual speed feels too fast or too slow**: check the weights and the Bike & position
  in Profile.

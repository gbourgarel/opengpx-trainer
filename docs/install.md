# Installing OpenGPX Trainer, step by step

*[Version française](install.fr.md)*

OpenGPX Trainer is a free app to ride a smart trainer: follow any GPX route or do structured
workouts. It shows in your web browser (Chrome, Safari, Firefox…) but runs on your own
computer, with no account to create.

Installing it takes **three commands** typed in a terminal. No worries: you only copy and
paste them.

## 1. Open a terminal

A terminal is a window where you type commands instead of clicking.

* **Mac**: press **Cmd + Space**, type **Terminal**, press **Enter**.
* **Windows**: open the Start menu, type **PowerShell**, click **Windows PowerShell**.

A window with some text and a blinking cursor opens. That is normal.

## 2. Install uv (once)

uv is a small tool that installs the app and everything it needs. Copy the line for your
computer, paste it into the window (right click → Paste, or Cmd+V / Ctrl+V) and press
**Enter**.

**Mac:**

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows:**

```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Wait until the text stops scrolling, then **close the window and open a new one** (as in
step 1). Otherwise the next step does not work.

## 3. Install the app (once)

In the new window, paste this line (the same on Mac and Windows) and press **Enter**:

```
uv tool install https://github.com/gbourgarel/opengpx-trainer/releases/download/v1.0.0/opengpx_trainer-1.0.0-py3-none-any.whl
```

It takes a minute. It is done when you see `Installed 1 executable: opengpx-trainer`.

## 4. Start the app (every ride)

Open a terminal (or PowerShell), type this and press **Enter**:

```
opengpx-trainer
```

The app opens in your browser. If it does not, go to **http://127.0.0.1:8000**.

⚠️ **Keep the terminal window open while you ride**: it is what runs the app. When you are
done, click in that window, press **Ctrl + C** (also on a Mac), then close it.

## 5. Connect the trainer and the sensors

1. Wake your sensors up: pedal a few turns, put the heart-rate strap on.
2. In the app, open the **Profile** tab. Fill in at least **Rider weight**, **Bike weight**
   and your **FTP**.
3. Under **Devices**, click **Scan for devices**. In the list, click **Use as trainer** next to
   your trainer, and likewise **Use as power meter** / **Use as heart rate** if you have them.
4. Click **Save profile** at the bottom of the page.
5. Click **Connect sensors** at the top of the page.

If a sensor does not show up:

* **Quit Zwift, Garmin Express, TrainerRoad**, etc.: a sensor often talks to only one app at
  a time.
* **Bluetooth on a Mac**: the first time, allow it for Terminal in **System Settings →
  Privacy & Security → Bluetooth**, then start the app again.
* **ANT+ USB stick on Windows**: it needs a driver, installed once with the small program
  **Zadig** (https://zadig.akeo.ie/). Plug the stick in, open Zadig, pick the stick in the list
  (*ANT USBStick2* or *ANT USB-m Stick*), choose **WinUSB** and click **Install Driver**.
  Garmin Express then no longer sees the stick. On a Mac the ANT+ stick works as is.

## 6. Ride

* **Routes (GPX)** tab: **Import GPX** adds a route; pick it and click **Ride this route**.
* **Workouts (ERG)** tab: import a workout file (.zwo, .erg or .mrc), or **Load planned from
  intervals.icu** if you use intervals.icu; then **Ride (ERG)**.

The ride starts when you pedal. At the end, it is saved as a FIT file: in the **History** tab,
the **.fit** button downloads it, to upload to Strava, Garmin Connect, etc.

## Updating

Run step 3 again with the link of the newest `.whl` file from the
[Releases page](https://github.com/gbourgarel/opengpx-trainer/releases). Your rides and
settings are kept.

## Windows

The app has not been tried on a real Windows PC with sensors yet. If something goes wrong,
please say so in an [issue](https://github.com/gbourgarel/opengpx-trainer/issues): feedback is
welcome.

# 08 · Hardware Build Guide (step by step)

This is the hands-on companion to the BOM in
[`03-hardware-bom.md`](03-hardware-bom.md). It takes you from parts-in-boxes to a
calibrated, auto-starting system installed in a vehicle.

**Golden rule: build and verify everything on the bench before it goes near the
car.** Every stage below ends with a **✅ gate** — a concrete check. Do not move
on until the gate passes. Debugging a wiring fault on a bench with a multimeter
takes minutes; debugging it under a dashboard takes hours.

> ⚠️ **Vehicle electrical safety.** You'll tap 12 V from the car. Always put an
> inline fuse (3–5 A) within a few inches of the battery/tap. Never work on
> wiring with the circuit live. A shorted unfused tap can start a fire. If you're
> not comfortable with automotive 12 V, have the final power tap done by an
> installer — the rest you can do yourself.

---

## Stage 0 — Inventory, tools, and prep

**Tools & consumables (beyond the BOM):**
- Multimeter (non-negotiable — you'll use it every stage)
- Bench DC power supply, adjustable 0–15 V with current limit (ideal), *or* a
  12 V supply + a car battery for realism
- Wire strippers, ratcheting crimper, heat-shrink, small screwdrivers
- Assorted crimp connectors, inline fuse holder + fuses, a fuse-tap for the car
- Dupont jumper wires (for the 40-pin header), a breadboard for bench tests
- An Ubuntu 20.04/22.04 host PC with a USB cable — **required** to flash the
  Jetson via NVIDIA SDK Manager
- Zip ties, adhesive cable mounts, a label maker if you have one

**✅ Gate 0:** Every BOM line item is physically present and accounted for, and
you have all the tools above. Missing the multimeter or the Ubuntu flashing host
will stall you later — sort them now.

---

## Stage 1 — Jetson bring-up (flash + boot)

Goal: a Jetson Orin Nano Super that boots JetPack 6 **from the NVMe SSD** and
reports its GPU.

1. **Fit the NVMe SSD** into the carrier's M.2 Key-M slot (the wide one), screw
   it down. Leave the microSD slot empty for now.
2. **Install SDK Manager** on your Ubuntu host (from NVIDIA's developer site).
3. **Enter Force Recovery mode:** with the board powered off, jumper the `FC REC`
   pin to `GND` on the button header (or hold the recovery button), then apply
   power. Connect the host via USB-C.
4. In SDK Manager, select **Jetson Orin Nano (Super)** + **JetPack 6.x**, and
   choose **NVMe** as the storage target. Flash. This takes a while.
5. Remove the recovery jumper, reboot, complete the Ubuntu first-boot setup
   (user, locale, network).
6. **Unlock Super performance:** update to the JetPack that enables the Super
   modes if prompted, then:
   ```bash
   sudo nvpmodel -p --verbose      # list power modes; find the MAXN SUPER id
   sudo nvpmodel -m <maxn_super_id>
   sudo jetson_clocks              # lock clocks to max
   ```
7. **Install the monitor:** `sudo pip3 install jetson-stats` then run `jtop`.

**✅ Gate 1:** `jtop` shows the GPU, the correct power mode (MAXN SUPER), and the
board boots from NVMe with the microSD slot empty. Reboot once more and confirm
it comes back up on its own.

**Pitfalls:** flashing to NVMe *requires* the SDK Manager host — you can't do it
from the board alone. If SDK Manager can't see the board, you're not truly in
recovery mode (re-check the jumper) or it's a USB-C data-cable issue.

---

## Stage 2 — Storage layout

Goal: OS on NVMe (done), plus the two recording volumes mounted reliably.

1. Insert the **high-endurance microSD** — this is the ring-buffer scratch.
2. Plug in the **USB 3 SSD** (blue USB3 port) — this is the evidence archive.
3. Format both as ext4 and give them stable mount points via `/etc/fstab` using
   **UUIDs** (never `/dev/sdX`, which can reorder):
   ```bash
   lsblk -f                                  # find the devices + UUIDs
   sudo mkfs.ext4 /dev/mmcblk1p1             # the microSD (confirm the name!)
   sudo mkfs.ext4 /dev/sda1                  # the USB SSD (confirm the name!)
   sudo mkdir -p /var/tvds/ring /var/tvds/archive
   # add to /etc/fstab, e.g.:
   # UUID=<sd-uuid>   /var/tvds/ring    ext4 defaults,noatime,nofail 0 2
   # UUID=<ssd-uuid>  /var/tvds/archive ext4 defaults,noatime,nofail 0 2
   sudo mount -a
   ```
   `noatime` reduces write wear; `nofail` keeps the box booting if a drive is
   absent.
4. Point the config at them later (`recorder.archive_dir`, `storage.media_dir`).

**✅ Gate 2:** Both volumes auto-mount after a reboot (`df -h` shows them at
`/var/tvds/...`), and you can create and read back a test file on each.

---

## Stage 3 — Cameras

Goal: both cameras enumerate and produce sharp frames. We use **USB3 cameras**
(not CSI) deliberately — no ribbon/driver pain, and the plate camera must be
**global shutter** (see [`07`](07-changes-from-original-spec.md)).

1. Plug the **wide forward camera** into a USB3 port. Then the **global-shutter
   telephoto**.
2. Enumerate:
   ```bash
   v4l2-ctl --list-devices
   v4l2-ctl -d /dev/video0 --list-formats-ext   # see supported res/fps
   ```
3. Grab a live preview to focus and aim (do this pointed out a window at traffic):
   ```bash
   gst-launch-1.0 v4l2src device=/dev/video0 ! videoconvert ! autovideosink
   ```
4. **Focus the telephoto** on a parked car's plate ~10–15 m away; lock the focus
   ring. **Aim** it slightly down-road and level.
5. Note which `/dev/videoN` is which — you'll set `capture.source` and
   `capture.plate_source` accordingly. (USB video nodes can reorder across
   reboots; if that bites you, pin them with a `udev` rule by serial.)

**✅ Gate 3:** Both cameras give a live, in-focus image. On the telephoto, a
parked car's plate is clearly human-readable in the preview. Grab a still and
confirm the plate characters are legible — this predicts ALPR success.

**Pitfalls:** rolling-shutter smear on the plate camera means you bought the
wrong sensor — verify global shutter now, not after install. USB3 cameras + a
GPS/Bluetooth antenna nearby can interfere; keep leads short.

---

## Stage 4 — Sensors (bench)

Goal: GPS fix, IMU reads, OBD connects — all on the bench.

**IMU (I²C, 40-pin header):**
```
Header pin 1 (3.3V) ─→ IMU VCC        Header pin 3 (SDA / I2C1) ─→ IMU SDA
Header pin 6 (GND)  ─→ IMU GND        Header pin 5 (SCL / I2C1) ─→ IMU SCL
```
```bash
sudo i2cdetect -y -r 1     # IMU address should appear (e.g. 0x28 for BNO085)
```
Set that address in `config.yaml` (`sensors.imu.i2c_addr`).

**GPS/GNSS (USB):**
```bash
sudo apt-get install -y gpsd gpsd-clients
sudo systemctl enable --now gpsd
cgps -s                    # near a window; wait for a 3D fix
```

**OBD-II (bench-optional):** you can't get real speed on a bench, but confirm the
adapter enumerates (USB `/dev/ttyUSB*`, or pair over Bluetooth). Full OBD test
happens in the car at Stage 8.

**✅ Gate 4:** `i2cdetect` shows the IMU; moving the IMU by hand changes its
readings; `cgps` reaches a 3D GPS fix with several satellites.

---

## Stage 5 — Power subsystem (the part people skip and regret)

Goal: the box runs from 12 V, survives a simulated engine crank, and **shuts
down cleanly when 12 V is removed** — with the supercap carrying it through.

Wiring (bench version, using your adjustable supply as "the car"):
```
 Bench PSU + ──[ 5A fuse ]── DC-DC IN+          DC-DC OUT 5V ─→ Supercap/UPS module ─→ Jetson DC jack
 Bench PSU + ─────────────── DC-DC ENABLE/IGN   UPS "power-good" out ─→ (level shift) ─→ Jetson GPIO
 Bench PSU − ─────────────── DC-DC IN- / GND    Jetson GND ───────────────────────────── common GND
```

1. **Set the DC-DC output to 5 V** (or the Jetson jack's rated voltage — check the
   kit label) *before* connecting the Jetson. Verify with the multimeter.
2. **Ignition/power-good sense → GPIO.** The car's ignition line is 12 V; the
   Jetson GPIO is 3.3 V-tolerant only. Use **either**:
   - an **optocoupler board** (cleanest, isolated): 12 V ignition drives the LED
     side; the transistor side pulls a GPIO high/low at 3.3 V; **or**
   - a **resistor divider** (e.g. 10 kΩ / 3.3 kΩ) to bring 12 V down to ~3 V.

   Many supercap/DC-UPS modules also expose a **PGOOD** ("power good") signal —
   that's the ideal thing to wire to the GPIO, because it tells you the *input*
   is gone while the cap is still powering the board.
3. **Wire the watcher** (software from Stage 6): `scripts/power_watch.py` reads
   that GPIO and issues `shutdown` after the signal is lost for a few seconds
   (long enough to ignore a crank dip, short enough that the cap can outlast it).
4. **Bench tests:**
   - **Crank simulation:** with everything running, briefly sag the PSU to ~8–9 V
     for ~1 s, back to 12 V. The Jetson must **not** reboot and the watcher must
     **not** trigger a shutdown.
   - **Power-loss test:** cut the PSU entirely. The supercap should hold 5 V long
     enough for the watcher to run `shutdown` and the OS to halt **before** 5 V
     collapses. Time it — you want the halt to finish with margin.

**✅ Gate 5:** Survives the crank sag without rebooting; on full power loss it
performs a clean `shutdown` and halts before the cap dies. Measure the shutdown
duration and confirm the cap holds longer than that.

**Pitfalls:** a bare buck converter with no load-dump protection can pass a
40 V+ spike straight into the Jetson and kill it — use the automotive-grade
DC-DC from the BOM. Undersized supercap = the OS gets cut off mid-write and
corrupts the card; that's exactly what this stage exists to prevent.

---

## Stage 6 — Software install & first full pipeline run (bench)

Goal: the actual TVDS software running on the device, end to end, on the bench.

1. Clone the repo onto the Jetson and run the provisioner:
   ```bash
   git clone https://github.com/jdlemay/traffic-violation-detector
   cd traffic-violation-detector
   bash scripts/setup_jetson.sh
   ```
2. Install PyTorch/torchvision from the **NVIDIA Jetson wheel index** (not PyPI),
   then export the model to TensorRT on-device:
   ```bash
   yolo export model=yolo11s.pt format=engine half=True device=0
   ```
3. Edit `config/config.yaml`: set `capture.source`/`plate_source` to your video
   nodes, `recorder.archive_dir: /var/tvds/ring`,
   `storage.media_dir: /var/tvds/archive`, IMU address, and detector `model` to
   the exported `.engine`.
4. First run, watching live:
   ```bash
   PYTHONPATH=src python3 -m tvd.main --config config/config.yaml
   ```
   Point the camera at traffic (out a window). Confirm detections appear and,
   when you shake the IMU, a `collision`/`harsh_driving` event fires and a clip +
   still land in `/var/tvds/archive`.
5. Install both services so it starts on boot:
   ```bash
   sudo cp deploy/tvds.service deploy/tvds-power-watch.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now tvds tvds-power-watch
   journalctl -u tvds -f
   ```

**✅ Gate 6:** The pipeline runs on the device at your target frame rate
(`jtop` shows GPU load, not thermal throttle), events produce clips+stills on the
archive volume, and after a reboot both services come up automatically.

---

## Stage 7 — Enclosure & thermal

Goal: everything packaged to survive heat and vibration.

1. Mount the carrier in the vented enclosure with standoffs; keep the fan intake
   and exhaust clear. Add a case fan if the BOM's included one isn't enough.
2. Route internal cables with slack and strain relief; nothing pulling on a
   connector. Hot-glue or zip-tie the Dupont IMU leads — vibration loosens them.
3. **Thermal soak:** run the pipeline for 30+ minutes in a warm room and watch
   `tegrastats`/`jtop` for throttling. Target: no throttle at ~45 °C ambient.

**✅ Gate 7:** 30-minute soak at target fps with **no thermal throttling**, and
no connector backs out when you (gently) shake the enclosure.

---

## Stage 8 — Vehicle installation

Goal: the box in the car, powered from the vehicle, cameras aimed, OBD connected.

1. **Cameras:** mount high and centered behind the mirror, in the wiper-swept
   zone, **legal** for your state (see
   [`06`](06-legal-and-privacy.md#4-windshield-mounting-laws)). Use
   vibration-damped ball mounts. Aim the wide cam level down-road; aim the
   telephoto slightly down and lock it.
2. **Compute box:** somewhere ventilated (under dash / console with airflow), not
   baking on the dash in the sun. Secure it so it can't fly loose in a stop.
3. **Power tap:** run the fused 12 V from the battery or a **fuse-tap** at the
   fuse box. Take **ignition/ACC** from a switched circuit (only live when the key
   is on). Common-ground to chassis. Double-check with the multimeter *before*
   connecting the DC-DC: constant 12 V on the battery line, 0 V→12 V on the ACC
   line as you turn the key.
4. **OBD-II:** plug the adapter into the OBD port; route or Bluetooth-pair it.
   Run the real OBD test:
   ```bash
   PYTHONPATH=src python3 -c "import obd; c=obd.OBD(); print(c.query(obd.commands.SPEED))"
   ```
   Set `sensors.obd.port` in the config if not auto-detected.
5. **GNSS antenna:** place with sky view (top of dash), away from USB3 leads.

**✅ Gate 8:** Key on → the box powers up and the service starts. Key off → the
watcher triggers a clean shutdown (watch `journalctl` on the next boot for the
clean halt). OBD returns a live speed while driving. GPS holds a fix. **The car
battery is not being drained when parked** — confirm the box is fully off on ACC
loss (measure quiescent current if unsure).

---

## Stage 9 — Camera calibration

Goal: distance/speed estimates that are actually correct. Required for
tailgating, TTC, and any speed math (see [`05`](05-detection-design.md#calibration)).

1. Park facing a straight, flat stretch. Place markers at known distances ahead
   (e.g. 5, 10, 20, 30 m) along your lane — or use lane-dash geometry.
2. Capture a frame; note the **image pixel** of each marker's ground contact and
   its real **ground coordinate** (X across, Y forward, meters).
3. Fit and save the homography:
   ```python
   from tvd.geometry import fit_ground_homography
   H = fit_ground_homography(image_points, ground_points)
   print(H.tolist())   # paste into config.yaml under geometry.homography
   ```
4. **Validate:** with `H` set, check the estimated distance to a known object vs.
   a tape measure — aim for < 10% error.

**✅ Gate 9:** Estimated distance to a known target is within ~10% of measured.
Until this passes, keep distance-based detectors in their degraded (proxy) mode.

---

## Stage 10 — Road test & tuning

Goal: real-world precision. Drive, review, adjust thresholds, repeat.

1. Do a mix of drives (highway, city, day, dusk). Let it record.
2. Review with the local UI:
   ```bash
   python3 -m tvd.review --db /var/tvds/archive/events.db
   ```
   Browse events, watch clips, sanity-check GPS/speed on each.
3. **Tune thresholds** in `config.yaml` from what you see:
   - Too many pothole "collisions"? Raise `violations.collision.threshold_g`.
   - Tailgating firing on curves? Tighten lane tolerance / raise `hold_seconds`.
   - Missing real events? Lower the relevant threshold a notch.
4. Track precision: for a batch of events, how many are true? Iterate until the
   Tier-1 events hit your target (≥ 90% precision, per
   [`01`](01-project-plan.md#2-success-criteria-v1)).

**✅ Gate 10:** A representative drive yields events that are overwhelmingly real
(few false positives), each with a correct clip, GPS, and speed. That's a
working v1.

---

## Appendix A — 40-pin header quick reference (the pins we use)

| Pin | Function | Used for |
| --- | --- | --- |
| 1 | 3.3 V | IMU VCC |
| 3 | I2C1 SDA | IMU SDA |
| 5 | I2C1 SCL | IMU SCL |
| 6 | GND | IMU GND |
| (any free GPIO, e.g. 7) | GPIO input | ignition/PGOOD sense (via opto/divider) |

Set the exact GPIO pin you use in `config.yaml` under `power.ignition_gpio` and
in `scripts/power_watch.py`'s `--pin`.

## Appendix B — Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| SDK Manager can't see board | Not in recovery / wrong USB cable | Re-check FC REC jumper; use a data USB-C cable |
| Reboots on engine start | No load-dump protection / weak supply | Use automotive DC-DC; check crank sag test (Stage 5) |
| Card corrupts after drives | Ungraceful power-off | Fix ignition sense + supercap + watcher (Stage 5) |
| Plate unreadable | Rolling shutter or bad focus/aim | Confirm global-shutter sensor; refocus/lock (Stage 3) |
| Distance/speed wrong | Not calibrated / camera moved | Redo homography (Stage 9); lock the mount |
| No thermal headroom | Poor airflow / no Super clocks | Improve venting; `jetson_clocks`; check `nvpmodel` |
| GPS never fixes | Antenna blocked / USB3 noise | Move antenna to sky view, away from USB3 leads |

---

**Build order recap:** flash → storage → cameras → sensors → **power (bench crank
+ loss tests)** → software end-to-end → enclosure/thermal → vehicle install →
calibrate → road-test & tune. Each ✅ gate protects the next stage. The power
stage is the one that most often gets skipped and most often kills the build —
don't.

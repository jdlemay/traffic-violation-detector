# 03 · Hardware Bill of Materials, Wiring & Mounting

Prices are approximate USD, mid-2025, single-unit retail. Swap-in alternatives
are listed so you can trade cost vs. quality.

## 1. Bill of materials

### Compute
| Item | Recommended part | ~Price | Notes |
| --- | --- | --- | --- |
| Edge AI compute | **NVIDIA Jetson Orin Nano Super Developer Kit (8 GB)** | $249 | 67 TOPS after the Super firmware. Includes carrier board + heatsink/fan. |
| — alt (more headroom) | Jetson Orin NX 16 GB + carrier | $600+ | If you push multiple 4K streams or heavier models. |

### Cameras & lenses
| Item | Recommended part | ~Price | Notes |
| --- | --- | --- | --- |
| Forward wide camera | USB3 or CSI **1080p60, ~120° HFOV**, good low-light (e.g. IMX291/IMX327 module) | $60–120 | Rolling shutter OK for scene/lane/vehicle detection. |
| Plate/telephoto camera | **Global-shutter USB3** (e.g. Sony IMX296/IMX264 module) + **fixed ~16 mm lens** | $150–220 | Global shutter is essential to freeze moving plates. Narrow FOV = more pixels on plate. |
| — alt single-camera build | Just the wide camera | — | ALPR quality drops; fine for Tier-1 only. |

> **Why global shutter for plates:** a rolling-shutter sensor exposes rows
> sequentially, so a car crossing the frame skews and smears — plate characters
> become unreadable at relative speeds above ~30 km/h. Global shutter exposes the
> whole frame at once. This one choice dominates ALPR success.

### Storage
| Item | Recommended part | ~Price | Notes |
| --- | --- | --- | --- |
| OS / boot | **M.2 NVMe SSD 256–500 GB** | $40–70 | Boot Jetson from NVMe, *not* SD. Far faster + reliable. |
| Ring-buffer scratch | **High-endurance ("dashcam-rated") microSD 128 GB** | $25 | Rated for continuous write; consumer cards die in weeks here. |
| Evidence archive | **USB 3 SSD 1–2 TB** | $90–150 | Event clips + rolling archive. |

### Sensors
| Item | Recommended part | ~Price | Notes |
| --- | --- | --- | --- |
| GNSS + dead reckoning | **u-blox ZED-F9R** module (or NEO-M9N if budget) | $60–120 | DR keeps position/speed through tunnels & urban canyons. |
| IMU | **6/9-axis** (e.g. BNO085 / ICM-20948) over I²C | $15–35 | BNO085 does onboard fusion → clean orientation. |
| Vehicle bus | **OBD-II to USB or Bluetooth** (ELM327-class, prefer a quality STN2120) | $20–40 | True wheel speed, RPM, brake/throttle on many vehicles. |

### Power
| Item | Recommended part | ~Price | Notes |
| --- | --- | --- | --- |
| DC-DC converter | **Automotive-grade 12V→5V/5A** with wide input & load-dump protection | $30–50 | Not a bare buck board — must survive cranking dips & 40V load dumps. |
| Ignition sense | Wire to a **switched/ACC 12V** source (or a 3-wire hardwire kit with ignition detect) | $15 | Lets the Pi/Jetson know when the engine turns off. |
| Graceful-shutdown reserve | **Supercapacitor module** (e.g. 2×10F) or small UPS HAT | $25–40 | Holds 5V for the few seconds needed to `shutdown -h`. |

### Enclosure, cooling, mounting
| Item | Recommended part | ~Price | Notes |
| --- | --- | --- | --- |
| Enclosure | Vented ABS/aluminum enclosure sized for carrier + fan | $30–50 | Aluminum helps as a heatsink. |
| Active cooling | The kit fan + optional 40 mm case fan | included/$10 | Cabin can hit 70 °C; keep airflow. |
| Camera mounts | Windshield suction or adhesive GoPro-style mounts, ball-joint | $20–40 | Rigid, vibration-damped, legal placement (see §4). |
| Cabling | USB3 (short, shielded), power leads, inline fuse (3–5 A), fuse tap | $30 | Always fuse the 12V tap. |

**Single-unit total ≈ $1,060** (see budget table in
[`01-project-plan.md`](01-project-plan.md)).

## 2. Power wiring diagram

```
 Vehicle 12V battery (+) ──[ inline 5A fuse ]── DC-DC IN+ ──┐
                                                            │  Automotive
 Vehicle ACC/ignition (switched 12V) ── DC-DC ENABLE/SENSE  │  DC-DC 12→5V
                                                            │  (load-dump
 Vehicle GND (chassis) ────────────────── DC-DC IN- / GND ──┘   protected)
                                                            │
                                        DC-DC OUT 5V ──► Supercap module ──► Jetson USB-C PD / barrel 5V
                                                            │
                        GPIO/ADC reads ignition-sense line ─┘  (software watches it)
```

- **Fuse everything** tapped from the battery (3–5 A inline).
- **Ignition-sense** goes to a Jetson GPIO through a voltage divider (12V→3.3V
  logic). Software (`sensors/` + a small watcher) triggers `systemd` shutdown
  when the line drops and the supercap is carrying the load.
- **Never** run the Jetson straight off a bare 12V→5V buck without load-dump
  protection; alternator load dumps can spike to 40 V+.

## 3. Data/sensor wiring

| From | To | Bus |
| --- | --- | --- |
| Wide camera | Jetson USB3 (or CSI ribbon) | USB3 / MIPI CSI-2 |
| Telephoto camera | Jetson USB3 | USB3 |
| GNSS module | Jetson USB or UART | USB/serial (NMEA + UBX) |
| IMU | Jetson I²C (pins 3/5) | I²C |
| OBD-II adapter | OBD port ↔ Jetson USB/BT | USB or Bluetooth |
| NVMe | M.2 slot on carrier | PCIe |
| Archive SSD | Jetson USB3 | USB3 |

Keep USB3 leads short and shielded — USB3 radiates ~2.4 GHz noise that can
desense GNSS/Bluetooth. Route the GNSS antenna away from USB3 cabling.

## 4. Mounting & placement (also a legal matter)

- Mount cameras high and centered behind the mirror; keep the wiper-swept zone
  clear. Many states restrict how much windshield area a device may block and
  where it may be placed — check your jurisdiction (see
  [`06-legal-and-privacy.md`](06-legal-and-privacy.md)).
- Use vibration-damped ball mounts; rigid metal mounts transfer road buzz and
  ruin ALPR and IMU signals.
- The telephoto should sit level and be aimed slightly down-road; lock it once
  calibrated (calibration depends on a fixed pose).
- Keep the compute box in a ventilated spot (not baking on the dash in the sun);
  under-dash or center console with airflow is ideal.

## 5. Bench bring-up checklist (Phase 1)

1. Flash Jetson, enable NVMe boot, confirm `nvidia-smi`/`jtop` shows the GPU.
2. Power the whole rig from the DC-DC on a bench 12V supply; sag the supply to
   simulate cranking and confirm no reboot.
3. Cut 12V; confirm supercap holds 5V and software issues a clean shutdown.
4. Enumerate both cameras (`v4l2-ctl --list-devices`), grab test frames.
5. Confirm GNSS fix (`gpsmon`/`cgps`), IMU reads (I²C scan), OBD connects.
6. Run a 30-minute thermal soak at target fps; watch `tegrastats` for throttling.

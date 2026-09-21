# PMW3610 standalone trackball test

Solder-test firmware for the [Sidera PMW3610 PCB Rev. 2.x](https://siderakb.ziteh.dev/mouse-sensors/pmw3610/rev2/), using one **nice!nano v2** controller.

> **Assembly note — C1 substitution:** This board was assembled with **4.7 µF for C1** instead of the BOM's **3.3 µF**, because 3.3 µF was hard to find. It still seems to work fine in the trackball test with this substitution.

The `pmw3610_test` shield sends sensor movement straight to a USB mouse at **600 CPI** and exposes a USB serial debug log. It has no physical keys, mouse buttons, layers, split connection, Bluetooth, or ZMK Studio. A one-position, empty mock scan satisfies ZMK's keymap requirement without using any keyboard GPIOs.

## Wiring

Configure the sensor PCB for **3.3 V logic**: bridge **JP1 pads 1–2**, leaving pad 3 separate. Supply VIN from the nice!nano's **3.3 V VCC**, not RAW, the battery terminal, or 5 V. The PCB's regulator supplies the sensor's internal 1.8 V rail.

Use the connector's pin numbers/silkscreen; the header and FFC orders differ:

| Sensor signal | J1 header pin | J2 FFC pin | nice!nano v2 connection |
|---------------|---------------|------------|-------------------------|
| VIN | 1 | 2 | VCC / 3.3 V |
| GND | 2 | 1 | GND |
| SDIO | 3 | 5 | P0.17 (Pro Micro D2) |
| SCLK | 4 | 6 | P0.08 (Pro Micro D0) |
| nCS | 5 | 3 | P0.06 (Pro Micro D1) |
| MOTION | 6 | 7 | P0.02 (Pro Micro A1 / D19) |
| nRESET | 7 | 8 | Leave unconnected; PCB pull-up holds it high |

J2 pin 4 is unused. JP2 on Rev. 2.1 only connects nRESET to the FFC and can stay open for this test.

**SDIO is a single bidirectional connection.** Both SPIM MOSI and MISO are assigned to P0.17 in firmware; wire only that one pin to SDIO. P0.20 from the old PMW3360 wiring is unused. MOTION is required by this interrupt-driven configuration. Reset is performed over SPI.

Fit the **LM18-LSI lens**. The specified distance from the lens's lowest reference plane to the tracking surface (ball or mouse pad) is **2.2–2.6 mm**, nominally **2.4 mm**.

## Build and flash

```bash
nix build .#firmware
# Output: result/zmk.uf2

nix run .#flash
```

The flash helper prompts for a single controller. Connect it with a USB data cable, briefly short **RST to GND twice** to enter its UF2 bootloader, and mount the bootloader drive when prompted. Alternatively, copy `result/zmk.uf2` onto that drive manually. The controller reboots into **PMW3610 Test**.

GitHub Actions builds the same single shield via `build.yaml`, with artifact name `pmw3610_test-nice_nano_v2`.

## Bench test

1. Power the controller over USB and allow about **1.3 seconds** for sensor initialization. Firmware enables VCC and delays initialization by an extra second for power to settle.
2. Open its USB serial device (usually `/dev/ttyACM0` on Linux) at 115200 baud. For example:

   ```bash
   nix shell nixpkgs#picocom -c picocom -b 115200 /dev/ttyACM0
   ```

   Exit picocom with `Ctrl-A`, then `Ctrl-X`. The device number may differ if other serial devices are connected. If you missed startup messages, keep the terminal ready and reconnect after a single reset.

3. Successful initialization logs **`PMW3610 initialized`** after the driver's self-test and product-ID check (expected ID **0x3e**). Move the ball or a textured surface at the lens's working distance: the pointer should move, and the serial log should show **`x/y: .../...`** deltas.
4. Check motion in both axes and again after leaving the sensor idle for a minute.

### Diagnosing soldering or wiring problems

| Observation | Check |
|-------------|-------|
| No USB device | USB data cable, bootloader/firmware, controller power |
| `Incorrect product id ...`, `Failed self-test ...`, or `PMW3610 initialization failed ...` | VIN/GND, JP1, regulator output (~1.8 V), SDIO/SCLK/nCS continuity and solder bridges |
| Initialization succeeds but no motion/deltas | MOTION wiring, fitted lens, lens-to-surface distance, tracking surface |
| Deltas appear but no pointer movement | Host USB HID device recognition; reconnect the controller |
| Motion works but axes are reversed/swapped | Adjust `invert-x;`, `invert-y;`, or `swap-xy;` in the overlay |

The initial `invert-y;` converts the sensor's native upward-positive Y to screen coordinates. Final trackball mounting may require different axis settings. Adjust `cpi = <600>;` in the overlay for sensitivity; this sensor supports **200–3200 CPI in steps of 200**.

## Configuration files

- `boards/shields/pmw3610_test/pmw3610_test.overlay`: pinout, sensor settings, USB mouse input listener.
- `boards/shields/pmw3610_test/pmw3610_test.conf`: USB-only operation, power-up delay, debug logging.
- `config/west.yml`: ZMK v0.3 and the [badjeff PMW3610 driver](https://github.com/badjeff/zmk-pmw3610-driver/tree/5c5af40de4d8cdf55dc63c4c5907af1e52da6a95), pinned to its compatible `zmk-0.3` revision.
- `flake.nix` / `build.yaml`: local and CI build targets.

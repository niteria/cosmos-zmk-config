# Cosmos PMW3610 and three mouse buttons

## Status and target

Integration branch: `feature/pmw3610-mouse-buttons`, based on `origin/main` at `eb2ecfd` (including the backspace quick-tap fix). This repository's default branch is named `main`.

Target: the right/central Cosmos controller, a SuperMini/ProMicro NRF52840 using the `nice_nano_v2` board definition. Replace the PMW3360/PMW3389 module with the already-tested [Sidera PMW3610 Rev. 2.x board](https://siderakb.ziteh.dev/mouse-sensors/pmw3610/rev2/), and add left, right, and middle mouse buttons.

**The PMW3610 and three-button configuration is implemented and builds successfully for both halves.** The generated files are `result/zmk_left.uf2` and `result/zmk_right.uf2`. The integrated hardware test is pending. The successful standalone PMW3610 hardware test is saved on `test/pmw3610-trackball` at `d1a9de2`.

## Pin budget: enough for direct wiring

The controller has **18 GPIOs on its two main side headers**. This allocation uses 17:

| Function | GPIO count |
|----------|------------|
| Existing matrix: 4 rows + 6 columns | 10 |
| PMW3610: SCLK, SDIO, nCS, MOTION | 4 |
| Three independent microswitches | 3 |
| Spare: P0.31 | 1 |

Thus the three buttons can be wired directly to GPIOs and GND, without adding matrix rows/columns or changing the existing keyboard wiring. This count does not rely on any extra underside pads. Power, GND, and the controller's RST pin are separate from these 18 GPIOs. The split link uses BLE and consumes no header pins.

The allocation was checked against `cosmos.dtsi`, `cosmos_right.overlay`, and the ZMK v0.3 `nice_nano` Pro Micro pin mapping. It assumes the physical keyboard follows the recorded wiring and has no additional undocumented peripherals on the spare pins.

### Existing right-half matrix

| Function | nRF GPIO | Pro Micro alias |
|----------|----------|-----------------|
| Row 0 | P1.13 | D15 |
| Row 1 | P1.11 | D14 |
| Row 2 | P0.10 | D16 |
| Row 3 | P0.09 | D10 |
| Local column 0 / global column 6 | P0.22 | D4 |
| Local column 1 / global column 7 | P0.24 | D5 |
| Local column 2 / global column 8 | P1.00 | D6 |
| Local column 3 / global column 9 | P0.11 | D7 |
| Local column 4 / global column 10 | P1.04 | D8 |
| Local column 5 / global column 11 | P1.06 | D9 |

## Sensor replacement wiring

Use the nRF GPIO numbers to identify the controller connections; Pro Micro aliases are provided for cross-checking. Match the Sidera connector's pin numbers/silkscreen rather than the old module's physical connector order.

| Existing controller wire | Old module connection | New PMW3610 connection | J1 header pin | J2 FFC pin |
|--------------------------|-----------------------|------------------------|---------------|------------|
| VCC / 3.3 V | VIN | VIN | 1 | 2 |
| GND | GND | GND | 2 | 1 |
| P0.17 / D2 | MISO | **SDIO** | 3 | 5 |
| P0.08 / D0 | SCK | SCLK | 4 | 6 |
| P0.06 / D1 | CS | nCS | 5 | 3 |
| P0.02 / A1 / D19 | MT | MOTION | 6 | 7 |

**P0.20, formerly MOSI, becomes available for a mouse button.** The PMW3610 has a single bidirectional SDIO wire, with both SPIM MOSI and MISO mapped to P0.17 in firmware. Do not join the old P0.20 and P0.17 wires together.

Leave the PMW3610 **nRESET** connection (J1 pin 7 / J2 pin 8) unconnected: the board has a pull-up and the driver resets the sensor over SPI. The old README listed **P1.15** for optional sensor reset, although the old overlay did not drive that pin. If that wire was fitted, detach it from the old module and repurpose it for the right mouse button. **P1.15 is the A0/D18 GPIO, not the controller's RST terminal.**

J2 pin 4 is unused; the Rev. 2.1 JP2 reset-to-FFC jumper can stay open.

### Sensor assembly and mounting

- Bridge **JP1 pads 1–2** for 3.3 V logic; leave pad 3 separate.
- Supply VIN from **regulated 3.3 V VCC**, not RAW or the battery terminal.
- MOTION is required for this interrupt-driven configuration.
- Fit the LM18-LSI lens, with **2.4 mm nominal spacing** from its lowest reference plane to the ball surface (specified range 2.2–2.6 mm). The driver has no 2 mm / 3 mm lift-off selection.
- **Tested C1 substitution:** this assembled board uses **4.7 µF instead of the BOM's 3.3 µF**, because 3.3 µF was hard to find. It still seems to work fine in the standalone trackball test.

## Three microswitch buttons

Configured logical assignments:

| Button | nRF GPIO | Pro Micro alias | Previous use | ZMK input event |
|--------|----------|-----------------|--------------|-----------------|
| Left click | **P0.20** | D3 | Old sensor MOSI | `INPUT_BTN_0` |
| Right click | **P1.15** | A0 / D18 | Optional old sensor reset | `INPUT_BTN_1` |
| Middle click | **P0.29** | A2 / D20 | Spare | `INPUT_BTN_2` |
| Remaining spare | **P0.31** | A3 / D21 | Spare | — |

For each three-terminal microswitch:

```text
controller GPIO ───── NO
                     microswitch
controller GND  ───── COM
                     NC: unconnected
```

Use the terminals marked **COM** and **NO** (normally open). All three COM terminals can share a GND wire. Each NO terminal gets its own GPIO wire. Configure the GPIOs as `GPIO_ACTIVE_LOW | GPIO_PULL_UP`; the controller supplies the pull-ups. No matrix diodes or external pull-up resistors are needed for these independent button inputs.

For a removable button assembly, a four-wire harness is enough: GND + left + right + middle. The sensor uses a separate six-wire harness: VIN, GND, SDIO, SCLK, nCS, MOTION. GND is common to both.

### Firmware representation

Use Zephyr `gpio-keys` and a dedicated `zmk,input-listener` on the right half. ZMK v0.3's listener handles `INPUT_BTN_0` through `INPUT_BTN_4` directly; use those codes for mouse buttons, not `INPUT_BTN_LEFT`/`INPUT_BTN_RIGHT`/`INPUT_BTN_MIDDLE`.

The button device and its listener in `cosmos_right.overlay` are:

```dts
#include <zephyr/dt-bindings/gpio/gpio.h>
#include <zephyr/dt-bindings/input/input-event-codes.h>

/ {
    mouse_buttons: mouse_buttons {
        compatible = "gpio-keys";
        debounce-interval-ms = <5>;

        left {
            gpios = <&gpio0 20 (GPIO_ACTIVE_LOW | GPIO_PULL_UP)>;
            zephyr,code = <INPUT_BTN_0>;
        };

        right {
            gpios = <&gpio1 15 (GPIO_ACTIVE_LOW | GPIO_PULL_UP)>;
            zephyr,code = <INPUT_BTN_1>;
        };

        middle {
            gpios = <&gpio0 29 (GPIO_ACTIVE_LOW | GPIO_PULL_UP)>;
            zephyr,code = <INPUT_BTN_2>;
        };
    };

    mouse_buttons_listener {
        compatible = "zmk,input-listener";
        device = <&mouse_buttons>;
    };
};
```

`CONFIG_INPUT_GPIO_KEYS=y` is explicitly set in `config/cosmos_right.conf`: ZMK v0.3 overrides Zephyr's default and disables this driver even when the node exists. Debounce starts at 5 ms; check for double clicks during the hardware test.

This approach sends mouse clicks independently of the keyboard layers and works alongside the 42-key matrix and its Studio layout. These direct-input buttons will not appear as three extra remappable key positions in ZMK Studio. The existing trackball listener can continue handling RAISE-layer scrolling separately.

## Integration and bring-up

1. **Done: integrate the tested PMW3610 driver into the split build.** `badjeff/zmk-pmw3610-driver` is pinned to `5c5af40de4d8cdf55dc63c4c5907af1e52da6a95`, the tested ZMK v0.3-compatible revision. The manifest, sensor configuration, Nix dependency hash, and CI references are updated; the old PMW3360 submodule is removed. Shared configuration is now in `config/cosmos.conf`, where ZMK actually loads it for both split shields. Right-only configuration is in `config/cosmos_right.conf`.
2. **Done: replace the right-half sensor node and pinctrl.** Both pinctrl states use P0.17 for SPIM MOSI/MISO, with 2400 CPI (raised from 600 for higher sensitivity) and 1000 ms extra startup delay. The sensor was remounted during spacing troubleshooting, reversing both movement directions. `invert-y` is now enabled and `invert-x` disabled to reverse both axes relative to the previous mounted configuration. Confirmation of this remounted orientation is pending. External power and settings/NVS storage are enabled for the full keyboard. USB sensor logging uses a dedicated console separate from Studio's serial interface.
3. **Done: add the independent button input device/listener.** The three GPIO assignments above are active with pull-ups and 5 ms debounce, alongside the existing matrix scan device.
4. **Done: build both halves and inspect the resolved configuration.** Verified right-side PMW3610 + GPIO button drivers, correct button codes/pins, USB/BLE pointing, Studio, and the 42-key layout. SPI data functions use P0.17, and P0.20 is the left button. The left image is the BLE peripheral. `nix build .#firmware` generates both UF2 files; each half's Nix package also retains `diagnostics/zephyr.config` and `diagnostics/zephyr.dts` for inspection. The flash helper and flake evaluation checks pass.
5. **Swap the hardware with USB and battery power disconnected.** Label the old wires before removing the module. Transfer the six sensor wires as above and wire the switch COM/NO terminals. Flash the integrated right-half firmware before exercising the buttons: the old firmware uses P0.20 as a SPI output.
6. **Validate the assembled keyboard.** Test the full matrix and left-half split connection; left/right/middle clicks and releases; click-and-drag while rolling; simultaneous button presses; USB and BLE output; RAISE scrolling; Studio access; and motion/buttons after idle and a power cycle.
7. **Tune the mounted trackball.** Verify axes in the final mounting position using `swap-xy`/inversion. The old `rotate-270`/`invert-x` settings need translating for the new sensor orientation. Fine-angle rotation requires a software input processor. Tune sensitivity and scroll scaling after the physical mounting and button behavior work.

## Integration checklist

- [x] Create a branch from the latest main keyboard configuration.
- [x] Audit the 18 side-header GPIOs and allocate sensor/buttons without overlap.
- [x] Check the native ZMK v0.3 button-listener path and document the harnesses.
- [x] Implement the PMW3610 and button configuration in the split firmware.
- [x] Build and inspect both firmware images.
- [ ] Rewire and validate the integrated hardware.
- [ ] Tune mounted orientation, sensitivity, and scrolling.

# Private Deck unlock shortcut

Hold the **physical Func key and J+K+L together for two seconds** on the right
half. Press Func first, then the three home-row keys within 200 ms. A personalized
right half types its dedicated LUKS passphrase and presses Enter over USB.

- Releasing any of the four keys during the two-second hold cancels activation.
- After typing starts, the chord may be released. It fires only once per hold.
- A tapped/one-shot Func layer does not count as physically holding Func.
- Another keyboard key, USB disconnect/suspend/reset, output change, or HID
  protocol change aborts the operation. Enter is omitted after an incomplete
  password transmission.
- USB must be configured, awake, and the selected output. There is no Bluetooth
  fallback. Host Caps Lock does not affect the 48-digit credential.
- The behavior uses fixed physical positions 35/19/20/21 and Func layer 3. Studio
  remaps must preserve that arrangement, or restore the stock keymap.

## Public build, private personalization

Ordinary firmware, public CI artifacts, Nix store paths, and diagnostics contain
an **empty** unlock slot. The shortcut does nothing until the public right-half
UF2 has been personalized. Secret data is never included in a keymap or macro.

```text
public source -> normal Nix build on zuffie -> public right-half UF2
                                                   |
agenix runtime credential -> local private helper --+
                                                   |
                          private RAM -> right-half flash -> cleanup
```

The helper and agenix configuration live in `~/zuffie-nixos`:

- `scripts/cosmos-unlock.py` / `scripts/cosmos-unlock.nix`
- `modules/cosmos-unlock.nix`, imported by Deck and zuffie
- `secrets/cosmos-deck-unlock.age`, created by interactive enrollment
- [`docs/cosmos-unlock.md`](https://github.com/niteria/zuffie-nixos/blob/master/docs/cosmos-unlock.md) in that repository

The credential has its own LUKS keyslot. The existing YubiKey static password is
an independent unlock/recovery path. The age recipients are the Deck and zuffie
host keys plus the existing personal recovery keys.

The keyboard and a personalized UF2 are copies of the unlock credential. Any
USB host can receive it when the chord is used; the keyboard cannot recognize a
LUKS prompt. Revoke the dedicated keyslot if the keyboard is lost.

## Build and flash

Build the public firmware normally:

```bash
nix build .#firmware
```

Use the `cosmos-unlock` helper from zuffie-nixos for private flashing, following
its enrollment/flashing guide. It takes the public `result/zmk_right.uf2` and an
**unmounted** nice!nano bootloader device. It mounts that device privately, reads
the root-only agenix credential, personalizes a temporary copy, and flashes it.

Flashing an ordinary public UF2 later clears the unlock capability. Personalize
again after firmware updates. The left half contains neither unlock code nor a
secret slot and uses the normal flashing workflow.

## Implementation and checks

`src/cosmos_unlock.c` observes physical positions before ZMK hold-taps/combos.
The linked-image check enforces this ordering. The combo is restricted to Func;
J+K still sends Escape on Base, and Raise retains IJKL arrows.

Secret reports go directly to the USB HID endpoint, with separate boot/report
protocol encoding and completion waits. They never enter ZMK's ordinary keycode
events, global HID report, or BLE report queues. Normal USB reports are excluded
during private transmission. No secret characters are logged.

The flash slot is a read-only, 256-byte-aligned record occupying one UF2 payload:

| Offset | Size | Value |
|---|---|---|
| 0 | 16 | ASCII `COSMOS-UNLOCK-V1` |
| 16 | 4 | Little-endian version `1` |
| 20 | 4 | Length: `0` public, `48` personalized |
| 24 | 64 | Decimal ASCII password followed by zero padding |
| 88 | 4 | IEEE CRC32 of the 48 password bytes, or zero when empty |
| 92 | 164 | Zero padding |

CRC is a corruption check, not encryption or authentication. Public-build checks
verify the empty slot and USB wrapper symbols in the actual linked ELF. Tests
exercise the hold/cancel/rearm state machine and the host UF2 parser/personalizer.

```bash
nix build .#checks.x86_64-linux.unlock-guard
```

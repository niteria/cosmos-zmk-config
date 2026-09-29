# Persistent private Deck unlock

Hold the **physical Func key and J+K+L together for two seconds** on the right
half. Press Func first, then the three home-row keys within 200 ms. A provisioned
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

## Provision once, then use public firmware updates

The credential lives in **`cosmos_unlock/record` in ZMK's settings/NVS partition**,
outside the application image. Normal firmware updates retain it. Bluetooth and
Studio settings use their own namespaces.

Public firmware, CI artifacts, Nix store paths, and diagnostics contain an empty
**provisioning mailbox**, not a password. The local helper can insert a one-time
SET or CLEAR command into a temporary copy of a public right-half UF2. On startup,
the firmware applies the command to NVS and verifies the saved record by reading
it back. USB password output uses only the persisted record; there is no runtime
fallback to an embedded password.

```text
agenix -> local provision helper -> temporary provisioning UF2 -> NVS credential
public source -> normal firmware builds/updates ----------------> NVS retained
```

The flasher, provisioning code, and tests live in this repository:

- `scripts/flash.py` / `nix/flash.nix`
- `tests/test_flash.py`
- the `flash` package and `checks.x86_64-linux.flash` flake output

Provisioning assumes that `/run/agenix/cosmos-deck-unlock` already exists as a
root-owned `0400` JSON file. It contains `version` (1), `luks_uuid` (UUID),
`keyslot` (integer 0–31), and `passphrase` (48 ASCII decimal digits). The disk
credential must already be enrolled. The flasher reads this runtime file; it
does not generate credentials, manage a secrets repository, or decrypt age files.

Host-side [LUKS enrollment and agenix deployment](https://github.com/niteria/zuffie-nixos/blob/master/docs/luks-agenix-enrollment.md)
are maintained in `zuffie-nixos`. The credential has its own LUKS keyslot, with
the existing YubiKey static password providing an independent recovery path.

The keyboard and a provisioning UF2 are copies of the unlock credential. Any
USB host can receive it when the chord is used; the keyboard cannot recognize a
LUKS prompt. Revoke the dedicated keyslot if the keyboard is lost.

## Flashing and provisioning

From this repository, use the same entry point for all firmware uploads:

```bash
nix build .#firmware
nix run .#flash -- right
nix run .#flash -- left
nix run .#flash
```

The last command flashes both halves in turn. Normal flashing uses public
firmware and retains the NVS credential. Follow the flasher's bootloader/mount
instructions.

To install or replace the right-half credential:

```bash
nix run .#flash -- right --provision
```

Nix builds the public firmware as your normal user. At runtime, the credential
operation uses sudo, then waits for the **right half** in its UF2 bootloader.
Use Func+Slash or double reset and leave the volume **unmounted**. If it is
mounted, use `udisksctl unmount -b /dev/sdX` first. When several UF2 devices are
connected, select the right one explicitly:

```bash
nix run .#flash -- right --provision --bootloader /dev/sdX
```

The helper checks the public UF2 and board ID before reading the runtime secret,
mounts the device privately, and creates the provisioning image in a non-swapping
RAM-backed directory. Its memory is locked and core dumps are disabled. The
temporary image is cleaned up after flashing. Both halves have the same board
ID, so physically select/reset the right half.

For a different runtime credential location, add `--secret-file /run/path/to/record`.
The same JSON schema and root-only permissions are required. This option applies
only to provisioning.

Read-only image validation and a credential-free runtime check are available:

```bash
nix run .#flash -- right --inspect
nix run .#flash -- --check-runtime
```

After provisioning, test the chord at a masked cryptsetup prompt. To verify
retention, flash ordinary public firmware and repeat that test. The left half
uses normal flashing and contains no unlock storage code.

## Clearing and recovery

```bash
nix run .#flash -- right --clear-credential
```

This creates and flashes a CLEAR command. It reads no runtime secret and logically
disables the keyboard credential, preserving Bluetooth/Studio settings. It does
**not** revoke the disk's LUKS keyslot or delete the encrypted recovery record.
Use `--provision` to restore the keyboard credential afterward. Both credential
flags require exactly `right` and are mutually exclusive.

Flashing a public UF2 no longer clears the credential. A full settings-reset
image, mass erase, or incompatible partition-layout change can remove it. Studio
"restore stock keymap" does not touch the separate credential namespace.
Clearing is not a promise of forensic erasure: older NVS records can remain until
flash garbage collection. Revoke the recorded Cosmos LUKS keyslot if this keyboard
is lost.

For credential operations, exit status **2** means the UF2 device reset or an I/O
error prevented a clean close, so upload completion is unconfirmed. Check that
Cosmos reconnects, then verify the requested operation. A masked credential test
can be run without rebooting or modifying the disk:

```bash
sudo cryptsetup open --test-passphrase --key-slot SLOT /dev/disk/by-partlabel/NIXROOT
```

Use the slot reported by enrollment and the Cosmos chord at the prompt. For a
clear operation, verify that the chord is inactive. No Deck reboot is automatic.

## Implementation and checks

`src/cosmos_unlock.c` observes physical positions before ZMK hold-taps/combos.
The linked-image check enforces this ordering. The combo is restricted to Func;
J+K still sends Escape on Base, and Raise retains IJKL arrows.

Secret reports go directly to the USB HID endpoint, with separate boot/report
protocol encoding and completion waits. They never enter ZMK's ordinary keycode
events, global HID report, or BLE report queues. Normal USB reports are excluded
during private transmission. No secret characters are logged.

The read-only provisioning mailbox is 256-byte aligned and occupies one UF2
payload. Version 2 has this format:

| Offset | Size | Value |
|---|---|---|
| 0 | 16 | ASCII `COSMOS-UNLOCK-V2` |
| 16 | 4 | Little-endian version `2` |
| 20 | 4 | Operation: `0` public/no-op, `1` provision, `2` clear |
| 24 | 16 | Fresh nonzero command ID; zero in a public image |
| 40 | 48 | Decimal ASCII password for provision; otherwise zero |
| 88 | 4 | IEEE CRC32 of bytes 16–87; zero for the empty public mailbox |
| 92 | 164 | Zero padding |

The persistent 76-byte record stores its schema version, SET/CLEAR state, command
ID, credential, and CRC as one atomic NVS value. Remembering the most recently
applied command ID avoids writes on every reboot of that image. CLEAR stores an empty record with a
receipt. Provisioning failures or failed readback disable output rather than
using an unpersisted credential. A one-time worker with a dedicated 4 KiB stack
performs the transaction after settings loading; the 1 KiB ZMK main stack only
signals it. The handler has no settings read/export API.

CRC detects corruption, not malicious changes or disclosure. The settings area
is ordinary on-device flash. Public-build checks verify the empty mailbox,
settings handler, and USB wrappers in the linked ELF. The partition bounds are
checked at compile time: application ends at `0xec000`, settings occupies
`0xec000–0xf4000` (32 KiB).

```bash
nix build .#checks.x86_64-linux.unlock-guard
nix build .#checks.x86_64-linux.unlock-storage
nix build .#checks.x86_64-linux.flash
```

#!/usr/bin/env python3
"""Flash Cosmos firmware and manage its persistent USB unlock credential.

Provisioning consumes an existing root-only runtime record. Secret material is
never a Nix input, command-line argument, log message, or ordinary temporary file.
"""
import argparse
import contextlib
import ctypes
import errno
import json
import os
from pathlib import Path
import re
import resource
import secrets
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import zlib

MAGIC = b"COSMOS-UNLOCK-V2"
PUBLIC_MAILBOX = MAGIC + struct.pack("<II", 2, 0) + bytes(232)
UF2_MAGIC = (0x0A324655, 0x9E5D5157, 0x0AB16F30)
FAMILY = 0xADA52840
PASSWORD_LENGTH = 48
DEFAULT_SECRET = Path("/run/agenix/cosmos-deck-unlock")


class SafeError(Exception):
    """Messages in this exception must never interpolate secret data."""


class FlashNeedsVerification(SafeError):
    """UF2 devices can reboot before the host finishes flushing/closing."""


def checked(command):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        # No subprocess output or arguments: an error could contain input data.
        raise SafeError(f"{Path(command[0]).name} failed (exit {result.returncode})")
    return result.stdout


def password_bytes(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{48}", value) is None:
        raise SafeError("Expected exactly 48 decimal digits in the unlock credential")
    return value.encode("ascii")


def decode_record(data):
    if len(data) > 4096:
        raise SafeError("Unlock credential record is too large")
    try:
        record = json.loads(data)
        if not isinstance(record, dict) or type(record.get("version")) is not int or record["version"] != 1:
            raise ValueError
        if not isinstance(record["luks_uuid"], str):
            raise ValueError
        uuid.UUID(record["luks_uuid"])
        slot = record["keyslot"]
        if type(slot) is not int or not 0 <= slot < 32:
            raise ValueError
        password_bytes(record["passphrase"])
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise SafeError("Invalid unlock credential record") from None
    return record


def parse_uf2(data):
    if not data or len(data) % 512 or len(data) > 2 * 1024 * 1024:
        raise SafeError("Invalid UF2 size")
    count = len(data) // 512
    numbers, addresses, mailboxes = set(), set(), []
    for offset in range(0, len(data), 512):
        m0, m1, flags, address, size, number, total, family = struct.unpack_from("<8I", data, offset)
        end = struct.unpack_from("<I", data, offset + 508)[0]
        if (m0, m1, end) != UF2_MAGIC:
            raise SafeError("Invalid UF2 magic")
        if flags != 0x2000 or family != FAMILY or size != 256:
            raise SafeError("Expected an unextended nRF52840 UF2 with 256-byte payloads")
        if total != count or number >= count or number in numbers:
            raise SafeError("Invalid or duplicate UF2 block number")
        if address % 256 or not 0x26000 <= address < 0xEC000 or address in addresses:
            raise SafeError("UF2 address outside the nice!nano application or duplicated")
        numbers.add(number)
        addresses.add(address)
        payload = data[offset + 32 : offset + 288]
        if payload.startswith(MAGIC):
            if payload != PUBLIC_MAILBOX:
                raise SafeError("Provisioning mailbox is not empty or is incompatible; use a public build")
            mailboxes.append((offset + 32, address))
    if len(mailboxes) != 1:
        raise SafeError("Expected exactly one empty Cosmos v2 provisioning mailbox (right-half firmware only)")
    return mailboxes[0]


def prepare_command(public_firmware, operation, record=None):
    offset, _ = parse_uf2(public_firmware)
    if operation == "provision":
        if record is None:
            raise SafeError("Provisioning requires an unlock credential")
        opcode, password = 1, password_bytes(record["passphrase"])
    elif operation == "clear" and record is None:
        opcode, password = 2, bytes(PASSWORD_LENGTH)
    else:
        raise SafeError("Invalid provisioning operation")
    nonce = bytes(16)
    while not any(nonce):
        nonce = secrets.token_bytes(16)
    body = struct.pack("<II16s48s", 2, opcode, nonce, password)
    payload = MAGIC + body + struct.pack("<I", zlib.crc32(body)) + bytes(164)
    result = bytearray(public_firmware)
    result[offset : offset + 256] = payload
    return result


def harden_process():
    if os.geteuid() != 0:
        raise SafeError("Credential operations require sudo")
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
        raise SafeError("Cannot disable process dumps")
    # Keep Python's secret-bearing buffers out of swap as well as the tmpfs files.
    resource.setrlimit(resource.RLIMIT_MEMLOCK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    if libc.mlockall(1 | 2) != 0:  # MCL_CURRENT | MCL_FUTURE
        raise SafeError("Cannot lock helper memory")
    if libc.unshare(0x00020000) != 0:  # CLONE_NEWNS
        raise SafeError("Cannot create a private mount namespace")
    checked(["mount", "--make-rprivate", "/"])

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)


@contextlib.contextmanager
def private_workspace():
    directory = Path(tempfile.mkdtemp(prefix="cosmos-flash-", dir="/run"))
    mounted = False
    try:
        checked(["mount", "-t", "tmpfs", "-o", "mode=0700,size=16m,noswap",
                 "cosmos-unlock", str(directory)])
        mounted = True
        yield directory
    finally:
        if mounted:
            subprocess.run(["umount", "--lazy", str(directory)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Never recursively remove a mountpoint, especially a UF2 volume.
        try:
            directory.rmdir()
        except OSError:
            pass  # Private namespace teardown also releases mounts after SIGKILL.


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def runtime_record(path):
    # Agenix uses a symlink into /run/agenix.d; validate the resolved inode.
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        raise SafeError("Runtime credential is missing; deploy it before using --provision") from None
    fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise SafeError("Runtime secret must be a root-owned regular file with no group/other access")
        return decode_record(stream.read(4097))


def bootloader_device(path):
    device = path.resolve(strict=True)
    if not stat.S_ISBLK(device.stat().st_mode):
        raise SafeError("Bootloader must be a block device, not a directory")
    # lsblk -s includes parent disks for a partition. Refuse ordinary disks and
    # already mounted volumes so no public mount exposes a provisioning image.
    nodes = json.loads(checked(["lsblk", "--json", "--paths", "--inverse", "--output",
                               "NAME,TRAN,MOUNTPOINTS", str(device)]))["blockdevices"]

    def flatten(items):
        for node in items:
            yield node
            yield from flatten(node.get("children", []))

    related = list(flatten(nodes))
    if not any(node.get("tran") == "usb" for node in related):
        raise SafeError("Bootloader device must be USB storage")
    if any(point for node in related for point in (node.get("mountpoints") or [])):
        raise SafeError("Unmount the bootloader volume first; it will be mounted privately")
    return device


def find_bootloader():
    nodes = json.loads(checked(["lsblk", "--json", "--paths", "--nodeps", "--output",
                               "NAME,TRAN,MODEL"]))["blockdevices"]
    candidates = [Path(node["name"]) for node in nodes
                  if node.get("tran") == "usb" and "nRF UF2" in (node.get("model") or "")]
    if len(candidates) > 1:
        raise SafeError("Multiple UF2 devices found; connect only the right half or specify --bootloader")
    return candidates[0] if candidates else None


def select_bootloader(explicit):
    if explicit is not None:
        return bootloader_device(explicit)
    print("Put the RIGHT half in its UF2 bootloader and leave the drive unmounted.", flush=True)
    while (device := find_bootloader()) is None:
        time.sleep(1)
    return bootloader_device(device)


def copy_to_bootloader(private_file, destination):
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb", buffering=0) as output, private_file.open("rb") as source:
            while chunk := source.read(16384):
                view = memoryview(chunk)
                while view:
                    written = output.write(view)
                    if not written:
                        raise SafeError("Short write to bootloader")
                    view = view[written:]
            os.fsync(output.fileno())
    except OSError as error:
        if error.errno in (errno.EIO, errno.ENODEV, errno.ENXIO, errno.ENOENT):
            raise FlashNeedsVerification(
                "UF2 transfer ended without a clean close; the bootloader may have reset. "
                "Completion is unconfirmed. Check that Cosmos reconnects and verify the "
                "requested provisioning/clearing operation. Temporary storage was released."
            ) from None
        raise


def flash_command(args):
    # Check the public artifact before touching any secret or USB filesystem.
    public = (args.firmware_dir / "zmk_right.uf2").read_bytes()
    _, address = parse_uf2(public)
    if args.mode == "provision" and not args.secret_file.exists():
        raise SafeError("Runtime credential is missing; deploy it before using --provision")
    device = select_bootloader(args.bootloader)
    with private_workspace() as workspace:
        volume = workspace / "bootloader"
        volume.mkdir(mode=0o700)
        checked(["mount", "-t", "vfat", "-o", "nosuid,nodev,noexec,umask=0077",
                 str(device), str(volume)])
        try:
            info = (volume / "INFO_UF2.TXT").read_text()
            if re.search(r"^Board-ID:\s*nRF52840-nicenano\s*$", info, re.MULTILINE) is None:
                raise SafeError("USB volume is not the expected nice!nano nRF52840 UF2 bootloader")
            record = None
            if args.mode == "provision":
                record = runtime_record(args.secret_file)
            command_image = prepare_command(public, args.mode, record)
            private_file = workspace / "cosmos-right-command.uf2"
            write_private(private_file, command_image)
            print(f"Flashing RIGHT-half {args.mode} command to {device} (mailbox address {address:#x}).",
                  flush=True)
            # Only the private mount can see this file. No output filename or
            # arbitrary destination is accepted for provisioning firmware.
            copy_to_bootloader(private_file, volume / "COSMOS.UF2")
        finally:
            subprocess.run(["umount", "--lazy", str(volume)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("Firmware copy completed; temporary storage released. The command runs on keyboard startup.")
    if args.mode == "provision":
        print("Verify the chord. Future ordinary public firmware flashes will retain this credential.")
    else:
        print("Verify that the chord is inactive. The LUKS disk keyslot and encrypted recovery record were not changed.")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="cosmos-flash", description=__doc__)
    parser.add_argument("--firmware-dir", type=Path, required=True, help=argparse.SUPPRESS)
    parser.add_argument("--public-flasher", type=Path, required=True, help=argparse.SUPPRESS)
    parser.add_argument("--tool-path", help=argparse.SUPPRESS)
    parser.add_argument("parts", nargs="*", metavar="HALF", help="left and/or right; omit for both halves during normal flashing")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--provision", dest="mode", action="store_const", const="provision",
                       help="Install or replace the right-half credential from the runtime secret")
    modes.add_argument("--clear-credential", dest="mode", action="store_const", const="clear",
                       help="Disable the right-half credential, preserving other settings and disk keyslots")
    modes.add_argument("--inspect", dest="mode", action="store_const", const="inspect",
                       help="Validate the public right-half image without reading a secret or flashing")
    modes.add_argument("--check-runtime", dest="mode", action="store_const", const="check-runtime",
                       help="Test private RAM storage without reading a secret or accessing a disk")
    parser.add_argument("--bootloader", type=Path, help="Explicit unmounted UF2 device for a credential operation, e.g. /dev/sdb")
    parser.add_argument("--secret-file", type=Path, help=f"Runtime credential for --provision; default: {DEFAULT_SECRET}")
    args = parser.parse_args(argv)
    if any(part not in ("left", "right") for part in args.parts) or len(set(args.parts)) != len(args.parts):
        parser.error("HALF must be left and/or right, without duplicates")
    if args.mode in ("provision", "clear", "inspect") and args.parts != ["right"]:
        parser.error("this option requires exactly the right half")
    if args.mode == "check-runtime" and args.parts:
        parser.error("--check-runtime is used without a half")
    if args.bootloader is not None and args.mode not in ("provision", "clear"):
        parser.error("--bootloader requires --provision or --clear-credential")
    if args.secret_file is not None and args.mode != "provision":
        parser.error("--secret-file requires --provision")
    args.secret_file = args.secret_file or DEFAULT_SECRET
    return args


def elevate(argv):
    if os.geteuid() == 0:
        return
    sudo = shutil.which("sudo")
    if sudo is None:
        raise SafeError("sudo is required for credential operations")
    os.execv(sudo, [sudo, "--", sys.executable, "-I", str(Path(__file__).resolve()), *argv])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)
    try:
        if args.mode is None:
            os.execv(args.public_flasher, [str(args.public_flasher), *args.parts])
            return
        if args.mode == "inspect":
            _, address = parse_uf2((args.firmware_dir / "zmk_right.uf2").read_bytes())
            print(f"Valid public Cosmos right-half UF2; empty provisioning mailbox at {address:#x}; settings are retained")
            return
        elevate(argv)
        # sudo resets PATH. Restore only the tool paths supplied by the Nix wrapper.
        if args.tool_path:
            os.environ["PATH"] = args.tool_path
        harden_process()
        if args.mode == "check-runtime":
            with private_workspace() as workspace:
                probe = workspace / "probe"
                write_private(probe, b"public runtime test")
                if probe.stat().st_mode & 0o777 != 0o600:
                    raise SafeError("Private temporary-file permissions are incorrect")
            print("Runtime checks passed: locked memory, disabled core dumps, private mount namespace, private noswap tmpfs")
        else:
            flash_command(args)
    except FlashNeedsVerification as error:
        print(f"cosmos-flash: {error}", file=sys.stderr)
        sys.exit(2)
    except SafeError as error:
        print(f"cosmos-flash: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("cosmos-flash: interrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        # Never print an exception value or traceback from a secret-bearing operation.
        print(f"cosmos-flash: operation failed ({type(error).__name__})", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

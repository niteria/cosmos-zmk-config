"""No real credentials or disks are used by these tests."""
import importlib.util
import contextlib
import errno
import io
import json
from pathlib import Path
import struct
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

spec = importlib.util.spec_from_file_location("cosmos_flash", sys.argv.pop(1))
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def firmware(payload=None):
    payload = helper.PUBLIC_MAILBOX if payload is None else payload
    block = bytearray(512)
    struct.pack_into("<8I", block, 0, *helper.UF2_MAGIC[:2], 0x2000, 0x30000, 256, 0, 1, helper.FAMILY)
    block[32:288] = payload
    struct.pack_into("<I", block, 508, helper.UF2_MAGIC[2])
    return bytes(block)


def record():
    return {"version": 1, "luks_uuid": "f7165788-3475-4c22-8d10-ad930b9a1a78",
            "keyslot": 1, "passphrase": "0123456789" * 4 + "01234567"}


class UF2Tests(unittest.TestCase):
    def test_public_mailbox_and_provision_command(self):
        public = firmware()
        self.assertEqual(helper.parse_uf2(public), (32, 0x30000))
        private = helper.prepare_command(public, "provision", record())
        self.assertEqual(public, firmware())  # Public input is immutable.
        self.assertEqual(private[:32], public[:32])
        self.assertEqual(private[288:], public[288:])
        self.assertEqual(struct.unpack_from("<II", private, 48), (2, 1))
        self.assertNotEqual(private[56:72], bytes(16))
        secret = record()["passphrase"].encode()
        self.assertEqual(private[72:120], secret)
        self.assertEqual(private[124:288], bytes(164))
        self.assertEqual(struct.unpack_from("<I", private, 120)[0], zlib.crc32(private[48:120]))
        with self.assertRaises(helper.SafeError):
            helper.parse_uf2(private)  # Only empty public mailboxes are inputs.

    def test_clear_command_contains_no_credential(self):
        image = helper.prepare_command(firmware(), "clear")
        self.assertEqual(struct.unpack_from("<II", image, 48), (2, 2))
        self.assertNotEqual(image[56:72], bytes(16))
        self.assertEqual(image[72:120], bytes(48))
        self.assertEqual(struct.unpack_from("<I", image, 120)[0], zlib.crc32(image[48:120]))
        with self.assertRaises(helper.SafeError):
            helper.prepare_command(firmware(), "clear", record())

    def test_commands_use_fresh_nonzero_ids(self):
        with patch.object(helper.secrets, "token_bytes", side_effect=[bytes(16), b"1" * 16, b"2" * 16]):
            first = helper.prepare_command(firmware(), "provision", record())
            second = helper.prepare_command(firmware(), "provision", record())
        self.assertEqual(first[56:72], b"1" * 16)
        self.assertEqual(second[56:72], b"2" * 16)

    def test_unsupported_mailbox_format_is_rejected(self):
        unsupported = b"COSMOS-UNLOCK-V9" + struct.pack("<II", 9, 0) + bytes(232)
        with self.assertRaises(helper.SafeError):
            helper.parse_uf2(firmware(unsupported))

    def test_refuse_left_or_other_firmware(self):
        with self.assertRaises(helper.SafeError):
            helper.parse_uf2(firmware(bytes(256)))

    def test_reject_corrupt_headers(self):
        for offset, value in [(0, 0), (4, 0), (8, 0), (12, 0x1000), (12, 0xEC000),
                              (12, 0x30001), (16, 128), (20, 2), (24, 2), (28, 0), (508, 0)]:
            data = bytearray(firmware())
            struct.pack_into("<I", data, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(helper.SafeError):
                helper.parse_uf2(data)

    def test_reject_duplicate_number_address_and_slot(self):
        for case in ("number", "address", "slot"):
            data = bytearray(firmware() * 2)
            struct.pack_into("<I", data, 24, 2)
            struct.pack_into("<I", data, 512 + 24, 2)
            if case != "number":
                struct.pack_into("<I", data, 512 + 20, 1)
            if case != "address":
                struct.pack_into("<I", data, 512 + 12, 0x30100)
            with self.subTest(case=case), self.assertRaises(helper.SafeError):
                helper.parse_uf2(data)

    def test_reject_wrong_slot_version_and_padding(self):
        for index in (16, 20, 24, 255):
            data = bytearray(helper.PUBLIC_MAILBOX)
            data[index] ^= 1
            with self.subTest(index=index), self.assertRaises(helper.SafeError):
                helper.parse_uf2(firmware(data))

    def test_reject_bad_file_size(self):
        for data in (b"", firmware()[:-1], firmware() + b"\0"):
            with self.assertRaises(helper.SafeError):
                helper.parse_uf2(data)


class CredentialTests(unittest.TestCase):
    def test_record(self):
        self.assertEqual(helper.decode_record(json.dumps(record()).encode()), record())

    def test_bad_passwords(self):
        for password in ("1" * 47, "1" * 49, "a" * 48, "١" * 48, "1" * 47 + "\n", None):
            with self.subTest(password_type=type(password)), self.assertRaises(helper.SafeError):
                helper.password_bytes(password)

    def test_bad_metadata(self):
        for field, value in [("keyslot", -1), ("keyslot", 32), ("keyslot", True),
                             ("version", 2), ("version", True), ("luks_uuid", "invalid"),
                             ("luks_uuid", None)]:
            bad = record() | {field: value}
            with self.subTest(field=field), self.assertRaises(helper.SafeError):
                helper.decode_record(json.dumps(bad).encode())
        for data in (b"[]", b"not json", b"x" * 4097):
            with self.assertRaises(helper.SafeError):
                helper.decode_record(data)

    def test_private_creation_is_exclusive_and_0600(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "private"
            helper.write_private(target, b"test-only")
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                helper.write_private(target, b"replacement")


class FlashTests(unittest.TestCase):
    def test_clear_does_not_read_any_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public = root / "zmk_right.uf2"
            public.write_bytes(firmware())
            workspace = root / "ram"
            workspace.mkdir()
            args = SimpleNamespace(mode="clear", firmware_dir=root, bootloader=Path("/dev/test-only"))

            def mounted(command, **kwargs):
                (workspace / "bootloader" / "INFO_UF2.TXT").write_text("Board-ID: nRF52840-nicenano\n")

            def copied(source, destination):
                data = source.read_bytes()
                self.assertEqual(struct.unpack_from("<II", data, 48), (2, 2))
                self.assertEqual(data[72:120], bytes(48))

            with patch.object(helper, "bootloader_device", return_value=args.bootloader), \
                 patch.object(helper, "private_workspace", return_value=contextlib.nullcontext(workspace)), \
                 patch.object(helper, "checked", side_effect=mounted), \
                 patch.object(helper, "copy_to_bootloader", side_effect=copied), \
                 patch.object(helper.subprocess, "run"), \
                 patch.object(helper, "runtime_record") as runtime, \
                 contextlib.redirect_stdout(io.StringIO()):
                helper.flash_command(args)
                runtime.assert_not_called()

    def test_copy_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / "source", Path(directory) / "COSMOS.UF2"
            source.write_bytes(b"public test bytes" * 2048)
            helper.copy_to_bootloader(source, destination)
            self.assertEqual(source.read_bytes(), destination.read_bytes())
            with self.assertRaises(FileExistsError):
                helper.copy_to_bootloader(source, destination)

    def test_reset_during_flush_is_unconfirmed_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / "source", Path(directory) / "COSMOS.UF2"
            source.write_bytes(b"public test bytes")
            with patch.object(helper.os, "fsync", side_effect=OSError(errno.EIO, "test reset")):
                with self.assertRaises(helper.FlashNeedsVerification):
                    helper.copy_to_bootloader(source, destination)


class RuntimeCredentialTests(unittest.TestCase):
    def test_runtime_record_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credential"
            path.write_bytes(json.dumps(record()).encode())
            for owner, mode, allowed in ((0, 0o400, True), (0, 0o600, True),
                                          (0, 0o644, False), (1000, 0o400, False)):
                info = SimpleNamespace(st_mode=stat.S_IFREG | mode, st_uid=owner)
                with self.subTest(owner=owner, mode=mode), patch.object(helper.os, "fstat", return_value=info):
                    if allowed:
                        self.assertEqual(helper.runtime_record(path), record())
                    else:
                        with self.assertRaises(helper.SafeError):
                            helper.runtime_record(path)

    def test_missing_secret_fails_before_device_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "zmk_right.uf2").write_bytes(firmware())
            args = SimpleNamespace(mode="provision", firmware_dir=root,
                                   secret_file=root / "missing", bootloader=None)
            with patch.object(helper, "select_bootloader") as select:
                with self.assertRaisesRegex(helper.SafeError, "Runtime credential is missing"):
                    helper.flash_command(args)
                select.assert_not_called()


class EntryPointTests(unittest.TestCase):
    base = ["--firmware-dir", "/public", "--public-flasher", "/public-flasher"]

    def test_public_flashes_delegate_without_privileges_or_secrets(self):
        for parts in ([], ["right"], ["left"], ["left", "right"]):
            with self.subTest(parts=parts), patch.object(helper.os, "execv") as execute, \
                 patch.object(helper, "elevate") as elevate, \
                 patch.object(helper, "harden_process") as harden, \
                 patch.object(helper, "runtime_record") as runtime:
                helper.main(self.base + parts)
                execute.assert_called_once_with(Path("/public-flasher"), ["/public-flasher", *parts])
                elevate.assert_not_called()
                harden.assert_not_called()
                runtime.assert_not_called()

    def test_reject_invalid_combinations_before_elevation(self):
        invalid = (["--provision"], ["left", "--provision"], ["left", "right", "--provision"],
                   ["right", "--provision", "--clear-credential"], ["left", "--inspect"],
                   ["right", "right"], ["wrong-half"], ["--check-runtime", "right"],
                   ["right", "--secret-file", "/secret"], ["right", "--bootloader", "/dev/test"])
        for args in invalid:
            with self.subTest(args=args), patch.object(helper, "elevate") as elevate, \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    helper.main(self.base + args)
                self.assertEqual(error.exception.code, 2)
                elevate.assert_not_called()

    def test_private_modes_route_to_right_image(self):
        for flag, mode in (("--provision", "provision"), ("--clear-credential", "clear")):
            argv = self.base + ["right", flag, "--bootloader", "/dev/test"]
            with self.subTest(mode=mode), patch.object(helper, "elevate") as elevate, \
                 patch.object(helper, "harden_process"), patch.object(helper, "flash_command") as flash:
                helper.main(argv)
                elevate.assert_called_once_with(argv)
                self.assertEqual(flash.call_args.args[0].mode, mode)
                self.assertEqual(flash.call_args.args[0].firmware_dir, Path("/public"))
                self.assertEqual(flash.call_args.args[0].secret_file, helper.DEFAULT_SECRET)

    def test_inspect_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "zmk_right.uf2").write_bytes(firmware())
            with patch.object(helper, "elevate") as elevate, \
                 patch.object(helper, "runtime_record") as runtime, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                helper.main(["--firmware-dir", str(root), "--public-flasher", "/unused", "right", "--inspect"])
                self.assertIn("empty provisioning mailbox", output.getvalue())
                elevate.assert_not_called()
                runtime.assert_not_called()

    def test_elevation_retains_only_cli_arguments(self):
        argv = self.base + ["right", "--provision"]
        with patch.object(helper.os, "geteuid", return_value=1000), \
             patch.object(helper.shutil, "which", return_value="/trusted/sudo"), \
             patch.object(helper.os, "execv") as execute:
            helper.elevate(argv)
            command = execute.call_args.args[1]
            self.assertEqual(command[:4], ["/trusted/sudo", "--", sys.executable, "-I"])
            self.assertEqual(command[5:], argv)


class DiscoveryTests(unittest.TestCase):
    def test_only_usb_uf2_devices_match(self):
        nodes = [{"name": "/dev/nvme0n1", "tran": "nvme", "model": "nRF UF2"},
                 {"name": "/dev/sda", "tran": "usb", "model": "Other disk"}]
        with patch.object(helper, "checked", return_value=json.dumps({"blockdevices": nodes}).encode()):
            self.assertIsNone(helper.find_bootloader())
        nodes.append({"name": "/dev/sdb", "tran": "usb", "model": "nRF UF2"})
        with patch.object(helper, "checked", return_value=json.dumps({"blockdevices": nodes}).encode()):
            self.assertEqual(helper.find_bootloader(), Path("/dev/sdb"))

    def test_multiple_bootloaders_require_selection(self):
        nodes = [{"name": f"/dev/{name}", "tran": "usb", "model": "nRF UF2"} for name in ("sda", "sdb")]
        with patch.object(helper, "checked", return_value=json.dumps({"blockdevices": nodes}).encode()):
            with self.assertRaises(helper.SafeError):
                helper.find_bootloader()

    def test_explicit_bootloader_skips_discovery(self):
        with patch.object(helper, "find_bootloader") as discover, \
             patch.object(helper, "bootloader_device", return_value=Path("/dev/test")):
            self.assertEqual(helper.select_bootloader(Path("/dev/test")), Path("/dev/test"))
            discover.assert_not_called()


unittest.main()

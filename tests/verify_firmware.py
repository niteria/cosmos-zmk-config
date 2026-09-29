"""Inspect the actual linked public image, not merely its configuration."""
import struct
import sys

from elftools.elf.elffile import ELFFile

with open(sys.argv[1], "rb") as stream:
    elf = ELFFile(stream)
    symbols = {s.name: s.entry["st_value"] for s in elf.get_section_by_name(".symtab").iter_symbols()}
    slot = elf.get_section_by_name(".cosmos_unlock_slot")
    if slot is None:
        assert "zmk_listener_cosmos_unlock" not in symbols, "Unlock code without its slot"
        print("Peripheral: no unlock code or secret slot")
        sys.exit(0)

    expected = b"COSMOS-UNLOCK-V1" + struct.pack("<II", 1, 0) + bytes(232)
    assert slot.data() == expected, "Public secret slot is not empty or has wrong size"
    assert slot["sh_addr"] % 256 == 0, "Secret slot must occupy one aligned UF2 payload"
    assert not slot["sh_flags"] & 1, "Secret slot must remain in read-only flash"
    start = symbols["__event_subscriptions_start"]
    end = symbols["__event_subscriptions_end"]
    entries = None
    for section in elf.iter_sections():
        if section["sh_addr"] <= start < end <= section["sh_addr"] + section["sh_size"]:
            offset = start - section["sh_addr"]
            entries = section.data()[offset : offset + end - start]
            break
    assert entries is not None, "Cannot inspect event subscriptions"
    position_type = symbols["zmk_event_zmk_position_state_changed"]
    first = next(listener for event, listener in struct.iter_unpack("<II", entries)
                 if event == position_type)
    assert first == symbols["zmk_listener_cosmos_unlock"], "Physical observer is not first"
    assert "__wrap_hid_int_ep_write" in symbols
    assert "__wrap_usb_hid_register_device" in symbols
    print(f"Central: empty unlock slot at {slot['sh_addr']:#x}; physical observer precedes combos")

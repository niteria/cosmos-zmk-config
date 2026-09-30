"""Inspect the actual linked public image, not merely its configuration."""
import struct
import sys

from elftools.elf.elffile import ELFFile

with open(sys.argv[1], "rb") as stream:
    elf = ELFFile(stream)
    symbols = {s.name: s.entry["st_value"] for s in elf.get_section_by_name(".symtab").iter_symbols()}
    slot = elf.get_section_by_name(".cosmos_unlock_provision")
    if slot is None:
        assert "zmk_listener_cosmos_unlock" not in symbols, "Unlock code without its slot"
        assert "zmk_listener_cosmos_scroll" not in symbols, "Scroll code belongs on the central half"
        print("Peripheral: no unlock code or secret slot")
        sys.exit(0)

    expected = b"COSMOS-UNLOCK-V2" + struct.pack("<II", 2, 0) + bytes(232)
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
    subscriptions = set(struct.iter_unpack("<II", entries))
    pmw3610_listener = symbols["zmk_listener_zmk_pmw3610_idle_sleeper"]
    for event_name in ("zmk_activity_state_changed", "zmk_usb_conn_state_changed"):
        assert (symbols[f"zmk_event_{event_name}"], pmw3610_listener) in subscriptions, (
            f"PMW3610 is not subscribed to {event_name}"
        )
    assert "pmw3610_performance_work" in symbols, "PMW3610 power changes must use the work queue"
    print("Central: PMW3610 USB/activity power listener and deferred work present")
    position_type = symbols["zmk_event_zmk_position_state_changed"]
    first = next(listener for event, listener in struct.iter_unpack("<II", entries)
                 if event == position_type)
    assert first == symbols["zmk_listener_cosmos_unlock"], "Physical observer is not first"
    position_listeners = [listener for event, listener in struct.iter_unpack("<II", entries)
                          if event == position_type]
    scroll_listener = symbols["zmk_listener_cosmos_scroll"]
    for name in ("behavior_hold_tap", "combo", "keymap"):
        assert position_listeners.index(scroll_listener) < position_listeners.index(
            symbols[f"zmk_listener_{name}"]
        ), f"Scroll cancellation must precede {name}"
    for name in ("zmk_layer_state_changed", "zmk_usb_conn_state_changed", "zmk_endpoint_changed"):
        assert (symbols[f"zmk_event_{name}"], scroll_listener) in subscriptions
    assert "scroll_processor_api" in symbols
    assert "scroll_behavior_api" in symbols
    print("Central: scroll latch behavior, input processor and early physical cancellation present")
    assert "__wrap_hid_int_ep_write" in symbols
    assert "__wrap_usb_hid_register_device" in symbols
    assert "settings_handler_cosmos_unlock" in symbols
    assert "cosmos_unlock_credential_ready" in symbols
    print(f"Central: empty provisioning mailbox at {slot['sh_addr']:#x}; persistent settings and physical guard present")

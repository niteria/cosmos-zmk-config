#!/usr/bin/env python3
"""Print the generated keymap and current Hyprland YAML as vector A4 PDFs.

Run update-assets first. Labels come from its YAML; geometry comes from its SVG.
Requires PyYAML, ReportLab and DejaVu fonts (provided by the flake app).
"""

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import yaml
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
NS = {"s": "http://www.w3.org/2000/svg"}
INK = HexColor("#17212b")
MUTED = HexColor("#46515c")
WIDTH, HEIGHT = 800, 272
MARGIN = 8 * mm


@dataclass
class Panel:
    title: str
    gesture: str
    notes: tuple[str, str]


PANELS = [
    Panel("Base · typing and thumb keys", "Center = tap; bottom = hold / sticky modifier", (
        "Hold Enter for Super, Tab for Lower, Backspace for Raise (200 ms). Escape: J+K together.",
        "Sticky Alt/Ctrl/Shift/Func: tap for the next key, or hold. Use left Alt and outer left Shift.",
    )),
    Panel("Lower · numbers and symbols", "Hold the left inner Tab / Lower thumb", (
        "Numbers are on A–Quote. The right Shift thumb becomes colon on Lower.",
        "▽ means the layer underneath. For one-shot Func, press modifiers before tapping Func.",
    )),
    Panel("Raise · navigation and media", "Hold the right inner Backspace / Raise thumb", (
        "I/J/K/L = ↑/←/↓/→. Raise+H latches scrolling after release; any next key/button press cancels.",
        "Esc/Ctrl thumb: tap Escape, hold Ctrl. Pause after a Backspace tap before holding for Raise.",
    )),
    Panel("Func · function keys and utilities", "Tap Func for the next key; hold for several actions", (
        "Fn+N unlocks Studio. Fn+B / Fn+Slash enters the left / right bootloader.",
        "Private unlock: hold physical Fn+J+K+L for 2 s; requires USB and a provisioned right half.",
    )),
    Panel("Super · workspaces and launcher", "Hold Enter / Super; top legends add Shift", (
        "Move 1–10 moves the window and follows. Magic = special:magic. Z actions on G fire on release.",
        "Sets = the monitor-dependent workspace-set helper. Resolve the Super hold before the action key.",
    )),
    Panel("Alt · applications and window groups", "Hold LEFT Alt; top legends add Shift", (
        "Parent selects the enclosing group; Flip grp changes its orientation. Term. = terminal.",
        "For Terminal, tap Enter while holding Alt. Alt+Shift+Space toggles Waybar.",
    )),
    Panel("Alt + Raise · focus, move and resize", "Hold left Alt + Backspace / Raise; top legends add Shift", (
        "Add outer Shift for smart window movement or height resize. Smart move can cross monitor edges.",
        "Resize: physical D/F (minus/equal), 100 px per tap. Retap directions for repeated focus/move.",
    )),
    Panel("Alt + Lower · numeric workspaces", "Hold left Alt + Tab / Lower; top legends add Shift", (
        "Physical A S D F G H J K L Quote = 1–10. Add outer left Shift to move the window and follow.",
        "The right Shift thumb sends colon on Lower. Super + Q–P is the simpler workspace shortcut.",
    )),
    Panel("Raise · physical-key reference", "Hold Backspace / Raise; bottom legends identify Base keys", (
        "Raise+H latches scrolling; any next key/button press cancels. Super + scrolling changes workspace.",
        "Drag/resize: release Raise, hold left Alt + left/right microswitch, and roll the trackball.",
    )),
    Panel("Deck · Super + Raise navigation", "Hold Enter / Super + Backspace / Raise; top legends add Shift", (
        "Super+arrows focuses; add Shift to move via hy3 directly, without the smart-move fallback.",
        "Super+Escape lock and Super+Shift+Escape exit are unbound on Deck; use the rail lock button.",
    )),
]

# Display abbreviations only; the underlying bindings remain in the source YAML.
ALIASES = {
    "LALT": "L Alt", "RALT": "R Alt", "LSHFT": "Shift", "LCTRL": "Ctrl",
    "LGUI": "Super", "TAB": "Tab", "ENTER": "Enter", "BSPC": "Bspc",
    "SPC": "Space", "DEL": "Del", "INS": "Ins", "CAPS": "Caps",
    "HOME": "Home", "END": "End", "UP": "↑", "DOWN": "↓",
    "LEFT": "←", "RIGHT": "→", "PG UP": "PgUp", "PG DN": "PgDn",
    "COPY": "Copy", "PASTE": "Paste", "MUTE": "Mute", "PREV": "Prev",
    "NEXT": "Next", "VOL DN": "Vol −", "VOL UP": "Vol +", "APP": "Menu",
    "ESC": "Esc", "RAISE": "Raise", "LOWER": "Lower", "SUPER": "Super",
    "ALT": "Alt", "Quote": "'", "Comma": ",", "Dot": ".", "Slash": "/",
    "Ctrl thumb": "Ctrl", "Shift key": "Shift", "tap Enter": "Enter",
    "Quote→0": "' → 0", "Previous": "Prev", "Terminal": "Term.",
    "ChatGPT": "Chat\nGPT", "&bootloader": "Boot", "&studio_unlock": "Studio",
    "Sft+DEL": "Sft+Del", "Ctl+INS": "Ctrl+Ins", "Sft+INS": "Sft+Ins",
    "+SHIFT": "+Shift", "To magic": "→Magic", "Move 10": "Move10",
    "Smart ↑": "Smart↑", "Smart ←": "Smart←", "Smart ↓": "Smart↓", "Smart →": "Smart→",
    "Height +": "Height+", "Height -": "Height−",
    "Focus ↑": "↑", "Focus ←": "←", "Focus ↓": "↓", "Focus →": "→",
    "Page ↑": "PgUp", "Page ↓": "PgDn",
}


def label(value):
    text = str(value)
    # The physical Base letter is enough; the center already explains the action.
    if " → " in text:
        text = text.split(" → ")[0]
    return ALIASES.get(text, text)


def key_dict(key):
    return key if isinstance(key, dict) else {"t": str(key)}


def flatten(keys):
    return [key_dict(key) for row in keys for key in (row if isinstance(row, list) else [row])]


def geometry():
    layer = ET.parse(ROOT / "assets/cosmos_keymap.svg").getroot().find("s:g", NS)
    result = []
    for group in layer.findall(".//s:g", NS):
        match = re.search(r"\bkeypos-(\d+)\b", group.get("class", ""))
        if not match:
            continue
        values = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", group.attrib["transform"])]
        x, y, *angle = values
        # Reduce unused inter-half space, preserving key positions within each half.
        if x > 420:
            x -= 40
        rect = group.find("s:rect", NS)
        result.append((int(match[1]), x, y, angle[0] if angle else 0, float(rect.attrib["height"])))
    assert [key[0] for key in result] == list(range(42)), "Expected the generated 42-key Corne geometry"
    return result


def text(c, x, y, value, size=8.5, bold=False, color=INK):
    c.setFillColor(color)
    c.setFont("DejaVu-Bold" if bold else "DejaVu", size)
    c.drawString(x, y, value)


def centered(c, value, y, size, width=48, bold=False):
    font = "DejaVu-Bold" if bold else "DejaVu"
    size = min(size, size * width / max(pdfmetrics.stringWidth(value, font, size), 1))
    if size < 11.5:
        raise ValueError(f"Print label too small: {value!r} ({size:.1f} native units)")
    c.setFont(font, size)
    c.drawCentredString(0, y, value)


def wrapped(value, width, size=8.5):
    lines = []
    for paragraph in value.split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if line and pdfmetrics.stringWidth(candidate, "DejaVu", size) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


def draw_key(c, key, position, base):
    _, x, y, angle, height = position
    kind = key.get("type", "")
    fill = {"held": "#f4dede", "deck": "#e3eef5", "zuffie": "#eee6f6"}.get(kind, "#ffffff")
    c.saveState()
    c.translate(x, -y)
    c.rotate(-angle)
    c.setFillColor(HexColor(fill))
    c.setStrokeColor(HexColor("#b4bbc2" if kind in ("idle", "trans") else "#66727d"))
    c.setLineWidth(0.8)
    if kind == "ghost":
        c.setDash(3, 2)
    c.roundRect(-26, -height / 2, 52, height, 5, fill=1, stroke=1)
    c.setFillColor(MUTED if kind in ("idle", "trans") else INK)
    tap = label(key.get("t", ""))
    lines = tap.split("\n") if "\n" in tap else wrapped(tap, 48, 13.5)
    if len(lines) > 2:
        raise ValueError(f"Too many lines in key label: {tap!r}")
    for i, line in enumerate(lines):
        size = 18 if len(tap) == 1 and (base or tap in "↑←↓→") else 13.5
        centered(c, line, (2 if len(lines) == 2 else -4) - i * 13, size)
    if key.get("h"):
        centered(c, label(key["h"]), -height / 2 + 3, 11.5)
    if key.get("s"):
        centered(c, label(key["s"]), height / 2 - 11, 11.5)
    c.restoreState()


def draw_combos(c, combos, layer, base_keys):
    for combo in combos:
        if layer not in combo.get("l", []):
            continue
        key = key_dict(combo["k"])
        lines = ["+".join(label(base_keys[p]["t"]) for p in combo["p"]), label(key["t"])]
        if key.get("h"):
            lines.append(label(key["h"]))
        if key.get("s"):
            lines.append("+Shift: " + label(key["s"]))
        c.saveState()
        c.translate(400, -85)
        c.setStrokeColor(HexColor("#87929d"))
        c.setFillColor(HexColor("#f3f5f7"))
        c.roundRect(-58, -len(lines) * 17 + 3, 116, len(lines) * 17 + 10, 5, stroke=1, fill=1)
        c.setFillColor(INK)
        for i, line in enumerate(lines):
            centered(c, line, -i * 17 - 5, 12, width=108)
        c.restoreState()


def draw_panel(c, panel, data, geom, x, top, width, height, large):
    layer, keys, combos, base_keys, is_keymap = data
    text(c, x, top - 12, panel.title, 12, bold=True)
    if large:
        scale = min((width - 160) / WIDTH, (height - 22) / HEIGHT)
        diagram_top = top - 22
        notes_x, notes_top = x + WIDTH * scale + 14, top - 31
        notes_width = width - WIDTH * scale - 14
        notes = (panel.gesture, *panel.notes)
    else:
        text(c, x, top - 22, panel.gesture, 8.5, color=MUTED)
        scale = width / WIDTH
        diagram_top = top - 26
        notes_x, notes_top = x, diagram_top - HEIGHT * scale - 7
        notes_width = width
        notes = panel.notes
    c.saveState()
    c.translate(x, diagram_top)
    c.scale(scale, scale)
    for key, pos in zip(keys, geom, strict=True):
        draw_key(c, key, pos, is_keymap)
    draw_combos(c, combos, layer, base_keys)
    c.restoreState()
    y = notes_top
    for note in notes:
        for line in wrapped(note, notes_width, 8.2):
            text(c, notes_x, y, line, 8.2)
            y -= 9.5
        if large:
            y -= 7
    if y + 2 < top - height:
        raise ValueError(f"Panel notes overflow: {panel.title}")


def make_pdf(path, datasets, geom, reviewed, large=False):
    size = landscape(A4) if large else A4
    groups = [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]] if large else [[0, 1], [2, 3], [4, 5, 6], [7, 8, 9]]
    c = canvas.Canvas(str(path), pagesize=size, invariant=1, pageCompression=1)
    c.setTitle("Cosmos keyboard layout and current Hyprland shortcuts")
    c.setAuthor("cosmos-zmk-config")
    c.setSubject(f"Repository keymap; Hyprland bindings reviewed {reviewed}; A4 at 100%")
    width, height = size
    usable_width = width - 2 * MARGIN
    for number, group in enumerate(groups, 1):
        top = height - MARGIN
        text(c, MARGIN, top - 12, "COSMOS / Keyboard + Hyprland", 15, bold=True)
        text(c, MARGIN, top - 26, f"Repository keymap · Hyprland reviewed {reviewed} · " + ("large / 2 per page" if large else "compact / 2–3 per page"), 8.5, color=MUTED)
        text(c, MARGIN, top - 39, "Keymap bottom: hold/sticky. Hyprland bottom: Base key; top: +Shift. Pink: hold; dashed: optional Shift.", 8.2)
        body_top = top - 44
        body_bottom = MARGIN + 16
        gap = 10
        panel_height = (body_top - body_bottom - gap * (len(group) - 1)) / len(group)
        for i, index in enumerate(group):
            panel_top = body_top - i * (panel_height + gap)
            draw_panel(c, PANELS[index], datasets[index], geom, MARGIN, panel_top, usable_width, panel_height, large)
            if i:
                c.setStrokeColor(HexColor("#d0d5da"))
                c.setLineWidth(0.5)
                c.line(MARGIN, panel_top + 5, width - MARGIN, panel_top + 5)
        text(c, MARGIN, MARGIN - 2, "D = Deck only · Z = zuffie only · ▽ = transparent · Details: HYPRLAND.md · Print A4, actual size (100%).", 8)
        text(c, width - MARGIN - 27, MARGIN - 2, f"{number}/{len(groups)}", 8)
        c.showPage()
    c.save()
    print(f"Created {path} ({len(groups)} pages)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-dir", type=Path, required=True)
    args = parser.parse_args()
    for name, filename in (("DejaVu", "DejaVuSans.ttf"), ("DejaVu-Bold", "DejaVuSans-Bold.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(args.font_dir / filename)))
    keymap = yaml.safe_load((ROOT / "assets/cosmos_keymap.yaml").read_text())
    hyprland = yaml.safe_load((ROOT / "assets/cosmos_hyprland.yaml").read_text())
    base_keys = flatten(keymap["layers"]["Base"])
    datasets = []
    for document in (keymap, hyprland):
        for layer, keys in document["layers"].items():
            datasets.append((layer, flatten(keys), document.get("combos", []), base_keys, document is keymap))
    assert len(datasets) == len(PANELS), "Update print panel descriptions for the new layer list"
    reviewed = re.search(r"Hyprland was reviewed on (\d{4}-\d{2}-\d{2})", (ROOT / "HYPRLAND.md").read_text())[1]
    geom = geometry()
    make_pdf(ROOT / "assets/cosmos_print.pdf", datasets, geom, reviewed)
    make_pdf(ROOT / "assets/cosmos_print_large.pdf", datasets, geom, reviewed, large=True)


if __name__ == "__main__":
    main()

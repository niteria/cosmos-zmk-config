# Mark Stosberg Layout for Cosmos Keyboard

This is an adaptation of [Mark Stosberg's Corne layout](https://github.com/markstos/qmk_userspace/blob/main/keyboards/crkbd/keymaps/markstos/keymap.c) for the Cosmos split keyboard running ZMK firmware.

## Layout Overview

### Base Layer (QWERTY)

```
┌─────┬─────┬─────┬─────┬─────┬─────┐   ┌─────┬─────┬─────┬─────┬─────┬─────┐
│ TAB │  Q  │  W  │  E  │  R  │  T  │   │  Y  │  U  │  I  │  O  │  P  │ DEL │
├─────┼─────┼─────┼─────┼─────┼─────┤   ├─────┼─────┼─────┼─────┼─────┼─────┤
│LALT │  A  │  S  │  D  │  F  │  G  │   │  H  │  J  │  K  │  L  │  ;  │RALT │
│     │ LCTL│ LALT│ LGUI│LSHFT│     │   │     │LSHFT│ LGUI│ LALT│ LCTL│     │
├─────┼─────┼─────┼─────┼─────┼─────┤   ├─────┼─────┼─────┼─────┼─────┼─────┤
│LSHFT│  Z  │  X  │  C  │  V  │  B  │   │  N  │  M  │  ,  │  .  │  /  │ FUN │
├─────┼─────┼─────┼─────┼─────┼─────┤   ├─────┼─────┼─────┼─────┼─────┼─────┤
│     │     │     │LCTL │GUI/ │LOW/ │   │RSE/ │ SPC │LSHFT│     │     │     │
│     │     │     │     │ ENT │ TAB │   │ BSP │     │     │     │     │     │
└─────┴─────┴─────┴─────┴─────┴─────┘   └─────┴─────┴─────┴─────┴─────┴─────┘
```

**Features:**
- **Home Row Mods**: ASDF (left) and JKL; (right) have tap-hold modifiers
  - Tap = letter, Hold = modifier (Ctrl/Alt/Gui/Shift)
- **Outer Columns**: TAB (left), DEL (right), with sticky modifiers on rows 1-2
- **Thumb Cluster** (Mark's layout):
  - Left: LCTL | GUI/Enter | Lower/Tab
  - Right: Raise/Backspace | Space | LSHFT

### Lower Layer

```
┌─────┬─────┬─────┬─────┬─────┬─────┐   ┌─────┬─────┬─────┬─────┬─────┬─────┐
│     │ F1  │ F2  │ F3  │ F4  │ F5  │   │ F6  │ F7  │ F8  │ F9  │ F10 │ F11 │
├─────┼─────┼─────┼─────┼─────┼─────┤   ├─────┼─────┼─────┼─────┼─────┼─────┤
│     │  1  │  2  │  3  │  4  │  5  │   │  6  │  7  │  8  │  9  │  0  │ F12 │
├─────┼─────┼─────┼─────┼─────┼─────┤   ├─────┼─────┼─────┼─────┼─────┼─────┤
│     │  !  │  @  │  #  │  $  │  %  │   │  ^  │  &  │  *  │  (  │  )  │     │
├─────┼─────┼─────┼─────┼─────┼─────┤   ├─────┼─────┼─────┼─────┼─────┼─────┤
│     │     │     │     │     │     │   │     │     │     │     │     │     │
└─────┴─────┴─────┴─────┴─────┴─────┘   └─────┴─────┴─────┴─────┴─────┴─────┘
```

### Raise Layer

```
┌─────┬─────┬─────┬─────┬─────┬─────┐   ┌─────┬─────┬─────┬─────┬─────┬─────┐
│     │ HOME│ PGUP│     │     │     │   │     │     │     │ END │ PGDN│     │
├─────┼─────┼─────┼─────┼─────┼─────┤   ├─────┼─────┼─────┼─────┼─────┼─────┤
│     │ LEFT│ UP  │ DOWN│RIGHT│     │   │     │     │     │     │     │     │
├─────┼─────┼─────┼─────┼─────┼─────┤   ├─────┼─────┼─────┼─────┼─────┼─────┤
│     │  [  │  ]  │  {  │  }  │  |  │   │  +  │  -  │  =  │  _  │     │     │
├─────┼─────┼─────┼─────┼─────┼─────┤   ├─────┼─────┼─────┼─────┼─────┼─────┤
│     │     │     │     │     │     │   │     │     │     │     │     │     │
└─────┴─────┴─────┴─────┴─────┴─────┘   └─────┴─────┴─────┴─────┴─────┴─────┘
```

## Combos

Combos work on the base layer with 50ms timeout:

| Combo | Keys | Output |
|-------|------|--------|
| esc | J+K | ESC |
| tab | A+S | TAB |
| bspc | ,+. | BSPC |
| del | K+L | DEL |
| ent | ,+. | ENTER |

**3-Key Combos** (1 second hold):

| Combo | Keys | Output |
|-------|------|--------|
| bootloader_left | Q+W+E | Bootloader mode |
| bootloader_right | Y+U+I | Bootloader mode |
| reset_left | A+S+D | System reset |
| reset_right | H+J+K | System reset |

## Behaviors

### Home Row Mods
- **hml** (left): LCTRL/LALT/LGUI/LSHFT on ASDF
- **hmr** (right): LSHFT/LGUI/LALT/LCTRL on JKL;
- Flavor: balanced
- Tapping term: 200ms

### Thumb Keys
- **gui_ent**: GUI/Enter mod-tap
- **low_tab**: Lower layer/Tab mod-tap  
- **rse_bsp**: Raise layer/Backspace mod-tap

### Sticky Keys
- LALT, RALT, LSHFT, LCTRL on outer columns

## Important Notes

1. **Split Keyboard**: Right half is central, left is peripheral
2. **Bootloader Combos**: Only work when both halves are connected (processed by central)
3. **Single Half Mode**: To flash left half alone, short RST pin to GND
4. **Key Matrix**: 4 rows × 12 columns (6 per half)

## Credits

Based on [Mark Stosberg's QMK Corne layout](https://github.com/markstos/qmk_userspace)

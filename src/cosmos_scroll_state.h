#pragma once

#include <stdbool.h>
#include <stdint.h>

/* Protected by scroll_lock in the firmware. Input frames keep one mode for
 * both axes, even if a key/button changes the latch between X and Y events. */
struct cs_state {
    bool raise;
    bool latched;
    bool frame_open;
    bool frame_scroll;
    bool reset_pending;
    bool last_key_valid;
    uint32_t last_key_position;
    int64_t last_key_timestamp;
    int32_t remainder[2];
};

static inline bool cs_scrolling(const struct cs_state *s) {
    return s->raise || s->latched;
}

static inline void cs_raise(struct cs_state *s, bool active) {
    bool before = cs_scrolling(s);
    s->raise = active;
    s->reset_pending |= before != cs_scrolling(s);
}

static inline void cs_latch(struct cs_state *s, bool active) {
    bool before = cs_scrolling(s);
    s->latched = active;
    s->reset_pending |= before != cs_scrolling(s);
}

static inline void cs_press(struct cs_state *s, bool pressed) {
    if (pressed) {
        cs_latch(s, false);
    }
}

static inline void cs_key(struct cs_state *s, uint32_t position, int64_t timestamp,
                          bool pressed) {
    if (pressed) {
        s->last_key_valid = true;
        s->last_key_position = position;
        s->last_key_timestamp = timestamp;
        cs_press(s, true);
    }
}

static inline void cs_button(struct cs_state *s, bool pressed) {
    if (pressed) {
        s->last_key_valid = false;
        cs_press(s, true);
    }
}

static inline bool cs_arm(struct cs_state *s, uint32_t position, int64_t timestamp) {
    /* A hold-tap can buffer H's behavior until after a later physical press.
     * That later press must cancel even if H's callback has not run yet. */
    if (!s->last_key_valid || s->last_key_position != position ||
        s->last_key_timestamp != timestamp) {
        return false;
    }
    cs_latch(s, true);
    return true;
}

static inline void cs_disconnect(struct cs_state *s) {
    s->last_key_valid = false;
    cs_latch(s, false);
    s->reset_pending = true;
}

/* Return whether this X/Y event becomes scroll; otherwise leave its value alone.
 * Preserve fractional motion independently on each axis at the existing 1/256
 * scroll scale. Discard old fractions when starting a new scrolling session. */
static inline bool cs_motion(struct cs_state *s, unsigned int axis, bool sync,
                             int32_t divisor, int32_t *value) {
    if (!s->frame_open) {
        s->frame_scroll = cs_scrolling(s);
        if (s->reset_pending) {
            s->remainder[0] = s->remainder[1] = 0;
            s->reset_pending = false;
        }
    }
    s->frame_open = !sync;
    if (!s->frame_scroll) {
        return false;
    }
    int64_t total = (int64_t)*value + s->remainder[axis];
    *value = total / divisor;
    s->remainder[axis] = total % divisor;
    return true;
}

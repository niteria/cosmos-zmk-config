/* Pure trigger state machine, shared with the host-side C tests. */
#pragma once
#include <stdbool.h>
#include <stdint.h>

#define CU_FN 35
#define CU_J 19
#define CU_K 20
#define CU_L 21
#define CU_CHORD ((UINT64_C(1) << CU_FN) | (UINT64_C(1) << CU_J) | \
                  (UINT64_C(1) << CU_K) | (UINT64_C(1) << CU_L))
#define CU_HOLD_MS 2000

struct cu_guard {
    uint64_t down;
    int64_t deadline;
    bool armed;
    bool sending;
    bool blocked;
};

static inline void cu_cancel(struct cu_guard *g) {
    g->armed = false;
    g->sending = false;
    g->blocked = g->down != 0;
}

static inline void cu_position(struct cu_guard *g, uint32_t position, bool down,
                               bool local) {
    if (position >= 64) {
        cu_cancel(g);
        return;
    }
    uint64_t bit = UINT64_C(1) << position;
    /* The four unlock keys must come from the right/central scanner. */
    if ((bit & CU_CHORD) && !local) {
        cu_cancel(g);
        return;
    }
    if (down) {
        g->down |= bit;
        if (!(bit & CU_CHORD)) {
            cu_cancel(g);
        }
    } else {
        g->down &= ~bit;
        if (g->armed) {
            cu_cancel(g);
        }
        /* After firing, chord releases are allowed; unrelated input and USB
         * changes still abort. A completed hold can fire only once. */
        if (!g->down && !g->sending) {
            g->blocked = false;
        }
    }
}

static inline bool cu_arm(struct cu_guard *g, int64_t now, bool eligible) {
    if (!eligible || g->down != CU_CHORD || g->blocked || g->sending || g->armed) {
        return false;
    }
    g->deadline = now + CU_HOLD_MS;
    g->armed = true;
    return true;
}

static inline bool cu_fire(struct cu_guard *g, int64_t now, bool eligible) {
    if (!g->armed) {
        return false;
    }
    if (!eligible || g->down != CU_CHORD) {
        cu_cancel(g);
        return false;
    }
    if (now < g->deadline) {
        return false;
    }
    g->armed = false;
    g->sending = true;
    g->blocked = true;
    return true;
}

static inline void cu_finished(struct cu_guard *g) {
    g->sending = false;
    g->blocked = g->down != 0;
}

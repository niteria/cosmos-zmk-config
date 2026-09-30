#include <assert.h>
#include "cosmos_scroll_state.h"

static int32_t motion(struct cs_state *s, unsigned int axis, int32_t delta,
                      bool sync, bool scroll) {
    assert(cs_motion(s, axis, sync, 256, &delta) == scroll);
    return delta;
}

int main(void) {
    struct cs_state s = {0};
    assert(motion(&s, 0, 130, false, false) == 130);
    assert(motion(&s, 1, -50, true, false) == -50);

    /* Ordinary held-Raise scrolling keeps its direction, scale and fractions. */
    cs_raise(&s, true);
    assert(motion(&s, 0, 128, false, true) == 0);
    assert(motion(&s, 1, -64, true, true) == 0);
    assert(motion(&s, 0, 128, false, true) == 1);
    assert(motion(&s, 1, -192, true, true) == -1);
    cs_raise(&s, false);
    assert(motion(&s, 0, 256, true, false) == 256);

    /* Raise+H: observer sees the H press before its behavior arms the latch.
     * Releasing H and the Raise thumb must not cancel it or lose fractions. */
    cs_key(&s, 39, 100, true);
    cs_raise(&s, true);
    cs_key(&s, 18, 310, true);
    assert(cs_arm(&s, 18, 310));
    assert(motion(&s, 1, 128, true, true) == 0);
    cs_key(&s, 18, 350, false); /* H release. */
    cs_key(&s, 39, 370, false); /* Backspace/Raise release. */
    cs_raise(&s, false);
    assert(s.latched && !s.raise);
    assert(motion(&s, 1, 128, true, true) == 1);
    cs_button(&s, false); /* Mouse-button release is not a cancelling press. */
    assert(s.latched);

    /* Any next key/button press cancels; subsequent pointer deltas are raw. */
    cs_button(&s, true);
    assert(!s.latched);
    assert(motion(&s, 1, 123, true, false) == 123);

    /* A press clears only the latch; a physically held Raise still scrolls. */
    cs_raise(&s, true);
    cs_latch(&s, true);
    cs_press(&s, true);
    assert(!s.latched && s.raise);
    assert(motion(&s, 0, -512, true, true) == -2);
    cs_raise(&s, false);
    assert(motion(&s, 0, -7, true, false) == -7);

    /* Fractions cannot leak into a new scroll session, even without an
     * intervening motion event in pointer mode. */
    cs_latch(&s, true);
    assert(motion(&s, 0, 255, true, true) == 0);
    cs_press(&s, true);
    cs_latch(&s, true);
    assert(motion(&s, 0, 1, true, true) == 0);
    assert(motion(&s, 0, -1, true, true) == 0);
    assert(motion(&s, 1, -256, true, true) == -1);

    /* Do not turn one sensor frame into X scroll plus Y pointer movement. */
    assert(motion(&s, 0, 512, false, true) == 2);
    cs_press(&s, true);
    assert(motion(&s, 1, -512, true, true) == -2);
    assert(motion(&s, 1, -512, true, false) == -512);
    assert(motion(&s, 0, 17, false, false) == 17);
    cs_latch(&s, true);
    assert(motion(&s, 1, 19, true, false) == 19);
    assert(motion(&s, 1, 256, true, true) == 1);

    /* Reconnection starts in pointer mode; int16-extreme deltas stay signed. */
    cs_disconnect(&s);
    assert(!s.latched);
    assert(motion(&s, 0, -32768, true, false) == -32768);
    cs_latch(&s, true);
    assert(motion(&s, 0, 32767, true, true) == 127);
    assert(motion(&s, 0, 1, true, true) == 1);
    assert(motion(&s, 1, -32768, true, true) == -128);

    /* Buffered H must not re-arm after a later key (either half), button or
     * connection change, including presses that share a millisecond timestamp. */
    cs_key(&s, 18, 400, true);
    cs_key(&s, 1, 400, true);
    assert(!cs_arm(&s, 18, 400));
    assert(!s.latched);
    cs_key(&s, 18, 500, true);
    cs_key(&s, 30, 501, true);
    assert(!cs_arm(&s, 18, 500));
    cs_key(&s, 18, 600, true);
    cs_button(&s, true);
    assert(!cs_arm(&s, 18, 600));
    cs_key(&s, 18, 700, true);
    cs_disconnect(&s);
    assert(!cs_arm(&s, 18, 700));
    cs_key(&s, 18, 800, true);
    assert(!cs_arm(&s, 18, 700));
    cs_key(&s, 18, 810, false);
    assert(cs_arm(&s, 18, 800)); /* Releases alone do not invalidate the trigger. */
    return 0;
}

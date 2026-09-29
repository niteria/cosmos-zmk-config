#include <assert.h>
#include "cosmos_unlock_guard.h"

static void press_chord(struct cu_guard *g) {
    cu_position(g, CU_FN, true, true);
    cu_position(g, CU_J, true, true);
    cu_position(g, CU_K, true, true);
    cu_position(g, CU_L, true, true);
}

int main(void) {
    struct cu_guard g = {0};
    /* A one-shot layer/virtual combo without physical Func cannot arm. */
    cu_position(&g, CU_J, true, true);
    cu_position(&g, CU_K, true, true);
    cu_position(&g, CU_L, true, true);
    assert(!cu_arm(&g, 0, true));
    g = (struct cu_guard){0};
    press_chord(&g);
    assert(!cu_arm(&g, 0, false)); /* USB unavailable / no provisioned secret. */
    assert(cu_arm(&g, 10, true));
    assert(!cu_fire(&g, 2009, true));
    assert(cu_fire(&g, 2010, true));
    assert(!cu_fire(&g, 5000, true));
    cu_finished(&g);
    assert(!cu_arm(&g, 6000, true)); /* No repeat while held. */

    const int positions[] = {CU_FN, CU_J, CU_K, CU_L};
    for (int i = 0; i < 4; ++i) {
        g = (struct cu_guard){0};
        press_chord(&g);
        assert(cu_arm(&g, 0, true));
        cu_position(&g, positions[i], false, true);
        assert(!cu_fire(&g, 3000, true));
        cu_position(&g, positions[i], true, true);
        assert(!cu_arm(&g, 3000, true)); /* Release everything to retry. */
    }
    g = (struct cu_guard){0};
    press_chord(&g);
    assert(cu_arm(&g, 0, true));
    assert(!cu_fire(&g, 2000, false)); /* Disconnect/suspend/layer changed. */
    assert(!cu_arm(&g, 3000, true));

    g = (struct cu_guard){0};
    press_chord(&g);
    assert(cu_arm(&g, 0, true));
    cu_position(&g, 12, true, true); /* Additional modifier/key cancels. */
    assert(!cu_fire(&g, 3000, true));

    g = (struct cu_guard){0};
    cu_position(&g, CU_FN, true, false); /* Remote/left source rejected. */
    assert(g.down == 0);
    g = (struct cu_guard){0};
    press_chord(&g);
    assert(cu_arm(&g, 0, true));
    assert(cu_fire(&g, 2000, true));
    for (int i = 0; i < 4; ++i) {
        cu_position(&g, positions[i], false, true);
    }
    assert(g.sending); /* Release after the hold does not truncate output. */
    cu_finished(&g);
    press_chord(&g);
    assert(cu_arm(&g, 4000, true));
    assert(cu_fire(&g, 6000, true));
    cu_cancel(&g); /* USB/protocol change aborts even during typing. */
    assert(!g.sending);
    return 0;
}

/* Raise+H latches only trackball scrolling, never the keyboard's Raise layer. */
#define DT_DRV_COMPAT cosmos_scroll_latch

#include <zephyr/kernel.h>
#include <drivers/behavior.h>
#include <drivers/input_processor.h>
#include <zmk/behavior.h>
#include <zmk/event_manager.h>
#include <zmk/events/endpoint_changed.h>
#include <zmk/events/layer_state_changed.h>
#include <zmk/events/position_state_changed.h>
#include <zmk/events/usb_conn_state_changed.h>
#include "cosmos_scroll_state.h"

#define SCROLL_NODE DT_NODELABEL(cosmos_scroll)
#define RAISE_LAYER DT_PROP(SCROLL_NODE, raise_layer)
#define SCROLL_DIVISOR DT_PROP(SCROLL_NODE, scroll_divisor)

BUILD_ASSERT(SCROLL_DIVISOR > 0, "Scroll divisor must be positive");

static struct cs_state scroll_state;
K_MUTEX_DEFINE(scroll_lock);

static int scroll_pressed(struct zmk_behavior_binding *binding,
                          struct zmk_behavior_binding_event event) {
    k_mutex_lock(&scroll_lock, K_FOREVER);
    cs_arm(&scroll_state, event.position, event.timestamp);
    k_mutex_unlock(&scroll_lock);
    return ZMK_BEHAVIOR_OPAQUE;
}

static int scroll_released(struct zmk_behavior_binding *binding,
                           struct zmk_behavior_binding_event event) {
    return ZMK_BEHAVIOR_OPAQUE;
}

static const struct behavior_driver_api scroll_behavior_api = {
    .binding_pressed = scroll_pressed,
    .binding_released = scroll_released,
};
BEHAVIOR_DT_INST_DEFINE(0, NULL, NULL, NULL, NULL, POST_KERNEL,
                       CONFIG_KERNEL_INIT_PRIORITY_DEFAULT, &scroll_behavior_api);

static int scroll_listener(const zmk_event_t *eh) {
    const struct zmk_position_state_changed *pos = as_zmk_position_state_changed(eh);
    const struct zmk_layer_state_changed *layer = as_zmk_layer_state_changed(eh);
    k_mutex_lock(&scroll_lock, K_FOREVER);
    if (pos) {
        /* Observe both halves before combos/hold-taps can capture the press.
         * H's trigger press reaches us before scroll_pressed arms the latch. */
        cs_key(&scroll_state, pos->position, pos->timestamp, pos->state);
    } else if (layer) {
        if (layer->layer == RAISE_LAYER) {
            cs_raise(&scroll_state, layer->state);
        }
    } else {
        cs_disconnect(&scroll_state);
    }
    k_mutex_unlock(&scroll_lock);
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(cosmos_scroll, scroll_listener);
ZMK_SUBSCRIPTION(cosmos_scroll, zmk_position_state_changed);
ZMK_SUBSCRIPTION(cosmos_scroll, zmk_layer_state_changed);
ZMK_SUBSCRIPTION(cosmos_scroll, zmk_usb_conn_state_changed);
ZMK_SUBSCRIPTION(cosmos_scroll, zmk_endpoint_changed);

static int scroll_handle_event(const struct device *dev, struct input_event *event,
                               uint32_t param1, uint32_t param2,
                               struct zmk_input_processor_state *state) {
    k_mutex_lock(&scroll_lock, K_FOREVER);
    if (event->type == INPUT_EV_KEY && event->code >= INPUT_BTN_0 &&
        event->code <= INPUT_BTN_4) {
        /* The GPIO buttons bypass the keymap. Cancel before the normal mouse
         * listener handles the click, without swallowing or delaying it. */
        cs_button(&scroll_state, event->value > 0);
    } else if (event->type == INPUT_EV_REL &&
               (event->code == INPUT_REL_X || event->code == INPUT_REL_Y)) {
        unsigned int axis = event->code == INPUT_REL_X ? 0 : 1;
        if (cs_motion(&scroll_state, axis, event->sync, SCROLL_DIVISOR, &event->value)) {
            event->code = axis == 0 ? INPUT_REL_HWHEEL : INPUT_REL_WHEEL;
        }
    }
    k_mutex_unlock(&scroll_lock);
    return ZMK_INPUT_PROC_CONTINUE;
}

static const struct zmk_input_processor_driver_api scroll_processor_api = {
    .handle_event = scroll_handle_event,
};
DEVICE_DT_DEFINE(SCROLL_NODE, NULL, NULL, NULL, NULL, POST_KERNEL,
                 CONFIG_KERNEL_INIT_PRIORITY_DEFAULT, &scroll_processor_api);

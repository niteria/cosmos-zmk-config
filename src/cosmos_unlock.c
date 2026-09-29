/* Private reports use only a credential loaded from persistent settings.
 * Provisioning is separate; no secret enters builds, key events, or BLE.
 */
#define DT_DRV_COMPAT cosmos_unlock

#include <errno.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/usb/usb_device.h>
#include <zephyr/usb/class/usb_hid.h>
#include <drivers/behavior.h>
#include <zmk/behavior.h>
#include <zmk/event_manager.h>
#include <zmk/events/endpoint_changed.h>
#include <zmk/events/keycode_state_changed.h>
#include <zmk/events/position_state_changed.h>
#include <zmk/events/usb_conn_state_changed.h>
#include <zmk/hid.h>
#include <zmk/keymap.h>
#include <zmk/matrix.h>
#include <zmk/usb.h>
#include <zmk/usb_hid.h>
#include <zmk/endpoints.h>
#include "cosmos_unlock_guard.h"
#include "cosmos_unlock_store.h"

BUILD_ASSERT(CONFIG_ZMK_HID_REPORT_TYPE_HKRO && CONFIG_ZMK_HID_KEYBOARD_REPORT_SIZE == 6,
             "Private USB encoder requires the Cosmos six-key HID report format");
BUILD_ASSERT(ZMK_KEYMAP_LEN <= 64, "Physical key tracking mask is too small");

static struct cu_guard guard;
K_MUTEX_DEFINE(guard_lock);
K_SEM_DEFINE(in_ready, 0, 1);
K_SEM_DEFINE(trigger_requested, 0, 1);
static atomic_t exclusive;
static atomic_t usb_epoch;
static atomic_t protocol = HID_PROTOCOL_REPORT;
static atomic_val_t armed_epoch;
static const struct device *usb_device;
static struct hid_ops private_ops;
static const struct hid_ops *original_ops;
static bool observer_first;

void __real_usb_hid_register_device(const struct device *, const uint8_t *, size_t,
                                   const struct hid_ops *);
int __real_hid_int_ep_write(const struct device *, const uint8_t *, uint32_t, uint32_t *);

static void private_in_ready(const struct device *dev) {
    k_sem_give(&in_ready);
    if (original_ops->int_in_ready) {
        original_ops->int_in_ready(dev);
    }
}

static void private_protocol(const struct device *dev, uint8_t value) {
    atomic_set(&protocol, value);
    atomic_inc(&usb_epoch);
    if (original_ops->protocol_change) {
        original_ops->protocol_change(dev, value);
    }
}

void __wrap_usb_hid_register_device(const struct device *dev, const uint8_t *desc,
                                   size_t size, const struct hid_ops *ops) {
    usb_device = dev;
    original_ops = ops;
    private_ops = *ops;
    private_ops.int_in_ready = private_in_ready;
    private_ops.protocol_change = private_protocol;
    __real_usb_hid_register_device(dev, desc, size, &private_ops);
}

/* Ordinary reports cannot interleave with the private USB transaction. */
int __wrap_hid_int_ep_write(const struct device *dev, const uint8_t *data,
                           uint32_t len, uint32_t *written) {
    if (atomic_get(&exclusive)) {
        return -EBUSY;
    }
    return __real_hid_int_ep_write(dev, data, len, written);
}

static bool usb_available(void) {
    enum usb_dc_status_code status = zmk_usb_get_status();
    return usb_device && zmk_usb_is_hid_ready() &&
           (status == USB_DC_CONFIGURED || status == USB_DC_RESUME ||
            status == USB_DC_CLEAR_HALT);
}

static bool usb_ready(void) {
    return usb_available() && zmk_endpoints_selected().transport == ZMK_TRANSPORT_USB;
}

static bool keyboard_idle(void) {
    const struct zmk_hid_keyboard_report *report = zmk_hid_get_keyboard_report();
    if (report->body.modifiers) {
        return false;
    }
    for (size_t i = 0; i < sizeof(report->body.keys); ++i) {
        if (report->body.keys[i]) {
            return false;
        }
    }
    return true;
}

static int unlock_pressed(struct zmk_behavior_binding *binding,
                          struct zmk_behavior_binding_event event) {
    k_mutex_lock(&guard_lock, K_FOREVER);
    if (cu_arm(&guard, k_uptime_get(), observer_first && !atomic_get(&exclusive) &&
               cosmos_unlock_credential_ready() && usb_ready() &&
               keyboard_idle() && zmk_keymap_highest_layer_active() == 3)) {
        armed_epoch = atomic_get(&usb_epoch);
        k_sem_give(&trigger_requested);
    }
    k_mutex_unlock(&guard_lock);
    return ZMK_BEHAVIOR_OPAQUE;
}

static int unlock_released(struct zmk_behavior_binding *binding,
                           struct zmk_behavior_binding_event event) {
    /* Physical releases were already observed before the combo engine. */
    return ZMK_BEHAVIOR_OPAQUE;
}

static const struct behavior_driver_api unlock_api = {
    .binding_pressed = unlock_pressed,
    .binding_released = unlock_released,
};
BEHAVIOR_DT_INST_DEFINE(0, NULL, NULL, NULL, NULL, POST_KERNEL,
                       CONFIG_KERNEL_INIT_PRIORITY_DEFAULT, &unlock_api);

static int unlock_listener(const zmk_event_t *eh) {
    k_mutex_lock(&guard_lock, K_FOREVER);
    const struct zmk_position_state_changed *pos = as_zmk_position_state_changed(eh);
    if (pos) {
        cu_position(&guard, pos->position, pos->state,
                    pos->source == ZMK_POSITION_STATE_CHANGE_SOURCE_LOCAL);
    } else if (as_zmk_usb_conn_state_changed(eh) || as_zmk_endpoint_changed(eh)) {
        atomic_inc(&usb_epoch);
        cu_cancel(&guard);
    } else {
        const struct zmk_keycode_state_changed *key = as_zmk_keycode_state_changed(eh);
        if (key && key->state) {
            cu_cancel(&guard);
        }
    }
    k_mutex_unlock(&guard_lock);
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(cosmos_unlock, unlock_listener);
ZMK_SUBSCRIPTION(cosmos_unlock, zmk_position_state_changed);
ZMK_SUBSCRIPTION(cosmos_unlock, zmk_usb_conn_state_changed);
ZMK_SUBSCRIPTION(cosmos_unlock, zmk_endpoint_changed);
ZMK_SUBSCRIPTION(cosmos_unlock, zmk_keycode_state_changed);

static bool transaction_valid(atomic_val_t epoch) {
    return guard.sending && atomic_get(&usb_epoch) == epoch && usb_ready();
}

/* Private reports never enter ZMK's global HID report or keycode event stream.
 * In particular, endpoint changes and GET_REPORT cannot expose them via BLE.
 */
static uint8_t private_report[9];
static int send_key(uint8_t key, atomic_val_t epoch, bool cleanup) {
    k_mutex_lock(&guard_lock, K_FOREVER);
    if (!usb_available() || (!cleanup && !transaction_valid(epoch))) {
        k_mutex_unlock(&guard_lock);
        return -ENODEV;
    }
    memset(private_report, 0, sizeof(private_report));
    bool boot = atomic_get(&protocol) == HID_PROTOCOL_BOOT;
    uint8_t *report = private_report + (boot ? 1 : 0);
    private_report[0] = ZMK_HID_REPORT_ID_KEYBOARD;
    report[boot ? 2 : 3] = key;
    k_sem_reset(&in_ready);
    int err = __real_hid_int_ep_write(usb_device, report, boot ? 8 : 9, NULL);
    k_mutex_unlock(&guard_lock);
    if (err) {
        return err;
    }
    /* A successful submit is not enough: wait for USB completion before the
     * next key, and never append Enter after a timeout or disconnect. */
    return k_sem_take(&in_ready, K_MSEC(200));
}

static void unlock_thread(void *a, void *b, void *c) {
    for (;;) {
        /* The rare unlock gesture adds no periodic wakeups during normal use. */
        k_sem_take(&trigger_requested, K_FOREVER);
        k_mutex_lock(&guard_lock, K_FOREVER);
        int64_t delay = guard.deadline - k_uptime_get();
        k_mutex_unlock(&guard_lock);
        if (delay > 0) {
            k_sleep(K_MSEC(delay));
        }
        k_mutex_lock(&guard_lock, K_FOREVER);
        bool fire = cu_fire(&guard, k_uptime_get(), armed_epoch == atomic_get(&usb_epoch) &&
                            usb_ready() && keyboard_idle() &&
                            zmk_keymap_highest_layer_active() == 3);
        atomic_val_t epoch = atomic_get(&usb_epoch);
        if (fire) {
            atomic_set(&exclusive, 1);
        }
        k_mutex_unlock(&guard_lock);
        if (!fire) {
            continue;
        }

        /* Let an ordinary in-flight report drain before using the endpoint. */
        k_sleep(K_MSEC(30));
        bool ok = send_key(0, epoch, false) == 0;
        for (size_t i = 0; ok && i < 48; ++i) {
            uint8_t digit = cosmos_unlock_digit(i);
            uint8_t usage = digit == '0' ? 0x27 : 0x1e + digit - '1';
            ok = send_key(usage, epoch, false) == 0;
            k_sleep(K_MSEC(20));
            if (ok) {
                ok = send_key(0, epoch, false) == 0;
                k_sleep(K_MSEC(20));
            }
        }
        if (ok) {
            send_key(0x28, epoch, false); /* Enter, only after all digits completed. */
            k_sleep(K_MSEC(20));
        }
        send_key(0, epoch, true); /* Best-effort release, including on abort. */
        memset(private_report, 0, sizeof(private_report));
        k_mutex_lock(&guard_lock, K_FOREVER);
        cu_finished(&guard);
        atomic_clear(&exclusive);
        k_mutex_unlock(&guard_lock);
        if (usb_ready()) {
            zmk_usb_hid_send_keyboard_report();
        }
    }
}

K_THREAD_DEFINE(cosmos_unlock_thread, 1536, unlock_thread, NULL, NULL, NULL, 10, 0, 0);

static int unlock_init(void) {
    extern struct zmk_event_subscription __event_subscriptions_start[];
    extern struct zmk_event_subscription __event_subscriptions_end[];
    for (struct zmk_event_subscription *s = __event_subscriptions_start;
         s < __event_subscriptions_end; ++s) {
        if (s->event_type == &zmk_event_zmk_position_state_changed) {
            observer_first = s->listener == &zmk_listener_cosmos_unlock;
            break;
        }
    }
    return observer_first ? 0 : -EINVAL;
}
SYS_INIT(unlock_init, APPLICATION, CONFIG_KERNEL_INIT_PRIORITY_DEFAULT);

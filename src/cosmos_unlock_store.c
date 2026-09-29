#include <zephyr/kernel.h>
#include <zephyr/devicetree.h>
#include <zephyr/settings/settings.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/atomic.h>
#include "cosmos_unlock_storage.h"
#include "cosmos_unlock_store.h"

LOG_MODULE_REGISTER(cosmos_unlock_store, LOG_LEVEL_INF);

BUILD_ASSERT(DT_REG_ADDR(DT_NODELABEL(storage_partition)) == 0xec000 &&
             DT_REG_SIZE(DT_NODELABEL(storage_partition)) == 0x8000,
             "Review persistence and UF2 bounds before changing the storage partition");
BUILD_ASSERT(!IS_ENABLED(CONFIG_ZMK_SETTINGS_RESET_ON_START),
             "Use explicit credential clearing, not automatic settings erasure");

static const struct cu_command provision_data
    __attribute__((section(".cosmos_unlock_provision"), used, aligned(256))) = {
        .magic = "COSMOS-UNLOCK-V2",
        .version = 2,
};
/* No compiler constant-folding of the post-build-personalized command. */
static const volatile struct cu_command *const provision = &provision_data;
static struct cu_record active;
static atomic_t ready;
K_SEM_DEFINE(storage_requested, 0, 1);

struct read_result {
    struct cu_record *record;
    int status;
};

static int read_record(const char *name, size_t len, settings_read_cb read_cb,
                       void *cb_arg, void *param) {
    struct read_result *result = param;
    if (name && *name) {
        return 0;
    }
    if (len != sizeof(*result->record)) {
        /* Present but invalid; an explicit provisioning/clear command may
         * repair it. A public image still fails closed on this record. */
        memset(result->record, 0, sizeof(*result->record));
        result->status = 1;
    } else {
        ssize_t count = read_cb(cb_arg, result->record, len);
        result->status = count == (ssize_t)len ? 1 : -EIO;
    }
    return 1;
}

static int load_record(void *ctx, struct cu_record *record) {
    struct read_result result = {.record = record};
    int err = settings_load_subtree_direct(CU_SETTINGS_KEY, read_record, &result);
    return err ? err : result.status;
}

static int save_record(void *ctx, const struct cu_record *record) {
    return settings_save_one(CU_SETTINGS_KEY, record, sizeof(*record));
}

/* Run once after ZMK's initial settings_load. All further firmware boots load
 * the existing record; only a new explicit command writes/clears it.
 */
static int unlock_settings_set(const char *name, size_t len, settings_read_cb read_cb, void *cb_arg) {
    return name && strcmp(name, "record") == 0 ? 0 : -ENOENT;
}

static int unlock_settings_commit(void) {
    /* ZMK's main stack is only 1 KiB and settings_load holds the settings
     * mutex. Hand off nested reads/writes to a dedicated stack after loading.
     * Later reloads must not change the credential during USB transmission. */
    static bool initialized;
    if (!initialized) {
        initialized = true;
        k_sem_give(&storage_requested);
    }
    return 0;
}

static void storage_thread(void *a, void *b, void *c) {
    k_sem_take(&storage_requested, K_FOREVER);
    struct cu_command command;
    const volatile uint8_t *input = (const volatile uint8_t *)provision;
    for (size_t i = 0; i < sizeof(command); ++i) {
        ((uint8_t *)&command)[i] = input[i];
    }
    int err = cu_storage_boot(&active, &command, load_record, save_record, NULL);
    memset(&command, 0, sizeof(command));
    if (err) {
        LOG_ERR("Unlock storage unavailable (%d)", err);
        return;
    }
    atomic_set(&ready, active.operation == CU_COMMAND_SET && cu_record_valid(&active));
    LOG_INF("Persistent unlock credential %s", atomic_get(&ready) ? "ready" : "absent");
}

K_THREAD_DEFINE(cosmos_unlock_storage_thread, 4096, storage_thread,
                NULL, NULL, NULL, 10, 0, 0);

/* No read/export API: neither Studio nor generic settings exports expose it. */
SETTINGS_STATIC_HANDLER_DEFINE(cosmos_unlock, "cosmos_unlock", NULL, unlock_settings_set,
                               unlock_settings_commit, NULL);

bool cosmos_unlock_credential_ready(void) { return atomic_get(&ready); }

uint8_t cosmos_unlock_digit(unsigned int index) {
    return atomic_get(&ready) && index < CU_PASSWORD_LEN ? active.password[index] : 0;
}

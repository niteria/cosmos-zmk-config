#include <assert.h>
#include "cosmos_unlock_storage.h"

struct fake_nvs {
    struct cu_record stored;
    bool present;
    unsigned int writes;
    int load_error;
    int save_error;
    bool bad_readback;
    bool drop_write;
};

static int load(void *ctx, struct cu_record *record) {
    struct fake_nvs *nvs = ctx;
    if (nvs->load_error) {
        return nvs->load_error;
    }
    if (!nvs->present) {
        return 0;
    }
    *record = nvs->stored;
    if (nvs->bad_readback && nvs->writes) {
        record->crc ^= 1;
    }
    return 1;
}

static int save(void *ctx, const struct cu_record *record) {
    struct fake_nvs *nvs = ctx;
    if (nvs->save_error) {
        return nvs->save_error;
    }
    ++nvs->writes;
    if (!nvs->drop_write) {
        nvs->stored = *record;
        nvs->present = true;
    }
    return 0;
}

static void checksum(struct cu_command *command) {
    command->crc = cu_crc32(&command->version, 72);
}

static struct cu_command command(uint32_t operation, uint8_t nonce, uint8_t digit) {
    struct cu_command result = {.version = 2, .operation = operation};
    memset(result.nonce, nonce, sizeof(result.nonce));
    if (operation == CU_COMMAND_SET) {
        memset(result.password, digit, sizeof(result.password));
    }
    checksum(&result);
    return result;
}

int main(void) {
    assert(cu_crc32("123456789", 9) == 0xcbf43926);
    struct cu_record active;
    struct fake_nvs nvs = {0};
    struct cu_command public = {.version = 2};
    struct cu_command set = command(CU_COMMAND_SET, 1, '3');
    struct cu_command clear = command(CU_COMMAND_CLEAR, 2, 0);

    /* New public firmware on an unprovisioned keyboard does not install a key. */
    assert(cu_storage_boot(&active, &public, load, save, &nvs) == 0);
    assert(active.operation == CU_COMMAND_NONE && nvs.writes == 0);

    /* Provision once, power-cycle the SAME image, then install public images. */
    assert(cu_storage_boot(&active, &set, load, save, &nvs) == 0);
    assert(active.operation == CU_COMMAND_SET && active.password[0] == '3');
    assert(nvs.writes == 1 && cu_record_valid(&nvs.stored));
    assert(cu_storage_boot(&active, &set, load, save, &nvs) == 0);
    assert(nvs.writes == 1);
    for (int boot = 0; boot < 5; ++boot) {
        assert(cu_storage_boot(&active, &public, load, save, &nvs) == 0);
        assert(active.operation == CU_COMMAND_SET && active.password[47] == '3');
    }
    assert(nvs.writes == 1);

    /* Clearing persists an empty record and receipt, not a replayable deletion. */
    assert(cu_storage_boot(&active, &clear, load, save, &nvs) == 0);
    assert(active.operation == CU_COMMAND_CLEAR && cu_zero(active.password, 48));
    assert(nvs.writes == 2);
    assert(cu_storage_boot(&active, &clear, load, save, &nvs) == 0);
    assert(cu_storage_boot(&active, &public, load, save, &nvs) == 0);
    assert(active.operation == CU_COMMAND_CLEAR && nvs.writes == 2);

    /* A fresh explicit provisioning command can restore or rotate a credential. */
    set = command(CU_COMMAND_SET, 3, '7');
    assert(cu_storage_boot(&active, &set, load, save, &nvs) == 0);
    assert(active.password[0] == '7' && nvs.writes == 3);
    struct cu_command collision = command(CU_COMMAND_SET, 3, '8');
    assert(cu_storage_boot(&active, &collision, load, save, &nvs) == -EINVAL);
    assert(cu_zero((uint8_t *)&active, sizeof(active)) && nvs.writes == 3);

    /* Failed writes/readback never expose an unpersisted credential. */
    struct cu_command replacement = command(CU_COMMAND_SET, 4, '9');
    nvs.save_error = -ENOSPC;
    assert(cu_storage_boot(&active, &replacement, load, save, &nvs) == -ENOSPC);
    assert(cu_zero((uint8_t *)&active, sizeof(active)));
    nvs.save_error = 0;
    assert(cu_storage_boot(&active, &public, load, save, &nvs) == 0);
    assert(active.password[0] == '7');
    nvs.bad_readback = true;
    assert(cu_storage_boot(&active, &replacement, load, save, &nvs) == -EIO);
    assert(cu_zero((uint8_t *)&active, sizeof(active)));
    nvs.bad_readback = false;
    /* A reset after a completed write but before enabling output is recoverable. */
    unsigned int writes = nvs.writes;
    assert(cu_storage_boot(&active, &replacement, load, save, &nvs) == 0);
    assert(active.password[0] == '9' && nvs.writes == writes);
    nvs.load_error = -EIO;
    assert(cu_storage_boot(&active, &public, load, save, &nvs) == -EIO);
    assert(cu_zero((uint8_t *)&active, sizeof(active)));
    nvs.load_error = 0;

    /* Corrupt storage is disabled on public boot and repairable explicitly. */
    nvs.stored.crc ^= 1;
    assert(cu_storage_boot(&active, &public, load, save, &nvs) == -EINVAL);
    assert(cu_storage_boot(&active, &replacement, load, save, &nvs) == 0);

    struct cu_command invalid = replacement;
    invalid.nonce[0] ^= 1; /* Bad command checksum. */
    assert(cu_storage_boot(&active, &invalid, load, save, &nvs) == -EINVAL);
    invalid = command(CU_COMMAND_SET, 0, '1'); /* Missing transaction ID. */
    assert(cu_storage_boot(&active, &invalid, load, save, &nvs) == -EINVAL);
    invalid = command(CU_COMMAND_SET, 5, 'a');
    assert(cu_storage_boot(&active, &invalid, load, save, &nvs) == -EINVAL);
    invalid = clear;
    invalid.password[0] = '1';
    checksum(&invalid);
    assert(cu_storage_boot(&active, &invalid, load, save, &nvs) == -EINVAL);
    invalid = public;
    invalid.padding[0] = 1;
    assert(cu_storage_boot(&active, &invalid, load, save, &nvs) == -EINVAL);

    nvs = (struct fake_nvs){.drop_write = true};
    assert(cu_storage_boot(&active, &set, load, save, &nvs) == -EIO);
    assert(cu_zero((uint8_t *)&active, sizeof(active)));
    return 0;
}

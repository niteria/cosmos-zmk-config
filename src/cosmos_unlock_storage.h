/* Persistent credential format and boot transaction, shared with host tests.
 * Mailbox v2 is a one-time SET/CLEAR command, never a runtime password source.
 */
#pragma once
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define CU_PASSWORD_LEN 48
#define CU_COMMAND_NONE 0
#define CU_COMMAND_SET 1
#define CU_COMMAND_CLEAR 2
#define CU_SETTINGS_KEY "cosmos_unlock/record"

struct cu_command {
    uint8_t magic[16];
    uint32_t version;
    uint32_t operation;
    uint8_t nonce[16];
    uint8_t password[CU_PASSWORD_LEN];
    uint32_t crc;
    uint8_t padding[164];
};

/* Credential and consumed-command receipt are written as ONE NVS value. */
struct cu_record {
    uint32_t version;
    uint32_t operation;
    uint8_t nonce[16];
    uint8_t password[CU_PASSWORD_LEN];
    uint32_t crc;
};

_Static_assert(sizeof(struct cu_command) == 256, "Provisioning mailbox layout changed");
_Static_assert(offsetof(struct cu_command, crc) == 88, "Provisioning CRC offset changed");
_Static_assert(sizeof(struct cu_record) == 76, "Persistent record layout changed");
_Static_assert(offsetof(struct cu_record, crc) == 72, "Persistent CRC offset changed");

static inline bool cu_zero(const uint8_t *data, size_t len) {
    uint8_t any = 0;
    for (size_t i = 0; i < len; ++i) {
        any |= data[i];
    }
    return any == 0;
}

static inline uint32_t cu_crc32(const void *data, size_t len) {
    const uint8_t *bytes = data;
    uint32_t crc = UINT32_MAX;
    for (size_t i = 0; i < len; ++i) {
        crc ^= bytes[i];
        for (int bit = 0; bit < 8; ++bit) {
            crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
        }
    }
    return ~crc;
}

static inline bool cu_payload_valid(uint32_t operation, const uint8_t *password) {
    if (operation == CU_COMMAND_CLEAR) {
        return cu_zero(password, CU_PASSWORD_LEN);
    }
    if (operation != CU_COMMAND_SET) {
        return false;
    }
    for (size_t i = 0; i < CU_PASSWORD_LEN; ++i) {
        if (password[i] < '0' || password[i] > '9') {
            return false;
        }
    }
    return true;
}

static inline bool cu_record_valid(const struct cu_record *record) {
    return record->version == 1 && !cu_zero(record->nonce, sizeof(record->nonce)) &&
           cu_payload_valid(record->operation, record->password) &&
           record->crc == cu_crc32(record, offsetof(struct cu_record, crc));
}

static inline bool cu_command_empty(const struct cu_command *command) {
    return command->version == 2 && command->operation == CU_COMMAND_NONE &&
           cu_zero(command->nonce, sizeof(command->nonce)) &&
           cu_zero(command->password, sizeof(command->password)) && command->crc == 0 &&
           cu_zero(command->padding, sizeof(command->padding));
}

static inline bool cu_command_valid(const struct cu_command *command) {
    return command->version == 2 && !cu_zero(command->nonce, sizeof(command->nonce)) &&
           cu_payload_valid(command->operation, command->password) &&
           cu_zero(command->padding, sizeof(command->padding)) &&
           command->crc == cu_crc32(&command->version,
                                   offsetof(struct cu_command, crc) - offsetof(struct cu_command, version));
}

/* load returns 0 for absent, 1 for present, or a negative error.
 * save returns 0 only after the whole record has been stored.
 */
typedef int (*cu_load_record)(void *ctx, struct cu_record *record);
typedef int (*cu_save_record)(void *ctx, const struct cu_record *record);

static inline int cu_storage_boot(struct cu_record *active, const struct cu_command *command,
                                  cu_load_record load, cu_save_record save, void *ctx) {
    memset(active, 0, sizeof(*active));
    struct cu_record stored = {0};
    int present = load(ctx, &stored);
    if (present < 0) {
        return present;
    }
    if (present > 1) {
        return -EINVAL;
    }
    bool valid = present == 1 && cu_record_valid(&stored);

    if (cu_command_empty(command)) {
        if (present && !valid) {
            return -EINVAL;
        }
        if (valid) {
            *active = stored;
        }
        return 0; /* Ordinary public updates do not write settings. */
    }
    if (!cu_command_valid(command)) {
        return -EINVAL;
    }

    struct cu_record desired = {
        .version = 1,
        .operation = command->operation,
    };
    memcpy(desired.nonce, command->nonce, sizeof(desired.nonce));
    memcpy(desired.password, command->password, sizeof(desired.password));
    desired.crc = cu_crc32(&desired, offsetof(struct cu_record, crc));
    if (valid && memcmp(stored.nonce, desired.nonce, sizeof(desired.nonce)) == 0) {
        if (memcmp(&stored, &desired, sizeof(stored)) != 0) {
            return -EINVAL; /* Reject reuse of a command ID for different contents. */
        }
        *active = stored;
        return 0; /* The same provisioning image must not rewrite on every boot. */
    }

    int err = save(ctx, &desired);
    if (err) {
        return err;
    }
    memset(&stored, 0, sizeof(stored));
    present = load(ctx, &stored);
    if (present != 1 || !cu_record_valid(&stored) ||
        memcmp(&stored, &desired, sizeof(stored)) != 0) {
        return -EIO;
    }
    *active = stored; /* Expose only a persisted and read-back-verified credential. */
    return 0;
}

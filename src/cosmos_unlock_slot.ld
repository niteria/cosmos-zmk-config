SECTION_PROLOGUE(.cosmos_unlock_slot,,)
{
    . = ALIGN(256);
    KEEP(*(.cosmos_unlock_slot))
} GROUP_LINK_IN(ROMABLE_REGION)

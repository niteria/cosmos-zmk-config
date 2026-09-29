SECTION_PROLOGUE(.cosmos_unlock_provision,,)
{
    . = ALIGN(256);
    KEEP(*(.cosmos_unlock_provision))
} GROUP_LINK_IN(ROMABLE_REGION)

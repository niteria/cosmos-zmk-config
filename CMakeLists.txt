if(CONFIG_PMW3610)
  include(cmake/pmw3610.cmake)
endif()

if(CONFIG_COSMOS_UNLOCK)
  # Added during Zephyr module discovery, before ZMK's application sources.
  # The physical-key observer must precede hold-taps and combos. It also
  # verifies subscription order at boot and fails closed if that changes.
  target_sources(app PRIVATE src/cosmos_unlock.c src/cosmos_unlock_store.c)
  zephyr_linker_sources(SECTIONS src/cosmos_unlock_provision.ld)
  zephyr_link_libraries(
    -Wl,--wrap=usb_hid_register_device
    -Wl,--wrap=hid_int_ep_write
  )
endif()

if(CONFIG_COSMOS_SCROLL_LATCH)
  # Follow the private-unlock observer, but precede ZMK hold-taps and combos.
  target_sources(app PRIVATE src/cosmos_scroll.c)
endif()

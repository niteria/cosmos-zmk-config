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

if(CONFIG_ZMK_BLE AND CONFIG_ZMK_BLE_PASSKEY_ENTRY AND
   (NOT CONFIG_ZMK_SPLIT OR CONFIG_ZMK_SPLIT_ROLE_CENTRAL))
  # ZMK v0.3 adds ble.c after hid_listener.c. Its passkey listener must run
  # before ordinary keycode consumers, otherwise pairing digits reach USB.
  # Defer until ZMK has added its sources; only ble.c's link order changes.
  function(cosmos_order_ble_passkey)
    get_target_property(cosmos_app_sources app SOURCES)
    set(cosmos_ble_sources "${cosmos_app_sources}")
    list(FILTER cosmos_ble_sources INCLUDE REGEX "(^|/)src/ble\\.c$")
    list(LENGTH cosmos_ble_sources cosmos_ble_source_count)
    if(NOT cosmos_ble_source_count EQUAL 1)
      message(FATAL_ERROR "Unexpected ZMK BLE sources; review passkey listener ordering")
    endif()
    list(REMOVE_ITEM cosmos_app_sources ${cosmos_ble_sources})
    list(PREPEND cosmos_app_sources ${cosmos_ble_sources})
    set_property(TARGET app PROPERTY SOURCES "${cosmos_app_sources}")
    message(STATUS "Cosmos: BLE passkey entry precedes ordinary keycode handling")
  endfunction()

  cmake_language(DEFER DIRECTORY "${APPLICATION_SOURCE_DIR}" CALL cosmos_order_ble_passkey)
endif()

if(CONFIG_ZMK_USB AND CONFIG_ZMK_BLE AND
   (NOT CONFIG_ZMK_SPLIT OR CONFIG_ZMK_SPLIT_ROLE_CENTRAL))
  include(cmake/endpoints.cmake)
endif()

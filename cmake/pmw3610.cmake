# Patch a build-local copy so both Nix and ordinary west builds use the same
# driver, without modifying the fetched module or GitHub Actions' module cache.
# zephyr/module.yml orders this module after pmw3610.
get_property(pmw3610_targets DIRECTORY "${ZEPHYR_PMW3610_CMAKE_DIR}"
             PROPERTY BUILDSYSTEM_TARGETS)
list(LENGTH pmw3610_targets pmw3610_target_count)
if(NOT pmw3610_target_count EQUAL 1)
  message(FATAL_ERROR "Unexpected PMW3610 library layout; review the local driver patch")
endif()
list(GET pmw3610_targets 0 pmw3610_target)
get_target_property(pmw3610_sources ${pmw3610_target} SOURCES)
if(NOT pmw3610_sources STREQUAL "src/pmw3610.c" AND
   NOT pmw3610_sources STREQUAL "${ZEPHYR_PMW3610_MODULE_DIR}/src/pmw3610.c")
  message(FATAL_ERROR "Unexpected PMW3610 sources: ${pmw3610_sources}")
endif()

set(pmw3610_patch "${CMAKE_CURRENT_LIST_DIR}/../patches/pmw3610-usb-awake.patch")
set(pmw3610_patched_dir "${CMAKE_CURRENT_BINARY_DIR}/pmw3610-usb")
file(MAKE_DIRECTORY "${pmw3610_patched_dir}/src")
configure_file("${ZEPHYR_PMW3610_MODULE_DIR}/src/pmw3610.c"
               "${pmw3610_patched_dir}/src/pmw3610.c" COPYONLY)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${pmw3610_patch}")
find_program(PATCH_EXECUTABLE patch REQUIRED)
execute_process(
  COMMAND "${PATCH_EXECUTABLE}" --batch --fuzz=0 -p1 --input "${pmw3610_patch}"
  WORKING_DIRECTORY "${pmw3610_patched_dir}"
  RESULT_VARIABLE pmw3610_patch_result
  OUTPUT_VARIABLE pmw3610_patch_output
  ERROR_VARIABLE pmw3610_patch_error
)
if(NOT pmw3610_patch_result EQUAL 0)
  message(FATAL_ERROR "PMW3610 patch failed: ${pmw3610_patch_output}${pmw3610_patch_error}")
endif()

set_property(TARGET ${pmw3610_target} PROPERTY SOURCES
             "${pmw3610_patched_dir}/src/pmw3610.c")
target_include_directories(${pmw3610_target} PRIVATE "${ZEPHYR_PMW3610_MODULE_DIR}/src")
message(STATUS "PMW3610: applied USB-powered forced-awake override")

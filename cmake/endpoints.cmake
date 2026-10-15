# Keep output preference in RAM, while Bluetooth, Studio and unlock settings
# continue using their normal storage. Patch a build-local copy for Nix/west.
function(cosmos_session_only_output)
  get_target_property(cosmos_app_sources app SOURCES)
  set(cosmos_endpoint_sources "${cosmos_app_sources}")
  list(FILTER cosmos_endpoint_sources INCLUDE REGEX "(^|/)src/endpoints\\.c$")
  list(LENGTH cosmos_endpoint_sources cosmos_endpoint_source_count)
  if(NOT cosmos_endpoint_source_count EQUAL 1)
    message(FATAL_ERROR "Unexpected ZMK endpoint sources; review the session-only output patch")
  endif()

  set(cosmos_endpoint_patch "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../patches/endpoints-session-only.patch")
  set(cosmos_endpoint_dir "${CMAKE_CURRENT_BINARY_DIR}/cosmos-session-output")
  file(MAKE_DIRECTORY "${cosmos_endpoint_dir}/src")
  configure_file("${APPLICATION_SOURCE_DIR}/src/endpoints.c"
                 "${cosmos_endpoint_dir}/src/endpoints.c" COPYONLY)
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${cosmos_endpoint_patch}")
  find_program(PATCH_EXECUTABLE patch REQUIRED)
  execute_process(
    COMMAND "${PATCH_EXECUTABLE}" --batch --fuzz=0 -p1 --input "${cosmos_endpoint_patch}"
    WORKING_DIRECTORY "${cosmos_endpoint_dir}"
    RESULT_VARIABLE cosmos_endpoint_patch_result
    OUTPUT_VARIABLE cosmos_endpoint_patch_output
    ERROR_VARIABLE cosmos_endpoint_patch_error
  )
  if(NOT cosmos_endpoint_patch_result EQUAL 0)
    message(FATAL_ERROR "Endpoint patch failed: ${cosmos_endpoint_patch_output}${cosmos_endpoint_patch_error}")
  endif()

  list(FIND cosmos_app_sources "${cosmos_endpoint_sources}" cosmos_endpoint_index)
  list(REMOVE_AT cosmos_app_sources ${cosmos_endpoint_index})
  list(INSERT cosmos_app_sources ${cosmos_endpoint_index} "${cosmos_endpoint_dir}/src/endpoints.c")
  set_property(TARGET app PROPERTY SOURCES "${cosmos_app_sources}")
  message(STATUS "Cosmos: output preference is session-only, with USB preferred at startup")
endfunction()

cmake_language(DEFER DIRECTORY "${APPLICATION_SOURCE_DIR}" CALL cosmos_session_only_output)

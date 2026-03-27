# Dead Ends

## 2026-03-28: Trackball module not included in nix build

**Problem**: Building with trackball support fails with:
```
undefined reference to `__device_dts_ord_142'
```

**Cause**: The `zmk-driver-pmw3360` external west module from `george-norton` is not being included in the nix build.

**Solution**: 
1. Added pmw3360 driver as a git submodule: `modules/pmw3360`
2. Updated `config/west.yml` to reference the module with both remote and local path
3. Updated `flake.nix` with new zephyrDepsHash

**Status**: RESOLVED - Build works WITH trackball support

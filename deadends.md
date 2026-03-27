# Dead Ends

## 2026-03-28: Trackball module not included in nix build

**Problem**: Building with trackball support fails with:
```
undefined reference to `__device_dts_ord_142'
```

**Cause**: The `zmk-driver-pmw3360` external west module from `george-norton` is not being included in the nix build. The `cosmos_right.overlay` references the `pixart,pmw3360` device which doesn't exist without the module.

**Solution**: Disabled trackball support to get a working build.
- Removed `zmk-driver-pmw3360` from `config/west.yml`
- Removed pointing/trackball configs from `cosmos.conf`
- Simplified `cosmos_right.overlay` to remove trackball device

**Status**: RESOLVED - Build works without trackball

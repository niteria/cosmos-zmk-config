{ pkgs, firmware, publicFlasher }:
let
  tools = with pkgs; [
    util-linux
    util-linux.mount
  ];
in
pkgs.writeShellApplication {
  name = "cosmos-flash";
  meta.platforms = pkgs.lib.platforms.linux;
  runtimeInputs = tools;
  text = ''
    exec ${pkgs.python3}/bin/python3 -I ${../scripts/flash.py} \
      --firmware-dir ${firmware} \
      --tool-path ${pkgs.lib.makeBinPath tools} \
      --public-flasher ${publicFlasher}/bin/zmk-uf2-flash "$@"
  '';
}

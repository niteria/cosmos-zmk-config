{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/release-25.11";

    zmk-nix = {
      url = "github:lilyinstarlight/zmk-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      zmk-nix,
    }:
    let
      forAllSystems = nixpkgs.lib.genAttrs (nixpkgs.lib.attrNames zmk-nix.packages);
    in
    {
      packages = forAllSystems (system: rec {
        default = firmware;

        firmware = zmk-nix.legacyPackages.${system}.buildSplitKeyboard {
          name = "firmware";

          src = nixpkgs.lib.sourceFilesBySuffices self [
            ".board"
            ".c"
            ".h"
            ".ld"
            "CMakeLists.txt"
            "Kconfig"
            "verify_firmware.py"
            ".cmake"
            ".conf"
            ".defconfig"
            ".dts"
            ".dtsi"
            ".json"
            ".keymap"
            ".overlay"
            ".patch"
            ".shield"
            ".yml"
            ".yaml"
            "_defconfig"
          ];

          board = "nice_nano_v2";
          shield = "cosmos_%PART%";
          centralPart = "right";
          enableZmkStudio = true;

          zephyrDepsHash = "sha256-d59ARpUFZcvbfZcRuX0BsDfGY9cLOXNyJGQkzaz7sME=";

          # Retain each half's resolved pin/configuration data for wiring audits.
          postInstall = ''
            mkdir -p "$out/diagnostics"
            cp zephyr/.config "$out/diagnostics/zephyr.config"
            cp zephyr/zephyr.dts "$out/diagnostics/zephyr.dts"
            python3 ${./tests/verify_firmware.py} zephyr/zmk.elf
            cp zephyr/zmk.elf "$out/diagnostics/zmk.elf"
          '';

          meta = {
            description = "ZMK firmware";
            license = nixpkgs.lib.licenses.mit;
            platforms = nixpkgs.lib.platforms.all;
          };
        };

        flash = import ./nix/flash.nix {
          pkgs = nixpkgs.legacyPackages.${system};
          inherit firmware;
          publicFlasher = zmk-nix.packages.${system}.flash.override { inherit firmware; };
        };
        update = zmk-nix.packages.${system}.update;
      });

      apps = forAllSystems (system: {
        print-cheatsheet = {
          type = "app";
          program = "${
            nixpkgs.legacyPackages.${system}.writeShellApplication {
              name = "print-cheatsheet";
              runtimeInputs = [
                nixpkgs.legacyPackages.${system}.git
                (nixpkgs.legacyPackages.${system}.python3.withPackages (p: [
                  p.pyyaml
                  p.reportlab
                ]))
              ];
              text = ''
                REPO_ROOT="$(git rev-parse --show-toplevel)"
                exec python3 "$REPO_ROOT/scripts/print_cheatsheet.py" \
                  --font-dir "${nixpkgs.legacyPackages.${system}.dejavu_fonts}/share/fonts/truetype" "$@"
              '';
            }
          }/bin/print-cheatsheet";
        };
        update-assets = {
          type = "app";
          program = "${
            nixpkgs.legacyPackages.${system}.writeShellApplication {
              name = "update-assets";
              runtimeInputs = [
                nixpkgs.legacyPackages.${system}.keymap-drawer
                (nixpkgs.legacyPackages.${system}.python3.withPackages (p: [ p.pyyaml ]))
              ];
              text = ''
                                                                REPO_ROOT="$(git rev-parse --show-toplevel)"

                                                                if [ -z "$REPO_ROOT" ]; then
                                                                    echo "Error: could not determine repository root. Are you in a git repository?" >&2
                                                                    exit 1
                                                                fi

                                echo "Parsing keymap from boards/shields/cosmos/cosmos.keymap..."
                                keymap parse -c 12 -z "''${REPO_ROOT}/boards/shields/cosmos/cosmos.keymap" -o "''${REPO_ROOT}/assets/cosmos_keymap.yaml"

                                # Use the Corne 6-column physical layout so the SVG matches the actual 42-key matrix.
                                python3 -c "
                import yaml

                yaml_path = '$REPO_ROOT/assets/cosmos_keymap.yaml'

                with open(yaml_path, 'r') as f:
                    data = yaml.safe_load(f)

                data['layout'] = {'zmk_keyboard': 'corne', 'layout_name': 'foostan_corne_6col_layout'}

                for combo in data.get('combos', []):
                    if combo['k'] == '&cosmos_unlock':
                        combo.update(k={'t': 'Unlock', 'h': 'Fn + 2s'}, w=70, h=40)

                with open(yaml_path, 'w') as f:
                    yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
                "

                                echo "Generating SVG from parsed keymap..."
                                keymap draw "''${REPO_ROOT}/assets/cosmos_keymap.yaml" -o "''${REPO_ROOT}/assets/cosmos_keymap.svg"

                                for reference in cosmos_hyprland cosmos_hyprland_proposal; do
                                    echo "Generating ''${reference}.svg..."
                                    keymap draw "''${REPO_ROOT}/assets/''${reference}.yaml" -o "''${REPO_ROOT}/assets/''${reference}.svg"
                                done

                                                                echo "Successfully updated keymap and Hyprland reference SVGs!"
              '';
            }
          }/bin/update-assets";
        };
      });

      devShells = forAllSystems (system: {
        default = zmk-nix.devShells.${system}.default;
      });

      checks = forAllSystems (system: {
        flash = nixpkgs.legacyPackages.${system}.runCommand "cosmos-flash-tests" { } ''
          ${nixpkgs.legacyPackages.${system}.python3}/bin/python3 -B ${./tests/test_flash.py} ${./scripts/flash.py}
          touch $out
        '';
        unlock-storage = nixpkgs.legacyPackages.${system}.runCommandCC "cosmos-unlock-storage-tests" { } ''
          $CC -std=c11 -Wall -Wextra -Werror ${./tests/unlock_storage.c} -I${./src} -o storage-test
          ./storage-test
          touch $out
        '';
        unlock-guard = nixpkgs.legacyPackages.${system}.runCommandCC "cosmos-unlock-guard-tests" { } ''
          $CC -std=c11 -Wall -Wextra -Werror ${./tests/unlock_guard.c} -I${./src} -o guard-test
          ./guard-test
          touch $out
        '';
      });
    };
}

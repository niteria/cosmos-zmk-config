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
            ".cmake"
            ".conf"
            ".defconfig"
            ".dts"
            ".dtsi"
            ".json"
            ".keymap"
            ".overlay"
            ".shield"
            ".yml"
            "_defconfig"
          ];

          board = "nice_nano_v2";
          shield = "cosmos_%PART%";
          centralPart = "right";
          enableZmkStudio = true;

          zephyrDepsHash = "sha256-ZZ8y4DkCqklcUDXezjdFbAcJedxCvqAS6fd8oFvDGTE=";

          meta = {
            description = "ZMK firmware";
            license = nixpkgs.lib.licenses.mit;
            platforms = nixpkgs.lib.platforms.all;
          };
        };

        flash = zmk-nix.packages.${system}.flash.override { inherit firmware; };
        update = zmk-nix.packages.${system}.update;
      });

      apps = forAllSystems (system: {
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

                with open(yaml_path, 'w') as f:
                    yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
                "

                                echo "Generating SVG from parsed keymap..."
                                keymap draw "''${REPO_ROOT}/assets/cosmos_keymap.yaml" -o "''${REPO_ROOT}/assets/cosmos_keymap.svg"

                                                                echo "Successfully updated assets/cosmos_keymap.svg!"
              '';
            }
          }/bin/update-assets";
        };
      });

      devShells = forAllSystems (system: {
        default = zmk-nix.devShells.${system}.default;
      });
    };
}

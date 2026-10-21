# Local binary-preserving repack of verified original Armada package files.
%global debug_package %{nil}
%global _build_id_links none
%global __os_install_post %{nil}

Name:           inputplumber
Version:        0.81.0
Release:        3.fc44.caihong
Summary:        Restore the official Armada inputplumber payload
License:        GPL-3.0-or-later
URL:            https://github.com/armada-os/armada
Source0:        inputplumber-armada-original.tar.gz
ExclusiveArch:  aarch64
Vendor:         Caihong local restore
Packager:       Caihong local restore
Requires:       dbus
Requires:       systemd

%description
Restores unmodified original Armada package files after a generic repository
upgrade. The original version is retained; this package is a deliberate downgrade.
Local files under /etc are not included. Service transitions are owned by the
operator; this package contains no start/restart scriptlets.

%prep
%setup -q -c -T
%{__tar} -xzf %{SOURCE0}

%build
# No compilation, stripping, debug rewriting, or build-id regeneration.

%install
mkdir -p %{buildroot}
cp -a usr %{buildroot}/

%files
%defattr(-,root,root,-)
/usr/bin/inputplumber
/usr/lib/.build-id/52/451e7c0e2356f5728a9d46bafd400defd771a4
/usr/lib/systemd/system/inputplumber-suspend.service
/usr/lib/systemd/system/inputplumber.service
/usr/lib/udev/hwdb.d/59-inputplumber.hwdb
/usr/lib/udev/hwdb.d/60-inputplumber-autostart.hwdb
/usr/lib/udev/rules.d/50-8bitdo-u2-controller.rules
/usr/lib/udev/rules.d/60-inputplumber-uaccess.rules
/usr/lib/udev/rules.d/90-inputplumber-autostart.rules
/usr/lib/udev/rules.d/99-inputplumber-device-setup.rules
/usr/share/dbus-1/system.d/org.shadowblip.InputPlumber.conf
%dir /usr/share/doc/inputplumber
%doc /usr/share/doc/inputplumber/README.md
%dir /usr/share/inputplumber
%dir /usr/share/inputplumber/capability_maps
/usr/share/inputplumber/capability_maps/ally_type1.yaml
/usr/share/inputplumber/capability_maps/ally_type2.yaml
/usr/share/inputplumber/capability_maps/anbernic_type1.yaml
/usr/share/inputplumber/capability_maps/ayaneo_type1.yaml
/usr/share/inputplumber/capability_maps/ayaneo_type10.yaml
/usr/share/inputplumber/capability_maps/ayaneo_type11.yaml
/usr/share/inputplumber/capability_maps/ayaneo_type2.yaml
/usr/share/inputplumber/capability_maps/ayaneo_type3.yaml
/usr/share/inputplumber/capability_maps/ayaneo_type4.yaml
/usr/share/inputplumber/capability_maps/ayaneo_type5.yaml
/usr/share/inputplumber/capability_maps/ayaneo_type6.yaml
/usr/share/inputplumber/capability_maps/ayaneo_type7.yaml
/usr/share/inputplumber/capability_maps/ayaneo_type8.yaml
/usr/share/inputplumber/capability_maps/ayaneo_type9.yaml
/usr/share/inputplumber/capability_maps/ayn_type1.yaml
/usr/share/inputplumber/capability_maps/ayn_type2.yaml
/usr/share/inputplumber/capability_maps/ayn_type3.yaml
/usr/share/inputplumber/capability_maps/cec.yaml
/usr/share/inputplumber/capability_maps/dinput_generic.yaml
/usr/share/inputplumber/capability_maps/flow_type1.yaml
/usr/share/inputplumber/capability_maps/flydigi_vader_4_pro.yaml
/usr/share/inputplumber/capability_maps/gpd_menu.yaml
/usr/share/inputplumber/capability_maps/gpd_type1.yaml
/usr/share/inputplumber/capability_maps/gpd_type2.yaml
/usr/share/inputplumber/capability_maps/gpd_type3.yaml
/usr/share/inputplumber/capability_maps/gpd_type4.yaml
/usr/share/inputplumber/capability_maps/imu_generic.yaml
/usr/share/inputplumber/capability_maps/konkr_type1.yaml
/usr/share/inputplumber/capability_maps/konkr_type2.yaml
/usr/share/inputplumber/capability_maps/konkr_type3.yaml
/usr/share/inputplumber/capability_maps/logitech_dualaction.yaml
/usr/share/inputplumber/capability_maps/msiclaw_type1.yaml
/usr/share/inputplumber/capability_maps/msiclaw_type2.yaml
/usr/share/inputplumber/capability_maps/onexplayer_type1.yaml
/usr/share/inputplumber/capability_maps/onexplayer_type2.yaml
/usr/share/inputplumber/capability_maps/onexplayer_type3.yaml
/usr/share/inputplumber/capability_maps/onexplayer_type4.yaml
/usr/share/inputplumber/capability_maps/onexplayer_type5.yaml
/usr/share/inputplumber/capability_maps/onexplayer_type6.yaml
/usr/share/inputplumber/capability_maps/onexplayer_type7.yaml
/usr/share/inputplumber/capability_maps/onexplayer_type8.yaml
/usr/share/inputplumber/capability_maps/orangepi_type1.yaml
/usr/share/inputplumber/capability_maps/retroid_type1.yaml
/usr/share/inputplumber/capability_maps/retroid_type2.yaml
/usr/share/inputplumber/capability_maps/rsinput_type1.yaml
/usr/share/inputplumber/capability_maps/swap_west_north.yaml
/usr/share/inputplumber/capability_maps/zone_type1.yaml
%dir /usr/share/inputplumber/devices
/usr/share/inputplumber/devices/10-ignore_unsupported.yaml
/usr/share/inputplumber/devices/50-anbernic_win600.yaml
/usr/share/inputplumber/devices/50-aokzoe_a1.yaml
/usr/share/inputplumber/devices/50-ayaneo_2.yaml
/usr/share/inputplumber/devices/50-ayaneo_2021.yaml
/usr/share/inputplumber/devices/50-ayaneo_2s.yaml
/usr/share/inputplumber/devices/50-ayaneo_3.yaml
/usr/share/inputplumber/devices/50-ayaneo_air.yaml
/usr/share/inputplumber/devices/50-ayaneo_air_1s.yaml
/usr/share/inputplumber/devices/50-ayaneo_air_plus.yaml
/usr/share/inputplumber/devices/50-ayaneo_air_plus_mendo.yaml
/usr/share/inputplumber/devices/50-ayaneo_flip.yaml
/usr/share/inputplumber/devices/50-ayaneo_flip_1s.yaml
/usr/share/inputplumber/devices/50-ayaneo_kun.yaml
/usr/share/inputplumber/devices/50-ayaneo_next.yaml
/usr/share/inputplumber/devices/50-ayaneo_pocket_ds.yaml
/usr/share/inputplumber/devices/50-ayaneo_pocket_s2.yaml
/usr/share/inputplumber/devices/50-ayaneo_slide.yaml
/usr/share/inputplumber/devices/50-ayn_loki_max.yaml
/usr/share/inputplumber/devices/50-ayn_loki_mini_pro.yaml
/usr/share/inputplumber/devices/50-ayn_loki_zero.yaml
/usr/share/inputplumber/devices/50-ayn_odin2.yaml
/usr/share/inputplumber/devices/50-ayn_odin2_mini.yaml
/usr/share/inputplumber/devices/50-ayn_odin3.yaml
/usr/share/inputplumber/devices/50-ayn_thor.yaml
/usr/share/inputplumber/devices/50-ayn_thor_lite.yaml
/usr/share/inputplumber/devices/50-gpd_win3.yaml
/usr/share/inputplumber/devices/50-gpd_win4.yaml
/usr/share/inputplumber/devices/50-gpd_win5.yaml
/usr/share/inputplumber/devices/50-gpd_winmax2.yaml
/usr/share/inputplumber/devices/50-gpd_winmini.yaml
/usr/share/inputplumber/devices/50-konkr-fit.yaml
/usr/share/inputplumber/devices/50-konkr_pocket_fit.yaml
/usr/share/inputplumber/devices/50-konkr_pocket_fit_elite.yaml
/usr/share/inputplumber/devices/50-legion_go.yaml
/usr/share/inputplumber/devices/50-legion_go_2.yaml
/usr/share/inputplumber/devices/50-legion_go_s.yaml
/usr/share/inputplumber/devices/50-msi_claw7_a2vm.yaml
/usr/share/inputplumber/devices/50-msi_claw8_a2vm.yaml
/usr/share/inputplumber/devices/50-msi_claw8_ex_ai_cg3em.yaml
/usr/share/inputplumber/devices/50-msi_claw_a1m.yaml
/usr/share/inputplumber/devices/50-msi_claw_a8_bz2e.yaml
/usr/share/inputplumber/devices/50-onexplayer_2.yaml
/usr/share/inputplumber/devices/50-onexplayer_amd.yaml
/usr/share/inputplumber/devices/50-onexplayer_apex.yaml
/usr/share/inputplumber/devices/50-onexplayer_g1.yaml
/usr/share/inputplumber/devices/50-onexplayer_intel.yaml
/usr/share/inputplumber/devices/50-onexplayer_mini_a07.yaml
/usr/share/inputplumber/devices/50-onexplayer_mini_pro.yaml
/usr/share/inputplumber/devices/50-onexplayer_onexfly.yaml
/usr/share/inputplumber/devices/50-onexplayer_x1.yaml
/usr/share/inputplumber/devices/50-orangepi_neo.yaml
/usr/share/inputplumber/devices/50-retroid_pocket5.yaml
/usr/share/inputplumber/devices/50-retroid_pocket6.yaml
/usr/share/inputplumber/devices/50-retroid_pocket_flip2.yaml
/usr/share/inputplumber/devices/50-retroid_pocket_mini.yaml
/usr/share/inputplumber/devices/50-retroid_pocket_nova.yaml
/usr/share/inputplumber/devices/50-rog_ally.yaml
/usr/share/inputplumber/devices/50-rog_ally_x.yaml
/usr/share/inputplumber/devices/50-rog_flow_z13.yaml
/usr/share/inputplumber/devices/50-rog_xbox_ally.yaml
/usr/share/inputplumber/devices/50-steam_deck.yaml
/usr/share/inputplumber/devices/50-suiplay_0x1.yaml
/usr/share/inputplumber/devices/50-zotac-zone.yaml
/usr/share/inputplumber/devices/60-8bit_do_pro_2.yaml
/usr/share/inputplumber/devices/60-8bit_do_ultimate_2.yaml
/usr/share/inputplumber/devices/60-LogitechDualAction.yaml
/usr/share/inputplumber/devices/60-cec.yaml
/usr/share/inputplumber/devices/60-flydigi_vader_4_pro.yaml
/usr/share/inputplumber/devices/60-horipad_steam.yaml
/usr/share/inputplumber/devices/60-ps4_gamepad.yaml
/usr/share/inputplumber/devices/60-ps5_ds-edge_gamepad.yaml
/usr/share/inputplumber/devices/60-ps5_ds_gamepad.yaml
/usr/share/inputplumber/devices/60-switch_pro.yaml
/usr/share/inputplumber/devices/60-xbox_360_gamepad.yaml
/usr/share/inputplumber/devices/60-xbox_gamepad.yaml
/usr/share/inputplumber/devices/60-xbox_one_bt_gamepad.yaml
/usr/share/inputplumber/devices/60-xbox_one_elite_gamepad.yaml
/usr/share/inputplumber/devices/60-xbox_one_gamepad.yaml
/usr/share/inputplumber/devices/65-generic_gamepad.yaml
/usr/share/inputplumber/devices/69-ignore_generic.yaml
%dir /usr/share/inputplumber/profiles
/usr/share/inputplumber/profiles/debug.yaml
/usr/share/inputplumber/profiles/default.yaml
/usr/share/inputplumber/profiles/mouse_keyboard_wasd.yaml
/usr/share/inputplumber/profiles/test.yaml
%dir /usr/share/inputplumber/schema
/usr/share/inputplumber/schema/capability_map_v1.json
/usr/share/inputplumber/schema/capability_map_v2.json
/usr/share/inputplumber/schema/composite_device_v1.json
/usr/share/inputplumber/schema/device_profile_v1.json
%dir /usr/share/licenses/inputplumber
%license /usr/share/licenses/inputplumber/LICENSE
/usr/share/polkit-1/actions/org.shadowblip.InputPlumber.policy
/usr/share/polkit-1/rules.d/org.shadowblip.InputPlumber.rules

%changelog
* Wed Oct 21 2026 Caihong local restore - 0.81.0-3.fc44.caihong
- Restore the exact original Armada payload with a truthful original version.

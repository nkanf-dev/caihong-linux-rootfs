# Binary-preserving local repackage of the original official Armada OCI payload.
# Source/provenance is recorded alongside this spec. This is not an upstream RPM.
%global debug_package %{nil}
%global _build_id_links none
# Do not strip or rewrite prebuilt official binaries. Automatic ELF Requires stay enabled.
%global __os_install_post %{nil}

Name:           steamos-manager
Version:        26.4.1
Release:        3.fc44.caihong
Summary:        Restore the official Armada SteamOS Manager payload
License:        MIT
URL:            https://github.com/armada-os/armada
Source0:        steamos-manager-armada-26.4.1.tar.gz
ExclusiveArch:  aarch64
Vendor:         Caihong local restore
Packager:       Caihong local restore

# Original non-ELF runtime requirements. rpmbuild derives the ELF ABI requirements.
Requires:       dbus
Requires:       speech-dispatcher-libs
Requires:       systemd

%description
Restores the unmodified SteamOS Manager files from the original official Armada
stable OCI image. Its source patch is intended to pin NetworkManager to the
installed wpa_supplicant backend; the live u0 validation gate confirms behavior. This local repack has a higher release than the generic Terra package.
It owns only the original empty directories under /etc. It leaves local files
intact and does not start or restart services.

%prep
# Source0 contains the validated original package layout and two build-id links.
%setup -q -c -T
%{__tar} -xzf %{SOURCE0}

%build
# Official binaries are copied without recompiling or rewriting them.

%install
mkdir -p %{buildroot}
cp -a etc usr %{buildroot}/
# Own only the original package-scoped directories, never shared parents.
mkdir -p %{buildroot}/etc/steamos-manager/remotes.d \
    %{buildroot}/usr/share/steamos-manager/devices \
    %{buildroot}/usr/share/steamos-manager/remotes.d \
    %{buildroot}/usr/share/doc/steamos-manager \
    %{buildroot}/usr/share/licenses/steamos-manager

%files
%defattr(-,root,root,-)
%dir /etc/steamos-manager
%dir /etc/steamos-manager/remotes.d
%dir /usr/share/doc/steamos-manager
%dir /usr/share/licenses/steamos-manager
%dir /usr/share/steamos-manager
%dir /usr/share/steamos-manager/devices
%dir /usr/share/steamos-manager/remotes.d
/usr/bin/steamosctl
/usr/lib/.build-id/4e/5660b83fc03aff0603ec000b8c0572fa99a5f5
/usr/lib/.build-id/f3/14ee3b21aa64fa22813216b26bd26ec0d84ef5
/usr/lib/steamos-manager
/usr/lib/systemd/system/steamos-manager.service
/usr/lib/systemd/user/steamos-manager-configure-cecd.service
/usr/lib/systemd/user/steamos-manager-session-cleanup.service
/usr/lib/systemd/user/steamos-manager.service
/usr/share/dbus-1/interfaces/com.steampowered.SteamOSManager1.xml
/usr/share/dbus-1/services/com.steampowered.SteamOSManager1.service
/usr/share/dbus-1/system-services/com.steampowered.SteamOSManager1.service
/usr/share/dbus-1/system.d/com.steampowered.SteamOSManager1.conf
%doc /usr/share/doc/steamos-manager/README.md
%license /usr/share/licenses/steamos-manager/LICENSE
/usr/share/steamos-manager/devices/sm8250.toml
/usr/share/steamos-manager/devices/sm8550.toml
/usr/share/steamos-manager/devices/sm8650.toml
/usr/share/steamos-manager/devices/sm8750.toml
/usr/share/steamos-manager/platform.toml

%changelog
* Wed Oct 21 2026 Caihong local restore - 26.4.1-3.fc44.caihong
- Repackage original Armada payload to restore its supported Wi-Fi backend pin.

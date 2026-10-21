# Local binary-preserving repack of verified original Armada package files.
%global debug_package %{nil}
%global _build_id_links none
%global __os_install_post %{nil}

Name:           gamescope-session
Version:        0~20260920git.0232e0c
Release:        3.fc44.caihong
Summary:        Restore the official Armada gamescope-session payload
License:        MIT
URL:            https://github.com/armada-os/armada
Source0:        gamescope-session-armada-original.tar.gz
BuildArch:      noarch
Vendor:         Caihong local restore
Packager:       Caihong local restore
Requires:       gamescope
Requires:       /usr/bin/bash

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
/usr/bin/export-gpu
/usr/bin/gamescope-session-plus
/usr/lib/systemd/user/gamescope-session-plus@.service
/usr/lib/systemd/user/gamescope-session.target
%dir /usr/share/doc/gamescope-session
%doc /usr/share/doc/gamescope-session/README.md
/usr/share/gamescope-session-plus/device-quirks
/usr/share/gamescope-session-plus/gamescope-session-plus
%dir /usr/share/gamescope/scripts/50-custom/50-disable-explicit-sync.lua
/usr/share/gamescope/scripts/50-custom/50-disable-explicit-sync.lua/50-disable-explicit-sync.lua
%dir /usr/share/licenses/gamescope-session
%license /usr/share/licenses/gamescope-session/LICENSE

%changelog
* Wed Oct 21 2026 Caihong local restore - 0~20260920git.0232e0c-3.fc44.caihong
- Restore the exact original Armada payload with a truthful original version.

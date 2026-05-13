Name:           cc-usage
Version:        0.1.0
Release:        1%{?dist}
Summary:        Tray indicator for Claude Code usage

License:        MIT
URL:            https://github.com/youruser/gnome-cc-usage
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  python3-pip
BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-pytest
# PyGObject is needed at build time so importable smoke checks during %%check
# match the runtime surface (the indicator module guards `import gi` but the
# tests still import it through the package).
BuildRequires:  python3-gobject
BuildRequires:  desktop-file-utils

# Runtime: PyGObject + system libraries the GTK tray icon and notifications need.
Requires:       python3-gobject
Requires:       libayatana-appindicator-gtk3
Requires:       libnotify
# secretstorage talks to the Secret Service over D-Bus; gnome-keyring provides it.
Requires:       gnome-keyring
# On vanilla GNOME the tray icon is invisible without this extension.
Recommends:     gnome-shell-extension-appindicator

%global _description %{expand:
A Linux system-tray indicator for the GNOME/KDE/XFCE menu bar that shows
your Claude Code usage percentage. Polls /api/oauth/usage and displays the
highest active rate-limit bucket (5h session, 7d rolling, 7d Opus, 7d Sonnet,
and any others present).}

%description %_description

%prep
%autosetup -n %{name}-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files cc_usage

# Application launcher entry.
install -Dm0644 src/cc_usage/_resources/desktop/cc-usage.desktop \
    %{buildroot}%{_datadir}/applications/cc-usage.desktop

# Symbolic icons into the system theme so libnotify resolves them by name.
for icon in cc-usage-symbolic cc-usage-warn-symbolic cc-usage-crit-symbolic; do
    install -Dm0644 src/cc_usage/_resources/icons/${icon}.svg \
        %{buildroot}%{_datadir}/icons/hicolor/scalable/status/${icon}.svg
done

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/cc-usage.desktop
%pytest

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_bindir}/cc-usage
%{_datadir}/applications/cc-usage.desktop
%{_datadir}/icons/hicolor/scalable/status/cc-usage-symbolic.svg
%{_datadir}/icons/hicolor/scalable/status/cc-usage-warn-symbolic.svg
%{_datadir}/icons/hicolor/scalable/status/cc-usage-crit-symbolic.svg

%post
gtk-update-icon-cache --quiet --force %{_datadir}/icons/hicolor &>/dev/null || :
update-desktop-database --quiet &>/dev/null || :

%postun
if [ $1 -eq 0 ]; then
    gtk-update-icon-cache --quiet --force %{_datadir}/icons/hicolor &>/dev/null || :
    update-desktop-database --quiet &>/dev/null || :
fi

%changelog
* Fri May 08 2026 Alexander Bykov <alardus@gmail.com> - 0.1.0-1
- Initial RPM packaging.

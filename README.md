# Claude Code Usage Indicator

A Linux system-tray indicator that shows your Claude Code usage percentage in the GNOME/KDE/XFCE menu bar.

## What it does

Polls `https://api.anthropic.com/api/oauth/usage` (the same data shown on `claude.ai/settings/usage`) and displays the rate-limit buckets returned for your account: 5-hour session, 7-day rolling, 7-day Opus, 7-day Sonnet, and any others present. The highest bucket drives the percentage label so you can track remaining budget at a glance.

## Install

**1. System packages** (PyGObject and friends can't be pip-installed reliably, so they come from your distro):

```bash
# Fedora
sudo dnf install python3-gobject libayatana-appindicator-gtk3 libnotify pipx

# Debian/Ubuntu
sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7 pipx
```

**2. Install the app:**

```bash
pipx install --system-site-packages git+https://github.com/alardus/gnome-cc-usage.git
```

The `--system-site-packages` flag is required so the venv can see PyGObject from step 1.

**3. AppIndicator GNOME Shell extension** — required for the icon to appear in vanilla GNOME (most distros ship it pre-enabled):
<https://extensions.gnome.org/extension/615/appindicator-support/>

**4. Run:**

```bash
cc-usage           # tray indicator (default)
cc-usage --once    # fetch once, print snapshot, exit
cc-usage --settings  # open settings dialog (thresholds, autostart)
cc-usage --debug   # verbose logging on stderr
cc-usage --version
```

To autostart on login, open the settings dialog and toggle the autostart switch — it writes `~/.config/autostart/cc-usage.desktop`.

To uninstall: `pipx uninstall cc-usage` (plus `rm -rf ~/.config/cc-usage ~/.local/state/cc-usage` if you want a clean slate).

## Run from a clone (no install)

For trying it out or hacking on it — nothing global is touched:

```bash
git clone https://github.com/alardus/gnome-cc-usage.git
cd gnome-cc-usage
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/cc-usage --once     # smoke test
.venv/bin/cc-usage            # run the tray
.venv/bin/pytest -q
```

`-e` is editable: edits in `src/` take effect on next run. To uninstall, just `rm -rf` the clone.

## Authentication

The indicator reads `claudeAiOauth.{accessToken, refreshToken, expiresAt}` from `~/.claude/.credentials.json`, the same file Claude Code writes. Tokens are refreshed automatically before expiry, coordinated with Claude Code's own refresh via `fcntl.flock` and mtime checks.

If credentials are missing or the refresh fails, the indicator shows `!` and a menu entry asking you to run `claude` to re-authenticate.

## Troubleshooting

- **No tray icon on GNOME** — check the AppIndicator extension is enabled: `gnome-extensions list --enabled | grep -i appindicator`. If empty, install it from the link above and restart GNOME Shell (Wayland: log out and back in).
- **Label shows `429`** — Anthropic rate-limited us. The poller honors `Retry-After` and backs off; the label flips to a percentage on the next successful poll.
- **Label shows `!`** — auth error. Run `claude` to refresh credentials, then "Refresh now" from the tray menu.
- **Label shows `Err`** — network error. The poller retries with exponential backoff up to 30 minutes.
- **Notification icons look generic** — `pipx` doesn't put SVGs on the icon-theme search path. Copy them once:
  ```bash
  ICONS=$(~/.local/share/pipx/venvs/cc-usage/bin/python -c \
    "from importlib.resources import files; print(files('cc_usage._resources').joinpath('icons'))")
  mkdir -p ~/.local/share/icons/hicolor/scalable/status
  cp "$ICONS"/*.svg ~/.local/share/icons/hicolor/scalable/status/
  gtk-update-icon-cache -f ~/.local/share/icons/hicolor/ 2>/dev/null || true
  ```

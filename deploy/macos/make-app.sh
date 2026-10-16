#!/bin/bash
# Builds "Garmin Dashboard.app" in ~/Applications: a Dock/Launchpad shortcut
# that runs Dashboard.command (ETL in Terminal, then the page). The app holds
# only the absolute path to this checkout -- rerun after moving the repo.
#   deploy/macos/make-app.sh          build the app
#   deploy/macos/make-app.sh --dock   build it and pin it to the Dock
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
APP="$HOME/Applications/Garmin Dashboard.app"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$HOME/Applications"
rm -rf "$APP"
osacompile -o "$APP" -e "do shell script \"open \" & quoted form of \"$REPO/Dashboard.command\""

# Icon: the SVG rendered by any Chrome-family browser, then iconutil.
CHROME=""
# Globs, not ls: every one of these paths has spaces in it. Playwright's
# Chromium is the fallback, newest build first (older ones hang headless).
PLAYWRIGHT=("$HOME"/Library/Caches/ms-playwright/chromium-*/*/*.app/Contents/MacOS/*)
PW_SORTED=()
for ((i = ${#PLAYWRIGHT[@]} - 1; i >= 0; i--)); do PW_SORTED+=("${PLAYWRIGHT[$i]}"); done
for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
         "/Applications/Chromium.app/Contents/MacOS/Chromium" \
         "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
         "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
         ${PW_SORTED[@]+"${PW_SORTED[@]}"}; do
    [ -f "$c" ] && [ -x "$c" ] && CHROME="$c" && break
done
if [ -n "$CHROME" ]; then
    printf '<html><body style="margin:0;background:transparent">%s</body></html>' "$(cat "$HERE/icon.svg")" > "$WORK/icon.html"
    "$CHROME" --headless=new --disable-gpu --hide-scrollbars --default-background-color=00000000 \
        --user-data-dir="$WORK/profile" --window-size=1024,1024 \
        --screenshot="$WORK/icon.png" "file://$WORK/icon.html" >/dev/null 2>&1 &
    # A headless browser that hangs must not hang the build: 30 s, then on.
    for _ in $(seq 1 60); do [ -s "$WORK/icon.png" ] && break; sleep 0.5; done
    kill $! 2>/dev/null || true
fi
if [ -s "$WORK/icon.png" ]; then
    mkdir "$WORK/icon.iconset"
    for size in 16 32 128 256 512; do
        sips -z $size $size "$WORK/icon.png" --out "$WORK/icon.iconset/icon_${size}x${size}.png" >/dev/null
        sips -z $((size * 2)) $((size * 2)) "$WORK/icon.png" --out "$WORK/icon.iconset/icon_${size}x${size}@2x.png" >/dev/null
    done
    iconutil -c icns "$WORK/icon.iconset" -o "$APP/Contents/Resources/applet.icns"
    # osacompile also ships its script icon in Assets.car, which wins over
    # applet.icns while CFBundleIconName points at it.
    rm -f "$APP/Contents/Resources/Assets.car"
    /usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$APP/Contents/Info.plist" 2>/dev/null || true
    # The bundle changed after osacompile signed it: sign it again (ad hoc).
    codesign --force --sign - "$APP" >/dev/null 2>&1 || true
    touch "$APP"
else
    echo "Brak przegladarki Chrome/Chromium do wyrenderowania ikony - zostaje domyslna."
fi
echo "Gotowe: $APP"

if [ "${1:-}" = "--dock" ]; then
    if defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "Garmin%20Dashboard.app"; then
        echo "Juz jest w Docku."
        killall Dock  # pick up the new icon
    else
        defaults write com.apple.dock persistent-apps -array-add \
            "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>file://${APP// /%20}/</string><key>_CFURLStringType</key><integer>15</integer></dict></dict></dict>"
        killall Dock
        echo "Przypiete do Docka."
    fi
fi

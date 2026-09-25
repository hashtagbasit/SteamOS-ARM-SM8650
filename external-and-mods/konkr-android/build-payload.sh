#!/usr/bin/env bash
# build-payload.sh — fetch the binary parts of payload/common:
#   Play services + Services Framework + permissions (MindTheGapps 11 arm64),
#   the Play Store from MindTheGapps 14 (11's Phonesky has no arm64 libs;
#   14's needs Android 10+, fine on Lepton's 11), Simple Keyboard (F-Droid;
#   Lepton ships no keyboard). The text files next to them (freeform off,
#   Steam pad key layout) are in git.
# payload/lepton-<ver>/ (framework) comes from framework/build-framework.sh.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${HERE}/payload/common"
CACHE="${KONKR_ANDROID_CACHE:-${HERE}/.cache}"
MTG11="https://github.com/MindTheGapps/11.0.0-arm64/releases/download/MindTheGapps-11.0.0-arm64-20230922_081122/MindTheGapps-11.0.0-arm64-20230922_081122.zip"
MTG14="https://github.com/MindTheGapps/14.0.0-arm64/releases/download/MindTheGapps-14.0.0-arm64-20250203_200051/MindTheGapps-14.0.0-arm64-20250203_200051.zip"
KBD_VERSION=148
KBD="https://f-droid.org/repo/rkr.simplekeyboard.inputmethod_${KBD_VERSION}.apk"

mkdir -p "$CACHE"
[[ -s "$CACHE/mtg11.zip" ]] || curl -fL -o "$CACHE/mtg11.zip" "$MTG11"
for f in system/product/priv-app/PrebuiltGmsCore/PrebuiltGmsCore.apk \
         system/system_ext/priv-app/GoogleServicesFramework/GoogleServicesFramework.apk \
         system/product/etc/permissions/privapp-permissions-google-p.xml \
         system/system_ext/etc/permissions/privapp-permissions-google-se.xml \
         system/product/etc/sysconfig/google.xml \
         system/product/etc/sysconfig/google_build.xml \
         system/product/etc/sysconfig/google-hiddenapi-package-whitelist.xml; do
  mkdir -p "$OUT/$(dirname "$f")"
  unzip -p "$CACHE/mtg11.zip" "$f" >"$OUT/$f"
done

# Only Phonesky out of the 430 MB MindTheGapps 14 zip, via HTTP ranges.
mkdir -p "$OUT/system/product/priv-app/Phonesky"
python3 - "$MTG14" "$OUT/system/product/priv-app/Phonesky/Phonesky.apk" <<'PY'
import io, sys, urllib.request, zipfile
url, out = sys.argv[1:3]
class Remote(io.RawIOBase):
    def __init__(self, u):
        r = urllib.request.urlopen(urllib.request.Request(u, method="HEAD"))
        self.url, self.size, self.pos = r.geturl(), int(r.headers["Content-Length"]), 0
    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos
    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos
    def readinto(self, b):
        if self.pos >= self.size: return 0
        end = min(self.size, self.pos + len(b)) - 1
        d = urllib.request.urlopen(urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{end}"})).read()
        b[:len(d)] = d; self.pos += len(d); return len(d)
z = zipfile.ZipFile(io.BufferedReader(Remote(url), buffer_size=1 << 20))
open(out, "wb").write(z.read("system/product/priv-app/Phonesky/Phonesky.apk"))
PY

mkdir -p "$OUT/system/product/app/SimpleKeyboard"
curl -fL -o "$OUT/system/product/app/SimpleKeyboard/SimpleKeyboard.apk" "$KBD"
find "$OUT" -name '._*' -delete
echo "payload/common ready: $(du -sh "$OUT" | cut -f1)"

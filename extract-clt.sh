#!/bin/bash
set -euo pipefail
DMG=/srv/sandboxes/deepsbx/work/iosim/third_party/Command_Line_Tools_27.dmg
BASE=/srv/sandboxes/deepsbx/work/xnu-13432-recon/clt
PBZX=/srv/sandboxes/deepsbx/work/iosim/tools/pbzx.py
mkdir -p "$BASE/dmg" "$BASE/root" "$BASE/sdkroot" "$BASE/binroot"
cd "$BASE/dmg"
echo "[1/4] extracting CLT pkg from DMG"
7z x -y "$DMG" "Command Line Developer Tools/Command Line Tools.pkg"
cd "$BASE/dmg/Command Line Developer Tools"
echo "[2/4] xar TOC"
xar -tf "Command Line Tools.pkg" > "$BASE/xar-toc.txt"
echo "[3/4] extracting SDK and executable payloads"
xar -x -f "Command Line Tools.pkg" CLTools_macOS_SDK.pkg/Payload CLTools_Executables.pkg/Payload
echo "[4/4] unpacking payloads"
cd "$BASE/sdkroot"
python3 "$PBZX" ../dmg/Command\ Line\ Developer\ Tools/CLTools_macOS_SDK.pkg/Payload | cpio -idm --no-absolute-filenames
cd "$BASE/binroot"
python3 "$PBZX" ../dmg/Command\ Line\ Developer\ Tools/CLTools_Executables.pkg/Payload | cpio -idm --no-absolute-filenames
echo DONE

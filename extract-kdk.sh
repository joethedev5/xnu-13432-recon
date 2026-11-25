#!/bin/bash
set -euo pipefail
DMG=/srv/sandboxes/deepsbx/work/iosim/third_party/Kernel_Debug_Kit_27.0.1_build_26A434.dmg
BASE=/srv/sandboxes/deepsbx/work/xnu-13432-recon/kdk
PBZX=/srv/sandboxes/deepsbx/work/iosim/tools/pbzx.py
mkdir -p "$BASE/dmg" "$BASE/root" "$BASE/sdkroot"
cd "$BASE/dmg"
echo "[1/4] extracting flat package from DMG"
7z x -y "$DMG" "Kernel Debug Kit/KernelDebugKit.pkg"
cd "$BASE/dmg/Kernel Debug Kit"
echo "[2/4] xar TOC"
xar -tf KernelDebugKit.pkg > "$BASE/xar-toc.txt"
echo "[3/4] extracting KDK payloads"
xar -x -f KernelDebugKit.pkg KDK.pkg/Payload
xar -x -f KernelDebugKit.pkg KDK_SDK.pkg/Payload 2>/dev/null || echo "no KDK_SDK payload entry"
cd "$BASE/root"
echo "[4/4] unpacking KDK payload (pbzx -> cpio)"
python3 "$PBZX" ../dmg/"Kernel Debug Kit"/KDK.pkg/Payload | cpio -idm --no-absolute-filenames
if [ -f ../dmg/"Kernel Debug Kit"/KDK_SDK.pkg/Payload ]; then
  cd "$BASE/sdkroot"
  python3 "$PBZX" ../dmg/"Kernel Debug Kit"/KDK_SDK.pkg/Payload | cpio -idm --no-absolute-filenames
fi
echo DONE

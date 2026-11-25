#!/bin/bash
set -euo pipefail
BASE=/srv/sandboxes/deepsbx/work/xnu-13432-recon/clt
PBZX=/srv/sandboxes/deepsbx/work/iosim/tools/pbzx.py
cd "$BASE/dmg/Command Line Developer Tools"
xar -x -f "Command Line Tools.pkg" CLTools_macOSLMOS_SDK.pkg/Payload CLTools_macOSNMOS_SDK.pkg/Payload
for n in LMOS NMOS; do
  mkdir -p "$BASE/sdk-$n"
  cd "$BASE/sdk-$n"
  python3 "$PBZX" ../dmg/Command\ Line\ Developer\ Tools/CLTools_macOS${n}_SDK.pkg/Payload | cpio -idm --no-absolute-filenames
done
echo DONE

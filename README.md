# xnu-13432 reconstruction

Independent, evidence-driven reconstruction of Apple's **xnu-13432.1.9** kernel
(macOS 27.0.1 / Darwin 27.0.0) starting from the newest public
`apple-oss-distributions/xnu` source (`xnu-12377.121.6`) plus publicly
available reference materials.

## Target

```
Darwin Kernel Version 27.0.0: Tue Aug 11 21:00:07 PDT 2026;
root:xnu-13432.1.9~1/RELEASE_ARM64_VMAPPLE
```

Reference host: macOS 27.0.1 (26A434), Xcode 27.1 (27A9275), virtual Apple
M2 Pro. Kernel Debug Kit 27.0.1 (26A434) supplies x86_64 and arm64e release
kernels with dSYMs; the macOS 27 SDK supplies user-visible headers/stubs.

## Method

1. Inventory the reference kernels (versions, UUIDs, load commands, symbols).
2. Extract DWARF compile units, subprograms, types and line tables from the
   KDK dSYMs.
3. Diff the 13432 source set, ABI and dispatch tables against the public
   `xnu-12377.121.6` tree.
4. Reconstruct verified changes as patches on the public tree, with an
   evidence/confidence record per change.
5. Validate generated layouts and disassembly against the reference kernels.

See [`docs/RECONSTRUCTION-NOTES.md`](docs/RECONSTRUCTION-NOTES.md) for the
running evidence log, and `tools/` for the analysis pipeline.

## Repository policy

This repository contains **only original tooling, notes and reconstruction
patches**. It does not redistribute Apple KDK/SDK payloads, kernel binaries,
dSYMs or extracted proprietary headers. The base XNU source is available from
Apple under the Apple Public Source License; reconstruction patches are
provided under the same license unless stated otherwise.

This is a research/interoperability project and is not affiliated with Apple.

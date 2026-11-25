# XNU 13432 reconstruction — working notes

## Target
- Kernel: **xnu-13432.1.9~1**, `RELEASE_ARM64_VMAPPLE`, build stamp
  `Tue Aug 11 21:00:07 PDT 2026`.
- Host reference (GitHub Actions xcode-27 runner, measured 2026-11-20,
  artifact run-44753098912): macOS 27.0.1 build 26A434, Xcode 27.1 build
  27A9275, Apple M2 Pro (Virtual), Darwin 27.0.0.
- Raw `uname -a`:
  `Darwin ... 27.0.0 Darwin Kernel Version 27.0.0: Tue Aug 11 21:00:07 PDT 2026; root:xnu-13432.1.9~1/RELEASE_ARM64_VMAPPLE arm64`

## Public base
- Repo: `work/xnu` (apple-oss-distributions/xnu), cloned 2026-11-25.
- Newest public branch/tag: `rel/xnu-12377` / `xnu-12377.121.6`
  (2026-06-17). This is the reconstruction base; it post-dates
  xnu-12377.1.9 by 5 commits and precedes the 13432 build by ~2 months.

## Reference materials (local)
- `work/iosim/third_party/Kernel_Debug_Kit_27.0.1_build_26A434.dmg`:
  KDK 27.0.1 (packaged 2026-09-24). Unpacked to
  `work/xnu-13432-recon/kdk/root`: x86_64 release kernel + dSYM
  (UUID 8f0fa4f8…), arm64e `kernel.development.t60xx` variants, kexts and
  kext dSYMs, kernel-collection manifests.
- `work/iosim/third_party/Command_Line_Tools_27.dmg`: macOS 27.0 SDK
  (headers/stubs) — `CLTools_macOS_SDK.pkg`.
- KDK_SDK payload: `Kernel.framework` platform headers (SPTM, TrustCache,
  CodeSignature, CoreEntitlements).
- Xcode 27.1 + iOS 27.0/27.1/27.2 simulator runtimes on the xcode-27
  runner (userland ABI, dyld_sim/launchd_sim/SpringBoard).
- `work/iosim/recon-runner`: GitHub Actions workflows; repo
  `joethedev5/iosim-recon`; runs-on `xcode-27`.
- Prior recon artifacts: `recon-artifacts/run-44753098912`,
  `run-44753759820`.

## Method
1. **Ground truth inventory**: extract KDK kernel(s)/dSYMs; record UUID,
   arch, load commands, version string, build config; list CUs, symbols,
   types from DWARF.
2. **Source-set diff**: DWARF CU `DW_AT_name` paths give the exact
   13432 source file list. Diff against the public tree → added/removed/
   renamed files.
3. **ABI diff**: parse DWARF struct/union/enum/typedef DIEs; compare
   member offsets/sizes/names with public headers; regenerate headers.
4. **Dispatch-table diff**: decode `_mach_trap_table` (128 entries) and
   `_sysent` (558 entries) from the KDK kernel; map handlers to symbols;
   compare with the public generated tables → new/removed syscalls/traps.
5. **Function diff**: DWARF line table + disassembly; identify functions
   whose source lines no longer match public source, new functions, and
   changed constants/strings.
6. **Remote arm64 ground truth**: `xnu-recon` workflow on xcode-27
   runner collects host sysctls, kmutil metadata, `/System/Library/
   Kernels`, kernel collections, and macOS 27 SDK headers.
7. **Reconstruction**: apply verified deltas onto a branch of `work/xnu`
   (base `xnu-12377.121.6`): headers/types first, then dispatch tables,
   then function bodies where evidence supports them. Keep an evidence
   score/confidence per change.
8. **Validation**: compile reconstructed units with clang against the
   macOS 27 SDK where feasible; compare generated layouts/offsets and
   disassembly against the KDK reference.

## Ground-truth facts collected so far
- KDK kernel `_mach_trap_table`: 128 entries, 24-byte rows
  `{arg_info, handler, munge}`.
- KDK kernel `_sysent`: 558 entries, 24-byte rows
  `{sy_call, sy_arg_munge32, return type, narg, arg bytes}`.
- KDK 27.0.1 dSYM: 50,898 symbols (27,546 text); merged symbol coverage
  99.275% of executable bytes.
- Target build date: Tue Aug 11 21:00:07 PDT 2026.

## Open questions
- Does the KDK include a VMAPPLE/arm64e release kernel? (list after unpack)
- Is full DWARF type info present in kernel.dSYM, or only line tables?
- Can the runner's kernel collection be copied/decompressed legitimately
  (kmutil inspect metadata + `/System/Library/Kernels` files)?

## 2026-11-25: Exact target kernel recovered from the KDK

The KDK is not limited to the x86_64 kernel: it ships every release variant,
including **`kernel.release.vmapple`**, whose version string matches the
reference host exactly:

```
Darwin Kernel Version 27.0.0: Tue Aug 11 21:00:07 PDT 2026;
root:xnu-13432.1.9~1/RELEASE_ARM64_VMAPPLE
```

`kernel.release.vmapple` is a 16 MB arm64e Mach-O; its dSYM is 73 MB with
54,360 functions, 201,159 inlined functions, 263,794 unique source variables
and full DWARF v5 type/line information (Apple clang 21, LTO, `-O2`,
`-march=armv8.5a+sme2+amx1`, `ARM64_BOARD_CONFIG_VMAPPLE`). This is the
build target itself, not an approximation.

DWARF compile units: **1,046**, each `DW_AT_name` an absolute path under
`.../Sources/xnu/`. The embedded producer strings carry the full per-file
clang command lines, including all `-D` defines and search paths.

Local analysis pipeline:
- `tools/macho_dwarf.py` — dumps `__DWARF` sections from a thin Mach-O dSYM
  into a synthetic ELF that pyelftools can parse.
- `tools/dwarf_db.py` — builds a SQLite model (`cu`, `source_file`, `func`,
  `func_param`, `func_range`, `type`, `member`, `enumerator`, `line`).
- Reference extracts and derived ELF/DB files stay local and are gitignored;
  they are never committed or uploaded to the public repository.

Public repo: https://github.com/joethedev5/xnu-13432-recon
Private reference store: https://github.com/joethedev5/xnu-13432-refs

## 2026-11-25: dispatch tables and source deltas

DWARF model: 1,046 CUs, 76,861 subprograms, 308,987 types, 986,315 members,
368,826 variables, 126,767 call sites, 1,112,400 line-table rows.

Dispatch tables decoded from the exact VMAPPLE kernel using DWARF variable
locations and arm64e chained-pointer fixups (stride 4, unauth target =
vm offset from image base 0xfffffe0007004000):

- `sysent` @ `0xfffffe00072675e8`: 558 × 24 B, same field layout as public.
- `mach_trap_table` @ `0xfffffe0007236b40`: 128 × 24 B,
  `{arg_count:u8,u32_words:u8,returns_port:u8,pad:u8,fn@8,munge@16}`.
- First entries resolve exactly: `sysent[0]=nosys`, `sysent[1]=exit`.

BSD syscalls: 22 entries differ from public `syscalls.master`. Reserved
`nosys`/`enosys` slots now carry real handlers, including `pipe2` (148),
`sys_dup3` (149), `fchflagsat` (214), `getumask` (215), `aio_readv` (246),
`aio_writev` (247), `fsctlat` (249), `guarded_ftruncate_np` (352), and
`register_uexc_handler` (519).

Mach traps: 128 entries; the `mach_syscall_name_table` names line up with
the public `syscall_sw.c` table once that table block is parsed correctly.

Source set: 56 files in the 13432 DWARF are absent from public
`xnu-12377.121.6`. Largest groups: TCP modularisation (16 new `tcp_*.c`
files), arm64 hypervisor/PPL (`osfmk/arm64/hv/*`, `ppl/*`), DRAM ECC,
exclaves, telemetry, threadpair, virtual_env, task_apt, IOKit analytics.

## 2026-11-25: entry points implemented and validated against the reference

The reconstruction tree now implements every BSD/Mach entry point that is new
or changed in 13432:

- Nine new BSD syscalls (`pipe2`, `sys_dup3`, `fchflagsat`, `getumask`,
  `aio_readv`, `aio_writev`, `fsctlat`, `guarded_ftruncate_np`,
  `register_uexc_handler`) plus their `syscalls.master` rows.
- Mach trap 108 `thread_set_x86_64_compat_trap` with its name-table entry.
- Supporting refactors recovered from disassembly and DWARF signatures:
  `dup_internal`, `close_fp_for_dup`, `fd_expand_descr_table_locked`,
  `fp_close_and_unlock_with_action`, `ftruncate_internal`,
  `fchflagsat_internal`, `fsctlat_internal`, `configure_uexc_handler`,
  `handle_uexc_fault`, and the `ml_satisfies_x86_64_requirements` /
  entitlement path.

Validation: running `bsd/kern/makesyscalls.sh syscalls.master` reproduces the
dispatch table decoded from `kernel.release.vmapple` byte-for-byte for all
nine new entries — handler symbol, munge (`munge_ww`, `munge_www`,
`munge_wwww`, `munge_wwl`, `munge_wwwww`, NULL), return type, and argument
byte count. The reference `sysent` layout (`sy_call` 0, `sy_arg_munge32` 8,
`sy_return_type` 16, `sy_narg` 20, `sy_arg_bytes` 22) and trap-108 record
(`arg_count=1`, `u32_words=1`, `munge_w`) were both matched.

Type findings from the exact dSYM were applied where they live in shared
headers: `arm64_uexc_region_t` and the 32-byte `task.uexc` field at 0x368,
`task.x86_64_compat_entitled` at 0x38b, and `machine_thread.x86_64_compat`
at offset 48 after the matrix-state union.

## 2026-11-25: 56 new translation units reconstructed

`tools/newfile_recon.py` generates all 56 files that the 13432 DWARF places
in the tree but public `xnu-12377.121.6` lacks, preserving reference function
order, signatures and declaration lines. Current contents:

- **464 functions** with DWARF-exact signatures.
- **91 bodies relocated** verbatim from the public tree (4,025 lines removed
  from their public locations), chiefly the TCP modularisation splits
  (`tcp_segment.c`, `tcp_recovery.c`, `tcp_sack`-adjacent helpers) and
  `kern_exec_security.c`.
- **373 explicit stubs** carrying `RECON(13432)` markers and panic bodies.
- Every file registered in the matching `conf/files*` build list.

Per-file counts are in [NEW-FILES.md](NEW-FILES.md); the machine-readable
report (`analysis/newfile-report.json`) stays local.

Known deltas at this stage:
- The 13432 `nameidata` split (`ni_resolveflags` at offset 336 and renamed
  `NAMEI_*` values, `NAMEI_ATFD=0x400`) is recorded but not applied
  tree-wide; new code uses the public namei API.
- Stub bodies, include blocks and a few cross-file static call sites still
  need disassembly-driven completion/validation.

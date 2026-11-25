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

## 2026-11-25: smallest stub bodies and the full header set

Disassembly-driven recovery replaced 64 of the 373 explicit stubs with
bodies that reproduce the reference instruction sequences:

- 16 immediate-return `void` bodies, 11 pointer getters returning NULL,
  and three integer helpers returning 0.
- Five `KERN_NOT_SUPPORTED` (46) and two `KERN_FAILURE` (5) returns in the
  exclaves surface, DRAM ECC and APT entry points.
- All 19 `sptm_gen3dart_*` unsupported paths, with the exact panic format
  string, function name, `sptm_stubs.c`, and line numbers 42-60.
- `image4_v2_interface_register` (single assignment plus the line-13
  "already set" panic), `ecc_panic_non_acc`, and the APT zero-fill/no-op
  helpers.
- `hv_trap_vm_{map,unmap,protect}` tail calls into
  `hv_space_map_op_nested` with selectors `0xc6000015`-`c6000017`, and
  `hv_trap_vcpu_sysregs_sync` returning `HV_NO_DEVICE` (`0xfae94006`)
  when the current thread has no `hv_thread_target`.

The 30 headers that the reference source set contains but the public tree
does not are now reconstructed from the DWARF type graph
(`tools/newheader_recon.py`); per-file details are in
[NEW-HEADERS.md](NEW-HEADERS.md). `struct tcp_seg_sent` and the IOPM
driver-assertion typedefs were relocated textually out of their public
headers into the new ones. `vm_map_store_types_internal.h` is generated
but its definitions still also live in `vm_map_store_internal.h`; the
textual relocation is the remaining delta.

Current stub count: 309.

## 2026-11-25: RBBR window init, tcpcb delta, VM map store relocation

`tcp_rbbr_rwnd_init` is recovered from its 100-byte body: initial window
= 10x MSS, rounded down to an MSS multiple, clamped to
`0xffff << rcv_scale`, then `win_change_pending = 1`.  The reference
reads the multiplier (10) from `0xfffffe0007cbf450`.  This required the
missing 13432 `tcpcb.t_rbbr_state` pointer between `t_rlstate` and
`rcv_srtt`; the field is now present.

The VM map store packed-pointer, node/root, reservation and guard-object
types and their packing macros moved verbatim from
`vm_map_store_internal.h` into `vm_map_store_types_internal.h`, so the
header set no longer duplicates live definitions.  Remaining explicit
stubs: 308.

## 2026-11-25: RBBR receive-window algorithm reconstruction

DWARF variable locations resolved every RBBR tunable to its address
(`0xfffffe0007cbf44c`-`0x7cbf4c0`) and the reference image supplied the
initial values, so all 30 `int` parameters are restored by name and
value (for example `rbbr_rtt_probe_period = 30`,
`rbbr_rtt_probe_rwnd_mss = 10`, `rbbr_min_rwnd_mss = 2`,
`rbbr_startup_gain = 200`).

Recovered bodies:
- `tcp_rbbr_init` / `tcp_rbbr_switch_to` (identical in the reference,
  which folded them): allocate `tcp_rbbr_state` from the kalloc-type
  `tcp_rbbr_state_zone`, bump `tcp_cc_rbbr.num_sockets`, initialize the
  window from `rbbr_rtt_probe_rwnd_mss`, and schedule the next probe
  boundary from `rbbr_rtt_probe_period`.
- `tcp_rbbr_cleanup`: decrement the socket count and free the state.
- `tcp_rbbr_get_rlwin`: skip-restrict and negotiation handling, window
  rounding to `rcv_scale`, and pending-window-change expiry against
  `rcv_adv`.
- `tcp_rbbr_after_idle`: state reset preserving `rwnd_est` and
  `delay_exceeded_seen`, initial-window fallback, phase reset and probe
  boundary scheduling.
- `ml_device_is_prod_fused`: `/chosen`
  `certificate-production-status` 32-bit property read.

`tcp_cc_rbbr` is declared and initialized in `tcp_cc.h` / `tcp_rbbr.c`.
Remaining explicit stubs: 302.

## 2026-11-25: RBBR utilization and RTT median

- `rbbr_sender_utilizing_rwnd`: computes expected bytes as
  `win * (now - cycle_measure_ts) / median_rtt`, compares the actual
  `cycle_bytes_rcvd` percentage against `rbbr_low_utilization_thresh`,
  and logs low utilization through `tcp_log_bbr` (line 825) when
  enabled.
- `rbbr_insertion_sort`, `rbbr_sorted_median`,
  `rbbr_sort_rtt_samples` and `rbbr_get_rtt_median`: recover the full
  RTT sample path; the median computation inlines to the reference's
  300-byte body, including the odd/even cases and the `rtt_sorted`
  cache flag.
- All 11 compiler-internal `__bounds_safety` type names in the new
  files were replaced with real C types and
  `__counted_by`/`__sized_by` annotations.

Remaining explicit stubs: 297.

## 2026-11-25: TFO last-ACK and RBBR phase logging

`tcp_tfo_process_last_ack` clears `TFO_F_COOKIE_VALID`, releases the
`tcp_tfo_halfcnt` reservation and `VERIFY`s it did not go negative,
matching the reference assfail at line 245. `rbbr_log_phase_end` logs
the phase transition with the reference format and line 483.

The public patch series now contains 14 patches and has been
re-applied to a clean `xnu-12377.121.6` worktree with `git am` without
conflicts. Remaining explicit stubs: 294.

## 2026-11-25: telemetry init and receive-window selector

`vm_page_telemetry_init` allocates the drain thread call with
`vmpt_drain_thread` as callback and stores it in
`vmpt_drain_thread_call`. `tcp_calc_rcv_window` caps `rcv_wnd` by the
window scale, and when timestamps are negotiated uses the selected
receive-CC algorithm's `get_rlwin`; `tcpcb.t_recv_cc_algo` was added
(1 = RBBR, 2 = rLedbat). The patch series now has 16 entries and still
applies cleanly to xnu-12377.121.6. Remaining explicit stubs: 292.

## 2026-11-25: AccECN acknowledgement and ECN heuristics

- `tcp_accecn_do_ack`: unacked-CE accounting and ACKNOW decisions,
  including the 2-segment/last_ack_sent boundary.
- `tcp_ecn_check_ce_heur`: latch `TE_ECEHEURI_SET`, count CE packets
  after 20 received packets, run `tcp_heuristic_ecn_aggressive` at the
  19-packet boundary, and update the reference's 0x04000000 AccECN
  flag (not named in the public header).
- `tcp_ecn_check_data_rst_heur`: require negotiated ECN or accurate ECN
  and a first data segment before invoking `tcp_heuristic_ecn_droprst`.

The patch series now has 18 entries. Remaining explicit stubs: 289.

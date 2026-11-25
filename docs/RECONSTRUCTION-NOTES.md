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

## 2026-11-25: SYN-ACK window path

The reference's only call to `tcp_calc_rcv_window` is in TCP input at
the SYN-ACK receive-window update; the public rLedbat-only clamp is
replaced by `tcp_calc_rcv_window(tp, TCP_RECV_BG(so))`. The argument
matches the `SOF1_TRAFFIC_MGT_TCP_RECVBG` (0x4000) test seen in the
reference disassembly. Patch series: 19 entries.

## 2026-11-25: ECN SYN-RST heuristic

`tcp_ecn_check_syn_rst_heur` applies only while classic or accurate ECN
setup is outstanding; local connections mark `TE_RCVD_SYN_RST` and
return the reference reason value `0x02010001`, while remote
connections invoke `tcp_heuristic_ecn_synrst`. Patch series: 20
entries; remaining explicit stubs: 288.

## 2026-11-25: TFO faulty-middlebox path

`tcp_tfo_synack_faulty_middlebox` detects a middlebox acknowledging
only one TFO byte, runs `tcp_heuristic_tfo_middlebox`, sets
`so_error = 0x60`, raises `SO_FILT_HINT_LOCKED |
SO_FILT_HINT_MP_SUB_ERROR`, and marks `TFO_S_ONE_BYTE_PROXY`; a
13432-only `t_flagsext` bit 24 suppresses it. Patch series: 21
entries, 287 explicit stubs remain.

## 2026-11-25: Per-CPU advanced TCP timers

The reference replaces the legacy per-connection `t_timer[]` offsets
with a per-CPU red-black tree of `tcp_timer_entry` objects.  All 28
functions of `bsd/netinet/tcp_timer_advanced.c` and the inline API in
`tcp_timer_advanced.h` are recovered:

- entry layout (`te_node`, `te_next`, `te_free`, `te_tp`, `te_inp`,
  `te_expires`, `te_softexpires`, `te_type`, `te_cpu`, `te_flags`)
  with `TE_FLAG_IN_TREE`/`TE_FLAG_EXECUTING`, plus the four inline
  accessors schedule/cancel/isactive/get_value.
- the RB tree ordered by hard expiry with a pointer tiebreak;
  `RB_GENERATE` over `te_expires` is visible in the image, and
  `tcp_timer_tree_remove` maintains the per-CPU active count.
- `tcp_timer_advanced_add`/`remove`/`cleanup`, including the inlined
  `socket_lock_assert_owned` and the socket usecount handoff
  (`TF_TIMER_ENTRY_USECOUNT`, `so_usecount`), plus the
  `te_softexpires` leeway calculation (1/10 of the timeout, capped at
  100 ms, with the 15/4/100 variants for PERSIST-related timers).
- the `thread_call` path: `tcp_timer_invoke_handler`,
  `tcp_timer_process_cpu_timer` with its 60 s lookahead,
  `tcp_timer_snapshot_if_probes`/`tcp_timer_execute_if_probes` for
  the interface-probe PTO, `tcp_timer_reschedule_cpu`, and
  `tcp_timer_advanced_init` with the `tcptimercpu` lock group.

`struct tcpcb` gains `t_timer_entries[TCPT_NTIMERS]` at offset 0x58
(which pushes `t_inpcb` to 0xa8, matching the DWARF), and the two
reused `t_flags` bits are named `TF_TIMER_ADVANCED` (0x02000000) and
`TF_TIMER_ENTRY_USECOUNT` (0x80000000).  `tcp_offset_from_latest_tx`
loses its static linkage so the header inline can call it.

The patch series now has 22 entries; 259 explicit stubs remain.

## 2026-11-25: ECN handshake, TFO and the segment RB tree

`tcp_ecn.c` gained 16 recovered bodies covering the full handshake
and feedback path:

- `tcp_ecn_process_syn`/`tcp_accecn_process_ip_ecn` and
  `tcp_ecn_process_synack`/`tcp_accecn_process_last_ack` carry the
  client and server AccECN state machines.  The reference treats
  ECT1/CE feedback as success only when the new `TE_SEND_ECT1`
  (0x08000000) bit is set; non-ECT/ECT0 feedback then marks ECT
  mangling.  The same bit is what makes an L4S SYN set
  `TE_SENDIPECT` from the start (`tcp_ecn_syn_respond`,
  `tcp_ecn_synack_respond`).
- `tcp_ecn_update_counters` no longer takes an inpcb; `tcp_ecn_ip_feedback`
  folds the window check and ACE-bleaching detection, gating
  `TE_SENDECE` on the 13432-only 0x04000000 heuristic flag.
- `tcp_accecn_feedback`, `tcp_classic_ecn_feedback` and
  `tcp_ecn_feedback` dispatch ACK feedback, classic ECE fast recovery
  and packet-count accounting.
- `tcp_classic_ecn_set_flags`, `tcp_accecn_set_ace_flags` and
  `tcp_ecn_set_flags` emit CWR/ECE and encode r.cep into the ACE
  field; `tcp_accecn_add_option` is the relocated AccECN option
  writer.

The six `tcp_fastopen.c` stubs are recovered by relocating the public
text: `tcp_tfo_process_syn`/`tcp_tfo_process_synack`,
`tcp_tfo_check`, the two cookie writers and `tcp_tfo_init`.  The
reference keeps `tfo_ctx` (the AES context) in `tcp_fastopen.c` at
line 100 rather than `tcp_subr.c`, and its half-counter check is the
non-atomic `tcp_tfo_halfcnt` compare used by the image.

The eleven `tcp_seg_sent_tree_head_RB_*` symbols at
`tcp_segment.c:45` are one `RB_GENERATE(tcp_seg_sent_tree_head,
tcp_seg_sent, seg_link, tcp_seg_cmp)`; the per-function stubs are
replaced.

The patch series now has 25 entries; 226 explicit stubs remain.

## 2026-11-25: Recovery, RTT and RBBR phase helpers

Four more translation units advanced:

- `tcp_recovery.c`: `tcp_detect_spurious_rxmt`,
  `tcp_restore_on_spurious_rxmt`,
  `tcp_recovery_check_spurious_rxmt` and
  `tcp_recovery_can_early_rxmt` — the public bad-rexmt/TLP/DSACK and
  early-retransmit paths under their 13432 names.  The decompilation
  confirms the reference's `EXIT_FASTRECOVERY` expansion (with the
  advanced-timer PTO removal).
- `tcp_rtt.c`: `tcp_get_base_rtt`, `tcp_update_curr_rtt`,
  `tcp_update_base_rtt` and `tcp_compute_rxmit_time` (the renamed
  `tcp_xmit_timer`).  The reference keeps 4 current-RTT samples and
  10 route RTT-history slots with the 60 s expiry.
- `tcp_rbbr.c`: `rbbr_apply_cruise_backoff`,
  `rbbr_enter_probe_rwnd` and `rbbr_enter_cruise`, including the
  reference's window rounding and `0xffff << rcv_scale` clamp.

The patch series now has 28 entries; 215 explicit stubs remain.

## 2026-11-25: Virtual environment and the last ECN paths

`osfmk/kern/virtual_env.c` is complete: all 20 reference bodies are
recovered.  The object is a refcounted `struct virtual_env` (uuid,
lazily materialized `IKOT_VIRTUAL_ENV` Mach port, lock, and copied-in
subsystem root path) with `virtual_env_count`/0x1000 limit growth,
`os_refgrp` accounting, the `virtual_env_no_senders` kobject callback
and the MIG create/get-info/get-current entry points.  Availability
checks the development-variant bits (`osvariant_status & 0xc00000 ==
0xc00000`) and caches the answer, so this also required making the
status word non-static in `bsd/kern/kern_sysctl.c` and declaring it in
`variant_internal.h`.  The public create path's entitlement is
`com.apple.private.virtualenv.manager`; the exec helper
`virtual_env_create_from_subsystem_root_path` is what will replace
`p_subsystem_root_path` once the exec/fork paths are reconstructed.

`tcp_ecn.c` now has no stubs.  The SYN-ACK handling is split into
`tcp_classic_ecn_process_synack`, `tcp_accecn_process_synack` (with
the TH_AE/TH_CWR/TH_ECE ACE flag matrix and the ECT/CE setup bits)
and `tcp_ecn_update_heuristics_synack`, dispatched by
`tcp_ecn_process_synack`.  `tcp_ecn_lastack_respond`,
`tcp_accecn_disable_option`, `tcp_ecn_set_ip`/`tcp_ecn_set_ip6` and
`tcp_ecn_check_ece_heur` are recovered from the development-kernel
image.  The ACE and AccECN option decoders live in this file in 13432
(`tcp_accecn_process_ace`/`tcp_accecn_process_options`), so the
duplicate public definitions were deleted from `tcp_input.c`.  The
reference counts CE marks in `t_ecn_capable_packets_marked/acked`
rather than the removed `total_ect_packets_*` fields; the remaining
`tcp_input.c` increments still use the old fields and are a known
existing-file delta.

The patch series now has 30 entries; 185 explicit stubs remain.

## 2026-11-25: Process virtual environment integration and TCP accounting

`struct proc` now carries `struct virtual_env *p_virtual_env` at offset
1976 in place of the public `p_subsystem_root_path` string.  The
reference disassembly pins each use: `forkproc` retains the parent's
environment into the child (line 1242), `forkproc_free` and `proc_exit`
release it, `bsd_init` clears it, and `csops` tests it for the LV-clear
path.  `kern_exec` publishes the path through
`virtual_env_get_subsystem_root_path` instead of copying a string.

posix_spawn creates the child environment from a spawn-time subsystem
root with `virtual_env_create_from_subsystem_root_path`, and the new
`PSPA_VIRTUAL_ENV` port action (enum value 6) lets an entitled parent
supply an existing environment.  `exec_handle_virtual_env_port_actions`
requires `com.apple.private.virtualenv.spawn` on the parent task,
rejects a second environment with EEXIST, and converts the action port
with `convert_port_to_virtual_env`; on failure the destroy path releases
the send right.  The `exec_port_actions` layout gains
`virtual_env_port` at offset 56 (size 64), matching the DWARF.

The TCP receive path now follows the reference's `tcpcb` layout:
`total_ect_packets_marked/acked` are gone, replaced by
`total_packets_received` at offset 408, and `t_recv_bg_algo` fills
offset 495.  `tcp_input` adds `segment_count` to that counter at both
receive-statistic sites and delegates ECN feedback: the data, control
and SACK paths call `tcp_accecn_feedback` (bytes acked, zero with the
control-packet flag, and SACK bytes respectively), while the main ACK
path calls `tcp_ecn_feedback`.  The last-ACK decoder and aggressive ECE
heuristic are only in `tcp_ecn.c`; the classic feedback path calls
`tcp_ecn_check_ece_heur`, whose reference mask clears `TE_SETUPSENT`
as well as `TE_SENDIPECT` and the heuristic bit.

The patch series now has 32 entries; 185 explicit stubs remain.

## 2026-11-25: Proportional rate reduction

The reference tcpcb carries `struct tcp_prr prr` at offset 1384
(delivered, out, recover_fs, sack_bytes_prev, dupacks), completing the
1408-byte layout.  `tcp_prr_delivered` distinguishes the SACK path
(`th_ack + sack_bytes_acked - snd_una - sack_bytes_prev`) from the
duplicate-ACK path (one MSS per duplicate, otherwise the newly ACKed
bytes divided into MSS-sized packet credits) and clamps the result to
one MSS.  `tcp_prr_update` accumulates delivered bytes, then applies
either the proportional branch `ceil(delivered * ssthresh /
recover_fs) - out` when the pipe exceeds ssthresh, or the slow-start
reduction bound `min(ssthresh - pipe, max(delivered - out,
delivered_new) + mss)` when `tcp_prr_ssrb` is set.  The cwnd update is
rounded down to an MSS multiple after adding the pipe.

`tcp_prr` and `tcp_prr_ssrb` default to 1 and use the reference sysctl
descriptions "TCP PRR" and "Enable Slow Start Reduction Bound for TCP
PRR".  `tcp_enter_fast_recovery` resets delivered/out/dupacks and
records `snd_max - snd_una` as recover_fs and the current SACK byte
count, and the partial-ACK path calls `tcp_prr_update`.  The reference
also calls it from the duplicate-ACK cwnd path and adds the sent length
to `prr.out` in tcp_output; those two existing-file edits still need
their exact source positions pinned down.

The patch series now has 33 entries; 183 explicit stubs remain.

## 2026-11-25: TCP reassembly, options relocation and TFO linkage

`tcp_reassembly.c` is a new translation unit in the reference; all seven
of its functions are `DW_AT_external`, and three of them had no recovered
body.  `tcp_reass_create_qent` (line 451) allocates through
`tcp_reass_qent_alloc`, bumps `t_reassqlen` and the atomic
`tcp_reass_total_qlen`, accounts the mbuf chain through
`m_chain_capacity`/`tcp_memacct_add`, and stores `tqe_th`, `tqe_m` and
`tqe_len`.  `tcp_reass_destroy_qent` (line 477) mirrors that accounting,
decrements the queue counters (the reference emits one 2-lane vector
subtract for `t_reassqlen`/`t_reassq_mbcnt`), releases the zone entry and
returns the mbuf chain.  `tcp_reassq_free` (line 494) walks
`LIST_FIRST(&tp->t_segq)`, removes each entry, destroys it and frees the
chain.  The old public names `tcp_create_reass_qent`,
`tcp_destroy_reass_qent` and `tcp_free_reassq` do not exist in 13432, so
the tcp_subr.c wrappers were deleted and `tcp_close` now calls
`tcp_reassq_free` directly (reference tcp_subr.c:1689).

The public `tcp_dooptions` is the reference `tcp_process_options` at
tcp_options.c:79 (1056 bytes); `tcp_finalize_options` (line 218) and
`tcp_addoptions` (line 268) share that unit.  All three are external in
the DWARF, so the tcp_input.c static copy and prototypes were removed,
tcp_input.c and tcp_handshake.c now call `tcp_process_options`, and
tcp_var.h declares the three functions.

All fourteen functions of tcp_fastopen.c are external in the reference;
the public copies still present in tcp_output.c (`tcp_tfo_check`,
`tcp_tfo_write_cookie_rep`, `tcp_tfo_write_cookie`), tcp_subr.c
(`tcp_tfo_init` and the TFO crypto context) and the static qualifiers in
tcp_fastopen.c were removed, and `tcp_fastopen.h` now declares the TFO
entry points.  `tcp_tfo_check`/`tcp_tfo_write_cookie*` and
`tcp_tfo_init` were the last duplicate function definitions in the TCP
subsystem.

The patch series now has 35 entries; 175 explicit stubs remain.

## 2026-11-25: Socket buffers, RACK failure path, TCP context, delayed ACK

The socket-buffer helpers split out of tcp_subr.c are external in the
reference.  `tcp_sbrcv_min_rwin` (tcp_sb.c:265) is the reference's
rename of the public `tcp_sbrcv_grow_rwin`: it grows the receive
buffer by sixteen segments when auto-resizing is enabled, the socket
is not background-throttled, less than one increment is free, and the
current high-water mark is within one increment of the ideal size.
`tcp_sbspace` calls it at its two mptcp/BDP sites, and the stale
public copy and prototypes were removed.

`tcp_seg_free_and_disable_rack` (tcp_segment.c:83) is static inline in
the reference.  Both inlined instances (in `tcp_seg_rto_insert_end`
and `tcp_seg_sent_insert_before`) show the same sequence: a TLEF_LOG
message "not enough memory to allocate segment, disabling RACK",
`tcp_segs_sent_clean(tp, true)` and clearing `TF_RACK_ENABLED`.

`struct tcp_context` is declared at tcp_var.h:293 and is 128 bytes
with 64-byte alignment: mbuf, inpcb/tcpcb reference pointers, socket,
tcphdr, an anonymous union of ip/ip6, tcpopt, the counted option
pointer and length, thflags, tlen, off0, iss/irs/tiwin, ts_offset,
ifscope, and the isipv6/is_th_swapped bits at byte 118.
`tcp_socket_exists_for_tuple` unlocks the socket, runs the IPv4 or
IPv6 `*_pcblookup_hash_exists` with the mbuf's source/destination
interface scopes (relaxed=false for IPv6), re-locks the socket and
reports a connected match.

The delayed-ACK decision moved from tcp_cc.c into tcp_ack.c as
`tcp_delay_ack`; every tcp_cc_algo `delay_ack` slot is NULL in the
reference module tables.  Modes 1/2 check `TF_RXWIN0SENT`, TH_PUSH
and `t_unacksegs == 1`; mode 3 uses the clamped `tcp_sbspace` window,
`TF_QUICKACK`, `t_forced_acks`, `sb_lowat`, `t_last_recwin`, the
1.5 * `tcp_recvspace` threshold, a quarter-window BDP bound and a
256-MSS ACK burst bound, counting delays in `t_stat.acks_delayed`.
`tcp_cc_delay_ack` and the four per-algorithm wrappers were removed,
and the tcp_input `DELAY_ACK` macro calls `tcp_delay_ack`.

The patch series now has 39 entries; 171 explicit stubs remain.

## 2026-11-25: Exec security configuration

The seven remaining stubs in `kern_exec_security.c` are recovered.  Note
that the previous count in this file (171 stubs) was off by two: the tree
actually carried 173 explicit stub bodies before this batch and carries
166 now.

`imgact_setup_platform_restrictions` (kern_exec_security.c:42) gained a
13432-only branch before the platform-binary check: when
`exec_security_get_hardened_browser()` is non-zero the task gets platform
restrictions version 1; platform binaries still get version 3.  The
string-entitlement path is unchanged from the public source (parse,
validate, free, then accept versions 2 through 7), and the integer
entitlement still selects version 2.

`encode_hardened_browser_entitlement` is the public `encode_HR_entitlement`
moved here: it ORs the mask into `load_result->hardened_browser` when the
vnode carries the entitlement.  `imgact_setup_hardened_browser` zeroes the
field and tests the host/GPU/network/webcontent entitlements with masks
1/2/4/8.  The reference image's GPU and network strings read
"com.apple.developer.web-browser-engine.gpu" and "...network", whereas the
matching KDK's `CodeSignature/Entitlements.h` still says "rendering" and
"networking"; the recovered source therefore carries its own definitions.

`exec_security_get_hardened_browser` simply returns the field; the DWARF
also records two dead locals (`_lr`, `_es`) left from a debug aid at
kern_exec_security.c:160.  `imgact_set_platform_binary_flag` advances the
state to PLATFORM_BINARY_SETUP and calls
`task_set_platform_binary(task, load_result->platform_binary)`.

`imgact_setup_ipc_containment` sets or clears the task's IPC containment
vessel bit; when the binary is a platform binary and its code-signing
identity begins with "com.apple.WebKit." it sets the new task security
config `webkit` bit (0x800), otherwise clears it.  The identity is obtained
with `csvnode_get_blob` + `csblob_get_identity`.  The clear-vessel call is
in the outer else, so a non-vessel binary returns without touching the
webkit bit.  `imgact_setup_ipc_security_policy` applies the platform-binary
flag and disables mach hardening for tasks that may load third-party
plugins (`IMGPF_3P_PLUGINS`); the reference keeps an always-false local
`override` in the condition.

`exec_setup_vfs_resolve_flags` reads
"com.apple.security.hardened-process.vfs.resolve-flags" with
`IOTaskGetEntitlement`, parses a base-10 value, masks it with 0x7ff, stores
it in `proc_ro_data.p_fixed_vfs_resolve_flags` through the new
`proc_set_fixed_vfs_resolve_flags` accessor, and ORs it into the new
`proc.p_vfs_resolve_flags` field at offset 0x44 (the field is volatile in
the DWARF).  The entitlement string is released with `kfree_data_addr`.

Supporting reference layout changes recovered here: `load_result_t` gains
the `is_vm_containment_vessel_cow_defeatured` bit (between `hardened_heap`
and `is_ipc_containment_vessel`) and the byte-sized `exec_security_state`
at offset 0x88; `task_security_config` gains
`vm_containment_vessel_cow_defeatured` (bit 9), `reserved2` (bit 10) and
`webkit` (bit 11); `proc_ro_data` gains `p_fixed_vfs_resolve_flags` at
offset 0x18.  `exec_security_advance_state` is a static inline in
kern_exec_security.h, and `EXEC_LOG` plus the two platform-restriction
entitlement macros moved to kern_exec_internal.h so the new translation
unit can use them.

The patch series now has 40 entries; 166 explicit stubs remain.

## 2026-11-25: Remaining PRR hooks

The reference has exactly two calls to `tcp_prr_update`: the partial-ACK
call already present in `tcp_input.c` (reference line 3287) and one in
the already-in-fast-recovery duplicate-ACK branch (reference lines
3083-3084).  The latter sits in an if/else-if chain ahead of the legacy
SACK `awnd` calculation: `if (tcp_prr && IN_FASTRECOVERY(tp))
tcp_prr_update(tp, th); else if (SACK_ENABLED(tp) && IN_FASTRECOVERY(tp))
{ ... awnd ... } else tp->snd_cwnd += tp->t_maxseg;`.

At the end of `tcp_output`, after `tcpstat.tcps_sndtotal++`, the
reference accounts the transmitted segment when PRR is active and the
connection is in fast recovery (`tp->prr.out += len`, reference lines
2769-2770) before the `sendalot` loop check.

The patch series now has 41 entries; 166 explicit stubs remain.

## 2026-11-25: RBBR phase machine and RTT sampling

`bsd/netinet/tcp_rbbr.c` had 13 bodies left; all are now reconstructed
from the release kernel.  The reference keeps every phase helper in this
unit (plus `rbbr_log_phase_end`, whose own log line is 483).

`rbbr_update_phase` switches on `rbbr->phase` (0 PROBE_RTT, 1
PROBE_RWND, 2 CRUISE) after computing `time_until_probe` once.

PROBE_RTT computes `elapsed`, `min_dur = MAX(srtt_ms,
rtt_probe_min_duration)` and `max_dur = MAX(rtt_probe_max_duration,
min_dur)`.  When `rbbr_action_elapsed` fires with
`MAX(rtt_probe_cycle_rtts, 1)`, a round with samples logs the median
(line 1277), updates `probe_rtt_min`/`probe_rtt_flat_rounds` against
`MAX(rtt_probe_plateau_rounds, 1)` and sets `conclude = elapsed >=
min_dur && (plateaued || elapsed >= max_dur)`; a sample-less round
concludes only at `max_dur`.  When the action has not elapsed, only
`elapsed >= max_dur` proceeds.  A non-concluding analyzed round starts
a new round and returns.  On conclusion `compute_jitter_stats_and_reset`
runs, then `time_until_probe < 3 * action_ms` selects CRUISE, otherwise
PROBE_RWND (`reprobe = false`).

The jitter reset computes the median, replaces the samples with their
absolute deviations, and sets `delay_threshold = median_rtt +
delay_thresh_mad_mult * rtt_mad + target_delay_ms`; with no samples it
only defaults a zero threshold to 100 and leaves the cycle counters
alone.

`rbbr_process_probe_rwnd_cycle` returns whether the cycle was
acceptable.  With no samples it is acceptable and logs "NO SAMPLES";
otherwise it computes the median and utilization and, when the median
exceeds the delay threshold, marks `delay_exceeded_seen` and logs the
delay exit.  In the acceptable branch it adopts `win` as `rwnd_est`
when a cycle has completed and the sender utilized the window, then
logs the cycle statistics.

PROBE_RWND computes `action_ms` from `rbbr_current_rtts`; a
`time_until_probe < 2 * action_ms` exit and the delay-ceiling and
max-cycle exits all log the phase end and enter CRUISE.  The max-cycle
test casts `rbbr_probe_rwnd_max_cycles` to `uint8_t`.  A completed,
acceptable action starts a round; an unutilized window sets
`win_change_pending` and logs "hold", while a utilized window picks
`reprobe_gain`, `probe_rwnd_main_gain` or `startup_gain` (reprobe
active, delay seen, otherwise), increments `probe_rwnd_cycle` and
applies `rbbr_update_win(tp, rbbr_pct(rwnd_est, gain))` before the
"grow" log.  The grow path leaves `rwnd_est` itself untouched.

CRUISE finalizes sawtooth detection and re-enters PROBE_RTT when the
scheduled probe is due.  Otherwise an elapsed action with samples
logs the cycle median, runs the chain detector only while
`cruise_backoff_count` is non-zero, applies a cruise backoff on delay,
starts the next round and, with `cruise_cycles >= 1`, increments
`cruise_action_count`; when the count reaches `(uint8_t)cruise_cycles`
and the next probe is at least `3 * action_ms` away it logs
CRUISE -> PROBE_RWND and enters PROBE_RWND with `reprobe = true`.  A
sample-less elapsed action just starts a new round.

Sawtooth detection keeps `prev_cruise_median`, a noise margin
(`noise_base_ms + rtt_mad * noise_mad_mult`) and a drop threshold.
Rising medians extend `current_chain_length`; a drop larger than
`prev_median * drop_pct / 100` with at least `queue_detect_increases`
chained rounds credits `sawtooth_cycles` and clears the chain.  The
finalizer converts the ratio to a percentage and, at or above
`queue_detect_fraction_pct`, sets `queue_competition_detected` and
`skip_rwnd_restrict = 2`.

PROBE_RTT entry sets the phase, schedules the next probe, resets
`probe_rtt_min`/`probe_rtt_flat_rounds`, starts a round, decrements
`skip_rwnd_restrict` (logging when it reaches zero), sets the window
to the minimum and clears the cruise-backoff state.

`tcp_rbbr_data_rcvd` gates sampling on `win_converged` plus
`!win_change_pending` and on the timestamp echo being recent
(`SEQ_GEQ` against `rwnd_change_ts`).  Accepted samples land in the
64-entry ring, and both log sites are rate-limited by per-site
`_last_ts` statics compared against `net_uptime()`.  The cycle byte
count and first measurement timestamp update on every accepted
segment, then the phase machine runs.

`rbbr_enter_probe_rwnd`, `rbbr_enter_cruise` and
`rbbr_apply_cruise_backoff` now call `rbbr_pct`, `rbbr_min_win`,
`rbbr_update_win`, `rbbr_start_round` and
`rbbr_reset_sawtooth_detection` exactly where the reference does.
`rbbr_action_elapsed` measures its duration branch from
`cycle_measure_ts` (not the round start); the fallback still uses the
passed start timestamp.

`tcp_utils.c`'s `scale_to_powerof2`, `tcp_ceil`, `tcp_round_to`,
`tcp_round_up` and `ntoh24` are external in the reference DWARF, so the
reconstruction no longer marks them static and `tcp_subr.c` uses an
extern declaration.

The patch series now has 42 entries; 143 explicit stubs remain.

## 2026-11-25: threadpair wait-owner and the turnstile type

`stackshot_thread_wait_owner_info` gains the `kThreadWaitThreadpair`
(0x23) case, dispatching to the new `kdp_threadpair_find_owner` in
`osfmk/kern/matchmaker.c`.  The function returns early when the waitq
interlock ticket is held and otherwise reports
`thread_tid(tp->tp_recver)`, matching the inlined instance at
`kern_stackshot.c:6644` (the `ldrh [+6]; eor lsr#8; tst #0xfe` ticket
check and `tp_recver` at offset 0x18).

The reference `turnstile_type` enum carries `TURNSTILE_THREADPAIR = 11`
with `TURNSTILE_TOTAL_TYPES = 12`; the promote policy table at
0xfffffe0007008c98 holds twelve entries ending in `0x2`
(`TURNSTILE_USER_PROMOTE`).  The hash lock policy entry is
`TURNSTILE_HASH_LOCK_POLICY_NONE`: the reference build folds the whole
array to constant comparisons, and only `TURNSTILE_SLEEP_INHERITOR`
takes the irq-unsafe/locked path, so type 11 uses the irq-safe table
with `splsched()` locking.  With the two array lines added, every later
function definition in `turnstile.c` sits exactly two lines below its
public-12377 counterpart, confirming the reference delta is only the
two table entries.

The patch series now has 43 entries; 142 explicit stubs remain.

## 2026-11-25: AMCC RORGN and the PV CTRR path

The four arm64 AMCC files are now fully recovered: `rorgn_contains`,
`rorgn_stash_range`, `rorgn_lockdown`, `rorgn_validate_core`, the
`lock_mmu` helper and the `pv_ctrr_map_reg_base`/`pv_ctrr_init` pair.
The KDK's kasan dSYM (100 MB, `kernel.kasan.vmapple.dSYM`) carries full
DWARF where the release image only keeps line tables: local variable
names and types, inlined-subroutine trees and, most usefully, the
`mach_assert_default` descriptors whose `expr` field holds the assert
source text.  Decoding the chained pointers in `__DATA_CONST` yields
strings such as `PV_CTRR_REG(PV_CTRR_NUM_REGIONS_OFFSET) >= 8`,
`reg_size == sizeof(*reg)` and
`PV_CTRR_REG64(PV_CTRR_D_LWR_OFFSET) == (begin & ~(ctrr_block_size - 1))`.

`PV_CTRR_REG(offset)` is a 32-bit MMIO read and `PV_CTRR_REG64(offset)`
a 64-bit one from `pv_ctrr_reg_base`; the register block has signature
`'ctrr'`, version 1, the region count at 0x0c, a block-size shift at
0x10, and four CTRR regions (0x40..0xb0) plus four CTXR regions
(0xc0..0x130), each with lower/upper/control registers.  `lock_mmu`
locks A and B only when they are not already locked, requires C and D
to be unlocked, verifies that the D window matches the request at the
encoded block size, enables the CTXR regions and calls
`rorgn_validate_core`.

`rorgn_stash_range` takes `segLOWESTRO` and either `segHIGHESTRO` or
`segLASTB + segSizeLAST` as the protected range, calls `pv_ctrr_init`
and only publishes `rorgn_begin`/`rorgn_end` when the CTRR is usable.
`rorgn_contains` gates on `ml_unsafe_kernel_text()` and
`startup_phase < 20`, converts the address with `kvtophys`, checks the
addition with `os_add_overflow` and tests the inclusive physical range.

The patch series now has 44 entries; 135 explicit stubs remain.

## 2026-11-25: ARM feature detection and the Apple AIDR keys

xnu-13432 moved the EL0-visible ARM feature detection out of
`osfmk/arm/commpage/commpage.c` and rewrote it around static_if keys.
The kasan DWARF names the true source files once the CU file table is
resolved with the DWARF v5 zero-based index: the 16 functions live in
`osfmk/arm64/cpu_features.c` (lines 73-739), the ARM_FEAT_* jump keys
are defined in `osfmk/arm/arm_features.inc` (lines 37-197), and the
Apple AIDR keys are defined in `osfmk/arm/apple_features.inc`
(lines 30-47), which `cpu_features.c` includes.  The public 12377
commpage code is the exact template for the register tests, so the
recovery is a matter of carrying the tests over, converting each
`gARM_FEAT_* = 1` into a `static_if_key_enable()`, and adding the
fields new in 13432.

An early reading of the file table treated its index as one-based,
which swapped the roles of `arm_features.inc` and `cpu_features.c`.
The `hv_init`/`current_task` attributions from the same table only
made sense zero-based, so the layout above is the corrected one.

Recovered layout:

 - `osfmk/arm/arm_features.inc` defines the 84 `ARM_FEAT_*` /
   `ARM_SME_*` keys, from `ARM_FEAT_FP8` at line 37 to
   `ARM_FEAT_MTE_NO_ADDRESS_TAGS` at line 197.
 - `osfmk/arm/apple_features.inc` defines `Apple_AFP`,
   `Apple_AMAIRCfg`, `Apple_AMX`, `Apple_AMX4_1`, `Apple_APFLG`,
   `Apple_CTRRv2`, `Apple_CTRRv3`, `Apple_GEXSCM`, `Apple_MILDDSB`,
   `Apple_MTE`, `Apple_MTEver_1`, `Apple_PRSVScalarFP`, `Apple_TBCF`
   and `Apple_TSO` at lines 30-47.
 - `osfmk/arm64/cpu_features.c` holds the zfr0/isar0/isar1/isar2/
   isar3/mmfr0/mmfr1/mmfr2/pfr0/pfr1/pfr2/smfr0/fpcr/misc init
   routines, the `arm_cpu_features_init` dispatcher (with the
   `enable_sme` boot arg) and `apple_cpu_features_init`, each
   registered with `STATIC_IF_INIT()`; it includes both key files.
 - New field tests beyond public 12377: ISAR1 API value 6
   (`FEAT_PAuth_LR`), ISAR2 LUT, ISAR3 FAMINMAX/CPA, MMFR0 ASIDBits,
   MMFR2 VARANGE, PFR1 CSV2_frac 1.2, PFR2 FPMR, SMFR0 LUTv2/F8F16/
   F8F32 and the SME2/SME2.1 version check read directly from SMFR0.
 - The Apple side reads AIDR and MIDR: a part-number test
   (`MIDR_EL1_PNUM_MASK & ~0x10 == 0x300`) clears AIDR bit 25
   (MILDDSB); MTE version V1 enables `Apple_MTEver_1`; bits for TSO,
   APFLG, PRSVScalarFP, AFP, TBCF, GEXSCM and the two CTRR versions
   map one-to-one to keys, and AMAIRCfg is enabled when its bit is
   clear.  MILDDSB requires both the AIDR bit and the `mdsb` boot arg.

The key enable sequence was verified against the reference image: the
recovered code enables the same 82 ARM keys and 12 of the 14 Apple
keys (`Apple_AMX` and `Apple_AMX4_1` are defined but enabled
elsewhere), with identical masks, thresholds and control flow.  Column numbers in
the kasan line table pin down the exact macro spellings, which is how
the longer `(pnum & (MIDR_EL1_PNUM_MASK & ~0x10)) == 0x300` form was
recovered instead of a plain PNUM compare.

The 12377 `ARM_FEATURE_FLAG()` list that used to live in
`osfmk/arm/arm_features.inc` moved to `osfmk/arm/arm_features.h` so
`commpage.c` and `kern_mib.c` keep generating their feature flags; the
`.inc` paths now carry only the static_if key definitions, and the
detection implementation lives in `cpu_features.c`.

Splitting the recovered code back into these three files leaves the
generated instructions unchanged apart from where the Apple key
structures are emitted, so the reconstruction branch was amended to
match the reference layout.

The patch series now has 45 entries; 119 explicit stubs remain.

## 2026-11-25: Hypervisor support layer and trap dispatcher

xnu-13432 split the hypervisor support layer by architecture.  The
x86-only `osfmk/kern/hv_support_kext.c` keeps the kext-facing trap and
callback APIs, while the new `osfmk/kern/hv_support_kern.c` holds the
machine-independent globals and accessors.  The kasan DWARF gives the
layout: `hv_support_available` at line 42 and `hv_disable` at 44, then
`hv_support_init` (48), `hv_get_support` (55), the task/thread setters
(62/69) and getters (76/83).  `hv_init` returns `_Bool` (the DWARF type
is one byte, and the reference stores the raw result in the `int`
global), and the kasan disassembly confirms the exact assignment and
the task/thread object offsets.  `task.hv_task_target` keeps its
`XNU_PTRAUTH_SIGNED_PTR` qualifier, while `thread.hv_thread_target` is
a plain pointer in the reference: the kasan setter/getter only show
KASAN shadow checks, never `pacda`/`autda`.

The new `osfmk/arm64/hv/hv.c` carries the kernel-side trap path.  Its
`hv_init` parses the `hypervisor` boot arg into an `int`, sets
`hv_internal_isa_guest_allowed` and returns
`hv_paranested_virtualization_init()`.  `_hv_trap_capabilities` asserts
`hv_get_support() != 0` (the kasan descriptor string is exactly that
expression), sizes its buffer from the shared measurement's
capabilities entry, allocates it with `kernel_memory_allocate(...,
PAGE_MASK, KMA_ZERO, VM_KERN_MEMORY_HV)`, fills it with
`hv_get_host_capabilities`, copyouts `MIN(size, sizeof(hv_capabilities_t))`
bytes and returns `HV_ERROR`/`HV_SUCCESS` (the error constants
`0xfae94001`/`0xfae94005`/`0xfae9400f` come from the standard
`err_local | err_sub(0xba5)` space).

The 19-entry `_vm_trap` table lives at line 380.  Decoding its chained
pointers from the kasan image recovers the complete dispatch map:
0 `_hv_trap_capabilities`, 1-5 `hv_trap_vm_create/destroy/map/unmap/
protect`, 6-10 `hv_trap_vcpu_create/destroy/sysregs_sync/run/
run_cancel`, 11-17 NULL, 18
`hv_trap_paravirtualized_nested_service`.  `hv_trap` reads the trap
number and argument from saved-state x0/x1 (not x1/x2), emits
`KDBG_RELEASE(MACHDBG_CODE(DBG_MACH_EXCP_SC, 5) | DBG_FUNC_START/END)`
events with debug ids `0x10c0015`/`0x10c0016`, dispatches through the
table when `hv_get_support()` is non-zero, and writes the result back
to saved-state x0.  The thread/task destroy callbacks tail-call
`hv_vcpu_destroy()` and `hv_vm_destroy()`.

The DWARF line attribution also pins the reference struct layouts:
`hv_capabilities_t` is packed (size 475, with `ipa_bits_4k` at offset
417 and `svl_b_max` at 433) and `hv_paranested_measurement_t` is packed
too (size 228, `arm_hv_state_version` at offset 20, measurement array
at 28), which is why the capabilities size load is at offset 0xd8.
`ARRAY_SIZE` is not a global macro in this source set, so the table
bounds are expressed with `sizeof`; the reference compiler's explicit
NULL check is folded into the initializer-known entries here.

New headers: `osfmk/kern/hv_support_kern.h`, `osfmk/arm64/hv/hv.h`,
`hv_vm.h` and `hv_vcpu.h`, with declaration line numbers recovered
from the DWARF; `hv_kern_types.h` now carries the hypervisor error
codes, and `hv_compat_paranested.h` the full compatibility helper set.
`hv_internal.h` declares the two lock objects and `_hv_vm_destroy`.

Both translation units compile with their recovered
`DW_AT_APPLE_flags` and reproduce the reference instruction sequences.
The local clang cannot emit ptrauth or bounds-safety instrumentation,
so the task target signing and the copyout wide-pointer check cannot be
exercised locally; the source forms are recorded from the reference.
The task and thread struct layouts in the reconstruction still differ
from the release DWARF (`hv_task_target` at 0x618 there, 0x5e0 here;
`hv_thread_target` 0x4a8 vs 0x4b8), so absolute member offsets remain
to be reconciled separately from these bodies.

The patch series now has 47 entries; 111 explicit stubs remain.

## 2026-11-25: hypervisor VM object policy and lookup helpers

`osfmk/arm64/hv/hv_vm.c` is now fully recovered.  The five out-of-line
functions are:

- `hv_map_lookup_protection` (line 375): declares the shared find lock
  context, calls `vm_map_find_entry_sh_locked(find_ctx, &map, addr,
  VMRL_FIND_SH_NO_MIN_MAX_CHECK)` (the disassembly passes 0x2000, and
  the 13432 DWARF confirms `VMRL_FIND_SH_NO_MIN_MAX_CHECK` = 8192),
  returns the error unchanged, otherwise reports
  `vme_protection(find_ctx->vmlc_vme)` and
  `find_ctx->vmlc_vme->vme_end`, unlocks with
  `vm_map_found_entry_sh_unlock` and returns.  The DWARF column
  annotations (383:8, 383:35, 384:13, 384:35) pin the source text: the
  function reads the context field directly instead of using
  `vm_map_found_entry_get_entry()`, and the protection helper is a new
  `vme_protection()` static inline at `vm_map_internal.h:515`.
- `hv_trap_vm_destroy` (line 390): `hv_lock()`; `vm = hv_get_vm()`; if
  NULL, `hv_unlock()` and `HV_NO_DEVICE` (0xfae94006); `hv_vm_lock(vm)`;
  if `bitmap_first(&vm->vcpu_online_mask[0], HV_VCPU_MAX) >= 0`,
  unlock both and `HV_BUSY` (0xfae94002); otherwise `hv_set_vm(NULL)`,
  unlock both and `hv_release_vm(vm)`, returning `HV_SUCCESS`.
  `HV_VCPU_MAX` is 64: the vCPU-create trap rejects ids above 0x3f.
- `hv_vm_destroy` (line 424): assert no online vCPU (the release build
  compiles the assert out; the kasan descriptor text is
  `bitmap_first(&vm->vcpu_online_mask[0], HV_VCPU_MAX) < 0`), then
  `os_ref_release_last(&vm->refcnt)` and `_hv_vm_destroy(vm)`.
- `hv_vm_max_permitted_isa` (line 437): the entitlement ladder is
  `com.apple.security.hypervisor` -> 1, plus
  `com.apple.private.hypervisor.vmapple` -> 3, plus
  `com.apple.private.hypervisor` -> 3 and 4 when
  `hv_internal_isa_guest_allowed` is set.  The string order was read
  from both the kasan and release images; the release build inlines the
  entitlement check through IOKitBSDInit.cpp.
- `hv_vm_allowed` (line 459): `if (hv_disable || isa ==
  _HV_VM_ISA_NONE) return false;` then
  `return isa <= hv_vm_max_permitted_isa();` (the inlined copy in
  hv_vm_allowed is visible in both images).

The `hv_internal.h` helpers were recovered as static inline functions
from the inlined call trees: `hv_get_vm` (73), `hv_set_vm` (80),
`hv_get_vcpu` (86), `hv_set_vcpu` (92), `hv_lock` (102), `hv_unlock`
(108), `hv_vm_lock` (117), `hv_vm_unlock` (123), `hv_reference_vm`
(135), `hv_get_lock_and_reference_vm` (141),
`hv_get_and_reference_vm` (155), `_hv_vm_destroy` (167) and
`hv_release_vm` (170).  The two reference helpers take hv_mtx, fetch
the task target, retain the VM, and `hv_get_lock_and_reference_vm`
additionally takes `vm->mtx` before dropping hv_mtx; their bodies come
from the call-site DWARF line/column records (144:2, 145:7, 147:3,
148:3, 150:2 and 158-163 respectively).

`hv_vm_isa_t` is `uint32_t` (declared at `hv_interface.h:208`), not an
enum.  The values 0/1/3/4 are recovered from the ISA policy; only the
`_HV_VM_ISA_APPLE` and `_HV_VM_ISA_GENERIC` spellings are attested (by
the public unit-test mocks), so the remaining macro names are marked
as inferred in the header.

New `hv_disable` declaration note: the arm64 kernel cannot include
`kern/hv_support.h` (it `#error`s outside `__x86_64__`), so the extern
is carried in `hv_support_kern.h` next to the definition; the
reference declaration site was not recovered.

Struct drift: the release `vm_map_entry` is 64 bytes but its bitfield
tail has been compacted versus the public tree: the `vme_is_tagged/
__unused1/__unused2` bits are gone, `behavior` starts at bit 1,
`protection` is at bit 4, `superpage_size` and the final
`vme_kernel_object/__unused3` bits are gone, and the object word is
`vme_kind:2 / vme_value:62` at offset 40.  `vme_protection()` compiles
against the public layout for now (protection at bit 7), so its
generated `ubfx` offset differs from the reference until the VM entry
layout is reconstructed.

Both translation units still compile with their recovered
`DW_AT_APPLE_flags`; the generated `hv_vm.c` code matches the release
control flow (error constants, `vm+0x18` bitmap, `vm+0x8` refcount,
HV_VCPU_MAX bound), and the local harness reproduces the release
`hv_vm_allowed`/`hv_vm_max_permitted_isa` value ladder.

The patch series now has 48 entries; 106 explicit stubs remain.

## 2026-11-25: hv_vcpu_obj_alloc

`hv_vcpu_obj_alloc` was recovered at `hv_vcpu.c:6079`; the file is large
in the reference (the allocation lives around line 6080, and the DWARF
names 6079 as the declaration line).  The kasan companion keeps the
full locals and line/column tables, and the release image pins the
control flow:

- The first argument is `hv_vcpu_t **` (the earlier stub had
  `hv_vcpu_t *`): entry stores zero to `*vcpu`, and the success path
  stores the allocated address through it.
- 64-byte vCPU object: `kmem_alloc(kernel_map, &addr, sizeof(hv_vcpu_t),
  KMA_ZERO, tag)` with `tag = VM_KERN_MEMORY_HV` (0x1c), then
  `assert(addr)` and `assert((addr & PAGE_MASK) == 0)` (DWARF lines
  6092/6093).
- 32 KB shared context: `kmem_alloc_contig(..., 0, 0, 0, KMA_DATA |
  KMA_ZERO, tag)` when `contiguous_context`, otherwise `kmem_alloc(...,
  KMA_DATA | KMA_ZERO, tag)`; the flags are 0x8080 in both images.
  Failure jumps straight to the vCPU free (line 6105 -> 6172), skipping
  the context free.  Asserts at 6109/6110.
- Remap: `rw_size`/`ro_size`/`remap_size` are 0x4000/0x4000/0x8000
  (lines 6116-6118); `user_addr` (6119:19), `remap_cur_prot` and
  `remap_max_prot` (6120/6121:12).  The first
  `mach_vm_remap_new_kernel()` maps the whole range read/read at a
  random address (`vmf_random_addr`, vmk_flags 0x1c000008); asserts
  6138/6139.  The second remaps the read-write half over the base with
  `vmf_overwrite` (0x1c004001) and protections 3/3 (6141/6142:17,
  call 6143:6).
- Failure layout: the success path returns first (asserts 6162/6163 on
  the page alignment of `&uif->rw` and `&uif->ro`, then `return ret;`
  at 6165).  The second-remap failure reaches a `fail_remap`-style
  label at 6166: `ret = HV_ERROR;` (6167), then
  `mach_vm_deallocate_kernel(user_map, user_addr, remap_size)` (6168,
  columns 2/38), which falls into the shared `fail` label (6169) and
  `kmem_free(kernel_map, shared_guest_context_addr,
  sizeof(arm_guest_context_t))` (6170:12).  `fail_free_vcpu` (6171)
  frees the 64-byte object (6172:12) and returns (6173/6174).  The
  first-remap failure branches directly to 6170, so it keeps the
  initial HV_NO_RESOURCES; only the second-remap failure becomes
  HV_ERROR (0xfae94001).
- The `(*vcpu)->uif = (arm_guest_context_t *)user_addr;` assignment at
  6161 has its cast at column 17, the `*vcpu` load at column 3 and the
  store at column 15 relative to the line, which matches the recovered
  columns 6161:17/3/15 exactly (Apple clang attributes the load to the
  cast expression start; LLVM 19 reports the operand position instead,
  so the local `.loc` for the load differs by column only).
- `kif` is stored at vCPU offset 8 and `uif` at offset 16 (the object
  layout recovered earlier: vm 0, kif 8, uif 16).

The KDK 27.0.1 `vm_kern_xnu.h` differs from the public 12377 header in
its inline expanders, which shows up in this function:

- `kmem_alloc_guard()` and `kernel_memory_allocate()` are inlined down
  to an out-of-line `kmem_alloc_guard_internal(map, size, mask, flags,
  guard, alloc_pages)` at `vm_kern.c` line 883 (release address
  0xfffffe0007428f80).
- `kmem_alloc_contig_guard()` builds a stack block whose invoke is
  `__kmem_alloc_contig_guard_block_invoke` (release address
  0xfffffe0007429cb8, i.e. the PAC-signed code pointer stored in the
  block) and passes it as the `alloc_pages` argument; the contiguous
  context call therefore reaches the internal function with a sixth
  argument rather than with the public seven-scalar prototype.
- `kmem_free_guard()` is inline in the reference and rounds the size to
  page size: the release frees the 64-byte vCPU object with an end
  address of `addr + 0x4000` (round_page(0x40)) and the 32 KB context
  with `addr + 0x8000`, and both calls reach
  `vm_map_remove_and_iunlock()` at 0xfffffe0007438328.

The source-level calls in `hv_vcpu.c` are the reference ones; the local
12377-derived header expands them to slightly different call shapes
because those inline bodies have not been reconstructed yet.  The
translation unit compiles with its recovered `DW_AT_APPLE_flags`, and
the generated instruction sequence matches the release control flow
(allocation sizes and flags, remap flag words, deallocate size, error
constants and the free order).

The patch series now has 49 entries; 105 explicit stubs remain.

## 2026-11-25: nested call, host capabilities and VM teardown

Four functions of `hv_vm_paranested.c` were recovered.  The file starts
with an inline `hvc` helper and ends (in this range) with the VM and
vCPU trap handlers; the kasan image keeps an out-of-line copy of the
helper (`_hv_nested_call` at 0xfffffe0007b9cc18, 172 bytes) even though
the release build inlines it everywhere.

- `hv_nested_call` (line 58, C99 `inline`): the body checks the service
  selector before entering the host.  The check compiles to
  `service >> 5 == 0x6300000`, i.e. it accepts the family
  0xc6000000-0xc600001f and rejects anything else with HV_BAD_ARGUMENT
  (0xfae94003); a mask-and-compare against 0xffffffe0 compiles
  differently, so the source uses a shift or `& ~0x1f` expression.
  The call itself loads x0-x5 from `input.service`/`input.args[0..4]`,
  executes `hvc #0` and stores x0-x5 into `output.result[0..5]`, then
  returns HV_SUCCESS.  The out-of-line symbol exists in the reference,
  so the definition is `inline` (not `static inline`); an extern
  declaration in `hv_vm.h` stands in for the unrecovered declaration
  site and gives the definition external linkage.
- `hv_get_host_capabilities` (line 121): asserts `caps_buffer != 0` and
  `(caps_buffer & PAGE_MASK) == 0` (kasan descriptor text), translates
  the buffer with `kvtophys()` (line 130:35, column pinned by
  `pmap_paddr_t caps_buffer_paddr = kvtophys(caps_buffer);`), returns
  HV_ERROR (0xfae94001) when the physical address is zero, asserts its
  page alignment (descriptor `(caps_buffer_paddr & PAGE_MASK) == 0`),
  then issues service 0xc6000000 with the physical address and
  `hv_vm_max_permitted_isa()` (zero-extended 32-bit) and returns
  `hv_nested_call(&pnv_args)` directly (the inline call is attributed
  to line 150, column 9, matching `return hv_nested_call(...)`).
- `_hv_vm_destroy` (line 163): drains `vm->map_list_head` with a
  `LIST_EMPTY`/`LIST_FIRST`/`LIST_REMOVE` loop (the source uses the
  bsd LIST macros: entry linkage is `le_next` at +0x18 and `le_prev` at
  +0x20, and the public LIST_REMOVE validation expands to the two
  `ml_fatal_trap_invalid_list_linkage` call sites visible at 168:3),
  `ubc_upl_commit(entry->upl)` (line 169, argument column 25) and
  `kfree_type(hv_map_entry_t, entry)` (line 170, which emits the local
  `kalloc_type_view_170` static that appears in the kasan symbol table
  as `__hv_vm_destroy.kalloc_type_view_170`).  It then issues service
  0xc6000018 with `vm->host_vm_id` (initializer at line 173:26, value
  at 174:12, host_vm_id read at 177:9, call at 181:2), frees the mutex
  with `lck_mtx_free(vm->mtx, &hv_lck_grp)` (line 184; the release
  build inlines lck_mtx_free into `lck_mtx_destroy` plus
  `zfree(KT_LCK_MTX, ...)` while kasan keeps the call) and frees the VM
  with `kfree_type(hv_vm_t, vm)` (line 186, `kalloc_type_view_186`).
- `hv_trap_paravirtualized_nested_service` (line 289): copies the
  96-byte call record in (the `__copyin_chk` inline from
  `libkern/copyio.h` is visible at copyio.h:54), returns HV_BAD_ARGUMENT
  when the copy fails (294:6), accepts only services with the low
  nibble free (`service >> 4 == 0xc600000`, line 300:6, i.e. the
  user-exposed range 0xc6000000-0xc600000f), runs the nested call,
  copies the record back out (copyio.h:63) and returns HV_SUCCESS or
  HV_BAD_ARGUMENT according to the copyout result (the final status is
  a `cmp`/`csel` pair in both images).

Structure fixes carried by this increment: `hv_nested_call_params_t`
was a placeholder pair of pointers and is now the real 96-byte record
(anonymous input { service; args[5] } at 0, anonymous output
{ result[6] } at 48; sizes and member names from the kasan type graph),
and `hv_map_entry_s` now uses `LIST_ENTRY`/`LIST_HEAD` so its 16-byte
linkage matches the recovered `le_next`/`le_prev` members and the
`hv_map_list_s.lh_first` head.

The kasan build's `hv_vm_t` is 56 bytes (user_map at 24, map_list_head
at 48) while the release build's is 48 bytes (user_map at 16,
map_list_head at 40): the kasan configuration adds one pointer-sized
member at offset 16.  The reconstruction follows the release layout.
The release build's `hv_nested_call`/`hv_paranested_...` code paths
were also the template for the local compile check, which reproduces
the service checks (`lsr #5`, `lsr #4`), the hvc register marshalling,
the LIST_REMOVE validation traps and the trap status `csel`.

The reference file also defines
`hv_paranested_virtualization_init_handshake` (line 406); the release
dSYM drops its DIE (LTO inlined the only call into hv_init), so it is
still a stub and must be recovered from the kasan body at
0xfffffe0007b9dc6c.  The local compile harness needed stubs for
Apple's `__builtin_xnu_type_summary`/`__builtin_xnu_type_signature`/
`__builtin_xnu_types_compatible` (used by the kalloc_type macros);
those shims are harness-only and not part of the tree.

The patch series now has 50 entries; 101 explicit stubs remain.


## 2026-11-25: VM creation and the host capability query

`hv_trap_vm_create` (line 190) and `pmap_ipa_size` (line 323) were
recovered, and the nested-call initializers in the whole file were
rewritten to the reference's nested designated-member form.

`hv_trap_vm_create`:

- The creation record is 28 bytes: DWARF gives the packed
  `hv_vm_create_t` size 28 with `min_ipa` at 0, `ipa_size` at 8,
  `granule` at 16, `flags` at 20 and `isa` at 24 (struct at
  hv_interface.h:225, typedef at 231).  The copy-in length is 0x1c in
  both images.  The header now marks the structure packed.
- Order of operations, pinned by line/column pairs: copy-in at 196:6
  (failure returns HV_BAD_ARGUMENT, 0xfae94003, the `sub w19,w19,#2`
  from the entry constant); `hv_vm_allowed(param.isa)` at 200
  (columns 27/7/6 for the isa load, the call and the `!`); the
  `assert(hv_get_support())` at 205 (kasan; the release build compiles
  the assert out, so no code appears); `kalloc_type(hv_vm_t, Z_WAITOK)`
  at 207:7 (`kalloc_type_view_207`), NULL returns HV_NO_RESOURCES;
  `LIST_INIT(&vm->map_list_head)` at 212:2 (store of zero at +0x28 in
  the release layout); the mutex assignment inside the condition,
  `if ((vm->mtx = lck_mtx_alloc_init(&hv_lck_grp, LCK_ATTR_NULL)) ==
  NULL)`, at 215 (columns 17 = callee start, 15 = `=`, 65 = `==`),
  whose failure frees the object at 217 and returns at 218 (same
  HV_NO_RESOURCES); `vm->user_map = get_task_map(current_task());` at
  221 (columns 17 and 30 for the two calls, 6/15 for the member and
  the assignment).
- The nested call record is built with the nested designated form
  `.input = { .service = 0xc6000014, .args = { ... } }` (line 223:37
  is the initializer brace; the service store is attributed to the
  `.input = {` line at 224:12; the args address computations to
  `.args = {` at 226:12; the four arguments share line 227 with
  columns 11/42/57 for `param.min_ipa`, `param.granule` and
  `param.isa`, which places them at four tabs and pins the nesting).
  Only `min_ipa`, `ipa_size`, `granule` and `isa` are forwarded;
  `flags` is not.
- `hv_return_t ret = hv_nested_call(&pnv_args);` is at 231:20 (the
  initializer of `ret`, whose DWARF decl line is 231); the host status
  is then reloaded from `output.result[0]` (kasan 233:22, release
  232:10) and tested as a 32-bit value at 235:10, which is why the
  source casts to `hv_return_t`.  A refused VM frees the mutex at 237
  (`vm->mtx` read at column 20) and the object at 239 before returning
  the host status at 240.
- Success stores `output.result[1]` into `host_vm_id` at 242
  (columns 19/17/6), clears `vcpu_online_mask` at 244 (inline
  `bitmap_zero`, call site 244:2, member column 19), takes `hv_lock`
  at 247:2 and checks `hv_get_vm()` at 249:6: an existing VM is
  destroyed under the unlocked mutex and HV_BUSY returned
  (251:3 unlock, 252:3 destroy, 253:3 return); otherwise
  `os_ref_init_count(&vm->refcnt, NULL, 1)` (257:2),
  `hv_set_vm(vm)` (258:2) and `hv_unlock()` (259:2) complete the
  function, whose closing brace is at 261:1.

`pmap_ipa_size`:

- The statics are at 325-327 (`ipa_sizes_acquired`, `ipa_bits_4k`,
  `ipa_bits_16k`); the function returns 0 without hv support (338) and
  performs the double-checked one-time query under `hv_lock` (339,
  second check 340).
- The capability buffer is a page-aligned kernel allocation:
  `kernel_memory_allocate(kernel_map, &caps_buffer,
  sizeof(hv_capabilities_t), PAGE_MASK, KMA_ZERO, VM_KERN_MEMORY_HV)`
  at 343 (call column 36; the size is 475, the mask 0x3fff and the tag
  0x1c in the image); `hv_get_host_capabilities()` at 350; the
  failure path frees the buffer at 352 and unlocks; the cached widths
  are read from the packed capability structure at offsets 417
  (`ipa_bits_4k`) and 425 (`ipa_bits_16k`), published with a
  release-order byte store, and the buffer is freed at 361; the outer
  unlock is at 363.  The granule switch compares 0x4000 before 0x1000
  and returns `1ULL << bits`.

The reference initializer form was confirmed against `_hv_vm_destroy`
(`.input = {` at 174:12, `.args = {` at 176:12, `vm->host_vm_id` at
177:9) and `hv_get_host_capabilities` (`.input = {` at 138:12, the
`args` block attributed to line 140, and the second argument cast to
uint64_t: the call lands at 146:15, ten columns into the line,
matching `(uint64_t)hv_vm_max_permitted_isa(),` at four tabs).

The patch series now has 51 entries; 99 explicit stubs remain.

## 2026-11-25: the measurement handshake

The release dSYM omits `hv_paranested_virtualization_init_handshake`
and `measurements_compatible` (LTO), so both bodies come from
`kernel.kasan.vmapple` and were cross-checked against
`kernel.development.vmapple` (which also keeps them out of line, though
without DWARF).  The kasan build's DWARF supplies the exact local
lines: 409 `paranested_supported`, 412 `version_call_args`, 423
`version_result`, 428 `selected_version_major`, 435
`intermediate_measurement`, 441/443 the pair size and address, 446
`allocate_retval`, 451/455 `measurement_pair` and its physical
address, 458 `nested_call_args`, the 512 `error` label and the 481
assert.  The assert descriptor at `_hv_paranested_virtualization_init_
handshake.__desc` spells out the recovered text exactly:
`selected_version_major == hv_get_state_version_major(shared_measurement)`.

- The version call uses service 0xc600001a with args {0x300, 0x300}
  (line 412; the two stores at 412:26, the inlined `hvc` at 423:31).
  The reply is tested as `output.result[0]` (424:54) and the raw
  64-bit `output.result[1]` is compared with 0x300 (428:82 loads it,
  429:29 compares it): the kasan and development kernels both emit
  `ldr x, [record, #0x38]; cmp x, #0x300` with no 16-bit truncation,
  so the check is on the full result register even though
  `selected_version_major` is the 16-bit `hv_context_version_major_t`.
  The lookup at 435:64 is folded to the constant 0x300 on the success
  path.
- The measurement pair is a 456-byte zeroed kernel allocation
  (`kmem_alloc_guard` with mask 0x3fff, flags 0x80, tag 0x1c; call at
  446:34, failure return at 448:6).  The guest measurement is copied
  into the first 228 bytes (memmove at 452:28), translated with
  `kvtophys_nofail` (455:51), and the pair's physical address plus the
  456-byte size are passed to service 0xc6000019 (initializer at 458,
  `hvc` at 468:7).  A nonzero `output.result[0]` (469:23) goes to the
  error label.
- The host-filled second measurement is copied out at 473:42 and
  checked by `measurements_compatible` (475:6).  An incompatible pair
  zeroes the shared measurement (476:3, 228 bytes) and leaves through
  the error label; the error path frees the 456-byte pair at 514:12
  and returns at 517:1.
- On success the major-conversion flag is cleared (482:30), the
  context-mismatch flag initialized (495:35), and the loop at 497:2
  walks the 25 entries (`measurement_type[i]` loaded at 498:50 from
  `hv_measurement_type[]`).  Entries whose type is greater than
  `MEASUREMENT_TYPE_RO_CONTEXT` are skipped (500:7); real entries
  compare 8 bytes (505:8, 505:101) and the first difference sets the
  mismatch flag (506:38) and breaks.  The function reports success
  even when contexts differ.
- `measurements_compatible` is at 381 (body brace 383:0) and is a pure
  return expression whose terms the image orders as: `this_size`
  (loads 387:30/387:69, compare 388:9), `measurement_array_size`
  (388:33/389:38, compare 390:9), `measurement_valid(shared)` (call
  390:12, branch 391:9), `version_major` (ldrh 391:33/391:76, compare
  392:9) and the state majors (inlined `hv_get_state_version_major`
  from hv_compat_paranested.h:58-59, compare 393:9; the second call is
  expanded as a 64-bit load plus `lsr #16`).
- `hv_get_state_version_major` is a static inline at
  hv_compat_paranested.h:56 with the assert at 58 and the
  `(hv_context_version_major_t)(arm_hv_state_version >> 16)` return at
  59; the inline's body compiles to a halfword load at +0x16.
- `hv_measurement_type[]` is the 25-entry constant at
  guest_thread_state.h:730 with kinds
  [CONTEXT_ROOT, CONTEXT_ROOT, RW x12, RO x7, SIZE x3, RW]; both local
  copies in the reference image are identical.

The patch series now has 52 entries; 98 explicit stubs remain.

## 2026-11-25: the measurement table and validator

`hv_compat_paranested.c` keeps its native measurement as a static const
record (DWARF decl line 36; `const hv_paranested_measurement_t` through
the release type table).  It lives at `0xfffffe000700b6f0` in the
release image (`0xfffffe000700a3f8` in kasan) and was read out
directly: `this_size` 228, `measurement_array_size` 200,
`version_major` 1, `version_minor` 1, `arm_hv_state_version`
0x2068797003000004, and 25 entries (offset, size):

    0x0000,0x4000  0x4000,0x4000  0x0008,0x0110  0x0140,0x0210
    0x0350,0x0068  0x03b8,0x00d0  0x0488,0x0220  0x06a8,0x0018
    0x0920,0x00e0  0x0a00,0x0008  0x0a08,0x0010  0x0a18,0x0298
    0x1000,0x1000  0x2000,0x1000  0x4000,0x0008  0x4008,0x0028
    0x4030,0x00e0  0x4110,0x0018  0x4128,0x0018  0x4140,0x0010
    0x4150,0x0010  0x0000,0x4000  0x0000,0x1440  0x0000,0x01db
    0x06c0,0x0260

- `hv_get_native_measurement` (line 41) returns the record's address
  (body 43:2).  `hv_get_supported_measurement` (line 47) compares the
  requested major with `hv_get_state_version_major(&native_measurement)`
  at 49 (the `==` operator at column 20, the inlined state-major call at
  49:23 and its `>> 16` at hv_compat_paranested.h:59) and returns the
  record or NULL; the closing brace is 59:1.  The DWARF also records an
  `unsigned int i` at line 53 with no location: the source had a loop
  that the optimizer eliminated completely, so only the comparison is
  observable.
- `hv_get_supported_measurement_nofail` (line 62): the measurement is
  declared at 64:51 (`... = hv_get_supported_measurement(major_version)`);
  the three assert descriptors are `measurement != NULL` (65),
  `major_version == hv_get_state_version_major(measurement)` (66; the
  inline call is at 66:2 and loads the state halfword at +0x16) and
  `measurement_valid(measurement)` (67; out-of-line call), and the
  record is returned at 68.
- `measurement_entry_within_range` (line 72) uses `const size_t
  measurement_start` (75), `size_t measurement_end` (76), `const
  size_t range_start` (77) and `size_t range_end` (78), loads the two
  entry sizes at 81:6 and 84:6, and compares at 88:27/88:42.  Both
  kernels compute 64-bit ends (`add x9,x9,x8`) and return
  `measurement_start >= range_start && measurement_end <= range_end`
  via `ccmp ...,#2,hs` + `cset ls`; the closing brace is 89:1.
- `measurement_valid` (line 92, body 93:0) starts with the ARM state
  signature: the high 32 bits of `arm_hv_state_version` (offset 0x18)
  must equal 0x20687970 (94:6/94:68).  It names the two roots
  `rw_context_measurement` (98) and `ro_context_measurement` (99) and
  requires `rw_context_measurement->size ==
  ro_context_measurement->offset` (the if at 102:30/102:62, compare at
  102:35).  The loop at 106:2 walks the 25 entries with `unsigned int
  i`; `measurement_type` (107) and `measurement_entry` (108) are
  loop-local.  A size of 0xffffffff is skipped (112:31) and a size of
  zero is invalid (the same line's compare); the type dispatch at 122:7
  sends read-write and read-only entries through `context_range` (125)
  and `measurement_entry_within_range` (127:59), and the remaining
  kinds compute a `uint32_t max_size` (132): 0x8000 for
  `MEASUREMENT_TYPE_SIZE`, otherwise the recovered assert
  `measurement_type == MEASUREMENT_TYPE_CONTEXT_ROOT` (descriptor at
  136) precedes 0x10000.  Entries larger than the ceiling fail at
  139:27; the success return and closing brace are at 147:1.  The
  local clang build (bounds-safety flags dropped) folds the const type
  table into bit tests; the reference loads `hv_measurement_type[i]`
  each iteration.
- The handshake state is three statics at lines 172-174, laid out
  consecutively in both kernels (`hv_major_conversion_needed`,
  `hv_context_measurement_mismatch`, `shared_measurement`; the dev
  symbols are local `b` entries at 0x81322f8-fa, release
  0x7da0110-112).  `hv_paranested_virtualization_init` (177) tail-calls
  the handshake with those three addresses (179:9).
- `hv_guest_needs_context_conversion` (184) returns the OR of
  `hv_guest_has_major_version_mismatch()` and
  `hv_guest_has_context_measurement_mismatch()` on one line (calls at
  186:9 and 186:50).  `hv_get_shared_version_major` (190) is the
  inlined `hv_get_state_version_major(&shared_measurement)` (192:9,
  halfword at shared+0x16); `hv_get_shared_measurement` (196) returns
  its address at 198:2; the two predicates return the flags at 204:9
  and 210:9.
- `context_size_from_measurement` is the header's static inline at
  line 73: `rw_context_measurement` (75) and `ro_context_measurement`
  (76) point at the two roots, the descriptor at line 78 is
  `rw_context_measurement->size == ro_context_measurement->offset`,
  and the return at 79 adds the two sizes (columns 33 and 66; the
  inlined instances appear at 76:57, 78:2 and 79:33/40/66).

The patch series now has 53 entries; 92 explicit stubs remain.

## 2026-11-25: the measurement-layout context conversion

`hv_convert_context_from_measurements` (decl line 223) is the static
copier shared by both directions of the guest conversion.  Its
parameters occupy lines 224-230 (src, src_size, src_measurement, dst,
dst_size, dst_measurement, copy_ro) and the body brace is 231:0.

- The three leading assertions are at 233:2, 234:2 and 237:2:
  `src_size == context_size_from_measurement(src_measurement)`,
  `dst_size == context_size_from_measurement(dst_measurement)` and the
  two state version majors.  The inlined context size is compiled as
  `ro_context_measurement->offset + ro_context_measurement->size`
  (`ldp w9,w8,[x,#0x20]` for the root check, then the 0x24/0x28 loads
  and `add w8,w9,w8`), which also pins the header inline's return text;
  both reference kernels inline it the same way.
- The loop at 238:2 walks the 25 entries (the byte index advances by 8
  to 0xc8); `src_entry` and `dst_entry` are the loop-local entries
  (lines 239/240).  A source or destination size of 0xffffffff skips
  the entry (243:18/243:54 and 244:18), and the type dispatch at
  250/251 copies read-write entries always and read-only entries only
  when `copy_ro`; the compiled select is `csel w11, wzr, w6, ne` after
  `cmp type, #2`, so the condition is exactly `type == RW ||
  (copy_ro && type == RO)`.
- The copied entries assert `(src_entry->size != 0) &&
  (dst_entry->size != 0)` (descriptor line 253) and then
  `memmove(dst + dst_entry->offset, src + src_entry->offset,
  MIN(src_entry->size, dst_entry->size))` (254:4, offsets at 254:39 and
  254:81, the minimum at 255:8).  The development kernel calls
  `_memmove`; the kasan build lowers the non-overlapping call to
  `__asan_memcpy`.  The closing brace is 258:1.
- The bounds-safety wide pointers produce the surrounding pointer+size
  pairs and the `ccmp` range checks seen in both kernels.

The patch series now has 54 entries; 91 explicit stubs remain.

## 2026-11-25: convert_context_by_guest (in progress)

`convert_context_by_guest` (decl 261, body brace 262:0, closing brace
312:1) is the only remaining stub in `hv_compat_paranested.c`.  The
recovered frame:

- asserts at 264:2 (`vcpu->kif_shared != NULL && vcpu->kif != NULL &&
  vcpu->kif != vcpu->kif_shared`; the dev build compares
  `[vcpu+0x18]`, `[vcpu+8]` and uses `ccmp ... #4, ne`) and 265:2
  (`direction == NATIVE_TO_SHARED || direction == SHARED_TO_NATIVE`).
- The direction selects four pairs on lines 267-274 and sets
  `copy_ro` at 278:33 (`direction == SHARED_TO_NATIVE`):
    NATIVE_TO_SHARED: src = kif, src_size = 0x8000,
      src_measurement = native_measurement, dst = kif_shared,
      dst_size = kif_shared_size, dst_measurement = shared_measurement;
    SHARED_TO_NATIVE: the reverse pair.
  The compiled selects use `[vcpu+8]` (kif), `[vcpu+0x18]`
  (kif_shared) and `[vcpu+0x20]` (kif_shared_size).
- 280/281 load the two handshake flags (inlined accessors at 204:9 and
  210:9); 282/283 compute the two state version majors (the shared
  side is the halfword at +0x16).  The dev build's decisions are:
    major=0: line 285 onward, then the assert at 304
      (`!major_version_mismatch && context_measurement_mismatch`,
      descriptor 0x...5fc) and, when it passes, the conversion call at
      305 (dev 0x770a5a0-0x770a5b8).
    major=1, context=1: the major-conversion path at 0x770a5fc-0x770a6ec:
      `hv_get_shared_version_major()` (shared+0x16 halfword),
      `hv_get_supported_measurement_nofail(...)` (asserts at 65/66/67,
      returning native_measurement for 0x300), then a
      `hv_convert_context_from_measurements` call through
      `vcpu->kif_intermediate` (`[vcpu+0x28]`, size `[vcpu+0x30]`) and
      the inlined `hv_convert_context_major_version` instances at
      291:4, 296:4, 298:4 and 302:3 (its unsupported-combination
      `assert(false)` is at line 166 and descriptors 0x...624/0x...ac0).
    major=1, context=0: the same inlined major path but without the
      shared-context conversion.
- 307:29 tests `direction == SHARED_TO_NATIVE` and the major flag, then
  310:9/14/21 stores 0x2068797003000004 at `kif + 0x4000` (the start of
  the read-only half of the guest context).

Completing this function needs the major-version converter's body
(decl 157, inlined only) and the intermediate-buffer layout; it remains
a RECON stub until then.

## 2026-11-25: the vCPU destroy and object-free paths

The vCPU teardown in `hv_vcpu_paranested.c` is recovered from the
development symbols and, for the source layout, from the kasan CU's
line table and inline records (the release dSYM carries line tables
only).

- `_hv_free_context` (static, decl 42, brace 43) declares
  `context_size` at 44, asserts `context_size > 0` at 45 (descriptor
  `context_size > 0`) and calls
  `kmem_free(kernel_map, context_addr, context_size)` at 46:12.  The
  inlined size computation is again
  `ro_context_measurement->offset + ro_context_measurement->size`.
- `_hv_vcpu_obj_free` (static, decl 51, brace 52:0) frees the shared
  context at 55:3 with `hv_get_shared_measurement()` (callee at
  55:51), clears `kif_shared_size` (56:25) and `kif_shared` (57:20),
  then, inside the same branch, frees a present intermediate context
  at 62:4 (the `kif_intermediate != NULL` test is at 60:30) using
  `hv_get_supported_measurement_nofail(hv_get_shared_version_major())`
  (61:66/61:102), clearing its size (63:32) and pointer (64:27).  The
  else branch asserts `vcpu->kif_intermediate == NULL` (69:3).  The
  tail deallocates the user mapping with
  `mach_vm_deallocate_kernel(vcpu->vm->user_map,
  (mach_vm_address_t)vcpu->uif, sizeof(arm_guest_context_t))`
  (72:34/72:38/72:2, continuation 73:31) and the kernel context and
  vCPU object with `kmem_free` (75:12/75:43 and 76:12), using
  `sizeof(arm_guest_context_t)` (0x8000) and `sizeof(hv_vcpu_t)`
  (0x40).
- `_hv_vcpu_destroy` (static, decl 80, brace 81:0) builds the nested
  call at 84-92 (`service = 0xc6000012`, `args = { vm->host_vm_id,
  vcpu->id }`; `vm` is read at 82:22), calls it at 93:20, prefers the
  host result when the call succeeded (94:10/95:22), then under
  `hv_vm_lock(vm)` (98:2) asserts
  `bitmap_test(&vm->vcpu_online_mask[0], vcpu->id)` (descriptor line
  99), clears the bit at 101:2 and unlocks (102:2).  The object is
  freed at 103:2 and `ret` returned at 104:2.
- `hv_vcpu_destroy` (decl 108) compiles to a four-byte tail branch to
  the static destroy (110:2).  `hv_trap_vcpu_destroy` (decl 301, brace
  302:0) declares `vcpu` at 303, tests
  `(vcpu = hv_get_vcpu()) == NULL` at 306:29, returns `HV_NO_DEVICE`
  when the thread has no vCPU, destroys it at 311:20 and clears the
  thread target with `hv_set_vcpu(NULL)` at 315 before returning `ret`
  (318:1).
- `hv_trap_vcpu_sysregs_sync` (decl 321, brace 322:0, closing 329:1)
  has no local variables: it calls `hv_get_vcpu()` at 323 and is
  compiled to a `cmp`/`csel` pair returning `HV_NO_DEVICE` when the
  thread has no vCPU and `HV_SUCCESS` otherwise.

The patch series now has 55 entries; 86 explicit stubs remain.

## 2026-11-25: the vCPU creation path

`allocate_context` (static, decl 115, brace 116) takes the context size
and a contiguity flag.  `tag` is declared at 117 and the context
address at 118; `kern_ret` at 120 selects `kmem_alloc_contig` (call at
122:14) or `kmem_alloc` (call at 125:14), both with the 0x8080
KMA_DATA|KMA_ZERO flags and tag 0x1c (VM_KERN_MEMORY_HV).  The failure
branch returns NULL at 129:6, and the assertions at 132:2 and 133:2
are `shared_guest_context_addr` and
`(shared_guest_context_addr & PAGE_MASK) == 0`; the closing return is
at 135 and the brace at 136.

`hv_trap_vcpu_create` (decl 139, brace 140:0) has locals `vcpu` (141),
`vc` (142, a 16-byte `hv_vcpu_create_t` whose members are `id` and
`interface`), `vcp` (143, the user address), `ret` (144, initialized to
HV_NO_RESOURCES), `vm` (163), `context_paddr` (192), the shared
measurement/size/pointer (196/197/198), the intermediate
measurement/size/pointer (208/209/210) and `pnv_args` (225), with the
labels `copyout_failed` (278), `vcpu_hvc_failed` (290),
`context_allocation_failed` (291) and `vcpu_alloc_failed` (294).

- 149:6 copies in the record (16 bytes) and rejects `vc.id` values
  above 0x3f (HV_VCPU_MAX) with HV_BAD_ARGUMENT; 155:6 refuses a
  thread that already has a vCPU (HV_BUSY); 163:16 is
  `hv_vm_t *vm = hv_get_lock_and_reference_vm()` and a NULL VM
  returns HV_NO_DEVICE (164).
- 173 is
  `ret = hv_vcpu_obj_alloc(&vcpu, get_task_map(current_task()), !hv_guest_needs_context_conversion())`
  and its failure jumps to `vcpu_alloc_failed` (174); 179/181 publish
  `vcpu->vm = vm` and `vcpu->id = vc.id`.
- 195 branches on `hv_guest_needs_context_conversion()`: 196/197 take
  the shared measurement and its size, 198 allocates a contiguous
  context (`true`), 199 tests the NULL result, 203/204 store
  `kif_shared_size` and `kif_shared`; 207 requires both
  `hv_guest_has_major_version_mismatch()` and
  `hv_guest_has_context_measurement_mismatch()`, after which 208-210
  take the nofail measurement for the shared major, its size and a
  plain (`false`) allocation, stored at 215/216.  218/222 set
  `context_paddr = kvtophys_nofail((vm_offset_t)vcpu->kif_shared)` or
  `...vcpu->kif`, and the else branch (219-221) clears the shared
  fields.
- 225-233 build the nested call with service 0xc6000011 and
  `{ vcpu->vm->host_vm_id, vcpu->id, context_paddr }`; 236:8 calls it,
  237 and 242 return to `vcpu_hvc_failed` on a call error or a nonzero
  host result (241 loads result[0]).  251/252 mirror the shared
  context with `convert_context_by_guest(vcpu, SHARED_TO_NATIVE)`,
  256 writes `vc.interface = (uint64_t)vcpu->uif` and 258 copies the
  record out.
- On success 264 sets `bitmap_set(&vm->vcpu_online_mask[0], vcpu->id)`,
  268 unlocks the VM, 272 releases it, 275 makes the vCPU the thread
  target and the function returns HV_SUCCESS.
- A copyout failure lands at 278, rebuilds the call record as a
  compound literal (279) with service 0xc6000012 and
  `{ host_vm_id, vcpu->id }`, issues it at 288 and falls through the
  two failure labels into `_hv_vcpu_obj_free` (292); the allocation
  failures reuse the same label.  295/296 unlock and release the VM and
  297 returns `ret`.

The patch series now has 56 entries; 84 explicit stubs remain.

## 2026-11-25: the vCPU run and run-cancel paths

`hv_trap_vcpu_run` (decl 332, brace 333:0) declares `vcpu` at 334 and
checks `hv_get_vcpu()` at 336:6, returning HV_NO_DEVICE, then converts
the context to the shared layout at 342:6/343:3
(`convert_context_by_guest(vcpu, NATIVE_TO_SHARED)`).  The nested call
record (`pnv_args`, 346:26) carries service 0xc6000010 with
`{ vcpu->vm->host_vm_id, vcpu->id }` (the two member loads at 350:11
and 350:15, the id load at 351:11, and the arguments store at 349:12).

The do loop starts at 358:2.  Each iteration issues the call
(359:31), takes `ret` from result[0] (360:22), leaves the loop when
the call itself failed (`if (hypercall_ret)`, 362:7) or when the host
status is nonzero or the second result word is not 0xb (365:46 and
365:49, the 11 compare), and otherwise disables preemption (371:4),
loads `current_thread()->machine.CpuDatap` (372:23), computes
`stay_in_runloop = (pcpu->cpu_pending_ast & ~AST_DEBUG_ASSERT) == 0`
(the 0x4c member load at 373:29 and the 0xff7fffff mask at 373:45),
and enables preemption again (374:4) before the back edge.  After the
loop the context is converted back at 380:6/381:28 and the host status
is returned (389:1).

`hv_trap_vcpu_run_cancel` (decl 392, brace 393:0) declares `vcpu`
(394), `vm` (395), `pnv_args` (406) and `ret` (416).  A thread vCPU
makes `vm = vcpu->vm` (the member load at 401:14, the join at 402:2);
without one the VM is looked up and referenced with
`hv_get_and_reference_vm()` (the inline's hv_lock/hv_get_vm/
hv_reference_vm/hv_unlock sites are hv_internal.h:158:2, 159:7, 161:3
and 163:2), returning HV_NO_DEVICE when there is no VM.  The record
uses service 0xc6000013 with `{ vm->host_vm_id, arg }` (410:9 and the
argument store at 409:12), the call is made at 416:20, result[0] is
taken under `if (!ret)` (417:6/418:22), and the VM reference is
released at 422:3 only when the vCPU was absent.  The return is at
426:1.

The release, development and kasan builds agree on the service
constants, the 0xb re-entry reason, the 0xff7fffff AST mask and the
VM-reference handling.  The kasan `hv_vm_t` places `host_vm_id` at
0x28 (its layout is 8 bytes larger than the release object, whose
host_vm_id is at 0x20); the reconstruction follows the release layout.

The patch series now has 57 entries; 82 explicit stubs remain.

## 2026-11-25: the nested-space block mapper and map-list helpers

The public tree ships `tests/unit/hypervisor/hv_space_paranested_test.c`,
which mocks `upl_phys_page`, `vm_map_create_upl`, `hv_call` and
`ubc_upl_commit` and pins the semantics below; the reference kernel
agrees with the tests line for line.

`hv_call` (decl 60) enters the host with the service in x0 and the
five arguments in x1-x5 (the asm is line 63 and `ret_code` is line
62); the host status is x0 and its second result is stored through
`ret_val`.

`nested_space_map_block` (decl 108) asserts `size && *size`,
`start_offset < PAGE_SIZE` and `physical_memory_info` (lines 110-112).
It reads the first page's pfn at 117, takes the first chunk's physical
address and guest address at 124/125 and its size as
`MIN(remaining_size, PAGE_SIZE - start_offset)` at 127.  The loop at
132 walks `upl_page_index` (131) with `upl_phys_page` (133), rejects a
zero pfn (134), counts the page index (139), and compares
`candidate_pa` (142) against the running block end (146): contiguous
pages extend `contiguous_chunk_size` (148), while a break flushes the
block with VMAPPLE_NESTED_SPACE_MAP (the inner `ret` at 151, checked
at 152), advances `mapped_size` (157) and re-bases the next block's
guest address at 162.  The final block is flushed at 168 and the
assert at 175 checks that the caller's size was fully mapped.

`add_map_entry` (decl 280) allocates a zeroed `hv_map_entry_t` at 284,
returns false on allocation failure, stores `upl`, `ipa` and `size` at
288/289 and inserts the entry at 291.  The caller commits the UPL when
the entry cannot be recorded.

`commit_map_entries` (decl 297) takes the VM lock at 299 and moves
every entry from the temporary list to `vm->map_list_head` at
300-303, then unlocks at 305.  `rollback_map_entries` (decl 310) asks
the host to unmap the already-processed guest bytes with
VMAPPLE_NESTED_SPACE_UNMAP at 314 when any were mapped, then commits
and frees every remaining entry (317-321).

`_hv_nested_space_unmap` (decl 404) searches the VM's map list under
the lock (417-419, matching the item's exact ipa and size), removes,
commits and frees the matching entry (425-427), unlocks at 429 and
returns the VMAPPLE_NESTED_SPACE_UNMAP host status at 430.  A missing
entry is not an error.  The release and kasan builds place the
bookkeeping at the same lines; kasan's larger `hv_vm_t` only moves
`host_vm_id` and `map_list_head` by 8 bytes.

The patch series now has 58 entries; 76 explicit stubs remain.

## 2026-11-25: the nested-space map operation and mach_vm_protect_kernel

The kasan build keeps a `mach_assert_default` descriptor for every
assert in `create_upl_chunk`, and each descriptor's expression text is
the exact source line; the disassembly resolves the rest.

`create_upl_chunk` (decl 181, `static`, parameters at 181-183):

- 185: `map = current_thread()->map`; 186 `prot = VM_PROT_NONE`;
  187 `entry_end = 0`; 188 `kr = hv_map_lookup_protection(map,
  current_uva, &prot, &entry_end)`; a nonzero result returns HV_ERROR
  (189).
- 198: `assert(entry_end > current_uva)`.
- 199: `remaining_size = MIN(remaining_size, entry_end - current_uva);`
  - the parameter is reassigned, and the descriptors at 254
  (`*upl_chunk_size <= remaining_size`) and the compare at 268 show
  that all later uses read the bounded value.  The earlier reading of
  199 as a `*chunk_mapping_size` store was wrong.
- 201: `*upl_chunk_size = (upl_size_t)MIN(remaining_size,
  UPL_SIZE_MAX)`, with UPL_SIZE_MAX = `UINT32_MAX & ~PAGE_MASK`
  (0xffffc000).
- 220: `if (prot & VM_PROT_EXECUTE) return HV_ERROR;` - an executable
  range cannot be made writable (226) without breaking its code
  signature.
- 223: `need_protect = (prot & VM_PROT_WRITE) == 0`; 224:
  `const upl_size_t protect_size = *upl_chunk_size`.
- 225/226: when the range is not writable, `mach_vm_protect_kernel(
  map, current_uva, protect_size, FALSE, prot | VM_PROT_WRITE)`;
  failure returns HV_ERROR (227).
- 232/233: `upl_flags = UPL_SET_INTERNAL | UPL_SET_IO_WIRE` (0x1040),
  `upl_count = 0`.
- 235: `assert((current_uva & PAGE_MASK) == 0)`; 236:
  `assert((*upl_chunk_size & PAGE_MASK) == 0)`.
- 237: `upl_kr = vm_map_create_upl(map, current_uva, upl_chunk_size,
  upl, NULL, &upl_count, &upl_flags, VM_KERN_MEMORY_HV)`.
- 240-247: the previous protection is restored (the same guard);
  when that fails, the UPL is committed if it was created (243/244)
  and HV_ERROR is returned.
- 250/251: a failed UPL creation returns HV_ERROR.
- 253-255: the descriptors give the exact text:
  `assert(*upl_chunk_size != 0)`,
  `assert(*upl_chunk_size <= remaining_size)`,
  `assert((*upl_chunk_size & PAGE_MASK) == 0)`.
- 257-259: `if (upl_flags & UPL_PHYS_CONTIG)` - the flags word is
  rewritten by vm_map_create_upl to the object-kind bits - commits
  the UPL and returns HV_ERROR; a physically contiguous object has no
  internal page list to hand to the block mapper.
- 264: `assert(*upl_chunk_size > first_page_offset)`; 265:
  `*chunk_mapping_size = *upl_chunk_size - first_page_offset`.
- 268-270: when `remaining_size == *upl_chunk_size` the window ends
  inside this chunk, so `assert(*chunk_mapping_size >
  last_page_trim)` and `*chunk_mapping_size -= last_page_trim`.
- 273: `assert(*chunk_mapping_size > 0)`; 275 returns KERN_SUCCESS.

`mach_vm_protect_kernel` is a reference-only kernel helper: the
release DWARF places it at `osfmk/vm/vm_kern.c:1572` with a 136-byte
body that is the user-side `mach_vm_protect` body moved down -
`map == VM_MAP_NULL` gives KERN_INVALID_ARGUMENT, a zero size gives
KERN_SUCCESS, and anything else tail-calls `vm_map_protect` with the
sanitized end.  The patch adds the body to vm_kern.c next to
`mach_vm_deallocate_kernel` and its declaration to vm_kern_xnu.h.

`_hv_nested_space_map` (decl 326) is now decoded as well: 330-334
reject a size that overflows the IPA or is zero, 339-341 compute
`region_end` with the UVA overflow check, 344/349 align the range,
350/351 split out `first_page_offset` and `last_page_trim`, 353-357
initialize the temporary list and the cursor variables.  The loop
(362) creates the chunk (367, `kr`), rolls back on failure (368-371),
records the entry (373/376 commit the UPL when the entry cannot be
allocated), maps the block (384 passes `mi->flags`), accounts the
guest bytes mapped so far (385), rolls back the mapped range on
failure, and advances `remaining_aligned_size` and `current_uva` by
the UPL window (393/394) while advancing `current_ipa` by the size
actually mapped (395) - the guest range stays contiguous across the
trimmed page partials - then clears `first_page_offset` (396).
Success publishes the list with `commit_map_entries`.

`_hv_space_map_op` (decl 436) copies in the 40-byte item (438),
accepts only asid 0 or UINT64_MAX (447; the latter only with a current
vCPU), references the VM (452), dispatches UNMAP/PROTECT/MAP at the
switch on 468 (protect call at 475, map call at 481), panics on an
unexpected function (486) and releases the VM (488).  `hv_space_map_op_nested` (decl 491) tail-calls it.

The patch series now has 59 entries; 73 explicit stubs remain.

## 2026-11-25: the hypervisor context conversion path

`convert_context_by_guest` (decl 261) was the last hypervisor stub.
It converts the guest's saved context between the native and shared
layouts and is reached only when `hv_guest_needs_context_conversion()`
is true.  The kasan line table, the argument/column rows and the
release build's inlined code together give the full structure.

- 264/265: the two assertions, exactly as their `mach_assert`
  descriptors read: `vcpu->kif_shared != NULL && vcpu->kif != NULL &&
  vcpu->kif != vcpu->kif_shared` and
  `direction == NATIVE_TO_SHARED || direction == SHARED_TO_NATIVE`.
- 267/268: `src` and `dst`, `vcpu->kif`/`vcpu->kif_shared` swapped by
  direction (rows 267:58/64/70 and 268:46/52/65/71 are the two
  branches and their `+ 0x8000` end computations).
- 270/271: `src_size` and `dst_size`: the kernel interface frame is
  0x8000 bytes (the selection blocks add the immediate), the shared
  side uses `vcpu->kif_shared_size`.
- 273/274: `src_measurement`/`dst_measurement`, pointing at
  `native_measurement`/`shared_measurement` according to direction.
- 278: `copy_ro = direction == SHARED_TO_NATIVE`; the comparison
  operator is at column 33, so the declaration is
  `const bool copy_ro = ...` without parentheses.
- 280-283: `major_version_mismatch`, `context_measurement_mismatch`,
  `src_version_major`, `dst_version_major`.  The DWARF call columns
  (280:38, 281:44, 282:55, 283:55) only line up for `const bool` and
  `const hv_context_version_major_t` declarations, which fixed those
  spellings (`bool` is `_Bool` in the DWARF either way).
- 285: `if (major_version_mismatch && context_measurement_mismatch)`;
  the `&&` is at column 29 of the source line.
- 289: `intermediate_measurement =
  hv_get_supported_measurement_nofail(hv_get_shared_version_major())`.
- 290: `if (direction == NATIVE_TO_SHARED)`, operator at column 17.
- 291: `hv_convert_context_major_version(src, src_version_major,
  vcpu->kif_intermediate, dst_version_major, copy_ro)`.  The kasan
  argument checks sit at 291:37 (`src`), 291:61 and 291:67 (the
  `vcpu->kif_intermediate` wide pointer and its member), fixing the
  argument order and columns.
- 293: `hv_convert_context_from_measurements(vcpu->kif_intermediate,
  vcpu->kif_intermediate_size, intermediate_measurement, dst,
  dst_size, dst_measurement, copy_ro)`.  The release build inlines it
  at call line 293 with src = x22 = `kif_intermediate`, src_size = x21
  = `kif_intermediate_size`, dst = x19 = `kif_shared`, and the
  intermediate measurement as the source measurement.
- 296: the reverse conversion,
  `hv_convert_context_from_measurements(src, src_size,
  src_measurement, vcpu->kif_intermediate,
  vcpu->kif_intermediate_size, intermediate_measurement, copy_ro)`;
  the kasan row 296:79 is the member access of the fourth argument on
  the call line.
- 298: `hv_convert_context_major_version(vcpu->kif_intermediate,
  src_version_major, dst, dst_version_major, copy_ro)`; rows
  298:37/43 fix the first argument and its member, row 298:80 fixes
  `dst`.
- 300/302: major-version-only mismatch,
  `hv_convert_context_major_version(src, src_version_major, dst,
  dst_version_major, copy_ro)` (rows 302:36 and 302:60).
- 304: `assert(!major_version_mismatch &&
  context_measurement_mismatch)` for the measurement-only case; the
  descriptor text matches.
- 305: the direct `hv_convert_context_from_measurements(src, src_size,
  src_measurement, dst, dst_size, dst_measurement, copy_ro)`.
- 307: `if (major_version_mismatch && direction ==
  SHARED_TO_NATIVE)`; the `&&` is at column 29, which fixes the
  operand order.
- 310: `vcpu->kif->ro.ver = ARM_HV_STATE_VER`.  The store is
  `str 0x2068797003000004, [kif + 0x4000]`; the DWARF kernel interface
  frame type has the `ro` union at 0x4000 and `ver` as its first
  member, and the source columns 9/14/21 are `kif`, `ro` and the
  assignment.

The helper (decl 157) is `static inline void
hv_convert_context_major_version(const void *src,
hv_context_version_major_t src_version_major, void *dst,
hv_context_version_major_t dst_version_major, bool copy_ro)`.  Its
abstract DIE lacks `DW_AT_external`, unlike every external inline
helper in the file, and the image has no symbol for it; at its three
call sites the only emitted code is the trap for the line-166
`assert(false)` descriptor.  In the release kernel `assert()` is
empty (`osfmk/kern/assert.h` defines it as `((void)0)` without
MACH_ASSERT), so the panic disappears and the release build executes
the explicit `kif_intermediate` conversions instead: its inlining
tree has exactly three `hv_convert_context_from_measurements` sites,
at call lines 293, 296 and 305, and no helper trap.

The release build of the recovered function now matches that
behaviour, and the kasan/dev build of the helper emits the same
`false` descriptor and three `brk #0xbffc` sites as the reference.
The header was corrected at the same time: `hv_get_state_version_major`
has no `assert(measurement)` (its inlined body is a single `ldrh`),
`ARM_HV_STATE_VER` is defined from the public unit-test mock's use,
and the read-only context root carries its recovered members
(`ver`, `exit`, `controls`, `state`, `ich`, `sme_state`, `misc`).

The patch series now has 60 entries; 72 explicit stubs remain.

## 2026-11-25: the page telemetry ring

`osfmk/vm/vm_page_telemetry.c` and its header are new in 13432.  The
whole translation unit was recovered from the kasan CU (which records
line and column for every inlined call), the development symbol table
and the release image.

Types and data.  The event enumeration is a 64-bit
`__enum_decl(vm_page_telemetry_event_t, uint64_t, ...)` with
`VMPT_DISABLED = ~0` and fifteen documented events.  The ring entry is
160 bytes: code at 0, subcode at 8, kext_timestamp at 16, frame_count
(`unsigned int`) at 24, frames[16] at 32.  The CoreAnalytics events are
`vm_page_event` and `vm_page_event_internal`, both 660 bytes
(backtrace[388], kext_ids[256], code, subcode), and
`vm_zero_wired_pages`, 182 bytes (process_name[17],
process_signing_id[128], process_uuid[37]).  The format strings read out
of the image are exactly `com.apple.xnu.vm_page_event`, `...internal`
and `...vm_zero_wired_pages` followed by the type/field pairs.  The
statics are the 4096-entry uint32 dedupe table, the disable and
disable-reported bytes, the lock group and spin lock, the 32-entry ring,
its size_t read/write/count indices and the drain thread call.  The lock
group name comes from its startup spec in the image and is
`vm_page_telemetry`, not `vmpt_lock`.

The drain path.  `vmpt_hash` runs the Jenkins update over the eight
bytes of code, the eight bytes of subcode and `frame_count * 8` bytes of
frames, finishes, and forces a non-zero result (`h ?: 1`) because zero
is the dedupe table's empty marker.  `vmpt_is_duplicate` probes
`probe & 0xfff` starting at the hash for at most 128 steps and stops at
the hash (duplicate), at zero (free slot) or at the limit;
`vmpt_mark_duplicate` repeats the probe and installs the hash with a
compare-and-swap, returning false only when the limit expires.
`vmpt_enqueue` takes the lock, rejects the entry when the ring is full,
admits only one `VMPT_DISABLED` event, appends, and enters the drain
thread call only once `startup_phase >= STARTUP_SUB_THREAD_CALL` (the
reference compares `_startup_phase` with 15).  The drain callback
allocates its call with `THREAD_CALL_PRIORITY_KERNEL` and
`THREAD_CALL_OPTIONS_ONCE` and panics with the reference message when
that fails.  It drains the ring in batches taken under the lock,
formatting and sending with the lock dropped.

Event conversion.  `vmpt_send_ca_event` only resolves kexts while
`entry->kext_timestamp == gLoadedKextSummariesTimestamp`, collects up to
four distinct `loadTag`s, joins their names with `,` into the 256-byte
identifier buffer, then fills code/subcode and sends.  The allocator
uses `Z_WAITOK_ZERO` (the image passes 4) and, in
`DEVELOPMENT || DEBUG`, selects the internal event name for codes of
100 and above; the internal name string is absent from the release
kernel, which fixes that guard.  `vm_page_telemetry_emit` reports the
disable event when the latch is set, starts the backtrace from
`__builtin_frame_address(0)`, stamps the summary generation, drops
duplicates, enqueues, marks, and latches `vmpt_disable` when the table
has no room.  `vm_page_telemetry_emit_zwp` reports the current process'
name, signing identity and executable UUID.

Source shape.  The header declares the two-argument emit at line 154
and a one-argument `static inline` at 157-161 marked
`__attribute__((overloadable))`.  Clang accepts that alongside the
plain two-argument declaration: one-argument calls inline to a forward
with subcode 0 while the two-argument symbol stays unmangled (verified
with a local clang experiment).  The panic macro in `kern/panic_call.h`
appends `" @%s:%d"` with `__FILE_NAME__` and `__LINE__`; the reference
string has one suffix, so the source passes only the message, and a
`#line` directive keeps the reference's line 373 in the message.
Column evidence fixes several spellings: the emit conditions at 444:6,
465:6, 469:7 and 478:7 (`if (vmpt_disable)`, `if
(vmpt_is_duplicate(hash))`, `if (!vmpt_enqueue(&entry))`, `if
(!vmpt_mark_duplicate(hash))`); the kext loop header at 288:39/51 and
289:46 (`i < entry->frame_count && seen_count < 4`); and the drain loop
at 342:24 (`while ((drain_count = vmpt_ring_count) != 0)`).

The file compiles with the reference RELEASE flags.  The emitted
CoreAnalytics format strings, the 160/660/182-byte structures, the panic
string and the startup-phase check match the reference image, and the
patch applies to the series with an identical tree hash.

## 2026-11-25: the COW-defeatured guard counters

`osfmk/vm/vm_cow_defeatured_telemetry.c` is recovered in patch 62.  Its
CU names the file `vm_cow_defeatured_telemetry.c` and declares the
private type `vm_cow_defeated_guard_count` (struct) /
`vm_cow_defeated_guard_count_s` (typedef): `next` at offset 0,
`proc_name_t name` at 8 and `uint8_t event_counts[3]` at 41, 48 bytes
total.  The initializer at 109 allocates it with
`kalloc_type(..., Z_WAITOK_ZERO)` (the view symbol is
`_vm_cow_defeated_get_or_insert_entry.kalloc_type_view_109`, the size
field 48), copies the name with `strlcpy` and pushes the entry on
`guard_count_head`.

The statics fix the file's shape: the TUNABLE at line 69 is
`vm_cow_defeated_soft_report_limit`, the startup spec name string is
`"vm_cow_defeated_soft_report_limit"`, the length is 1 and the initial
byte in the reference image is 10; the auto-startup entry symbols are
suffixed 70, 75 and 77, which pins the two-line invocations.  The lock
group is `vm_cow_defeated_telemetry_lock_grp` with name
`"vm_cow_defeated_telemetry_lock"` (read from the `lck_grp_spec` in
`__BOOTDATA,__init`), and the mutex is `LCK_MTX_DECLARE`d against it.
`guard_count_head` is at line 80.

The three signatures are at reference lines 88 (static inline
`vm_cow_defeated_get_or_insert_entry(char * name)`), 120 (static inline
`vm_cow_defeated_get_responsible_map_info(vm_map_t *, char *, size_t)`)
and 145 (global `vm_cow_defeated_soft_mode_report(
virtual_memory_guard_exception_code_t, uint64_t)`).  The kasan build
keeps `current_task`, `get_task_map`, `task_best_name` and the
`lck_mtx` calls out of line, so the bodies call exactly those helpers.
The report checks `event_idx = guard_code -
kGUARD_EXC_COW_DEFEATURED_FIRST` with the descriptor string
`event_idx < VM_COW_DEFEATURED_GUARD_COUNT` (line 157), takes the
responsible map and name, locks, inserts, reads the old counter, bumps
it while `send_guard` holds, unlocks and only then calls
`vm_map_guard_exception(map, fail_info, guard_code)` (line 182).

`vm_map.c` sees the report declared in
`vm_cow_defeated_telemetry.h` at line 44; the only caller is
`vm_map_policy_handle_cow_defeated_fail`, whose direct `bl` to the
report is at fffffe00078e6b98 in the kasan image.  The patch adds that
header at the recovered line.

The guard enumeration in the reference `vm_statistics.h` is extended:
`kGUARD_EXC_COW_DEFEATURED_COPY_DENIED` = 13, `..._EXTRACT_DENIED` =
14 and `..._SHARE_MAP_AS_COPY_DENIED` = 15, with `..._FIRST`/`..._LAST`
aliases; `kGUARD_EXC_LARGE_ALLOCATION_TELEMETRY` moves from 13 to 16,
and `VM_COW_DEFEATURED_GUARD_COUNT` is derived from the FIRST/LAST
aliases.

One codegen detail could not be reproduced in the reconstructed source:
the reference compares the old counter against the *low byte* of
`limit - 1` (`sub w10,w10,#1; cmp w9,w10,uxtb; b.ls`), while the line
table places the limit token at column 33 and the subtraction at
column 69, which matches the plain text
`event_old_count < vm_cow_defeated_soft_report_limit - 1` after the
correct 35-character identifier.  The recovered source therefore keeps
`event_old_count <= vm_cow_defeated_soft_report_limit - 1`; it behaves
identically for every limit except 0, where the reference's uint8_t
truncation keeps reporting.

The guard check at line 157 survives in the RELEASE kernel as a trap with its descriptor (`event_idx <
VM_COW_DEFEATURED_GUARD_COUNT`, file vm_cow_defeatured_telemetry.c,
line 157), although the translation unit's flags do not define
MACH_ASSERT and plain assert() therefore compiles away.  The check is
a release_assert(), which is always active; a local compile reproduces
the `sub w?,#13; cmp w?,#3; b.hs; adrp/add __desc; brk #0xbffc` shape
and the descriptor contents.

The patch compiles with the reference RELEASE flags and applies to the
series with tree hash 706980d57c2378460e79a8734a6fe3730f763dc5.

The patch series now has 62 entries; 59 explicit stubs remain.

## 2026-11-25: the OS metric encoder

Patch 63 recovers the production half of `libkern/os/metric.c` (five
functions) and the record layout in `libkern/os/metric_types.h`.

The reference metric.c CU declares `os_log_disabled(void)` at line 50
(extern, declaration only), `_os_metric_disabled` at 58 (static,
inlined at every call), `_os_metric_get_bins` at 64 (static),
`_create_os_metric_from_parts` at 74 (static), `_send_os_metric_to_log_queue`
at 136 (static) and the external `os_metric_coprocessor` at 187.  The
kasan image keeps out-of-line copies of `_create` (0x9270ddc) and
`_send` (0x927156c); the RELEASE image inlines all three statics into
`os_metric_coprocessor` at 0x7adf830 (1092 bytes).

The record types pin the layout in metric_types.h: the 16-byte
`_os_metric_metadata_s` (type 0, base_type 1, level 2, unit 3, scale 4,
bins 5, interval 8, flags 12), the 8-byte value, the 48-byte basic and
88-byte detail stats, the 32-byte `os_metric_label_s` and the 16-byte
`os_metric_dimensions_s`.  `_os_metric_get_data_size` is the static
helper at line 193; its expression is
`sizeof(value) + level * (sizeof(basic) - sizeof(value))`, which the
kasan build folds to `umull 40*level; add #8; cmp #3; csel lo`
with the metric_types.h row at 196:2.

The statement lines follow the kasan line table exactly: locals at
86-89 (`buffer_size`, `data_size`, `bin_size`, `p`), 121-123 (`dlist`,
`current`, `size`), `safe` 138, `pubdata` 150, `ctx` 151, `ns` 163,
`flags` 164, `trace_id` 169, `log` 173; the coprocessor's `buffer`
189, `buff_size` 190, `sid` 191, asserts 193-195, `_create` call 198
and `_send` call 201.  The assert descriptors carry the exact
expressions (`buffer_size + data_size` at 97, `buffer_size + bin_size`
at 107, `buffer_size + label->blob_size` at 114, `buffer_size + size`
at 124, `p - (uint8_t *)buffer` at 132, `num_bins != 0` at 67 and
`metadata`/`data`/`label` at 193-195).

Behaviour recovered from the images:

- `_os_metric_disabled` returns
  `os_log_disabled() || (atm_get_diagnostic_config() & ATM_TRACE_OFF)`
  (`tbnz w0,#0` and `tbnz w0,#10` in the kasan copy).
- `_create_os_metric_from_parts` copies the 16 metadata bytes, then the
  level-sized data payload, the histogram bins from the bytes that
  follow the data in the caller's record (only when `bins != 0`, with
  the `type != histogram` panic), the label blob and each dimension
  blob, checking every append against `OS_METRIC_MAX_DATA_SIZE`
  (1000) and finishing with `*buf_size` and the pointer-difference
  assert.  The panic string is `Metric had multiple bins but was %d
  NOT a histogram type!` at metric.c:105.
- `_send_os_metric_to_log_queue` drops the record when the log system
  is unsafe (`oslog_is_safe()` or startup phase <= 18) or disabled, or
  when the buffer exceeds 1000 bytes, incrementing
  `oslog_p_metric_dropped_msgcount`.  It initializes a 1024-byte
  `OS_METRIC_BUFFER_MAX_SIZE` context, encodes the metric body with
  `os_metric_context_encode(...,"%s","")`, builds the trace id with
  namespace 8, the base type in bits 8-15, the flags 0x100a (0x120a
  once `os_log_subsystem_id_valid(sid)`), the offset in the high word
  and the code in the low byte, fills a zeroed `log_payload_s`,
  initializes it for stream 7 with the encoded content size, and hands
  it to `log_queue_log`.  The context is freed on both exits and the
  function returns the payload result.
- `os_metric_coprocessor` asserts metadata/data/label, builds the
  record in a 1024-byte zeroed stack buffer, sends it with the
  metadata base type and returns `!ret`, which the release image
  computes with `eor w19,w20,#1`.

The metric-specific buffer constants are not the public
`OS_LOG_BUFFER_MAX_SIZE` (256): the reference uses 1024 for the
context/public buffer and 1000 for the data limit.  The counter
startup entries are
`__startup_TUNABLES_entry_scalable_counter_static_boot_mangle_48` and
`__startup_PERCPU_entry_scalable_counter_static_init_48`, pinning
`SCALABLE_COUNTER_DEFINE(oslog_p_metric_dropped_msgcount)` at line 48.

The DEVELOPMENT-only unit tests (reference lines 211-750) are not
reproduced; they are compiled out of the RELEASE kernel and their bodies
depend on the test harness.

Compiler-version artifacts: Apple clang attributes comparisons to the
operator column (103:16/21, 120:17, 144:15) while clang 19 attributes
them to the left operand (103:6, 120:6, 144:6); the inline size helper
is 196:2 in the reference and 196:6 here, and
`(char *)data + data_size` is 68:31 versus 68:30.  The source line
layout itself matches the reference row for row.

The patch compiles with the reference RELEASE flags and applies to
the series with tree hash 6b4fc9810ec9baff700c0e3cbbeeb4c721cc7e4e.

The patch series now has 63 entries; 54 explicit stubs remain.

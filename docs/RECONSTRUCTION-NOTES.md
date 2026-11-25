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

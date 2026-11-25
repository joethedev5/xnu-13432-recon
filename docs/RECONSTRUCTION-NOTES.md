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

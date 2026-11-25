# xnu-13432 reconstruction patches

These patches turn the public `apple-oss-distributions/xnu` tag
`xnu-12377.121.6` into the reconstruction of `xnu-13432.1.9`
(RELEASE_ARM64_VMAPPLE, macOS 27.0.1 build 26A434) developed in this
project.

Apply in numeric order from a clean checkout:

```
git checkout xnu-12377.121.6
git am 0001-*.patch ... 0060-*.patch
```

Contents:

1. New BSD syscalls and the x86_64-compat Mach trap, with validated
   `makesyscalls` output.
2. The 56 translation units present in the reference DWARF but absent
   from the public tree (464 functions; 91 bodies relocated from the
   public tree, explicit `RECON` stubs elsewhere).
3. Disassembly-recovered bodies for the smallest 64 stubs.
4. The 30 reference-only headers derived from the DWARF type graph.
5. `tcp_rbbr_rwnd_init` and the missing `tcpcb.t_rbbr_state` member.
6. Relocation of the VM map store types into
   `vm_map_store_types_internal.h`.
7-20. RBBR state management, tunables, utilization/RTT-median and
   phase-log code, `tcp_tfo_process_last_ack`, VM page telemetry
   init, the receive-window selector and its SYN-ACK call site, the
   AccECN/ECN heuristic functions, and the TFO faulty-middlebox path.
21-22. The per-CPU advanced TCP timer subsystem: the recovered
   `tcp_timer_advanced.c`, its inline header API, the new
   `tcpcb.t_timer_entries[]` array and the two reused `t_flags`
   bits.
23. The ECN handshake and feedback paths in `tcp_ecn.c`, including
   the 13432-only `TE_SEND_ECT1` branch.
24. The TCP Fast Open translation unit and its crypto context.
25. The `tcp_seg_sent` RB tree generator (`RB_GENERATE`).
26. The spurious/early retransmit recovery paths in `tcp_recovery.c`.
27. The RTT helpers and `tcp_compute_rxmit_time` in `tcp_rtt.c`.
28. The RBBR phase transitions and cruise backoff.
29. The virtual-environment object: lifecycle, lazy Mach port
    kobject, no-senders callback, MIG entry points, path copy-in and
    the development-variant availability policy.
30. The remaining AccECN acknowledgement paths: SYN-ACK dispatch and
    helpers, last-ACK response, the ACE and option decoders moved out
    of `tcp_input.c`, and the ECN marking helpers.
31. The reference TCP receive accounting: `total_packets_received`,
    `t_recv_bg_algo`, and the move of ECN feedback dispatch into
    `tcp_ecn.c`.
32. The process virtual-environment integration: `proc.p_virtual_env`,
    fork/exit/exec lifetime, the posix_spawn subsystem-root creation
    path and the `PSPA_VIRTUAL_ENV` port action.
33. The TCP proportional-rate-reduction unit and the missing
    `tcpcb.prr` state at offset 1384.
34. The TCP window scale helpers `tcp_set_window_scale` and
    `tcp_window_scale`, and their use from the SYN and SYN-ACK
    receive paths.
35. The TCP reassembly helpers (`tcp_reass_create_qent`,
    `tcp_reass_destroy_qent`, `tcp_reassq_free`), the external
    linkage of the moved reassembly, option-parsing and TFO
    functions, and the removal of the public duplicate bodies.
36. The TCP socket-buffer helpers and the recovery of
    `tcp_sbrcv_min_rwin`.
37. The RACK segment-allocation failure path
    (`tcp_seg_free_and_disable_rack`).
38. `struct tcp_context` and `tcp_socket_exists_for_tuple`.
39. The reference delayed-ACK policy in `tcp_ack.c` and the removal
    of the per-algorithm delay-ack hooks.
40. The exec security configuration: hardened-browser entitlement
    parsing, platform restrictions, the platform-binary task flag,
    IPC containment and WebKit signing-id detection, the IPC security
    policy hook, and the VFS resolve-flags entitlement, together with
    the new load-result state byte, task security bits and proc VFS
    resolve flag fields.
41. The remainder of the PRR integration: the duplicate-ACK
    `tcp_prr_update` call and the `tp->prr.out` transmit accounting in
    `tcp_output`.
42. The RBBR phase machine: the PROBE_RTT round analysis, the
    PROBE_RWND growth/hold/exit paths, the CRUISE sawtooth and
    backoff accounting, RTT sampling and the data-received gate,
    plus the helper-based enter/backoff refactors and the
    `cycle_measure_ts` duration measurement.
43. The threadpair wait-owner path: the `kThreadWaitThreadpair`
    block hint, `kdp_threadpair_find_owner` and the stackshot
    dispatch, plus `TURNSTILE_THREADPAIR` in the turnstile enum and
    both policy tables.
44. The AMCC RORGN/PV CTRR path: `rorgn_contains`,
    `rorgn_stash_range`, the MMU lockdown/validation helpers and
    `pv_ctrr_init`, with the recovered PV CTRR register definitions.
45. The ARM feature detection: the `ARM_FEAT_*`/`ARM_SME_*` static_if
    key definitions in `osfmk/arm/arm_features.inc`, the Apple AIDR
    keys in `osfmk/arm/apple_features.inc`, the per-register init
    routines and static_if initializers in `osfmk/arm64/cpu_features.c`,
    and the new 13432 ID-register field definitions in
    `arm64/proc_reg.h`.
46. The kernel-side hypervisor support layer: `hv_support_available`,
    `hv_disable`, the boot-time `hv_support_init`, and the task/thread
    target accessors in the new `osfmk/kern/hv_support_kern.c`, with
    `hv_support_kern.h` and the first part of `osfmk/arm64/hv/hv.h`.
47. The hypervisor trap path: `hv_init`, `_hv_trap_capabilities`, the
    19-entry `_vm_trap` dispatch table, `hv_trap` and the vCPU/VM
    destroy callbacks in `osfmk/arm64/hv/hv.c`, plus the hypervisor
    return codes and the new `hv_vm.h`, `hv_vcpu.h` and
    `hv_compat_paranested.h` declarations.
48. The hypervisor VM object policy and lookup helpers in
    `osfmk/arm64/hv/hv_vm.c`: the shared-lock protection lookup,
    `hv_trap_vm_destroy`, `hv_vm_destroy`,
    `hv_vm_max_permitted_isa` and `hv_vm_allowed`, the static inline
    `hv_internal.h` accessors and locks, the `hv_vm_isa_t` and
    `HV_VCPU_MAX` constants, and `vme_protection()` in
    `vm_map_internal.h`.
49. The hypervisor vCPU object allocation in
    `osfmk/arm64/hv/hv_vcpu.c`: the zeroed 64-byte vCPU object and the
    32 KB kernel/user shared guest context, the read-only whole-context
    remap at a random address and the read-write half remap with
    overwrite into the owning task, the `HV_ERROR` deallocation path,
    and the `kif`/`uif` publication with the page-alignment
    assertions.
50. The hypervisor nested-call and VM teardown paths in
    `osfmk/arm64/hv/hv_vm_paranested.c`: the inline `hvc`-based
    `hv_nested_call`, `hv_get_host_capabilities`,
    `_hv_vm_destroy` (map-list drain, host notification, mutex and
    object teardown) and `hv_trap_paravirtualized_nested_service`,
    with the real 96-byte `hv_nested_call_params_t` and the LIST-based
    `hv_map_entry_s` linkage.
51. The hypervisor VM creation path `hv_trap_vm_create` (28-byte packed
    `hv_vm_create_t` copy-in, permitted-ISA check, VM object allocation,
    the 0xc6000014 host call and task publication) and the one-time host
    capability query behind `pmap_ipa_size`, with the reference nested
    designated-initializer form for the nested-call records.
52. The hypervisor measurement handshake:
    `hv_paranested_virtualization_init_handshake` (version negotiation
    with host service 0xc600001a, the 456-byte measurement pair filled
    by service 0xc6000019, the compatibility check, the state-version
    assertion and the per-entry context mismatch scan) and
    `measurements_compatible`, with the static inline
    `hv_get_state_version_major` and the 25-entry
    `hv_measurement_type[]` array recovered from the kasan reference
    kernel, which keeps the full DWARF the release dSYM omits.
53. The hypervisor measurement table and validator: the static
    `native_measurement` record (228 bytes, interface 1.1 and the 25
    context entries read from the reference data section),
    `hv_get_native_measurement`, `hv_get_supported_measurement` and its
    asserting `_nofail` wrapper, `measurement_entry_within_range`, the
    `measurement_valid` entry/range checks with the 0x20687970 state
    signature, the static handshake flags and shared measurement, the
    accessors and `hv_paranested_virtualization_init`, plus the header's
    inline `context_size_from_measurement`.
54. The measurement-layout context conversion: the static
    `hv_convert_context_from_measurements` copier with its size/version
    assertions, the 0xffffffff entry skip, read-write (and optional
    read-only) entry copies using the smaller of the two entry sizes,
    and the corrected `context_size_from_measurement` return expression
    (`ro_context_measurement->offset + ro_context_measurement->size`).
55. The hypervisor vCPU teardown paths in
    `osfmk/arm64/hv/hv_vcpu_paranested.c`: the static
    `_hv_free_context` (measurement-derived size with its nonzero
    assertion), `_hv_vcpu_obj_free` (shared and intermediate context
    release with the intermediate-without-shared assertion, then the
    user mapping, kernel context and vCPU object deallocation),
    `_hv_vcpu_destroy` (host service 0xc6000012 and online-bitmap
    removal under the VM lock), the tail-calling `hv_vcpu_destroy`
    wrapper, `hv_trap_vcpu_destroy` (thread target clear) and the
    accessor-based `hv_trap_vcpu_sysregs_sync`.
56. The hypervisor vCPU creation path: the static
    `allocate_context` (contiguous or plain measurement-sized context
    with its nonzero/page-aligned assertions) and
    `hv_trap_vcpu_create` (16-byte create record copy-in with the id
    bound and thread/VM checks, the vCPU object allocation, the
    shared/intermediate context buffers for conversion guests, host
    service 0xc6000011, the post-create conversion, the copyout and
    its host-destroy failure path, and the online-bitmap publication).
57. The hypervisor vCPU run and run-cancel paths in
    `osfmk/arm64/hv/hv_vcpu_paranested.c`: `hv_trap_vcpu_run` (the
    shared-layout context conversion, host service 0xc6000010, the
    re-entry loop on result[1] == 0xb with the pending-AST check under
    disabled preemption, and the conversion back) and
    `hv_trap_vcpu_run_cancel` (the vCPU/VM selection with its VM
    reference, host service 0xc6000013 and the conditional VM release).
58. The hypervisor nested-space block mapper and map-list helpers in
    `osfmk/arm64/hv/hv_space_paranested.c`: the `hv_call` host-entry
    wrapper, `nested_space_map_block` (the UPL page walk, physically
    contiguous block coalescing, VMAPPLE_NESTED_SPACE_MAP calls and
    mapped-size accounting), `add_map_entry`, `commit_map_entries`
    and `rollback_map_entries` for the temporary map-entry list, and
    `_hv_nested_space_unmap` with its exact ipa/size lookup and
    VMAPPLE_NESTED_SPACE_UNMAP host call.
59. The hypervisor nested-space map operation in
    `osfmk/arm64/hv/hv_space_paranested.c`: the `create_upl_chunk`
    helper (protection lookup, window bounding, executable and
    physically contiguous rejection, temporary write protection around
    `vm_map_create_upl`, first/last page trim), `_hv_nested_space_map`
    (range alignment, chunk loop, rollback and commit, guest-address
    advance by the mapped size), `_hv_space_map_op` (item copy-in,
    asid validation, VM reference and UNMAP/PROTECT/MAP dispatch) and
    `hv_space_map_op_nested`; plus the reference-only
    `mach_vm_protect_kernel` helper and its declaration in
    `osfmk/vm/vm_kern.c` and `vm_kern_xnu.h`.
60. The hypervisor context conversion path in
    `osfmk/arm64/hv/hv_compat_paranested.c`: `convert_context_by_guest`
    (direction-selected buffers, sizes and measurements; the
    both-mismatch path through `kif_intermediate`, the major-only and
    measurement-only paths, and the shared-to-native version stamp in
    the read-only context root) and the unimplemented
    `hv_convert_context_major_version` helper, whose body is
    `assert(false)` and therefore panics in development and kasan
    kernels but falls away in release kernels.  The patch also gives
    the read-only context root its recovered members, defines
    `ARM_HV_STATE_VER`, declares the file's external inline helpers and
    drops a spurious assert from `hv_get_state_version_major`.

The patches contain only public xnu text plus original reconstruction;
no Apple binary, dSYM, SDK payload or extracted proprietary header is
included.  Stub bodies remain marked `RECON(13432)`; the current count
and evidence are in `docs/RECONSTRUCTION-NOTES.md`.

# xnu-13432 reconstruction patches

These patches turn the public `apple-oss-distributions/xnu` tag
`xnu-12377.121.6` into the reconstruction of `xnu-13432.1.9`
(RELEASE_ARM64_VMAPPLE, macOS 27.0.1 build 26A434) developed in this
project.

Apply in numeric order from a clean checkout:

```
git checkout xnu-12377.121.6
git am 0001-*.patch ... 0028-*.patch
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

The patches contain only public xnu text plus original reconstruction;
no Apple binary, dSYM, SDK payload or extracted proprietary header is
included.  Stub bodies remain marked `RECON(13432)`; the current count
and evidence are in `docs/RECONSTRUCTION-NOTES.md`.

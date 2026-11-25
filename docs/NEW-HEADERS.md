# Headers reconstructed from the xnu-13432 DWARF

These headers exist in the reference source set but not in public
`xnu-12377.121.6`.  `tools/newheader_recon.py` regenerates them from the
KDK 27.0.1 type graph: struct/union layouts (including bitfields and
arrays), enums with values, typedefs and function prototypes.  The
hypervisor headers additionally carry declaration line numbers and
small declaration-only APIs recovered from the reference DWARF.

| Header | Lines |
|---|---:|
| `bsd/kern/kern_exec_security.h` | 22 |
| `bsd/net/ipsec_offload.h` | 103 |
| `bsd/netinet/tcp_ecn.h` | 11 |
| `bsd/netinet/tcp_fastopen.h` | 11 |
| `bsd/netinet/tcp_rbbr.h` | 44 |
| `bsd/netinet/tcp_recovery.h` | 13 |
| `bsd/netinet/tcp_rtt.h` | 13 |
| `bsd/netinet/tcp_segment.h` | 34 |
| `bsd/netinet/tcp_timer_advanced.h` | 45 |
| `bsd/sys/proc_lifecycle.h` | 108 |
| `iokit/IOKit/IOUnifiedAddressTranslator.h` | 51 |
| `iokit/IOKit/pwr_mgt/IOPMAssertionTypes.h` | 40 |
| `iokit/Kernel/IOAnalytics.h` | 30 |
| `libkern/os/metric_types.h` | 75 |
| `osfmk/arm64/hv/guest_thread_state.h` | 384 |
| `osfmk/arm64/hv/hv.h` | 33 |
| `osfmk/arm64/hv/hv_compat_paranested.h` | 60 |
| `osfmk/arm64/hv/hv_interface.h` | 123 |
| `osfmk/arm64/hv/hv_internal.h` | 123 |
| `osfmk/arm64/hv/hv_kern_types.h` | 32 |
| `osfmk/arm64/hv/hv_objects.h` | 46 |
| `osfmk/arm64/hv/hv_vcpu.h` | 35 |
| `osfmk/arm64/hv/hv_vm.h` | 62 |
| `osfmk/arm64/ppl/t8020dart.h` | 119 |
| `osfmk/arm64/ppl/uat.h` | 27 |
| `osfmk/arm64/uexc.h` | 18 |
| `osfmk/kern/hv_support_kern.h` | 42 |
| `osfmk/kern/matchmaker.h` | 11 |
| `osfmk/kern/task_sanitizer_config.h` | 18 |
| `osfmk/kern/threadpair.h` | 25 |
| `osfmk/kern/virtual_env.h` | 25 |
| `osfmk/vm/vm_map_store_types_internal.h` | 326 |
| `osfmk/vm/vm_page_telemetry.h` | 31 |
| `pexpert/pexpert/arm64/cputrace_apt_interface.h` | 20 |

Notes:

- Declarations follow DWARF declaration order in the header copy recorded
  by the compiler; include order and macros are not recoverable from DWARF.
- Types that compiler-generated C++ members cannot express as free
  functions are listed in a trailing comment.
- `struct tcp_seg_sent`, the IOPM driver-assertion typedefs, and the VM
  map store types were moved textually from their public headers into
  the reconstructed ones.
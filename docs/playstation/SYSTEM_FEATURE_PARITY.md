# System feature parity

How PC5 relates to each PlayStation 5 system feature today. "Parity" is not the
goal for its own sake: where the genuine system runs, it should be the genuine
system, and no PC5 imitation should stand in for it.

| Feature | Genuine PS5 | PC5 today | Status |
|---|---|---|---|
| Boot experience | Sony system software | PC5 boot environment (clearly PC5-branded) | NOT EQUIVALENT (no imitation attempted) |
| Home screen | PS5 UI | none | NOT STARTED |
| Game library / cards | PS5 UI | none | NOT STARTED |
| System settings | PS5 UI | six diagnostic pages | NOT APPLICABLE |
| Notifications | PS5 | boot log only | NOT APPLICABLE |
| User profiles | PS5 accounts | none | NOT STARTED |
| Downloads / installation | PS5 store & disc | none | NOT STARTED |
| System update | Sony PUP | none (PC5 has no updater) | NOT APPLICABLE |
| Storage management | PS5 | none (no storage driver) | NOT STARTED |
| Audio / display configuration | PS5 | display mode chosen from VBE list | PARTIAL (diagnostics only) |
| Power: rest mode | suspend/resume | none | NOT STARTED |
| Power: shut down | ACPI | reboot works; power-off not implemented | PARTIAL |
| Recovery | Safe Mode | serial recovery console | DIFFERENT (PC5 sandbox) |
| Controller | DualSense full feature set | none (PS/2 keyboard) | NOT STARTED |
| Network | Ethernet + Wi-Fi 6 | none | NOT STARTED |
| PSN | full | none | BLOCKED (no authorised path) |

## Rules this table enforces

1. PC5 never draws a PS5 screen to look like progress; the boot environment is
   visibly PC5.
2. A PC5 page may show PS5-related *data* (chain state, firmware analysis), but
   never pretend to be a PS5 function.
3. Features listed as NOT STARTED have no buttons anywhere in the UI.
4. Anything that would require circumventing authentication is BLOCKED, not
   "in progress".

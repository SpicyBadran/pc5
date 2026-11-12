# Gaming compatibility

## 1. Three different things, never merged

| Category | What it means | Status |
|---|---|---|
| **PS5 games** | an actual PlayStation 5 title's code executing | not possible today; no path implemented |
| **PS5 binaries relinked** | a decrypted PS5 user-space executable converted to a native program and run with host implementations of the PSX libraries (the AnyPS5 approach) | research stage; not implemented in PC5 |
| **PC games** | native Linux/Windows titles through Steam/Proton/Wine | out of scope for this build; will be an explicitly separate category |

A PC game running under Proton is not a PS5 game running through PC5
compatibility. A relinked PS5 binary is not PS5 system software. The boot
environment says which one is running, and today the answer is none.

## 2. Status vocabulary (used in the game database)

```
NOT INVESTIGATED | RESEARCH REQUIRED | IMPLEMENTATION STARTED | BOOTS |
REACHES GAMEPLAY | PLAYABLE | PLAYABLE WITH ISSUES | NOT WORKING | BLOCKED
```

Rules:

* a title is **PLAYABLE** only after sustained gameplay with recorded
  measurements (frame times, crashes, audio, input),
* metadata readability, a listed library entry or a menu screenshot is
  **never** evidence of executability,
* `BLOCKED` must name the blocking subsystem,
* removing a title from the database requires the same evidence as adding it.

## 3. What a PS5 title would require, end to end

For the relinked-executable route (the only one that could produce results with
legitimate inputs today):

1. **Obtain a decrypted, unpacked PS5 executable** — the owner's own dump of
   their own disc; PC5 never distributes these and never circumvents encryption.
2. **Relink it** — the AnyPS5 relinker resolves imports by NID and rewrites the
   image for the host (ELF/PE). Requires its PRX library implementations.
3. **Provide the system libraries it imports** — 411 PRX projects exist
   upstream; coverage per title is what determines whether it starts.
4. **Provide the GPU translation** — shader recompilation is the upstream
   approach; full command translation for scene rendering is not solved there.
5. **Provide input, audio, storage I/O and timing** — host services.
6. **Test and record** — per-title, with the vocabulary above.

PC5 has none of 2–6 implemented. It has the container identification (step 0)
in the host tool and the reporting infrastructure around it.

## 4. What PC5 keeps away from this

* No PS4 titles presented as PS5 (they are different binaries and a different
  compatibility problem),
* no cloud streaming or Remote Play presented as execution,
* no video playback presented as gameplay,
* no mock game cards or launch buttons,
* no "compatible" label derived from a package being readable.

## 5. Near-term plan

| Step | Work | Status |
|---|---|---|
| 1 | Storage driver + ISO9660 reader in the kernel | NOT STARTED |
| 2 | `pc5ctl fw` intake for a user's own package images, hash + structure only | tool exists; kernel intake pending |
| 3 | An execution-layer prototype: build AnyPS5 on a capable host and run one known-good homebrew PS5 ELF | RESEARCH REQUIRED |
| 4 | Record the first per-title row in `docs/PS5_GAME_TEST_RESULTS.md` | NOT STARTED |

Step 3 must happen on a host that can build AnyPS5 (CMake + C++ toolchain +
submodules). This build environment cannot, and says so rather than faking a
result.

# Update system

## 1. Two completely different things

| | PC5 update | Sony system-software update |
|---|---|---|
| What changes | the PC5 boot environment and compatibility layer | the PlayStation 5 system software |
| Source | this project's releases | Sony |
| Format | PC5 release artifact (ISO + signed manifest) | `PS5UPDATE.PUP` (proprietary) |
| Implemented | design only (below) | not applicable: PC5 does not install or update Sony software |

Applying a Sony PUP is something only a PS5 console does, through its own
updater with its own signature checks. PC5 must not, and does not, attempt to
reproduce that.

## 2. PC5 update design (not implemented)

Target design, in the order it will be built:

1. **Artifact manifest** — `pc5-release.json`: version, channel, ISO SHA-256,
   kernel ABI version, hardware requirements, changelog, signature.
2. **Signature** — detached Ed25519 signature over the manifest, public key
   shipped in the image (`docs/SECURITY.md`).
3. **Channels** — `stable`, `beta`, `experimental`; the image records which
   channel it was built from.
4. **A/B slots** — once an installer exists, two system slots with an atomic
   switch and a boot counter; a failed boot falls back to the previous slot.
5. **Rollback** — keep the previous image until the new one has booted twice.
6. **Integrity check** — verify every file against the manifest before
   switching.
7. **Update history** — recorded on the target medium, shown in the UI.

## 3. What exists today

* `build/build-info.json` — machine-readable build record (layout, per-file
  SHA-256, image SHA-256). This is the seed of the release manifest.
* `build/pc5.iso.sha256` — the checksum users verify before flashing.
* `tools/verify_iso.py` — structural verification of an image.
* Version identity compiled into the kernel (`PC5_VERSION`, `PC5_BUILD_ID`,
  `PC5_BUILD_DATE`) and shown on every screen.

Missing: any notion of applying an update, slots, signatures, or a network
transport. Because PC5 has no storage driver yet, it cannot write an update at
all — the first real update mechanism has to wait for the installer milestone.

## 4. Sony firmware version tracking

`docs/playstation/FIRMWARE_VERSIONS.md` is the record of PlayStation system
software versions relevant to PC5's compatibility work. It is empty of analysed
versions because no firmware image has been supplied. When one is:

1. record the SHA-256 and the source (never the image),
2. run `tools/firmware.py analyze` and store the manifest,
3. add a row with the compatibility impact,
4. never infer that a new version works because the previous one did.

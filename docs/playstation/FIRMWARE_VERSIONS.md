# PlayStation system software versions

## Record

No version has been analysed. The repository was received without a firmware
image, and PC5 does not download, bundle or redistribute Sony firmware.

| Version | SHA-256 | Container | Size | Analysed | Compatibility impact |
|---|---|---|---|---|---|
| — | — | — | — | — | none recorded |

## Workflow when an image is supplied

```sh
# keep the image outside the repository; it is not redistributable
python3 tools/firmware.py analyze --input /path/PS5UPDATE.PUP \
    --json-out /tmp/fw.json --manifest-out firmware/manifest.json
make clean iso        # embeds a short summary, never the image
make verify && make boot-test
```

Then add a row: version (as reported by Sony, e.g. `24.06-10.40.00`), SHA-256,
container kind from the tool, size, analysis date, and what changed for PC5.

## Rules

1. A new firmware version is **never** assumed compatible because the previous
   one was.
2. No entry in this file may be created from a screenshot, a changelog or a
   forum post; it needs a hash.
3. Compatibility impact must name the PC5 subsystem affected (chain stage), not
   a general statement.
4. If the image cannot be identified, record that — an unidentified version is
   a legitimate research result.

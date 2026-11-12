#!/usr/bin/env node
/*
 * PC5 boot-test runner.
 *
 * Boots a PC5 image inside the v86 x86 emulator (a JavaScript/WASM PC,
 * SeaBIOS based) and records three kinds of evidence:
 *
 *   - everything the guest writes to COM1 (the PC5 kernel mirrors its boot
 *     log and accepts a small command console there),
 *   - the emulated VGA text screen, so the boot menu can be asserted without
 *     a display,
 *   - keystrokes injected either over the serial console ("serial:...") or
 *     as PS/2 scan codes ("key:...").
 *
 * It is deliberately dependency-light: node + the `v86-system` package.
 * Usage:
 *   node tests/v86_runner.mjs --cdrom build/pc5.iso --seconds 20 \
 *        --serial-out build/test/serial.log --screen-out build/test/screen.txt
 *
 * Exit code 0 means the emulator ran to the requested end condition.  The
 * caller decides what the log must contain (see tests/boot_test.py).
 */

import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);

function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) { out._.push(a); continue; }
    const key = a.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith("--")) { out[key] = true; }
    else { out[key] = next; i++; }
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));

function findAssets() {
  const candidates = [
    process.env.V86_ASSETS,
    path.join(process.cwd(), "node_modules/v86-system/assets"),
    "/home/user/work/v86/node_modules/v86-system/assets",
  ].filter(Boolean);
  for (const c of candidates) {
    if (fs.existsSync(path.join(c, "libv86.mjs"))) return c;
  }
  console.error("pc5-test: cannot find v86 assets (set V86_ASSETS)");
  process.exit(2);
}

const assets = findAssets();
const { V86 } = await import(path.join(assets, "libv86.mjs")).catch(async () => {
  const mod = await import(new URL("file://" + path.join(assets, "libv86.mjs")).href);
  return mod.default ?? mod;
});

const seconds = Number(args.seconds ?? 15);
const serialOut = args["serial-out"] ?? null;
const screenOut = args["screen-out"] ?? null;
const stopOn = args["stop-on"] ? new RegExp(args["stop-on"]) : null;
const driveKeys = args["keys"] ? args.keys.split(",").filter(Boolean) : [];

const memoryArg = String(args.mem ?? "128M");
const memorySize = (() => {
  const m = memoryArg.match(/^(\d+)([KMG]?)$/i);
  if (!m) return 128 * 1024 * 1024;
  const mult = { "": 1024 * 1024, K: 1024, M: 1024 ** 2, G: 1024 ** 3 }[
    (m[2] || "M").toUpperCase()
  ];
  return Number(m[1]) * mult;
})();

const config = {
  wasm_path: path.join(assets, "v86.wasm"),
  memory_size: memorySize,
  autostart: true,
  bios: { url: path.join(assets, "seabios.bin") },
  vga_bios: { url: path.join(assets, "vgabios.bin") },
  disable_speaker: true,
};

if (args.cdrom) config.cdrom = { url: path.resolve(args.cdrom) };
if (args.hda) config.hda = { url: path.resolve(args.hda) };
if (args.fda) config.fda = { url: path.resolve(args.fda) };
if (args["boot-order"]) config.boot_order = Number(args["boot-order"]);

const emulator = new V86(config);

let serial = "";
let stopped = false;

function finish(reason, code = 0) {
  if (stopped) return;
  stopped = true;
  try {
    if (screenOut) {
      let rows = [];
      try {
        rows = emulator.screen_adapter?.get_text_screen?.() ?? [];
      } catch (e) {
        rows = [];
      }
      fs.mkdirSync(path.dirname(path.resolve(screenOut)), { recursive: true });
      fs.writeFileSync(screenOut, rows.join("\n") + "\n");
    }
    if (serialOut) {
      fs.mkdirSync(path.dirname(path.resolve(serialOut)), { recursive: true });
      fs.writeFileSync(serialOut, serial);
    }
  } catch (e) {
    console.error("pc5-test: writing evidence failed:", e.message);
  }
  console.error(`pc5-test: finished (${reason})`);
  try { emulator.destroy(); } catch {}
  process.exit(code);
}

emulator.add_listener("serial0-output-byte", (byte) => {
  const ch = String.fromCharCode(byte);
  serial += ch;
  if (stopOn && stopOn.test(serial)) finish("serial pattern matched");
});

function sendSerial(text) {
  for (const ch of text) emulator.serial0_send(ch);
}

// Optional scripted input, e.g. --keys "serial:i,serial:\r,wait:3"
function runScript() {
  let delay = 800;
  for (const item of driveKeys) {
    const [kind, ...rest] = item.split(":");
    const value = rest.join(":");
    if (kind === "wait") { delay += Number(value) * 1000; continue; }
    setTimeout(() => {
      if (kind === "serial") sendSerial(value.replace(/\\r/g, "\r").replace(/\\n/g, "\n"));
      if (kind === "key") {
        for (const code of value.split("+")) emulator.keyboard_send_scancodes([Number(code)]);
      }
    }, delay);
    delay += 350;
  }
}

if (driveKeys.length) runScript();

setTimeout(() => finish("timeout reached"), seconds * 1000);

process.on("SIGTERM", () => finish("sigterm"));
process.on("uncaughtException", (e) => { console.error("pc5-test:", e); finish("error", 1); });

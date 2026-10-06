import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// The preload throws on channels outside its allowlist, and a throw while the Home tab loads leaves
// the window grey. Renderer tests mock IPC, so this test checks every literal channel against it.
const preloadSource = fs.readFileSync(path.join(__dirname, "index.ts"), "utf8");
const rendererRoot = path.join(__dirname, "..", "renderer", "src");

function listFromPreload(name: string): string[] {
  const start = preloadSource.indexOf(`const ${name} =`);
  expect(start, `${name} not found in preload`).toBeGreaterThanOrEqual(0);
  const end = preloadSource.indexOf("]", start);
  return [...preloadSource.slice(start, end).matchAll(/"([^"]+)"/g)].map((match) => match[1]);
}

function rendererFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return rendererFiles(full);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

function usedChannels(pattern: RegExp): string[] {
  const used = new Set<string>();
  for (const file of rendererFiles(rendererRoot)) {
    for (const match of fs.readFileSync(file, "utf8").matchAll(pattern)) used.add(match[1]);
  }
  return [...used].sort();
}

function blocked(channels: string[], exactName: string, prefixName: string): string[] {
  const exact = new Set(listFromPreload(exactName));
  const prefixes = listFromPreload(prefixName);
  return channels.filter((channel) => !exact.has(channel) && !prefixes.some((prefix) => channel.startsWith(prefix)));
}

describe("preload IPC allowlist", () => {
  it("allows every channel the renderer invokes", () => {
    const channels = usedChannels(/(?:invokeIpc|ipcRenderer\.invoke)(?:<[^>]*>)?\(\s*["'`]([A-Za-z0-9._:-]+)["'`]/g);
    expect(channels.length).toBeGreaterThan(20);
    expect(channels).toContain("game.play");
    expect(blocked(channels, "invokeExactChannels", "invokePrefixes")).toEqual([]);
  });

  it("allows every channel the renderer sends on", () => {
    const channels = usedChannels(/(?:sendIpc|ipcRenderer\.send)\(\s*["'`]([A-Za-z0-9._:-]+)["'`]/g);
    expect(blocked(channels, "sendExactChannels", "sendPrefixes")).toEqual([]);
  });

  it("allows every channel the renderer listens on", () => {
    const channels = usedChannels(/(?:onIpc|ipcRenderer\.on|ipcRenderer\.once)\(\s*["'`]([A-Za-z0-9._:-]+)["'`]/g);
    expect(blocked(channels, "onExactChannels", "onPrefixes")).toEqual([]);
  });
});

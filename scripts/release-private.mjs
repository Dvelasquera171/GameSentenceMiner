// Build a private GSM installer from this checkout and drop it in the releases folder that the
// other PCs watch (OneDrive\GSM releases by default). Mirrors the CI prerelease steps:
//   version stamp → backend wheel (Rust ext, abi3) → prerelease.json (distribution: private)
//   → overlay package → app build → installer + latest.json in the releases folder.
// The version is YEAR.MMDD.N. package.json / pyproject.toml and the build inputs are restored
// afterwards, so the working tree is left as it was.
//
//   npm run release:private                      # OneDrive\GSM releases
//   npm run release:private -- --to "D:\Some folder"
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const KEEP_INSTALLERS = 3;

function arg(name) {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

function run(command, args, options = {}) {
  console.log(`\n> ${command} ${args.join(' ')}`);
  const result = spawnSync(command, args, { stdio: 'inherit', shell: process.platform === 'win32', cwd: root, ...options });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed (exit ${result.status ?? result.error})`);
  }
}

function output(command, args) {
  return spawnSync(command, args, { cwd: root, encoding: 'utf8' }).stdout.trim();
}

// Same scheme as electron-src/main/distribution.ts nextPrivateVersion.
function nextVersion(now, previous) {
  const base = `${now.getFullYear()}.${(now.getMonth() + 1) * 100 + now.getDate()}`;
  const match = previous ? /^(\d+\.\d+)\.(\d+)$/.exec(previous) : null;
  return `${base}.${match && match[1] === base ? Number(match[2]) + 1 : 1}`;
}

function releasesFolder() {
  const folder = arg('to') || process.env.GSM_RELEASES_DIR || (process.env.OneDrive && path.join(process.env.OneDrive, 'GSM releases'));
  if (!folder) throw new Error('No releases folder: pass --to <folder> or set up OneDrive.');
  const resolved = path.resolve(folder);
  if (resolved.toLowerCase().startsWith(root.toLowerCase())) throw new Error('The releases folder must be outside the repository.');
  fs.mkdirSync(resolved, { recursive: true });
  return resolved;
}

// The Windows speech helper needs CMake; Visual Studio Build Tools ship one even when none is on PATH.
function ensureCmake() {
  if (spawnSync('cmake', ['--version'], { shell: true }).status === 0) return;
  const programFiles = [process.env['ProgramFiles(x86)'], process.env.ProgramFiles].filter(Boolean);
  for (const base of programFiles.map((dir) => path.join(dir, 'Microsoft Visual Studio'))) {
    if (!fs.existsSync(base)) continue;
    for (const version of fs.readdirSync(base)) {
      const versionDir = path.join(base, version);
      for (const edition of fs.statSync(versionDir).isDirectory() ? fs.readdirSync(versionDir) : []) {
        const bin = path.join(base, version, edition, 'Common7', 'IDE', 'CommonExtensions', 'Microsoft', 'CMake', 'CMake', 'bin');
        if (fs.existsSync(path.join(bin, 'cmake.exe'))) {
          process.env.PATH = `${bin};${process.env.PATH}`;
          console.log(`Using Visual Studio's CMake: ${bin}`);
          return;
        }
      }
    }
  }
  throw new Error('CMake not found: install it or Visual Studio Build Tools (C++).');
}

function main() {
  ensureCmake();
  const folder = releasesFolder();
  const manifestPath = path.join(folder, 'latest.json');
  const previous = fs.existsSync(manifestPath) ? JSON.parse(fs.readFileSync(manifestPath, 'utf8')).version : null;
  const version = nextVersion(new Date(), previous);
  const branch = output('git', ['rev-parse', '--abbrev-ref', 'HEAD']);
  const commit = output('git', ['rev-parse', 'HEAD']);
  const dirty = output('git', ['status', '--porcelain']) !== '';
  console.log(`Private release ${version} from ${branch}@${commit.slice(0, 8)}${dirty ? ' (uncommitted changes included)' : ''} -> ${folder}`);

  const restore = ['package.json', 'package-lock.json', 'pyproject.toml', 'uv.lock'].map((file) => [file, fs.readFileSync(path.join(root, file))]);
  const wheelDir = path.join(root, 'electron-src', 'assets', 'python');
  const metadataPath = path.join(root, 'electron-src', 'assets', 'prerelease.json');
  try {
    run('npm', ['version', version, '--no-git-tag-version', '--allow-same-version']);
    run('node', ['scripts/sync-version.mjs']);

    // Backend wheel: the installed app installs exactly this (never PyPI) in a private build.
    fs.mkdirSync(wheelDir, { recursive: true });
    for (const name of fs.readdirSync(wheelDir)) if (name.endsWith('.whl')) fs.rmSync(path.join(wheelDir, name));
    const uv = process.env.APPDATA && path.join(process.env.APPDATA, 'GameSentenceMiner', 'uv', 'uv.exe');
    run(uv && fs.existsSync(uv) ? `"${uv}"` : 'uv', ['build', '--wheel', '--python', '3.10', '--out-dir', `"${wheelDir}"`]);
    run('node', ['scripts/smoke-test-wheel.mjs']);
    run('node', ['scripts/write-prerelease-metadata.mjs', '--branch', branch, '--commit', commit, '--version', version, '--distribution', 'private']);

    // Yomitan's templates must be LF in the overlay package (as in CI).
    const templates = path.join(root, 'GSM_Overlay', 'yomitan', 'data', 'templates');
    for (const name of fs.existsSync(templates) ? fs.readdirSync(templates, { recursive: true }) : []) {
      const file = path.join(templates, String(name));
      if (file.endsWith('.handlebars') && fs.statSync(file).isFile()) {
        fs.writeFileSync(file, fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n'));
      }
    }
    run('npm', ['run', 'package'], { cwd: path.join(root, 'GSM_Overlay') });

    run('npm', ['run', 'build']);
    run('npm', ['run', 'build:windows-helpers']);
    run('npm', ['run', 'stage:overlay']);
    run('npx', ['electron-builder', '--publish=never']);
    run('npm', ['run', 'verify:overlay-package']);

    const installer = fs.readdirSync(path.join(root, 'dist')).find((name) => name.endsWith(`-Setup-${version}.exe`));
    if (!installer) throw new Error(`No installer for ${version} in dist/`);
    const source = path.join(root, 'dist', installer);
    fs.copyFileSync(source, path.join(folder, installer));
    const bytes = fs.readFileSync(source);
    const manifest = {
      version,
      installer,
      sha512: crypto.createHash('sha512').update(bytes).digest('hex'),
      size: bytes.length,
      releasedAt: new Date().toISOString(),
      commit: `${commit}${dirty ? '+dirty' : ''}`,
      branch,
    };
    // Installer first, manifest last: a PC never sees a manifest for a file that is not there yet.
    fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);

    const installers = fs
      .readdirSync(folder)
      .filter((name) => /^GameSentenceMiner-Setup-\d+\.\d+\.\d+\.exe$/.test(name) && name !== installer)
      .map((name) => ({ name, time: fs.statSync(path.join(folder, name)).mtimeMs }))
      .sort((a, b) => b.time - a.time);
    for (const old of installers.slice(KEEP_INSTALLERS - 1)) fs.rmSync(path.join(folder, old.name));

    console.log(`\nReleased ${version}: ${path.join(folder, installer)} (${(bytes.length / 1048576).toFixed(0)} MB)`);
  } finally {
    for (const [file, contents] of restore) fs.writeFileSync(path.join(root, file), contents);
    fs.rmSync(metadataPath, { force: true });
    for (const name of fs.existsSync(wheelDir) ? fs.readdirSync(wheelDir) : []) if (name.endsWith('.whl')) fs.rmSync(path.join(wheelDir, name));
  }
}

try {
  main();
} catch (error) {
  console.error(`\nRelease failed: ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
}

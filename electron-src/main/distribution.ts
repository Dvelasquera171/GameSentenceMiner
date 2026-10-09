// Private distribution: builds of this fork made with `npm run release:private`. They must never
// take upstream's installers (GitHub) or backends (PyPI), which would replace this fork's code.
// New versions arrive as an installer plus latest.json in a releases folder the user syncs
// between PCs (OneDrive by default).
import * as crypto from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import semver from 'semver';

export const RELEASES_MANIFEST = 'latest.json';
export const DEFAULT_RELEASES_FOLDER_NAME = 'GSM releases';

export interface PrivateRelease {
    version: string;
    installer: string;
    sha512: string;
    size: number;
    releasedAt?: string;
    commit?: string;
}

/** OneDrive folder on Windows; null when OneDrive is not set up. */
export function defaultReleasesFolder(env: NodeJS.ProcessEnv = process.env): string | null {
    const oneDrive = env.OneDrive || env.OneDriveConsumer || env.OneDriveCommercial;
    return oneDrive ? path.join(oneDrive, DEFAULT_RELEASES_FOLDER_NAME) : null;
}

export function resolveReleasesFolder(configured: string | null | undefined, env: NodeJS.ProcessEnv = process.env): string | null {
    const value = String(configured ?? '').trim();
    return value || defaultReleasesFolder(env);
}

export function parsePrivateRelease(raw: unknown): PrivateRelease {
    const data = raw as Partial<PrivateRelease> | null;
    if (
        !data ||
        typeof data.version !== 'string' ||
        !semver.valid(data.version) ||
        typeof data.installer !== 'string' ||
        path.basename(data.installer) !== data.installer ||
        !data.installer.toLowerCase().endsWith('.exe') ||
        typeof data.sha512 !== 'string' ||
        !/^[a-f0-9]{128}$/i.test(data.sha512) ||
        !Number.isInteger(data.size) ||
        (data.size as number) <= 0
    ) {
        throw new Error('The releases folder has an invalid latest.json.');
    }
    return {
        version: data.version,
        installer: data.installer,
        sha512: data.sha512.toLowerCase(),
        size: data.size as number,
        releasedAt: typeof data.releasedAt === 'string' ? data.releasedAt : undefined,
        commit: typeof data.commit === 'string' ? data.commit : undefined,
    };
}

export function readPrivateRelease(folder: string): PrivateRelease | null {
    const manifest = path.join(folder, RELEASES_MANIFEST);
    if (!fs.existsSync(manifest)) {
        return null;
    }
    return parsePrivateRelease(JSON.parse(fs.readFileSync(manifest, 'utf8')));
}

export function isNewerVersion(candidate: string, current: string): boolean {
    return Boolean(semver.valid(candidate) && semver.valid(current) && semver.gt(candidate, current));
}

export function sha512File(filePath: string): string {
    return crypto.createHash('sha512').update(fs.readFileSync(filePath)).digest('hex');
}

/**
 * Copy the installer out of the synced folder (OneDrive may only hold a placeholder until it is
 * read) and check it against latest.json before anything runs it.
 */
export function stageInstaller(folder: string, release: PrivateRelease, targetDir: string): string {
    const source = path.join(folder, release.installer);
    if (!fs.existsSync(source)) {
        throw new Error(`The installer ${release.installer} is not in the releases folder yet. Wait for it to finish syncing.`);
    }
    fs.mkdirSync(targetDir, { recursive: true });
    const target = path.join(targetDir, release.installer);
    fs.copyFileSync(source, target);
    if (fs.statSync(target).size !== release.size || sha512File(target) !== release.sha512) {
        fs.rmSync(target, { force: true });
        throw new Error(`The installer ${release.installer} does not match latest.json (still syncing, or damaged).`);
    }
    return target;
}

/** Version for a private build: YEAR.MMDD.N, valid for both semver (app) and PEP 440 (backend). */
export function nextPrivateVersion(now: Date, previous: string | null): string {
    const base = `${now.getFullYear()}.${(now.getMonth() + 1) * 100 + now.getDate()}`;
    const match = previous ? /^(\d+\.\d+)\.(\d+)$/.exec(previous) : null;
    const build = match && match[1] === base ? Number(match[2]) + 1 : 1;
    return `${base}.${build}`;
}

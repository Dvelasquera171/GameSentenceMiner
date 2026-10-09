import * as crypto from 'node:crypto';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
    defaultReleasesFolder,
    isNewerVersion,
    nextPrivateVersion,
    parsePrivateRelease,
    readPrivateRelease,
    resolveReleasesFolder,
    stageInstaller,
} from './distribution';

const sha512 = (data: string) => crypto.createHash('sha512').update(data).digest('hex');

describe('private distribution', () => {
    let folder: string;

    beforeEach(() => {
        folder = fs.mkdtempSync(path.join(os.tmpdir(), 'gsm-releases-'));
    });

    afterEach(() => {
        fs.rmSync(folder, { recursive: true, force: true });
    });

    function publish(version: string, contents = 'installer bytes') {
        const installer = `GameSentenceMiner-Setup-${version}.exe`;
        fs.writeFileSync(path.join(folder, installer), contents);
        const manifest = { version, installer, sha512: sha512(contents), size: Buffer.byteLength(contents) };
        fs.writeFileSync(path.join(folder, 'latest.json'), JSON.stringify(manifest));
        return manifest;
    }

    it('uses the OneDrive folder unless one is configured', () => {
        expect(defaultReleasesFolder({ OneDrive: 'C:\\Users\\me\\OneDrive' })).toBe(path.join('C:\\Users\\me\\OneDrive', 'GSM releases'));
        expect(defaultReleasesFolder({})).toBeNull();
        expect(resolveReleasesFolder('  D:\\Releases ', { OneDrive: 'X' })).toBe('D:\\Releases');
        expect(resolveReleasesFolder('', {})).toBeNull();
    });

    it('reads latest.json and compares versions', () => {
        expect(readPrivateRelease(folder)).toBeNull();
        publish('2026.1008.2');
        const release = readPrivateRelease(folder)!;
        expect(release.version).toBe('2026.1008.2');
        expect(isNewerVersion(release.version, '2026.1008.1')).toBe(true);
        expect(isNewerVersion(release.version, '2026.1008.2')).toBe(false);
        expect(isNewerVersion(release.version, '2026.1009.1')).toBe(false);
    });

    it('rejects manifests that point outside the folder or are malformed', () => {
        const good = { version: '2026.1008.1', installer: 'a.exe', sha512: 'a'.repeat(128), size: 3 };
        expect(() => parsePrivateRelease({ ...good, installer: '..\\evil.exe' })).toThrow();
        expect(() => parsePrivateRelease({ ...good, installer: 'a.bat' })).toThrow();
        expect(() => parsePrivateRelease({ ...good, version: 'latest' })).toThrow();
        expect(() => parsePrivateRelease({ ...good, sha512: 'short' })).toThrow();
        expect(parsePrivateRelease(good).installer).toBe('a.exe');
    });

    it('stages the installer only when it matches latest.json', () => {
        const manifest = publish('2026.1008.1');
        const target = path.join(folder, 'staged');
        const staged = stageInstaller(folder, parsePrivateRelease(manifest), target);
        expect(fs.readFileSync(staged, 'utf8')).toBe('installer bytes');

        fs.writeFileSync(path.join(folder, manifest.installer), 'half-synced');
        expect(() => stageInstaller(folder, parsePrivateRelease(manifest), target)).toThrow(/does not match/);
        expect(fs.existsSync(path.join(target, manifest.installer))).toBe(false);

        fs.rmSync(path.join(folder, manifest.installer));
        expect(() => stageInstaller(folder, parsePrivateRelease(manifest), target)).toThrow(/not in the releases folder/);
    });

    it('numbers private builds by date, counting up within a day', () => {
        const oct8 = new Date(2026, 9, 8, 12);
        expect(nextPrivateVersion(oct8, null)).toBe('2026.1008.1');
        expect(nextPrivateVersion(oct8, '2026.1008.1')).toBe('2026.1008.2');
        expect(nextPrivateVersion(oct8, '2026.1007.4')).toBe('2026.1008.1');
        // Across a year end the major part carries the order.
        expect(nextPrivateVersion(new Date(2027, 0, 2), '2026.1231.3')).toBe('2027.102.1');
        expect(isNewerVersion('2027.102.1', '2026.1231.3')).toBe(true);
        // Private builds sort above the upstream release they started from.
        expect(isNewerVersion('2026.1008.1', '2026.9.5')).toBe(true);
    });
});

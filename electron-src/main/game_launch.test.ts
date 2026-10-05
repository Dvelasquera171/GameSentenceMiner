import { describe, expect, it } from 'vitest';
import { findSteamAppId, launchCommandFor, resolveLaunchTarget, type LaunchFs } from './game_launch.js';

function fakeFs(files: Record<string, string>): LaunchFs {
    const norm = (p: string) => p.replace(/\//g, '\\').toLowerCase();
    return {
        readdirSync: (dir) => {
            const prefix = norm(dir) + '\\';
            const names = Object.keys(files)
                .filter((f) => norm(f).startsWith(prefix) && !norm(f).slice(prefix.length).includes('\\'))
                .map((f) => f.slice(prefix.length));
            if (!names.length) throw new Error('ENOENT');
            return names;
        },
        readFileSync: (file) => {
            const key = Object.keys(files).find((f) => norm(f) === norm(file));
            if (key === undefined) throw new Error('ENOENT');
            return files[key];
        },
        existsSync: (file) => Object.keys(files).some((f) => norm(f) === norm(file)),
    };
}

const MANIFEST = (appid: string, dir: string) => `"AppState"\n{\n\t"appid"\t\t"${appid}"\n\t"name"\t\t"x"\n\t"installdir"\t\t"${dir}"\n}`;

describe('findSteamAppId', () => {
    const fs = fakeFs({
        'D:\\SteamLibrary\\steamapps\\appmanifest_333600.acf': MANIFEST('333600', 'NEKOPARA Vol. 1'),
        'D:\\SteamLibrary\\steamapps\\appmanifest_10.acf': MANIFEST('10', 'Other Game'),
    });

    it('finds the app whose install dir holds the exe', () => {
        expect(findSteamAppId('D:\\SteamLibrary\\steamapps\\common\\NEKOPARA Vol. 1\\nekopara_vol1.exe', fs)).toBe('333600');
        expect(findSteamAppId('d:/steamlibrary/SteamApps/Common/nekopara vol. 1/bin/game.exe', fs)).toBe('333600');
    });

    it('returns null outside a Steam library or without a matching manifest', () => {
        expect(findSteamAppId('C:\\Games\\VN\\game.exe', fs)).toBeNull();
        expect(findSteamAppId('D:\\SteamLibrary\\steamapps\\common\\Unknown\\game.exe', fs)).toBeNull();
        expect(findSteamAppId('E:\\Lib\\steamapps\\common\\X\\x.exe', fakeFs({}))).toBeNull();
    });
});

describe('launch targets', () => {
    it('launches Steam games through Steam and others directly', () => {
        const fs = fakeFs({ 'D:\\SteamLibrary\\steamapps\\appmanifest_333600.acf': MANIFEST('333600', 'NEKOPARA Vol. 1') });
        const steam = resolveLaunchTarget('D:\\SteamLibrary\\steamapps\\common\\NEKOPARA Vol. 1\\nekopara_vol1.exe', fs);
        expect(steam.steamAppId).toBe('333600');
        expect(launchCommandFor(steam)).toEqual({ kind: 'steam', url: 'steam://rungameid/333600' });

        const plain = resolveLaunchTarget('C:\\Games\\VN\\game.exe', fs);
        expect(plain).toEqual({ path: 'C:\\Games\\VN\\game.exe' });
        expect(launchCommandFor(plain)).toMatchObject({ kind: 'exe', path: 'C:\\Games\\VN\\game.exe' });
    });
});

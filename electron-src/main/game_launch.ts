// How to start a set-up game from the GSM hub: its program file, or Steam when the game lives in a
// Steam library (so DRM and the overlay work as with a normal Steam launch).

import * as path from 'path';

export interface GameLaunchTarget {
    path: string;
    steamAppId?: string;
}

export interface LaunchFs {
    readdirSync(dir: string): string[];
    readFileSync(file: string, encoding: 'utf-8'): string;
    existsSync(file: string): boolean;
}

/** Steam app id of a game installed under <library>/steamapps/common/<installdir>/..., if any. */
export function findSteamAppId(exePath: string, fs: LaunchFs): string | null {
    const parts = path.win32.normalize(exePath).split(/[\\/]+/);
    const steamappsIndex = parts.findIndex(
        (part, index) => part.toLowerCase() === 'steamapps' && (parts[index + 1] ?? '').toLowerCase() === 'common',
    );
    if (steamappsIndex < 0 || !parts[steamappsIndex + 2]) return null;
    const installDir = parts[steamappsIndex + 2].toLowerCase();
    const steamappsDir = parts.slice(0, steamappsIndex + 1).join('\\');
    let manifests: string[];
    try {
        manifests = fs.readdirSync(steamappsDir).filter((name) => /^appmanifest_\d+\.acf$/i.test(name));
    } catch {
        return null;
    }
    for (const manifest of manifests) {
        try {
            const text = fs.readFileSync(path.win32.join(steamappsDir, manifest), 'utf-8');
            const dir = /"installdir"\s+"([^"]*)"/i.exec(text)?.[1];
            const appId = /"appid"\s+"(\d+)"/i.exec(text)?.[1];
            if (dir && appId && dir.toLowerCase() === installDir) return appId;
        } catch {
            // Unreadable manifest: try the next one.
        }
    }
    return null;
}

export function resolveLaunchTarget(exePath: string, fs: LaunchFs): GameLaunchTarget {
    const steamAppId = findSteamAppId(exePath, fs);
    return steamAppId ? { path: exePath, steamAppId } : { path: exePath };
}

export type LaunchCommand = { kind: 'steam'; url: string } | { kind: 'exe'; path: string; cwd: string };

export function launchCommandFor(target: GameLaunchTarget): LaunchCommand {
    if (target.steamAppId) return { kind: 'steam', url: `steam://rungameid/${target.steamAppId}` };
    return { kind: 'exe', path: target.path, cwd: path.dirname(target.path) };
}

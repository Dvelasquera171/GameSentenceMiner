// One click to read: when a game's scene becomes active, start Anki (if it is not running) and a
// reading session (unless one is already open); when the game closes or another game takes over,
// end its session. Driven by the same active-game evidence as the overlay automation.

import * as path from 'path';

export interface GameSessionSettings {
    startReadingSession: boolean;
    launchAnki: boolean;
    ankiPath: string;
}

export interface GameSessionDeps {
    getSettings(): GameSessionSettings;
    backendUrl(routePath: string): string;
    fetch(url: string, init?: { method?: string; headers?: Record<string, string>; body?: string }): Promise<{
        ok: boolean;
        json(): Promise<unknown>;
    }>;
    fileExists(filePath: string): boolean;
    isProcessRunning(exeName: string): Promise<boolean>;
    launchDetached(filePath: string): void;
    env: Record<string, string | undefined>;
    log(message: string): void;
}

/** The configured Anki, else the standard Windows install locations. */
export function resolveAnkiPath(
    configured: string,
    env: Record<string, string | undefined>,
    fileExists: (filePath: string) => boolean,
): string | null {
    const candidates = [
        configured.trim(),
        env.LOCALAPPDATA ? path.win32.join(env.LOCALAPPDATA, 'Programs', 'Anki', 'anki.exe') : '',
        env.ProgramFiles ? path.win32.join(env.ProgramFiles, 'Anki', 'anki.exe') : '',
        env['ProgramFiles(x86)'] ? path.win32.join(env['ProgramFiles(x86)'] as string, 'Anki', 'anki.exe') : '',
    ].filter(Boolean);
    return candidates.find((candidate) => fileExists(candidate)) ?? null;
}

export class GameSessionAutomation {
    private activeScene: string | null = null;
    private busy = false;

    constructor(private readonly deps: GameSessionDeps) {}

    /** Feed the current scene and whether its game is active (null = no evidence yet). */
    async update(sceneName: string | null, active: boolean | null): Promise<void> {
        if (this.busy) return;
        this.busy = true;
        try {
            const previous = this.activeScene;
            const gameGone = previous !== null && (active === false || (sceneName !== null && sceneName !== previous));
            if (gameGone) {
                this.activeScene = null;
                await this.onGameStopped(previous as string);
            }
            if (active === true && sceneName && this.activeScene !== sceneName) {
                this.activeScene = sceneName;
                await this.onGameStarted(sceneName);
            }
        } finally {
            this.busy = false;
        }
    }

    private async onGameStarted(sceneName: string): Promise<void> {
        const settings = this.deps.getSettings();
        if (settings.launchAnki) await this.ensureAnki(settings.ankiPath);
        if (settings.startReadingSession) await this.startSession(sceneName);
    }

    private async onGameStopped(sceneName: string): Promise<void> {
        if (!this.deps.getSettings().startReadingSession) return;
        try {
            await this.post('/api/review/sessions/end', { game_name: sceneName });
            this.deps.log(`[GameSession] Ended the reading session for "${sceneName}" (game closed or switched).`);
        } catch (error) {
            this.deps.log(`[GameSession] Could not end the reading session: ${(error as Error).message}`);
        }
    }

    private async ensureAnki(configuredPath: string): Promise<void> {
        try {
            if (await this.deps.isProcessRunning('anki.exe')) return;
            const ankiPath = resolveAnkiPath(configuredPath, this.deps.env, this.deps.fileExists);
            if (!ankiPath) {
                this.deps.log('[GameSession] Anki is not running and anki.exe was not found; set its path in GSM.');
                return;
            }
            this.deps.launchDetached(ankiPath);
            this.deps.log(`[GameSession] Started Anki (${ankiPath}).`);
        } catch (error) {
            this.deps.log(`[GameSession] Could not start Anki: ${(error as Error).message}`);
        }
    }

    private async startSession(sceneName: string): Promise<void> {
        try {
            const open = (await this.get('/api/review/sessions/open')) as { sessions?: Array<{ game_name?: string }> };
            if ((open.sessions ?? []).some((session) => session.game_name === sceneName)) return;
            await this.post('/api/review/sessions/start', {});
            this.deps.log(`[GameSession] Started a reading session for "${sceneName}".`);
        } catch (error) {
            this.deps.log(`[GameSession] Could not start a reading session: ${(error as Error).message}`);
        }
    }

    private async get(routePath: string): Promise<unknown> {
        const response = await this.deps.fetch(this.deps.backendUrl(routePath));
        if (!response.ok) throw new Error(`GET ${routePath} failed`);
        return response.json();
    }

    private async post(routePath: string, body: Record<string, unknown>): Promise<unknown> {
        const response = await this.deps.fetch(this.deps.backendUrl(routePath), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!response.ok) throw new Error(`POST ${routePath} failed`);
        return response.json();
    }
}

import { describe, expect, it, vi } from 'vitest';
import { GameSessionAutomation, resolveAnkiPath, type GameSessionDeps } from './game_session_automation.js';

const ANKI = 'C:\\Users\\me\\AppData\\Local\\Programs\\Anki\\anki.exe';

function makeDeps(overrides: Partial<GameSessionDeps> = {}, openSessions: Array<{ game_name: string }> = []) {
    const calls: Array<{ url: string; method: string; body?: unknown }> = [];
    const deps: GameSessionDeps = {
        getSettings: () => ({ startReadingSession: true, launchAnki: true, ankiPath: '' }),
        backendUrl: (route) => `http://localhost:7275${route}`,
        fetch: vi.fn(async (url: string, init?: { method?: string; body?: string }) => {
            calls.push({ url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(init.body) : undefined });
            return { ok: true, json: async () => (url.endsWith('/open') ? { sessions: openSessions } : {}) };
        }),
        fileExists: (filePath) => filePath === ANKI,
        isProcessRunning: vi.fn(async () => false),
        launchDetached: vi.fn(),
        env: { LOCALAPPDATA: 'C:\\Users\\me\\AppData\\Local' },
        log: () => {},
        ...overrides,
    };
    return { deps, calls };
}

describe('resolveAnkiPath', () => {
    it('prefers the configured path, then the standard install', () => {
        const exists = (p: string) => p === ANKI || p === 'D:\\Anki\\anki.exe';
        expect(resolveAnkiPath('D:\\Anki\\anki.exe', { LOCALAPPDATA: 'C:\\Users\\me\\AppData\\Local' }, exists)).toBe('D:\\Anki\\anki.exe');
        expect(resolveAnkiPath('', { LOCALAPPDATA: 'C:\\Users\\me\\AppData\\Local' }, exists)).toBe(ANKI);
        expect(resolveAnkiPath('', {}, exists)).toBeNull();
    });
});

describe('GameSessionAutomation', () => {
    it('starts Anki and a session once when the game becomes active', async () => {
        const { deps, calls } = makeDeps();
        const automation = new GameSessionAutomation(deps);
        await automation.update('NEKOPARA vol.1', null);
        expect(calls).toEqual([]);
        await automation.update('NEKOPARA vol.1', true);
        await automation.update('NEKOPARA vol.1', true);
        expect(deps.launchDetached).toHaveBeenCalledOnce();
        expect(deps.launchDetached).toHaveBeenCalledWith(ANKI);
        expect(calls.filter((c) => c.url.endsWith('/sessions/start'))).toHaveLength(1);
    });

    it('does not start a second session or a second Anki', async () => {
        const { deps, calls } = makeDeps({ isProcessRunning: vi.fn(async () => true) }, [{ game_name: 'NEKOPARA vol.1' }]);
        await new GameSessionAutomation(deps).update('NEKOPARA vol.1', true);
        expect(deps.launchDetached).not.toHaveBeenCalled();
        expect(calls.some((c) => c.url.endsWith('/sessions/start'))).toBe(false);
    });

    it('ends the session when the game closes or another game takes over', async () => {
        const { deps, calls } = makeDeps();
        const automation = new GameSessionAutomation(deps);
        await automation.update('Game A', true);
        await automation.update('Game B', true);
        await automation.update('Game B', false);
        const ends = calls.filter((c) => c.url.endsWith('/sessions/end')).map((c) => c.body);
        expect(ends).toEqual([{ game_name: 'Game A' }, { game_name: 'Game B' }]);
        expect(calls.filter((c) => c.url.endsWith('/sessions/start'))).toHaveLength(2);
    });

    it('respects both switches being off', async () => {
        const { deps, calls } = makeDeps({ getSettings: () => ({ startReadingSession: false, launchAnki: false, ankiPath: '' }) });
        const automation = new GameSessionAutomation(deps);
        await automation.update('Game A', true);
        await automation.update('Game A', false);
        expect(calls).toEqual([]);
        expect(deps.launchDetached).not.toHaveBeenCalled();
    });

    it('keeps going when GSM is unreachable', async () => {
        const log = vi.fn();
        const { deps } = makeDeps({
            fetch: vi.fn(async () => { throw new Error('ECONNREFUSED'); }),
            log,
        });
        await expect(new GameSessionAutomation(deps).update('Game A', true)).resolves.toBeUndefined();
        expect(log).toHaveBeenCalledWith(expect.stringContaining('Could not start a reading session'));
    });
});

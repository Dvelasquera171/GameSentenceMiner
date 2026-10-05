// Home tab "Play": switch OBS to the game's scene (so its saved hook, OCR mode, overlay, Anki and
// reading-session automation apply) and start the game.

import { dialog, ipcMain, shell } from 'electron';
import { spawn } from 'child_process';
import * as fs from 'fs';
import { launchCommandFor, resolveLaunchTarget } from '../game_launch.js';
import { getGameLaunchTarget, setGameLaunchTarget } from '../store.js';
import { setOBSSceneByUuid } from './obs.js';

type SceneRef = { id: string; name: string };

function isSceneRef(value: unknown): value is SceneRef {
    return Boolean(
        value && typeof value === 'object' &&
        typeof (value as SceneRef).id === 'string' && (value as SceneRef).id &&
        typeof (value as SceneRef).name === 'string',
    );
}

export async function playGame(scene: SceneRef): Promise<{ success: boolean; error?: string; via?: string }> {
    const target = getGameLaunchTarget(scene.id);
    if (!target) return { success: false, error: 'GSM does not know how to start this game yet.' };
    try {
        await setOBSSceneByUuid(scene.id);
    } catch (error) {
        // OBS may still be starting; the game can launch anyway and the scene is chosen when it connects.
        console.warn(`[Play] Could not switch OBS to "${scene.name}":`, error);
    }
    const command = launchCommandFor(target);
    try {
        if (command.kind === 'steam') {
            await shell.openExternal(command.url);
        } else {
            if (!fs.existsSync(command.path)) {
                return { success: false, error: `The game file is missing: ${command.path}` };
            }
            const child = spawn(command.path, [], { cwd: command.cwd, detached: true, stdio: 'ignore' });
            child.unref();
        }
        console.log(`[Play] Started "${scene.name}" via ${command.kind === 'steam' ? command.url : command.path}`);
        return { success: true, via: command.kind };
    } catch (error) {
        return { success: false, error: (error as Error).message };
    }
}

export function registerGameLaunchIPC(): void {
    ipcMain.handle('game.getLaunchTarget', async (_, sceneId: unknown) =>
        typeof sceneId === 'string' && sceneId ? getGameLaunchTarget(sceneId) : null,
    );

    ipcMain.handle('game.chooseLaunchFile', async (_, scene: unknown) => {
        if (!isSceneRef(scene)) return null;
        const result = await dialog.showOpenDialog({
            title: `Game file for ${scene.name}`,
            properties: ['openFile'],
            filters: [{ name: 'Programs', extensions: ['exe', 'bat', 'lnk'] }, { name: 'All files', extensions: ['*'] }],
        });
        if (result.canceled || !result.filePaths[0]) return getGameLaunchTarget(scene.id);
        const target = resolveLaunchTarget(result.filePaths[0], fs);
        setGameLaunchTarget(scene.id, target);
        return target;
    });

    ipcMain.handle('game.play', async (_, scene: unknown) => {
        if (!isSceneRef(scene)) return { success: false, error: 'No game selected.' };
        return playGame(scene);
    });
}

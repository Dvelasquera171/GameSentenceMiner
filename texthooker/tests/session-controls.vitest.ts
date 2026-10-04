import { mount, tick, unmount } from 'svelte';
import { afterEach, expect, test, vi } from 'vitest';
import SessionControls from '../src/components/SessionControls.svelte';

afterEach(() => {
	vi.unstubAllGlobals();
	document.body.replaceChildren();
});

function reply(body: unknown, ok = true, status = 200) {
	return Promise.resolve({ ok, status, json: async () => body });
}

function sessionButton() {
	return document.querySelector('.session-button') as HTMLButtonElement;
}

test('starts a session for the current game and shows it as open', async () => {
	let open: unknown[] = [];
	const fetcher = vi.fn((url: string, init?: RequestInit) => {
		if (url.endsWith('/sessions/open')) return reply({ sessions: open });
		if (url.endsWith('/sessions/start')) {
			open = [{ id: 7, game_key: 'g1', game_name: 'ゲーム', start_ts: Date.now() / 1000 - 120 }];
			return reply({ session: open[0] }, true, 201);
		}
		throw new Error(`unexpected ${url} ${init?.method}`);
	});
	vi.stubGlobal('fetch', fetcher);
	const component = mount(SessionControls, { target: document.body, props: { refreshMs: 60000 } });
	await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
	expect(sessionButton().textContent).toContain('Session');

	sessionButton().click();
	await vi.waitFor(() => expect(sessionButton().textContent).toContain('ゲーム · 2 min'));
	const start = fetcher.mock.calls.find(([url]) => String(url).endsWith('/sessions/start'))!;
	expect(JSON.parse(String(start[1]!.body))).toEqual({});
	await unmount(component);
});

test('ending closes every open session by id and offers the review link', async () => {
	let open: unknown[] = [{ id: 3, game_key: 'g 1', game_name: 'Game', start_ts: Date.now() / 1000 }];
	const ended: unknown[] = [];
	const fetcher = vi.fn((url: string, init?: RequestInit) => {
		if (url.endsWith('/sessions/open')) return reply({ sessions: open });
		if (url.endsWith('/sessions/end')) {
			ended.push(JSON.parse(String(init!.body)));
			open = [];
			return reply({ closed: [] });
		}
		throw new Error(`unexpected ${url}`);
	});
	vi.stubGlobal('fetch', fetcher);
	const component = mount(SessionControls, { target: document.body, props: { refreshMs: 60000 } });
	await vi.waitFor(() => expect(sessionButton().textContent).toContain('Game'));
	sessionButton().click();
	await vi.waitFor(() => expect(document.querySelector('.review-link')).not.toBeNull());
	expect(ended).toEqual([{ session_id: 3 }]);
	expect((document.querySelector('.review-link') as HTMLAnchorElement).getAttribute('href')).toBe('/review?game_key=g%201');
	await unmount(component);
});

test('shows GSM errors, e.g. no current game', async () => {
	const fetcher = vi.fn((url: string) => {
		if (url.endsWith('/sessions/open')) return reply({ sessions: [] });
		return reply({ error: 'No game selected and no current game detected.' }, false, 400);
	});
	vi.stubGlobal('fetch', fetcher);
	const component = mount(SessionControls, { target: document.body, props: { refreshMs: 60000 } });
	await tick();
	sessionButton().click();
	await vi.waitFor(() => expect(document.querySelector('[role=alert]')?.textContent).toContain('no current game'));
	await unmount(component);
});

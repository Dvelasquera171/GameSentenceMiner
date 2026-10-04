import { mount, tick, unmount } from 'svelte';
import { afterEach, expect, test, vi } from 'vitest';
import AIHelp from '../src/components/AIHelp.svelte';

afterEach(() => {
	vi.unstubAllGlobals();
	document.body.replaceChildren();
});

async function openHelp() {
	const component = mount(AIHelp, { target: document.body, props: { id: 'line-1', text: '例文' } });
	await tick();
	return component;
}

function button(text: string) {
	return [...document.querySelectorAll('button')].find((element) => element.textContent === text)!;
}

test('explains a selected task and renders provider text safely', async () => {
	const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ analysis: '<img src=x onerror=bad()>\nGrammar explanation' }) });
	vi.stubGlobal('fetch', fetcher);
	const component = await openHelp();
	const select = document.querySelector('select')!;
	select.value = 'grammar';
	select.dispatchEvent(new Event('change'));
	await tick();
	button('Explain').click();
	await vi.waitFor(() => expect(document.querySelector('.result')?.textContent).toContain('Grammar explanation'));
	expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ id: 'line-1', text: '例文', mode: 'grammar', question: '' });
	expect(document.querySelector('img')).toBeNull();
	await unmount(component);
});

test('shows setup-required guidance and allows retry after setup', async () => {
	const fetcher = vi.fn()
		.mockResolvedValueOnce({ ok: false, json: async () => ({ code: 'ai_setup_required', error: 'AI setup is open. Paste your key and retry.' }) })
		.mockResolvedValueOnce({ ok: true, json: async () => ({ analysis: 'Ready now' }) });
	vi.stubGlobal('fetch', fetcher);
	const component = await openHelp();
	button('Explain').click();
	await vi.waitFor(() => expect(document.querySelector('[role=alert]')?.textContent).toContain('Paste your key'));
	button('Explain').click();
	await vi.waitFor(() => expect(document.querySelector('.result')?.textContent).toBe('Ready now'));
	expect(document.querySelector('[role=alert]')).toBeNull();
	await unmount(component);
});

test('custom questions require text and duplicate clicks do not send another request', async () => {
	const fetcher = vi.fn(() => new Promise(() => {}));
	vi.stubGlobal('fetch', fetcher);
	const component = await openHelp();
	const select = document.querySelector('select')!;
	select.value = 'custom';
	select.dispatchEvent(new Event('change'));
	await tick();
	expect(button('Explain').disabled).toBe(true);
	const input = document.querySelector('textarea[aria-label="Your question"]') as HTMLTextAreaElement;
	input.value = 'Why this ending?';
	input.dispatchEvent(new Event('input'));
	await tick();
	button('Explain').click();
	button('Explain').click();
	await tick();
	expect(fetcher).toHaveBeenCalledTimes(1);
	expect(JSON.parse(fetcher.mock.calls[0][1].body).question).toBe('Why this ending?');
	await unmount(component);
});

async function choose(label: string, value: string) {
	const select = document.querySelector(`select[aria-label="${label}"]`) as HTMLSelectElement;
	select.value = value;
	select.dispatchEvent(new Event('change'));
	await tick();
}

function type(selector: string, value: string) {
	const element = document.querySelector(selector) as HTMLTextAreaElement;
	element.value = value;
	element.dispatchEvent(new Event('input'));
	return element;
}

function press(element: HTMLElement, init: KeyboardEventInit) {
	element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true, ...init }));
}

test('follow-ups keep the thread and send earlier turns as history', async () => {
	const fetcher = vi.fn()
		.mockResolvedValueOnce({ ok: true, json: async () => ({ analysis: 'It marks the topic.' }) })
		.mockResolvedValueOnce({ ok: true, json: async () => ({ analysis: 'が marks the subject.' }) });
	vi.stubGlobal('fetch', fetcher);
	const component = await openHelp();
	await choose('Explanation type', 'custom');
	type('textarea[aria-label="Your question"]', 'この「は」はなぜ？');
	await tick();
	button('Explain').click();
	await vi.waitFor(() => expect(document.querySelector('.result')?.textContent).toBe('It marks the topic.'));

	const followUp = type('textarea[aria-label="Follow-up question"]', 'じゃあ「が」なら？');
	await tick();
	press(followUp, {});
	await vi.waitFor(() => expect(document.querySelectorAll('.result')).toHaveLength(2));
	const body = JSON.parse(fetcher.mock.calls[1][1].body);
	expect(body).toEqual({
		id: 'line-1',
		text: '例文',
		mode: 'custom',
		question: 'じゃあ「が」なら？',
		history: [{ question: 'この「は」はなぜ？', answer: 'It marks the topic.' }],
	});
	expect([...document.querySelectorAll('.question')].map((node) => node.textContent)).toEqual([
		'この「は」はなぜ？',
		'じゃあ「が」なら？',
	]);

	button('New thread').click();
	await tick();
	expect(document.querySelectorAll('.result')).toHaveLength(0);
	await unmount(component);
});

test('Shift+Enter and IME confirmation do not send; context choice is sent', async () => {
	const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ analysis: 'Answer' }) });
	vi.stubGlobal('fetch', fetcher);
	const component = await openHelp();
	await choose('Explanation type', 'custom');
	await choose('Dialogue context', '-1');
	const question = type('textarea[aria-label="Your question"]', '彼は誰？');
	await tick();
	press(question, { shiftKey: true });
	press(question, { isComposing: true });
	await tick();
	expect(fetcher).not.toHaveBeenCalled();
	press(question, {});
	await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
	expect(JSON.parse(fetcher.mock.calls[0][1].body).context_lines).toBe(-1);
	await unmount(component);
});

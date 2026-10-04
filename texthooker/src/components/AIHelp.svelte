<script lang="ts">
	import { createEventDispatcher, onDestroy, onMount } from 'svelte';
	import { getGSMEndpoint } from '../gsm';

	export let id: string;
	export let text: string;
	type Turn = { question: string; answer: string };
	const dispatch = createEventDispatcher<{ close: void }>();
	let mode = 'sentence';
	let question = '';
	let followUp = '';
	let contextChoice = 'default';
	let thread: Turn[] = [];
	let error = '';
	let busy = false;
	let modeSelect: HTMLSelectElement;
	let followUpInput: HTMLTextAreaElement;
	let controller: AbortController | undefined;
	const modes = [
		['sentence', 'Sentence breakdown'], ['grammar', 'Grammar'], ['vocabulary', 'Vocabulary'],
		['nuance', 'Nuance and tone'], ['context', 'Scene summary'], ['custom', 'Ask a question'],
	];
	// "Whole session" = this reading session (stats gap rule), capped server-side at ~20k characters.
	const contexts = [
		['default', 'Default context'], ['25', '±25 lines'], ['50', '±50 lines'], ['-1', 'Whole session'],
	];
	onDestroy(() => controller?.abort());
	onMount(() => modeSelect?.focus());

	async function ask(requestMode: string, requestQuestion: string, label: string): Promise<boolean> {
		if (busy) return false;
		busy = true;
		error = '';
		controller = new AbortController();
		const source = text.trim();
		const history = thread.map(({ question, answer }) => ({ question, answer }));
		const body: Record<string, unknown> = { id, text: source, mode: requestMode, question: requestQuestion };
		if (history.length) body.history = history;
		if (contextChoice !== 'default') body.context_lines = Number(contextChoice);
		try {
			const response = await fetch(getGSMEndpoint('/analyze-line'), {
				method: 'POST', headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body), signal: controller.signal,
			});
			const data = await response.json();
			if (source !== text.trim()) return false;
			if (!response.ok) {
				error = data.error || 'AI request failed. Check AI / Translation settings and retry.';
				return false;
			}
			thread = [...thread, { question: label, answer: data.analysis }];
			return true;
		} catch (cause) {
			if (!controller.signal.aborted) error = 'Could not reach GSM. Check that it is running, then retry.';
			return false;
		} finally {
			busy = false;
		}
	}

	async function explain() {
		if (mode === 'custom' && !question.trim()) return;
		const asked = question.trim();
		const label = mode === 'custom' ? asked : `Explain: ${modes.find(([value]) => value === mode)?.[1] ?? mode}`;
		if (await ask(mode, mode === 'custom' ? asked : '', label)) {
			question = '';
			followUpInput?.focus();
		}
	}

	async function sendFollowUp() {
		const asked = followUp.trim();
		if (!asked) return;
		if (await ask('custom', asked, asked)) {
			followUp = '';
			followUpInput?.focus();
		}
	}

	// Enter sends, Shift+Enter adds a line; Enter that confirms IME conversion must not send.
	function sendOnEnter(event: KeyboardEvent, send: () => void) {
		if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
			event.preventDefault();
			send();
		}
	}

	function newThread() {
		thread = [];
		followUp = '';
		error = '';
	}

	async function openSettings() {
		try {
			const response = await fetch(getGSMEndpoint('/ai/open-settings'), { method: 'POST' });
			const data = await response.json();
			error = data.settings_opened
				? 'AI setup is open. Choose a provider, paste an API key, test the connection, then retry here.'
				: 'On the computer running GSM, open Config → AI / Translation to set up a provider.';
		} catch (_) {
			error = 'Could not reach GSM. Open Config → AI / Translation on the computer running GSM.';
		}
	}
</script>

<div class="ai-help">
	<section aria-label="AI sentence help">
		<div class="heading">
			<strong>Ask AI about this line</strong>
			<button class="close-button" aria-label="Close AI help" on:click={() => dispatch('close')}>×</button>
		</div>
		<div class="controls">
			<select aria-label="Explanation type" bind:this={modeSelect} bind:value={mode} disabled={busy}>
				{#each modes as [value, label]}<option {value}>{label}</option>{/each}
			</select>
			<select aria-label="Dialogue context" title="How much surrounding dialogue the AI sees" bind:value={contextChoice} disabled={busy}>
				{#each contexts as [value, label]}<option {value}>{label}</option>{/each}
			</select>
			<button disabled={busy || (mode === 'custom' && !question.trim())} on:click={explain}>{busy ? 'Thinking…' : 'Explain'}</button>
			<button on:click={openSettings}>AI setup</button>
			{#if thread.length}<button disabled={busy} on:click={newThread}>New thread</button>{/if}
		</div>
		{#if mode === 'custom' && !thread.length}
			<label>Your question
				<textarea aria-label="Your question" rows="2" bind:value={question} maxlength="4000" placeholder="この「は」はなぜ？ (Enter sends, Shift+Enter new line)" disabled={busy} on:keydown={(event) => sendOnEnter(event, explain)}></textarea>
			</label>
		{/if}
		<div class="thread" aria-live="polite">
			{#each thread as turn}
				<div class="turn">
					<div class="question">{turn.question}</div>
					<div class="result">{turn.answer}</div>
				</div>
			{/each}
		</div>
		{#if thread.length}
			<label>Follow-up
				<textarea aria-label="Follow-up question" rows="2" bind:this={followUpInput} bind:value={followUp} maxlength="4000" placeholder="じゃあ「が」なら？ (Enter sends, Shift+Enter new line)" disabled={busy} on:keydown={(event) => sendOnEnter(event, sendFollowUp)}></textarea>
			</label>
			<div class="controls follow-up-controls">
				<button disabled={busy || !followUp.trim()} on:click={sendFollowUp}>{busy ? 'Thinking…' : 'Ask'}</button>
			</div>
		{/if}
		{#if error}<p role="alert">{error} <a href="https://docs.gamesentenceminer.com/docs/features/ai-features" target="_blank" rel="noreferrer">Setup guide</a></p>{/if}
	</section>
</div>

<style>
	.ai-help { margin: -10px 15px 12px; font: 14px/1.5 system-ui, sans-serif; writing-mode: horizontal-tb; }
	button, select, textarea { color: inherit; background: var(--color-base-200, #222); border: 1px solid #666; border-radius: 5px; padding: 5px 9px; font: inherit; }
	button { cursor: pointer; }
	button:disabled { opacity: .55; cursor: wait; }
	section { border: 1px solid #666; border-radius: 7px; padding: 12px; max-width: 850px; }
	.heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
	.close-button { border: 0; background: transparent; font-size: 20px; line-height: 1; padding: 0 4px; }
	.controls { display: flex; gap: 8px; flex-wrap: wrap; }
	.follow-up-controls { margin-top: 6px; }
	label { display: block; margin-top: 10px; }
	textarea { display: block; width: 100%; box-sizing: border-box; resize: vertical; }
	p { margin-top: 10px; }
	a { text-decoration: underline; }
	.turn { margin-top: 12px; }
	.question { font-weight: 600; opacity: .85; white-space: pre-wrap; overflow-wrap: anywhere; }
	.result { white-space: pre-wrap; overflow-wrap: anywhere; margin-top: 4px; user-select: text; }
</style>

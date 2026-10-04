<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { getGSMEndpoint } from '../gsm';

	// Manual reading-session marks for Session Review (/review): Start uses GSM's current game.
	type OpenSession = { id: number; game_key: string; game_name: string; start_ts: number };
	export let refreshMs = 30000;
	let open: OpenSession[] = [];
	let busy = false;
	let error = '';
	let lastEnded: OpenSession | null = null;
	let now = Date.now();
	let timer: ReturnType<typeof setInterval> | undefined;

	async function post(path: string, body: Record<string, unknown>) {
		const response = await fetch(getGSMEndpoint(path), {
			method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
		});
		const data = await response.json().catch(() => ({}));
		if (!response.ok) throw new Error(data.error || `GSM answered ${response.status}`);
		return data;
	}

	async function refresh() {
		now = Date.now();
		try {
			const response = await fetch(getGSMEndpoint('/api/review/sessions/open'));
			if (response.ok) open = (await response.json()).sessions || [];
		} catch (_) {
			// GSM not reachable; keep the last known state.
		}
	}

	async function toggle() {
		if (busy) return;
		busy = true;
		error = '';
		try {
			if (open.length) {
				const ended = open[0];
				for (const session of open) await post('/api/review/sessions/end', { session_id: session.id });
				lastEnded = ended;
			} else {
				await post('/api/review/sessions/start', {});
				lastEnded = null;
			}
			await refresh();
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			busy = false;
		}
	}

	function minutes(session: OpenSession) {
		return Math.max(0, Math.floor((now - session.start_ts * 1000) / 60000));
	}

	onMount(() => {
		void refresh();
		timer = setInterval(() => void refresh(), refreshMs);
	});
	onDestroy(() => clearInterval(timer));
</script>

<span class="session-controls">
	<button
		class="session-button"
		class:active={open.length > 0}
		disabled={busy}
		title={open.length
			? `End the reading session for ${open[0].game_name || open[0].game_key} (Session Review)`
			: 'Start a reading session for the current game (Session Review)'}
		on:click={toggle}
	>
		{#if open.length}■ {open[0].game_name || open[0].game_key} · {minutes(open[0])} min{:else}▶ Session{/if}
	</button>
	{#if lastEnded && !open.length}
		<a class="review-link" href={`/review?game_key=${encodeURIComponent(lastEnded.game_key)}`} target="_blank" rel="noreferrer">Review →</a>
	{/if}
	{#if error}<span class="session-error" role="alert" title={error}>{error}</span>{/if}
</span>

<style>
	.session-controls { display: inline-flex; align-items: center; gap: 6px; margin-right: 8px; font-size: 13px; writing-mode: horizontal-tb; }
	.session-button { border: 1px solid currentColor; border-radius: 12px; padding: 1px 9px; background: transparent; color: inherit; cursor: pointer; white-space: nowrap; max-width: 260px; overflow: hidden; text-overflow: ellipsis; }
	.session-button.active { border-color: #e06c75; color: #e06c75; }
	.session-button:disabled { opacity: .55; cursor: wait; }
	.review-link { text-decoration: underline; white-space: nowrap; }
	.session-error { color: #e06c75; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>

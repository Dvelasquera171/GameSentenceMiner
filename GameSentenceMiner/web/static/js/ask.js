// "Ask AI about this line": opened over the game by the overlay's AI hotkey.
// Starts on the newest line; every question about a line is kept as a thread and sent as history.
(function () {
    const $ = (id) => document.getElementById(id);
    const LABELS = { sentence: 'Break down', grammar: 'Grammar', vocabulary: 'Vocabulary', nuance: 'Nuance', context: 'Scene' };
    const state = { lines: [], index: -1, thread: [], busy: false };

    function setStatus(text, isError = false) {
        $('status').textContent = text;
        $('status').classList.toggle('error', isError);
    }

    function currentLine() {
        return state.lines[state.index] || null;
    }

    function renderLine() {
        const line = currentLine();
        $('line').textContent = line ? line.text : 'No lines yet. Advance the game, then press the AI hotkey again.';
        $('line').classList.toggle('empty', !line);
        $('position').textContent = line ? `${state.index + 1} / ${state.lines.length}` : '';
        $('prevBtn').disabled = state.index <= 0;
        $('nextBtn').disabled = state.index >= state.lines.length - 1;
    }

    function renderThread() {
        const thread = $('thread');
        thread.replaceChildren();
        for (const turn of state.thread) {
            const q = document.createElement('div');
            q.className = 'q';
            q.textContent = turn.question;
            const a = document.createElement('div');
            a.className = 'a';
            a.lang = 'ja';
            a.textContent = turn.answer;
            thread.append(q, a);
        }
        thread.scrollTop = thread.scrollHeight;
    }

    function selectLine(index) {
        if (index < 0 || index >= state.lines.length || index === state.index) return;
        state.index = index;
        state.thread = [];
        setStatus('');
        renderLine();
        renderThread();
    }

    async function loadLines() {
        try {
            const res = await fetch('/api/ask/recent-lines?count=30');
            const data = await res.json();
            state.lines = data.lines || [];
            $('game').textContent = data.game || '';
            state.index = state.lines.length - 1;
        } catch (err) {
            setStatus('Could not reach GSM. Is it running?', true);
        }
        renderLine();
    }

    async function ask(mode, question, label) {
        const line = currentLine();
        if (!line || state.busy) return false;
        state.busy = true;
        document.querySelectorAll('button[data-mode]').forEach((b) => (b.disabled = true));
        setStatus('Thinking…');
        const body = { id: line.id, text: line.text, mode, question };
        if (state.thread.length) body.history = state.thread.map(({ question: q, answer }) => ({ question: q, answer }));
        const context = $('context').value;
        if (context !== 'default') body.context_lines = Number(context);
        try {
            const res = await fetch('/analyze-line', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await res.json().catch(() => ({}));
            if (currentLine() !== line) return false;
            if (!res.ok) {
                setStatus(data.error || 'The AI request failed. Check GSM Settings → AI.', true);
                return false;
            }
            state.thread.push({ question: label, answer: data.analysis });
            renderThread();
            setStatus('');
            return true;
        } catch (err) {
            setStatus('Could not reach GSM. Is it running?', true);
            return false;
        } finally {
            state.busy = false;
            document.querySelectorAll('button[data-mode]').forEach((b) => (b.disabled = false));
        }
    }

    async function sendQuestion() {
        const text = $('question').value.trim();
        if (!text) return;
        if (await ask('custom', text, text)) $('question').value = '';
        $('question').focus();
    }

    document.querySelectorAll('button[data-mode]').forEach((button) => {
        button.onclick = () => ask(button.dataset.mode, '', `Explain: ${LABELS[button.dataset.mode]}`);
    });
    $('prevBtn').onclick = () => selectLine(state.index - 1);
    $('nextBtn').onclick = () => selectLine(state.index + 1);
    $('closeBtn').onclick = () => window.close();
    $('newThreadBtn').onclick = () => {
        state.thread = [];
        renderThread();
        setStatus('');
    };

    // Enter sends, Shift+Enter adds a line; Enter that confirms IME conversion must not send.
    $('question').addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
            event.preventDefault();
            sendQuestion();
        }
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') window.close();
        if (event.key === 'PageUp') { event.preventDefault(); selectLine(state.index - 1); }
        if (event.key === 'PageDown') { event.preventDefault(); selectLine(state.index + 1); }
    });

    loadLines().then(() => $('question').focus());
})();

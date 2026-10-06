// Session Review page over /api/review/*.
// Japanese is shown by default; English lives in <details> so it stays hidden until wanted.
// Everything Japanese is plain selectable text so Firefox Yomitan works on it.
(function () {
    const $ = (id) => document.getElementById(id);
    const state = { gameKey: '', pollTimer: null, reviewId: null, review: null, attempts: [] };

    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const fmtTime = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : '');
    const fmtDur = (s) => `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
    const KIND_LABELS = { events: '出来事', speaker_intent: '話し手の意図', meaning_in_context: '文脈での意味', register: '言葉遣い' };
    const CATEGORY_LABELS = {
        aspect_modality: 'アスペクト・モダリティ', omitted_subject: '省略された主語', register_attitude: '言葉遣い・態度',
        particle_nuance: '助詞のニュアンス', negation_scope: '否定の範囲', conditional_counterfactual: '条件・反実仮想',
        set_phrase: '慣用表現', other: 'その他',
    };
    const VERDICT_LABELS = { correct: '正解', partial: '部分点', incorrect: '不正解' };

    async function api(path, opts) {
        const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
        return data;
    }

    function showError(target, err) {
        target.innerHTML = `<span class="rv-wrong">${esc(err.message || err)}</span>`;
    }

    // ---- sessions -------------------------------------------------------

    async function loadGames() {
        const { games } = await api('/api/review/games');
        const sel = $('gameSelect');
        sel.innerHTML = games.map((g) => `<option value="${esc(g.game_key)}">${esc(g.game_name || g.game_key)} (${g.line_count} lines)</option>`).join('');
        const wanted = state.gameKey || new URLSearchParams(location.search).get('game_key');
        if (wanted && games.some((g) => g.game_key === wanted)) sel.value = wanted;
        state.gameKey = sel.value;
        sel.onchange = () => { state.gameKey = sel.value; loadSessions(); loadReviews(); };
    }

    async function loadSessions() {
        const body = $('sessionsTable').querySelector('tbody');
        if (!state.gameKey) { body.innerHTML = '<tr><td colspan="6" class="rv-muted">No games with lines yet.</td></tr>'; return; }
        try {
            const { sessions } = await api(`/api/review/sessions?game_key=${encodeURIComponent(state.gameKey)}`);
            body.innerHTML = sessions.length ? sessions.map((s, i) => `
                <tr>
                    <td>${esc(fmtTime(s.start_ts))}</td><td>${esc(fmtDur(s.duration_seconds))}</td>
                    <td>${s.line_count}</td><td>${s.char_count}</td>
                    <td><span class="rv-pill ${esc(s.source)}">${esc(s.source)}</span></td>
                    <td class="rv-row">
                        <button class="control-btn genBtn" data-i="${i}">Generate review</button>
                        <button class="rv-link linesBtn" data-i="${i}">Lines</button>
                        <button class="rv-link deleteLinesBtn" data-i="${i}" title="Delete this session's lines (also removes them from stats)">Delete lines</button>
                        ${s.manual_id ? `<button class="rv-link removeMarkBtn" data-i="${i}" title="Remove the Start/End mark; the lines stay">Remove mark</button>` : ''}
                    </td>
                </tr>
                <tr class="rv-lines" data-i="${i}" style="display:none;"><td colspan="6"></td></tr>`).join('') : '<tr><td colspan="6" class="rv-muted">No sessions for this game.</td></tr>';
            const at = (b) => sessions[+b.dataset.i];
            body.querySelectorAll('.genBtn').forEach((b) => (b.onclick = () => generate(at(b).start_ts, at(b).end_ts, b)));
            body.querySelectorAll('.linesBtn').forEach((b) => (b.onclick = () => toggleLines(at(b), body.querySelector(`tr.rv-lines[data-i="${b.dataset.i}"]`))));
            body.querySelectorAll('.deleteLinesBtn').forEach((b) => (b.onclick = () => deleteSessionLines(at(b), b)));
            body.querySelectorAll('.removeMarkBtn').forEach((b) => (b.onclick = () => removeMark(at(b), b)));
            const { sessions: open } = await api('/api/review/sessions/open');
            $('openSessionBadge').textContent = open.length ? `Open session: ${open.map((o) => `${o.game_name || o.game_key} since ${fmtTime(o.start_ts)}`).join(', ')}` : '';
        } catch (err) { body.innerHTML = `<tr><td colspan="6">${esc(err.message)}</td></tr>`; }
    }

    function sessionLinesUrl(s) {
        return `/api/review/session-lines?game_key=${encodeURIComponent(s.game_key || state.gameKey)}&start_ts=${s.start_ts}&end_ts=${s.end_ts}`;
    }

    async function toggleLines(s, row) {
        if (row.style.display !== 'none') { row.style.display = 'none'; return; }
        const cell = row.querySelector('td');
        cell.innerHTML = '<span class="rv-spinner"></span>';
        row.style.display = '';
        try {
            const { lines } = await api(sessionLinesUrl(s));
            const shown = lines.slice(0, 300);
            cell.innerHTML = `<div class="rv-ja" lang="ja" style="max-height:320px; overflow:auto; font-size:15px;">${shown.map((ln) =>
                `<div><span class="rv-muted">${esc(new Date(ln.timestamp * 1000).toLocaleTimeString())}</span> ${esc(ln.text)}</div>`).join('')}</div>
                ${lines.length > shown.length ? `<div class="rv-muted">…and ${lines.length - shown.length} more</div>` : ''}`;
        } catch (err) { showError(cell, err); }
    }

    async function deleteSessionLines(s, button) {
        button.disabled = true;
        try {
            const { lines, char_count } = await api(sessionLinesUrl(s));
            if (!lines.length) { alert('This session has no lines left.'); return; }
            const question = `Delete ${lines.length} lines (${char_count} characters) of ${s.game_name || s.game_key}, `
                + `${fmtTime(s.start_ts)} → ${fmtTime(s.end_ts)}?\n\nThey are also removed from your stats. This cannot be undone.`;
            if (!confirm(question)) return;
            const result = await api('/api/delete-sentence-lines', { method: 'POST', body: JSON.stringify({ line_ids: lines.map((ln) => ln.id) }) });
            alert(result.message || `Deleted ${result.deleted_count} lines.`);
            await loadGames();
            await loadSessions();
        } catch (err) {
            alert(err.message);
        } finally {
            button.disabled = false;
        }
    }

    async function removeMark(s, button) {
        if (!confirm('Remove this Start/End mark? The lines stay and fall back into automatic sessions.')) return;
        button.disabled = true;
        try {
            await api(`/api/review/sessions/${s.manual_id}/delete`, { method: 'POST', body: '{}' });
            await loadSessions();
        } catch (err) {
            alert(err.message);
            button.disabled = false;
        }
    }

    async function generate(start, end, button, gameKey = state.gameKey, gameName = '') {
        if (button) button.disabled = true;
        try {
            const { review_id } = await api('/api/review/generate', {
                method: 'POST',
                body: JSON.stringify({ game_key: gameKey, start_ts: start, end_ts: end, ...(gameName ? { game_name: gameName } : {}) }),
            });
            await loadReviews();
            openReview(review_id);
        } catch (err) {
            alert(err.message);
        } finally {
            if (button) button.disabled = false;
        }
    }

    async function startOrEnd(path, body) {
        try { await api(path, { method: 'POST', body: JSON.stringify(body) }); await loadSessions(); } catch (err) { alert(err.message); }
    }

    // ---- review list ----------------------------------------------------

    function statusText(r) {
        if (r.status === 'running' || r.status === 'pending') return `${r.stage || 'queued'}${r.progress ? ` ${r.progress}` : ''}`;
        if (r.status === 'failed') return r.error || 'failed';
        return `${r.question_count ?? (r.quiz || []).length} questions`;
    }

    async function loadReviews() {
        const list = $('reviewsList');
        try {
            const { reviews } = await api(`/api/review/reviews?game_key=${encodeURIComponent(state.gameKey)}`);
            list.innerHTML = reviews.length ? reviews.map((r) => `
                <li class="${r.id === state.reviewId ? 'active' : ''}">
                    <span class="rv-pill ${esc(r.status)}">${esc(r.status)}</span>
                    <button class="rv-link openBtn" data-id="${r.id}">${esc(fmtTime(r.start_ts))} → ${esc(fmtTime(r.end_ts))}</button>
                    <span class="rv-muted">${r.line_count} lines · ${esc(statusText(r))}</span>
                    ${r.status === 'failed' ? `<button class="control-btn retryBtn" data-id="${r.id}">Retry</button>` : ''}
                </li>`).join('') : '<li class="rv-muted">No reviews yet. Pick a session above and press Generate review.</li>';
            list.querySelectorAll('.openBtn').forEach((b) => (b.onclick = () => openReview(+b.dataset.id)));
            list.querySelectorAll('.retryBtn').forEach((b) => {
                const r = reviews.find((x) => x.id === +b.dataset.id);
                b.onclick = () => generate(r.start_ts, r.end_ts, b, r.game_key, r.game_name);
            });
        } catch (err) { list.innerHTML = `<li>${esc(err.message)}</li>`; }
    }

    // ---- one review -----------------------------------------------------

    async function openReview(id) {
        state.reviewId = id;
        clearTimeout(state.pollTimer);
        const card = $('reviewCard');
        card.style.display = '';
        let r;
        try { r = await api(`/api/review/reviews/${id}`); } catch (err) { showError($('reviewStatus'), err); return; }
        if (state.reviewId !== id) return;
        state.review = r;
        history.replaceState(null, '', `?game_key=${encodeURIComponent(r.game_key)}&review=${id}`);
        $('reviewTitle').textContent = `${r.game_name || r.game_key}: ${fmtTime(r.start_ts)} → ${fmtTime(r.end_ts)}`;
        $('reviewMeta').textContent = `${r.line_count} lines · ${r.char_count} characters${r.model ? ` · ${r.provider} / ${r.model}` : ''}`;
        const status = $('reviewStatus');
        if (r.status === 'running' || r.status === 'pending') {
            $('reviewBody').style.display = 'none';
            status.innerHTML = `<span class="rv-spinner"></span> Generating: <b>${esc(r.stage || 'queued')}</b> ${esc(r.progress || '')} <span class="rv-muted">(updates every 3 s; you can leave this page)</span>`;
            state.pollTimer = setTimeout(() => openReview(id), 3000);
            return;
        }
        if (r.status === 'failed') {
            $('reviewBody').style.display = 'none';
            status.innerHTML = `<span class="rv-wrong">Failed: ${esc(r.error || 'unknown error')}</span> <button class="control-btn" id="retryOpenBtn">Retry</button>`;
            $('retryOpenBtn').onclick = (e) => generate(r.start_ts, r.end_ts, e.currentTarget, r.game_key, r.game_name);
            loadReviews();
            return;
        }
        status.innerHTML = '';
        try { state.attempts = (await api(`/api/review/reviews/${id}/attempts`)).attempts || []; } catch (_) { state.attempts = []; }
        render(r);
        loadReviews();
    }

    function render(r) {
        const extra = Array.isArray(r.highlights) ? { items: r.highlights } : (r.highlights || {});
        $('reviewBody').style.display = '';
        $('summaryJa').textContent = r.summary_ja || '';
        $('summaryEn').textContent = r.summary_en || '';

        const characters = extra.characters || [];
        $('charactersSection').style.display = characters.length ? '' : 'none';
        $('charactersList').innerHTML = characters.map((c) => `
            <div class="rv-card">
                <div lang="ja" class="rv-ja"><b>${esc(c.name)}</b>：${esc(c.attitude_ja)}</div>
                <details><summary>English</summary>${esc(c.attitude_en)}</details>
            </div>`).join('');

        const missedJa = extra.may_have_missed_ja || [];
        $('missedSection').style.display = missedJa.length ? '' : 'none';
        $('missedJa').innerHTML = missedJa.map((x) => `<li>${esc(x)}</li>`).join('');
        $('missedEn').innerHTML = (extra.may_have_missed_en || []).map((x) => `<li>${esc(x)}</li>`).join('');

        const items = extra.items || [];
        $('highlightsList').innerHTML = items.length ? items.map((h, i) => `
            <div class="rv-card">
                <div class="rv-quote" lang="ja">${esc(h.quote)}</div>
                <div class="rv-muted">${esc(h.construction)} · ${esc(CATEGORY_LABELS[h.category] || h.category)}${h.confidence ? ` · confidence ${esc(h.confidence)}` : ''}</div>
                <div class="rv-reading" lang="ja">
                    <div class="rv-wrong">✗ ${esc(h.naive_reading_ja)}</div>
                    <div class="rv-right">✓ ${esc(h.correct_reading_ja)}</div>
                </div>
                <details><summary>English</summary>
                    <div class="rv-wrong">✗ ${esc(h.naive_reading_en)}</div>
                    <div class="rv-right">✓ ${esc(h.correct_reading_en)}</div>
                    <div><i>${esc(h.why_it_matters_en)}</i></div>
                </details>
                <div class="rv-row" style="margin-top:6px;">
                    <button class="rv-link copyBtn" data-index="${i}">Copy line</button>
                    <a class="rv-link" href="/search?q=${encodeURIComponent(h.quote || '')}" target="_blank" rel="noreferrer">Find in Search</a>
                </div>
            </div>`).join('') : '<p class="rv-muted">No highlights in this session.</p>';
        $('highlightsList').querySelectorAll('.copyBtn').forEach((b) => (b.onclick = async () => {
            try { await navigator.clipboard.writeText(items[+b.dataset.index].quote || ''); b.textContent = 'Copied'; } catch (_) { b.textContent = 'Copy failed'; }
            setTimeout(() => (b.textContent = 'Copy line'), 1500);
        }));

        renderQuiz(r);
    }

    function attemptsFor(qid) {
        return state.attempts.filter((a) => String(a.question_id) === String(qid));
    }

    function renderScore(r) {
        const quiz = r.quiz || [];
        const best = quiz.map((q) => Math.max(-1, ...attemptsFor(q.id).map((a) => Number(a.grade?.score ?? -1))));
        const answered = best.filter((s) => s >= 0);
        $('quizScore').textContent = quiz.length
            ? `回答済み ${answered.length}/${quiz.length}${answered.length ? ` · 平均 ${Math.round(answered.reduce((a, b) => a + b, 0) / answered.length)}点` : ''}`
            : '';
    }

    function gradeHtml(g, q, attemptId) {
        const fixes = (g.japanese_fixes || []).map((f) => `
            <div lang="ja">✎ <span class="rv-wrong">${esc(f.original)}</span> → <span class="rv-right">${esc(f.fixed)}</span></div>
            ${f.note_en ? `<details><summary>Why (English)</summary>${esc(f.note_en)}</details>` : ''}`).join('');
        const original = g.original ? ` <span class="rv-muted">（元: ${esc(VERDICT_LABELS[g.original.verdict] || g.original.verdict)} ${esc(g.original.score)}点）</span>` : '';
        const reply = g.reply_ja ? `
            <div class="rv-reply"><div class="rv-muted">質問への回答</div>
                <div class="rv-ja" lang="ja">${esc(g.reply_ja)}</div>
                ${g.reply_en ? `<details><summary>English</summary>${esc(g.reply_en)}</details>` : ''}</div>` : '';
        const thread = (g.discussion || []).map((d) => `
            <div class="rv-reply">
                <div class="rv-muted">あなた</div><div class="rv-ja" lang="ja">${esc(d.message)}</div>
                <div class="rv-muted" style="margin-top:4px;">AI${d.revised ? ` · 採点を変更: ${esc(VERDICT_LABELS[d.revised.verdict] || d.revised.verdict)} ${esc(d.revised.score)}点` : ''}</div>
                <div class="rv-ja" lang="ja">${esc(d.reply_ja)}</div>
                ${d.reply_en ? `<details><summary>English</summary>${esc(d.reply_en)}</details>` : ''}
            </div>`).join('');
        const discuss = attemptId ? `
            <details class="rv-discuss"><summary>質問・異議</summary>
                <textarea lang="ja" rows="2" placeholder="採点への質問や異議、文法の質問など（日本語でも英語でも）"></textarea>
                <div class="rv-row" style="margin-top:6px;"><button class="control-btn discussBtn" data-attempt="${esc(attemptId)}">送る</button><span class="discussBusy rv-muted"></span></div>
            </details>` : '';
        return `
            <div><span class="rv-pill ${esc(g.verdict)}">${esc(VERDICT_LABELS[g.verdict] || g.verdict)}</span> <span class="rv-score">${esc(g.score)}点</span>${original}</div>
            <div class="rv-ja" lang="ja" style="margin-top:6px;">${esc(g.feedback_ja)}</div>
            <details><summary>Feedback in English</summary>${esc(g.feedback_en)}</details>
            ${fixes ? `<div class="rv-muted" style="margin-top:6px;">日本語の直し</div>${fixes}` : ''}
            ${reply}
            <details><summary>模範解答</summary><div class="rv-ja" lang="ja">${esc(g.model_answer_ja)}</div></details>
            ${q && q.reference_answer_ja ? `<details><summary>参考解答</summary><div class="rv-ja" lang="ja">${esc(q.reference_answer_ja)}</div>
                ${q.reference_answer_en ? `<details><summary>English</summary>${esc(q.reference_answer_en)}</details>` : ''}</details>` : ''}
            ${thread}
            ${discuss}`;
    }

    function wireDiscuss(card, q) {
        const button = card.querySelector('.discussBtn');
        if (!button) return;
        button.onclick = async () => {
            const box = card.querySelector('.rv-discuss textarea');
            const busy = card.querySelector('.discussBusy');
            const message = box.value.trim();
            if (!message || button.disabled) return;
            const reviewId = state.reviewId;
            const attemptId = Number(button.dataset.attempt);
            button.disabled = true;
            busy.innerHTML = '<span class="rv-spinner"></span> 考え中…';
            try {
                const { grade: g } = await api(`/api/review/reviews/${reviewId}/attempts/${attemptId}/discuss`, { method: 'POST', body: JSON.stringify({ message }) });
                if (state.reviewId !== reviewId) return;
                const attempt = state.attempts.find((a) => a.id === attemptId);
                if (attempt) attempt.grade = g;
                card.querySelector('.gradeResult').innerHTML = `<div class="rv-grade">${gradeHtml(g, q, attemptId)}</div>`;
                card.querySelector('.gradeHistory').innerHTML = historyHtml(card.dataset.qid);
                wireDiscuss(card, q);
                renderScore(state.review);
            } catch (err) {
                button.disabled = false;
                showError(busy, err);
            }
        };
    }

    function historyHtml(qid) {
        const past = attemptsFor(qid);
        if (!past.length) return '';
        return `<details class="pastAttempts"><summary>過去の解答 (${past.length})</summary>${past.map((a) => `
            <div class="rv-card">
                <div class="rv-muted">${esc(fmtTime(a.created_at))} · <span class="rv-pill ${esc(a.grade?.verdict)}">${esc(VERDICT_LABELS[a.grade?.verdict] || a.grade?.verdict || '')}</span> ${esc(a.grade?.score ?? '')}点</div>
                <div class="rv-ja" lang="ja">${esc(a.answer)}</div>
            </div>`).join('')}</details>`;
    }

    function renderQuiz(r) {
        const quiz = r.quiz || [];
        $('quizList').innerHTML = quiz.length ? quiz.map((q, i) => {
            const last = attemptsFor(q.id).slice(-1)[0];
            return `
            <div class="rv-card rv-quiz" data-qid="${esc(q.id)}">
                <div class="rv-ja" lang="ja"><b>Q${i + 1}.</b> ${esc(q.question_ja)} <span class="rv-muted">［${esc(KIND_LABELS[q.kind] || q.kind)}］</span></div>
                ${q.hint_ja ? `<details><summary>ヒント</summary><span class="rv-ja" lang="ja">${esc(q.hint_ja)}</span></details>` : ''}
                <textarea lang="ja" rows="3" placeholder="日本語で答えてください"></textarea>
                <div class="rv-row" style="margin-top:6px;">
                    <button class="control-btn gradeBtn">採点</button>
                    <span class="gradeBusy rv-muted"></span>
                </div>
                <div class="gradeResult">${last ? `<div class="rv-grade">${gradeHtml(last.grade || {}, q, last.id)}</div>` : ''}</div>
                <div class="gradeHistory">${historyHtml(q.id)}</div>
            </div>`;
        }).join('') : '<p class="rv-muted">No quiz questions.</p>';
        $('quizList').querySelectorAll('.rv-quiz').forEach((card) => {
            card.querySelector('.gradeBtn').onclick = () => grade(card);
            wireDiscuss(card, quiz.find((x) => String(x.id) === card.dataset.qid));
            card.querySelector('textarea').addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.isComposing) { e.preventDefault(); grade(card); }
            });
        });
        renderScore(r);
    }

    async function grade(card) {
        const answer = card.querySelector('textarea').value.trim();
        const button = card.querySelector('.gradeBtn');
        const busy = card.querySelector('.gradeBusy');
        const out = card.querySelector('.gradeResult');
        if (!answer || button.disabled) return;
        const reviewId = state.reviewId;
        const q = (state.review?.quiz || []).find((x) => String(x.id) === card.dataset.qid);
        button.disabled = true;
        busy.innerHTML = '<span class="rv-spinner"></span> 採点中…';
        try {
            const { grade: g, attempt_id } = await api(`/api/review/reviews/${reviewId}/grade`, { method: 'POST', body: JSON.stringify({ question_id: card.dataset.qid, answer }) });
            if (state.reviewId !== reviewId) return;
            state.attempts.push({ id: attempt_id, question_id: card.dataset.qid, answer, grade: g, created_at: Date.now() / 1000 });
            out.innerHTML = `<div class="rv-grade">${gradeHtml(g, q, attempt_id)}</div>`;
            card.querySelector('.gradeHistory').innerHTML = historyHtml(card.dataset.qid);
            wireDiscuss(card, q);
            renderScore(state.review);
        } catch (err) {
            showError(out, err);
        } finally {
            button.disabled = false;
            busy.textContent = '';
        }
    }

    $('startSessionBtn').onclick = () => startOrEnd('/api/review/sessions/start', { game_key: state.gameKey, game_name: $('gameSelect').selectedOptions[0]?.text.replace(/ \(\d+ lines\)$/, '') });
    $('endSessionBtn').onclick = () => startOrEnd('/api/review/sessions/end', { game_key: state.gameKey });

    loadGames()
        .then(() => {
            loadSessions();
            loadReviews();
            const wanted = Number(new URLSearchParams(location.search).get('review'));
            if (wanted) openReview(wanted);
        })
        .catch((err) => alert(err.message));
})();

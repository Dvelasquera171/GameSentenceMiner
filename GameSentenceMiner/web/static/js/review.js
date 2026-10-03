// Session Review page: bare functional scaffold over /api/review/*.
// Japanese is shown by default; English lives in <details> so it stays hidden until wanted.
(function () {
    const $ = (id) => document.getElementById(id);
    const state = { gameKey: '', pollTimer: null, reviewId: null };

    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const fmtTime = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : '');
    const fmtDur = (s) => `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;

    async function api(path, opts) {
        const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
        return data;
    }

    async function loadGames() {
        const { games } = await api('/api/review/games');
        const sel = $('gameSelect');
        sel.innerHTML = games.map((g) => `<option value="${esc(g.game_key)}">${esc(g.game_name || g.game_key)} (${g.line_count})</option>`).join('');
        state.gameKey = sel.value;
        sel.onchange = () => { state.gameKey = sel.value; loadSessions(); loadReviews(); };
    }

    async function loadSessions() {
        if (!state.gameKey) return;
        const { sessions } = await api(`/api/review/sessions?game_key=${encodeURIComponent(state.gameKey)}`);
        $('sessionsTable').querySelector('tbody').innerHTML = sessions.map((s) => `
            <tr>
                <td>${esc(fmtTime(s.start_ts))}</td><td>${esc(fmtDur(s.duration_seconds))}</td>
                <td>${s.line_count}</td><td>${s.char_count}</td><td>${esc(s.source)}</td>
                <td><button data-start="${s.start_ts}" data-end="${s.end_ts}" class="genBtn">Generate review</button></td>
            </tr>`).join('');
        document.querySelectorAll('.genBtn').forEach((b) => (b.onclick = () => generate(+b.dataset.start, +b.dataset.end)));
        const { sessions: open } = await api('/api/review/sessions/open');
        $('openSessionBadge').textContent = open.length ? `Open: ${open.map((o) => o.game_name || o.game_key).join(', ')}` : '';
    }

    async function loadReviews() {
        const { reviews } = await api(`/api/review/reviews?game_key=${encodeURIComponent(state.gameKey)}`);
        $('reviewsList').innerHTML = reviews.map((r) => `
            <li><a href="#" data-id="${r.id}">${esc(fmtTime(r.start_ts))} → ${esc(fmtTime(r.end_ts))}</a>
            — ${esc(r.status)}${r.stage ? ` (${esc(r.stage)} ${esc(r.progress)})` : ''}, ${r.question_count} questions</li>`).join('');
        $('reviewsList').querySelectorAll('a').forEach((a) => (a.onclick = (e) => { e.preventDefault(); openReview(+a.dataset.id); }));
    }

    async function generate(start, end) {
        try {
            const { review_id } = await api('/api/review/generate', { method: 'POST', body: JSON.stringify({ game_key: state.gameKey, start_ts: start, end_ts: end }) });
            await loadReviews();
            openReview(review_id);
        } catch (err) { alert(err.message); }
    }

    async function openReview(id) {
        state.reviewId = id;
        clearTimeout(state.pollTimer);
        const r = await api(`/api/review/reviews/${id}`);
        $('reviewCard').style.display = '';
        $('reviewTitle').textContent = `${r.game_name || r.game_key}: ${fmtTime(r.start_ts)} → ${fmtTime(r.end_ts)}`;
        $('reviewStatus').textContent = r.status === 'done' ? `${r.line_count} lines, ${r.char_count} chars, ${r.model}` : `${r.status}: ${r.stage} ${r.progress} ${r.error || ''}`;
        if (r.status === 'running' || r.status === 'pending') {
            state.pollTimer = setTimeout(() => openReview(id), 3000);
            return;
        }
        render(r);
        loadReviews();
    }

    function render(r) {
        const extra = Array.isArray(r.highlights) ? { items: r.highlights } : (r.highlights || {});
        $('summaryJa').textContent = r.summary_ja || '';
        $('summaryEn').textContent = r.summary_en || '';
        $('charactersList').innerHTML = (extra.characters || []).map((c) => `<li><b>${esc(c.name)}</b>: <span lang="ja">${esc(c.attitude_ja)}</span><details><summary>English</summary>${esc(c.attitude_en)}</details></li>`).join('');
        $('missedJa').innerHTML = (extra.may_have_missed_ja || []).map((x) => `<li>${esc(x)}</li>`).join('');
        $('missedEn').innerHTML = (extra.may_have_missed_en || []).map((x) => `<li>${esc(x)}</li>`).join('');
        $('highlightsList').innerHTML = (extra.items || []).map((h) => `
            <div class="dashboard-card" style="margin:8px 0;">
                <div lang="ja"><b>${esc(h.quote)}</b> <small>(${esc(h.construction)}, ${esc(h.category)})</small></div>
                <div lang="ja">✗ ${esc(h.naive_reading_ja)}<br>✓ ${esc(h.correct_reading_ja)}</div>
                <details><summary>English</summary>✗ ${esc(h.naive_reading_en)}<br>✓ ${esc(h.correct_reading_en)}<br><i>${esc(h.why_it_matters_en)}</i></details>
            </div>`).join('');
        $('quizList').innerHTML = (r.quiz || []).map((q, i) => `
            <div class="dashboard-card" style="margin:8px 0;" data-qid="${esc(q.id)}">
                <div lang="ja"><b>Q${i + 1}.</b> ${esc(q.question_ja)} <small>[${esc(q.kind)}]</small></div>
                ${q.hint_ja ? `<details><summary>ヒント</summary><span lang="ja">${esc(q.hint_ja)}</span></details>` : ''}
                <textarea lang="ja" rows="2" style="width:100%;" placeholder="日本語で答えてください"></textarea>
                <button class="gradeBtn">採点</button>
                <div class="gradeResult"></div>
            </div>`).join('');
        document.querySelectorAll('.gradeBtn').forEach((b) => (b.onclick = () => grade(b.closest('[data-qid]'))));
    }

    async function grade(card) {
        const answer = card.querySelector('textarea').value.trim();
        const out = card.querySelector('.gradeResult');
        if (!answer) return;
        out.textContent = '採点中…';
        try {
            const { grade: g } = await api(`/api/review/reviews/${state.reviewId}/grade`, { method: 'POST', body: JSON.stringify({ question_id: card.dataset.qid, answer }) });
            out.innerHTML = `<div><b>${esc(g.verdict)}</b> (${g.score})</div><div lang="ja">${esc(g.feedback_ja)}</div>
                ${(g.japanese_fixes || []).map((f) => `<div lang="ja">✎ ${esc(f.original)} → ${esc(f.fixed)} <details><summary>why</summary>${esc(f.note_en)}</details></div>`).join('')}
                <details><summary>English</summary>${esc(g.feedback_en)}</details>
                <details><summary>模範解答</summary><span lang="ja">${esc(g.model_answer_ja)}</span></details>`;
        } catch (err) { out.textContent = err.message; }
    }

    $('startSessionBtn').onclick = async () => { try { await api('/api/review/sessions/start', { method: 'POST', body: JSON.stringify({ game_key: state.gameKey, game_name: $('gameSelect').selectedOptions[0]?.text }) }); loadSessions(); } catch (e) { alert(e.message); } };
    $('endSessionBtn').onclick = async () => { try { await api('/api/review/sessions/end', { method: 'POST', body: JSON.stringify({ game_key: state.gameKey }) }); loadSessions(); } catch (e) { alert(e.message); } };

    loadGames().then(() => { loadSessions(); loadReviews(); }).catch((e) => alert(e.message));
})();

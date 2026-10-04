// Setup check page over /api/setup-check.
// Page load never sends the AI test request; only the Re-check button does (ai_test=1).
(function () {
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    function render(data) {
        $('setupSummary').textContent = data.summary && data.summary.text ? data.summary.text : 'No checks ran';
        const tested = data.ai_tested ? 'AI test request sent.' : 'AI test not sent (press Re-check).';
        $('setupMeta').textContent = `Checked ${new Date(data.checked_at).toLocaleTimeString()}. ${tested}`;
        $('setupChecks').innerHTML = (data.checks || []).map((c) => `
            <div class="setup-row" data-check="${esc(c.id)}">
                <span class="setup-badge ${esc(c.status)}">${esc(c.status)}</span>
                <div>
                    <div class="setup-title">${esc(c.title)}</div>
                    <div class="setup-detail">${esc(c.detail)}</div>
                    ${c.fix && c.status !== 'ok' ? `<div class="setup-fix">${esc(c.fix)}</div>` : ''}
                </div>
            </div>`).join('');
    }

    async function load(aiTest) {
        const btn = $('recheckBtn');
        btn.disabled = true;
        $('setupSummary').textContent = aiTest ? 'Checking (with AI test)…' : 'Checking…';
        try {
            const res = await fetch(`/api/setup-check${aiTest ? '?ai_test=1' : ''}`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
            render(data);
        } catch (err) {
            $('setupSummary').textContent = `Setup check failed: ${err.message}`;
        } finally {
            btn.disabled = false;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        $('recheckBtn').onclick = () => load(true);
        load(false);
    });
})();

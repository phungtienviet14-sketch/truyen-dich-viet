// Header search suggestions.
//
// Every value from the API is written with textContent or a validated image
// URL, never innerHTML: novel titles come from a crawled source and are
// untrusted text. Kept out of the page so the CSP can eventually drop
// 'unsafe-inline' for scripts.
(function () {
    const input = document.getElementById('navSearchInput');
    const panel = document.getElementById('navSearchResults');
    if (!input || !panel) return;

    let timer = null;
    let latest = 0;

    function hide() {
        panel.replaceChildren();
        panel.classList.add('hidden');
    }

    function row(item) {
        const link = ui.element('a', 'flex items-center gap-3 p-2.5 hover:bg-slate-800 transition-colors');
        link.href = `/novel/${encodeURIComponent(item.id)}`;

        const cover = ui.safeImageURL(item.cover_url || '');
        if (cover) {
            const image = ui.element('img', 'w-9 h-12 rounded-lg object-cover flex-shrink-0 bg-slate-800');
            image.src = cover;
            image.alt = '';
            image.loading = 'lazy';
            image.referrerPolicy = 'no-referrer';
            link.append(image);
        } else {
            link.append(ui.element('div', 'w-9 h-12 rounded-lg bg-slate-800 flex-shrink-0'));
        }

        const body = ui.element('div', 'min-w-0 flex-1');
        body.append(ui.element('p', 'text-xs font-bold text-slate-100 truncate', item.title || ''));
        const meta = [item.author, item.genre].filter(Boolean).join(' · ');
        body.append(ui.element('p', 'text-[10px] text-slate-500 font-mono truncate', meta));
        body.append(ui.element('p', 'text-[10px] text-slate-500 font-mono',
            `${item.translated_chapters || 0}/${item.total_chapters || 0} chương đã dịch`));
        link.append(body);
        return link;
    }

    function render(items, term) {
        if (!items.length) {
            panel.replaceChildren(ui.element('p', 'p-4 text-xs text-slate-500 text-center',
                'Không có truyện nào khớp.'));
        } else {
            const list = ui.element('div', 'divide-y divide-slate-800');
            items.forEach(item => list.append(row(item)));
            const all = ui.element('a',
                'block p-2.5 text-center text-[11px] font-semibold text-emerald-400 hover:bg-slate-800 transition-colors border-t border-slate-800',
                'Xem tất cả kết quả');
            all.href = `/tim-kiem?q=${encodeURIComponent(term)}`;
            panel.replaceChildren(list, all);
        }
        panel.classList.remove('hidden');
    }

    input.addEventListener('input', function () {
        clearTimeout(timer);
        const term = input.value.trim();
        if (term.length < 2) return hide();
        timer = setTimeout(async function () {
            const ticket = ++latest;
            try {
                const response = await fetch(`/api/novels/search?q=${encodeURIComponent(term)}`);
                if (!response.ok) return hide();
                const data = await response.json();
                // A slower earlier request must not overwrite a newer one.
                if (ticket !== latest) return;
                render(Array.isArray(data.results) ? data.results : [], term);
            } catch (error) {
                hide();
            }
        }, 220);
    });

    input.addEventListener('keydown', event => { if (event.key === 'Escape') hide(); });
    document.addEventListener('click', event => {
        if (!panel.contains(event.target) && event.target !== input) hide();
    });
})();

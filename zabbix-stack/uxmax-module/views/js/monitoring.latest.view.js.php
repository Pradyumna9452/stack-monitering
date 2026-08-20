<?php declare(strict_types = 0);
/**
 * uxMAX override of the stock JS view for "monitoring.latest.view". The stock
 * page calls $this->includeJsFile('monitoring.latest.view.js.php') and that
 * call resolves to this file when our module overrides the view. We render
 * the core JS view verbatim (re-using the original template in this scope,
 * where $this and $data are bound exactly like in the core CView include) and
 * then append the row-greying helper for items that came back with status
 * DISABLED.
 *
 * The greying is gated by an HTML attribute set in Module::getAssets() so it
 * activates only when the uxMAX preference is on.
 *
 * @var CView $this
 * @var array $data
 */

$core_js = APP::getRootDir().'/app/views/js/monitoring.latest.view.js.php';

if (is_readable($core_js)) {
    $src = file_get_contents($core_js);

    // Drop the leading PHP header block (license + declare + docblock) so the
    // remaining template can be eval'd in this file's scope without "declare()
    // must be the first statement" errors.
    $close = strpos($src, '?'.'>');
    $template = ($close !== false) ? substr($src, $close + 2) : $src;

    eval('?'.'>'.$template);
}
?>

<style>
[uxmax-latest-show-disabled='on'] tr.uxmax-row-disabled td,
[uxmax-latest-show-disabled='on'] tr.uxmax-row-disabled td a,
[uxmax-latest-show-disabled='on'] tr.uxmax-row-disabled td span {
    color: #888 !important;
    opacity: 0.65;
}
[uxmax-latest-show-disabled='on'] tr.uxmax-row-disabled td input[type="checkbox"] {
    opacity: 0.65;
}
[uxmax-latest-show-disabled='on'] .uxmax-disabled-badge {
    display: inline-block;
    width: 16px;
    height: 16px;
    padding: 0;
    background: #b5b5b5;
    color: #fff !important;
    font-weight: bold;
    font-style: italic;
    font-size: 11px;
    line-height: 16px;
    text-align: center;
    border-radius: 2px;
    opacity: 1;
    vertical-align: middle;
}
</style>

<script>
(function() {
    const ROW_CLASS = 'uxmax-row-disabled';
    const BADGE_CLASS = 'uxmax-disabled-badge';
    const BADGE_TITLE = <?= json_encode(_('Item is disabled')) ?>;

    function isEnabled() {
        // Check live — the uxmax-latest-show-disabled attribute is set by
        // zbx_add_post_js which fires on DOMContentLoaded, AFTER this IIFE
        // runs at parse time. Gating at the IIFE level would bail out before
        // the attribute is set.
        return document.documentElement.getAttribute('uxmax-latest-show-disabled') === 'on';
    }

    function disabledSet() {
        const ids = window.uxmaxDisabledItemIds;
        return Array.isArray(ids) ? new Set(ids.map(String)) : new Set();
    }

    function applyDisabledRowClass() {
        if (!isEnabled()) {
            return;
        }

        const set = disabledSet();

        // Latest data rows expose itemid through the row's item checkbox name "itemids[ID]".
        document.querySelectorAll('input[type="checkbox"][name^="itemids["]').forEach(cb => {
            const m = cb.name.match(/^itemids\[(\d+)\]$/);
            if (!m) return;
            const row = cb.closest('tr');
            if (!row) return;

            const is_disabled = set.has(m[1]);
            row.classList.toggle(ROW_CLASS, is_disabled);

            // Drop a tiny "D" badge into the Info column (rightmost cell) so it
            // is clear at a glance which rows are disabled items.
            const info_cell = row.querySelector('td:last-child');
            if (!info_cell) return;

            let badge = info_cell.querySelector('.' + BADGE_CLASS);
            if (is_disabled && !badge) {
                badge = document.createElement('span');
                badge.className = BADGE_CLASS;
                badge.textContent = 'D';
                badge.title = BADGE_TITLE;
                info_cell.appendChild(badge);
            }
            else if (!is_disabled && badge) {
                badge.remove();
            }
        });
    }

    // Intercept latest.view.refresh responses so that disabled-row styling stays
    // in sync with auto-refresh. Falls through transparently for every other URL.
    const __origFetch = window.fetch;
    window.fetch = function(input, init) {
        const url = (typeof input === 'string') ? input : (input && input.url) || '';
        const promise = __origFetch.apply(this, arguments);

        if (url.indexOf('latest.view.refresh') !== -1) {
            promise.then(response => {
                response.clone().json().then(data => {
                    if (data && Array.isArray(data.uxmax_disabled_itemids)) {
                        window.uxmaxDisabledItemIds = data.uxmax_disabled_itemids;
                    }
                }).catch(() => {});
            }).catch(() => {});
        }

        return promise;
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', applyDisabledRowClass);
    }
    else {
        applyDisabledRowClass();
    }

    // Re-apply the class whenever the table is re-rendered (auto-refresh,
    // subfilter expansion, sort change, etc.).
    const observer = new MutationObserver(() => {
        applyDisabledRowClass();
    });
    observer.observe(document.body, {childList: true, subtree: true});
})();
</script>

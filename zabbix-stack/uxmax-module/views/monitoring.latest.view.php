<?php declare(strict_types = 0);
/**
 * uxMAX override of the stock "monitoring.latest.view" view. Renders the
 * original Latest data page unchanged (by including the stock view by
 * absolute path) and then emits a small payload of disabled item IDs that
 * are visible in the current result set. The JS injected by the override of
 * monitoring.latest.view.js.php reads that payload to grey out the rows.
 *
 * @var CView $this
 * @var array $data
 */

$stock_view = APP::getRootDir().'/app/views/monitoring.latest.view.php';

if (is_readable($stock_view)) {
    include $stock_view;
}
else {
    error(_s('Cannot read original view: "%1$s".', $stock_view));
    return;
}

$uxmax_disabled_itemids = [];

foreach ($data['items'] ?? [] as $itemid => $item) {
    if (($item['status'] ?? null) == ITEM_STATUS_DISABLED) {
        $uxmax_disabled_itemids[] = (string) $itemid;
    }
}
?>
<script>
window.uxmaxDisabledItemIds = <?= json_encode($uxmax_disabled_itemids) ?>;
</script>

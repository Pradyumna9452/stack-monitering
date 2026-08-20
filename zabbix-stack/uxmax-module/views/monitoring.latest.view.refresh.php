<?php declare(strict_types = 0);
/**
 * uxMAX override of the stock "monitoring.latest.view.refresh" view. Captures
 * the stock JSON response, augments it with the list of disabled item IDs
 * present in the refreshed result set, and re-emits the JSON. The client-side
 * JS picks the key up to keep grey-out styling in sync after auto-refresh.
 *
 * @var CView $this
 * @var array $data
 */

$stock_view = APP::getRootDir().'/app/views/monitoring.latest.view.refresh.php';

if (!is_readable($stock_view)) {
    error(_s('Cannot read original view: "%1$s".', $stock_view));
    return;
}

ob_start();
include $stock_view;
$json = ob_get_clean();

$output = json_decode($json, true);

if (is_array($output)) {
    $disabled_itemids = [];

    foreach ($data['results']['items'] ?? [] as $itemid => $item) {
        if (($item['status'] ?? null) == ITEM_STATUS_DISABLED) {
            $disabled_itemids[] = (string) $itemid;
        }
    }

    $output['uxmax_disabled_itemids'] = $disabled_itemids;
    echo json_encode($output);
}
else {
    echo $json;
}

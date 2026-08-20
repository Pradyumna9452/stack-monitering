<?php

namespace Modules\uxMAX\Actions;

use API, CArrayHelper, CRoleHelper, CSettingsHelper, CControllerLatestViewRefresh;
use Modules\uxMAX\Module;

/**
 * Mirror of LatestView for the asynchronous table refresh action used by the
 * Latest data auto-refresh. Behaviour is identical to the stock controller
 * unless the uxMAX preference is on and filter_show_disabled=1 is set.
 */
class LatestViewRefresh extends CControllerLatestViewRefresh {

    public Module $module;

    private function showDisabled(): bool {
        return isset($this->module)
            && !empty($this->module->preferences->get()['state']['latestshowdisabled']);
    }

    protected function prepareData(array $filter, $sort_field, $sort_order) {
        $status_filter = $this->showDisabled()
            ? [ITEM_STATUS_ACTIVE, ITEM_STATUS_DISABLED]
            : [ITEM_STATUS_ACTIVE];

        $groupids = $filter['groupids'] ? getSubGroups($filter['groupids']) : null;

        $hosts = API::Host()->get([
            'output' => ['hostid', 'name', 'status', 'maintenanceid', 'maintenance_status', 'maintenance_type'],
            'groupids' => $groupids,
            'hostids' => $filter['hostids'] ?: null,
            'preservekeys' => true
        ]);

        $search_limit = CSettingsHelper::get(CSettingsHelper::SEARCH_LIMIT);
        $select_items_cnt = 0;
        $select_items = [];

        foreach ($hosts as $hostid => $host) {
            if ($select_items_cnt > $search_limit) {
                unset($hosts[$hostid]);
                continue;
            }

            $select_items += API::Item()->get([
                'output' => ['itemid', 'hostid', 'value_type'],
                'hostids' => [$hostid],
                'webitems' => true,
                'evaltype' => $filter['evaltype'],
                'tags' => $filter['tags'] ?: null,
                'filter' => [
                    'status' => $status_filter,
                    'state' => $filter['state'] == -1 ? null : $filter['state']
                ],
                'search' => $filter['name'] === '' ? null : ['name_resolved' => $filter['name']],
                'preservekeys' => true
            ]);

            $select_items_cnt = count($select_items);
        }

        if ($select_items) {
            $items = CArrayHelper::renameObjectsKeys(API::Item()->get([
                'output' => ['itemid', 'type', 'hostid', 'name_resolved', 'key_', 'delay', 'history', 'trends',
                    'status', 'value_type', 'units', 'description', 'state', 'error'
                ],
                'selectTags' => ['tag', 'value'],
                'selectValueMap' => ['mappings'],
                'itemids' => array_keys($select_items),
                'webitems' => true,
                'preservekeys' => true
            ]), ['name_resolved' => 'name']);

            $items_rw = $items;

            if (!$this->hasInput('filter_counters') && $this->getUserType() < USER_TYPE_SUPER_ADMIN
                    && !$this->checkAccess(CRoleHelper::ACTIONS_INVOKE_EXECUTE_NOW)) {
                $items_rw = API::Item()->get([
                    'output' => [],
                    'itemids' => array_keys($items),
                    'editable' => true,
                    'preservekeys' => true
                ]);
            }

            if ($sort_field === 'host') {
                $items = array_map(function ($item) use ($hosts) {
                    return $item + [
                        'host_name' => $hosts[$item['hostid']]['name']
                    ];
                }, $items);

                CArrayHelper::sort($items, [[
                    'field' => 'host_name',
                    'order' => $sort_order
                ]]);
            }
            else {
                CArrayHelper::sort($items, [[
                    'field' => 'name',
                    'order' => $sort_order
                ]]);
            }
        }
        else {
            $hosts = [];
            $items = [];
            $items_rw = [];
        }

        return [
            'hosts' => $hosts,
            'items' => $items,
            'items_rw' => $items_rw
        ];
    }
}

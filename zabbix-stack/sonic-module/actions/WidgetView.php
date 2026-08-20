<?php declare(strict_types = 0);

namespace Modules\SonicOverview\Actions;

use API,
	CControllerDashboardWidgetView,
	CControllerResponseData;

class WidgetView extends CControllerDashboardWidgetView {

	protected function doAction(): void {
		// ── Discover SONIC/* host groups ─────────────────────────────────────
		$sonic_sub_groups = API::HostGroup()->get([
			'output'      => ['groupid', 'name'],
			'search'      => ['name' => 'SONIC/'],
			'startSearch' => true,
			'sortfield'   => 'name',
			'sortorder'   => ZBX_SORT_UP,
		]);

		// Map suffix → canonical type key
		$suffix_to_type = [
			'Servers'   => 'Server',
			'Switches'  => 'Switch',
			'Storage'   => 'Storage',
			'Firewall'  => 'Firewall',
			'Firewalls' => 'Firewall',
		];

		$grp_id_to_type = [];
		$sonic_groupids = [];
		$found_types    = [];

		foreach ($sonic_sub_groups as $grp) {
			$suffix = substr($grp['name'], strlen('SONIC/'));
			$type   = $suffix_to_type[$suffix] ?? $suffix;
			$grp_id_to_type[$grp['groupid']] = $type;
			$sonic_groupids[]                = $grp['groupid'];
			$found_types[$type]              = true;
		}

		// Canonical display order — any discovered type appears in this order
		$type_order = ['Server', 'Firewall', 'Switch', 'Storage'];
		$ordered    = array_filter($type_order, fn($t) => isset($found_types[$t]));
		foreach (array_keys($found_types) as $t) {
			if (!in_array($t, $ordered)) $ordered[] = $t;
		}

		// Pre-populate groups (including empty ones like SONIC/Firewall)
		$groups = [];
		foreach ($ordered as $t) {
			$groups[$t] = [];
		}

		// ── Fetch hosts in SONIC/* groups ─────────────────────────────────────
		$hosts = $sonic_groupids
			? API::Host()->get([
				'output'           => ['hostid', 'name'],
				'selectInterfaces'  => ['ip', 'main', 'type', 'available'],
				'selectHostGroups'  => ['groupid'],
				'groupids'         => $sonic_groupids,
				'sortfield'        => 'name',
				'sortorder'        => ZBX_SORT_UP,
			])
			: [];

		$hostids       = array_column($hosts, 'hostid');
		$problem_count = array_fill_keys($hostids, 0);

		// ── Tally interface availability across all SONIC hosts ───────────────
		$iface_stats = ['up' => 0, 'down' => 0, 'unknown' => 0];
		foreach ($hosts as $host) {
			foreach ($host['interfaces'] as $iface) {
				$av = (int)($iface['available'] ?? 0);
				if ($av === 1)     $iface_stats['up']++;
				elseif ($av === 2) $iface_stats['down']++;
				else               $iface_stats['unknown']++;
			}
		}

		// ── ICMP ping ─────────────────────────────────────────────────────────
		$ping = [];
		if ($hostids) {
			foreach (API::Item()->get([
				'output'  => ['hostid', 'lastvalue'],
				'hostids' => $hostids,
				'filter'  => ['key_' => 'icmpping'],
			]) as $item) {
				$ping[$item['hostid']] = (int) $item['lastvalue'];
			}
		}

		// ── Performance items ─────────────────────────────────────────────────
		$cpu = $mem = $disk = $bw_in = $bw_out = [];
		if ($hostids) {
			foreach (API::Item()->get([
				'output'      => ['hostid', 'name', 'lastvalue'],
				'hostids'     => $hostids,
				'search'      => ['name' => [
					'CPU utilization',
					'Memory utilization',
					'Space: Used, in %',
					'Bits received',
					'Bits sent',
				]],
				'searchByAny' => true,
				'monitored'   => true,
			]) as $item) {
				$hid = $item['hostid'];
				$n   = strtolower($item['name']);
				$v   = (float) $item['lastvalue'];

				if (str_contains($n, 'cpu utilization'))        { $cpu[$hid]  = $v; }
				elseif (str_contains($n, 'memory utilization')) { $mem[$hid]  = $v; }
				elseif (str_contains($n, 'space: used, in %'))  { $disk[$hid] = max($disk[$hid] ?? 0, $v); }
				elseif (str_contains($n, 'bits received'))      { $bw_in[$hid]  = ($bw_in[$hid]  ?? 0) + $v; }
				elseif (str_contains($n, 'bits sent'))          { $bw_out[$hid] = ($bw_out[$hid] ?? 0) + $v; }
			}
		}

		// ── Active alarms per host ────────────────────────────────────────────
		if ($hostids) {
			$problems = API::Problem()->get([
				'output'     => ['objectid'],
				'hostids'    => $hostids,
				'suppressed' => false,
				'source'     => EVENT_SOURCE_TRIGGERS,
				'object'     => EVENT_OBJECT_TRIGGER,
			]);
			if ($problems) {
				$tids     = array_unique(array_column($problems, 'objectid'));
				$triggers = API::Trigger()->get([
					'output'      => ['triggerid'],
					'selectHosts' => ['hostid'],
					'triggerids'  => $tids,
				]);
				$host_set = array_flip($hostids);
				foreach ($triggers as $t) {
					foreach ($t['hosts'] as $h) {
						if (isset($host_set[$h['hostid']])) {
							$problem_count[$h['hostid']]++;
						}
					}
				}
			}
		}

		// ── Build rows and assign to groups ──────────────────────────────────
		foreach ($hosts as $host) {
			$hid = $host['hostid'];

			// IP and interface availability from main interface
			$ip = ''; $iface_avail = 0;
			foreach ($host['interfaces'] as $iface) {
				if ($iface['main'] == 1) {
					$ip          = $iface['ip'];
					$iface_avail = (int)($iface['available'] ?? 0);
					break;
				}
			}

			// Status: ICMP ping > interface availability > metric presence
			if (isset($ping[$hid])) {
				$status = $ping[$hid] ? 'Up' : 'Down';
			} elseif ($iface_avail === 1) {
				$status = 'Up';
			} elseif ($iface_avail === 2) {
				$status = 'Down';
			} elseif (isset($cpu[$hid]) || isset($mem[$hid]) || isset($bw_in[$hid]) || isset($bw_out[$hid])) {
				$status = 'Up';
			} else {
				$status = 'Unknown';
			}

			// Resolve group from SONIC/* group membership
			$type = 'Other';
			foreach ($host['hostgroups'] as $grp) {
				if (isset($grp_id_to_type[$grp['groupid']])) {
					$type = $grp_id_to_type[$grp['groupid']];
					break;
				}
			}

			if (!array_key_exists($type, $groups)) {
				$groups[$type] = [];
			}

			$groups[$type][] = [
				'hostid' => $hid,
				'name'   => $host['name'],
				'ip'     => $ip,
				'status' => $status,
				'type'   => $type,
				'cpu'    => isset($cpu[$hid])  ? round($cpu[$hid],  1) : null,
				'mem'    => isset($mem[$hid])  ? round($mem[$hid],  1) : null,
				'disk'   => isset($disk[$hid]) ? round($disk[$hid], 1) : null,
				'bw_in'  => $bw_in[$hid]  ?? null,
				'bw_out' => $bw_out[$hid] ?? null,
				'alarms' => $problem_count[$hid],
			];
		}

		$this->setResponse(new CControllerResponseData([
			'name'        => $this->getInput('name', $this->widget->getDefaultName()),
			'groups'      => $groups,
			'iface_stats' => $iface_stats,
			'error'       => null,
			'user'        => ['debug_mode' => $this->getDebugMode()],
		]));
	}
}

<?php declare(strict_types = 0);
/**
 * SONIC Site Overview — summary cards + aligned group table + clickable alarms.
 *
 * @var CView  $this
 * @var array  $data   {name, groups[], iface_stats[], error, user}
 */

$groups      = $data['groups']      ?? [];
$iface_stats = $data['iface_stats'] ?? ['up' => 0, 'down' => 0, 'unknown' => 0];
$error       = $data['error']       ?? null;

$group_meta = [
	'Server'   => ['label' => 'Servers',   'icon' => '&#x1F5A5;', 'css' => ''],
	'Firewall' => ['label' => 'Firewalls', 'icon' => '&#x1F6E1;', 'css' => 'grp-firewall'],
	'Switch'   => ['label' => 'Switches',  'icon' => '&#x1F500;', 'css' => 'grp-switch'],
	'Storage'  => ['label' => 'Storage',   'icon' => '&#x1F4BE;', 'css' => 'grp-storage'],
	'Other'    => ['label' => 'Other',     'icon' => '&bull;',     'css' => 'grp-other'],
];

$fmt_bps = static function(?float $bps): string {
	if ($bps === null) return 'N/A';
	if ($bps >= 1e9) return number_format($bps / 1e9, 1) . ' Gbps';
	if ($bps >= 1e6) return number_format($bps / 1e6, 1) . ' Mbps';
	if ($bps >= 1e3) return number_format($bps / 1e3, 1) . ' Kbps';
	return round($bps) . ' bps';
};

$pct_cls = static function(?float $v, float $w, float $c): string {
	if ($v === null) return '';
	if ($v >= $c) return 'sonic-crit';
	if ($v >= $w) return 'sonic-warn';
	return 'sonic-ok';
};

/* Stats per group */
$group_stats = [];
$total_all   = 0;
foreach ($groups as $type => $rows) {
	$up = $dn = $unk = 0;
	foreach ($rows as $r) {
		match(strtolower($r['status'])) {
			'up'    => $up++,
			'down'  => $dn++,
			default => $unk++,
		};
	}
	$group_stats[$type] = ['up' => $up, 'down' => $dn, 'unknown' => $unk, 'total' => count($rows)];
	$total_all += count($rows);
}

/* Build a per-group problem.view URL (empty group → link clears filter) */
$grp_url = static function(array $rows): string {
	$hids = array_column($rows, 'hostid');
	if (!$hids) {
		return 'zabbix.php?action=problem.view&filter_reset=1';
	}
	$qs = implode('&', array_map(
		fn($i, $h) => 'hostids%5B'.$i.'%5D='.urlencode($h),
		array_keys($hids), $hids
	));
	return 'zabbix.php?action=problem.view&filter_set=1&show=1&' . $qs;
};

ob_start();
?>
<div class="sonic-overview-widget">
<?php if ($error): ?>
	<div class="sonic-empty"><?= htmlspecialchars($error) ?></div>
<?php elseif (empty($groups)): ?>
	<div class="sonic-empty">No <strong>SONIC/*</strong> host groups found in Zabbix.</div>
<?php else: ?>

	<!-- ── Group Summary Cards ── -->
	<div class="sonic-summary">
<?php foreach ($groups as $type => $rows):
	$meta  = $group_meta[$type] ?? ['label' => $type, 'icon' => '&bull;', 'css' => 'grp-other'];
	$stats = $group_stats[$type];
	$url   = $grp_url($rows);
?>
		<a href="<?= $url ?>" target="_top" class="sonic-summary-card <?= $meta['css'] ?>"
		   title="View <?= htmlspecialchars($meta['label']) ?> problems">
			<div class="sonic-sc-title"><?= $meta['icon'] ?> <?= htmlspecialchars($meta['label']) ?> (<?= $stats['total'] ?>)</div>
			<div class="sonic-sc-badges">
<?php if ($stats['total'] === 0): ?>
				<span class="sonic-badge sonic-badge-empty">No hosts</span>
<?php else: ?>
				<span class="sonic-badge sonic-badge-up">&#9679; <?= $stats['up'] ?> Up</span>
				<?php if ($stats['down'] > 0): ?>
				<span class="sonic-badge sonic-badge-down">&#9679; <?= $stats['down'] ?> Down</span>
				<?php endif; ?>
				<?php if ($stats['unknown'] > 0): ?>
				<span class="sonic-badge sonic-badge-unknown">&#9679; <?= $stats['unknown'] ?> Unknown</span>
				<?php endif; ?>
<?php endif; ?>
			</div>
		</a>
<?php endforeach; ?>
	</div>

	<!-- ── Interface Stats Bar ── -->
	<div class="sonic-iface-bar">
		<span class="sonic-iface-label">&#x1F5A7; Network Interfaces</span>
		<span class="sonic-iface-up">&#9679; <?= $iface_stats['up'] ?> Up</span>
		<span class="sonic-iface-sep">&bull;</span>
		<span class="sonic-iface-down">&#9679; <?= $iface_stats['down'] ?> Down</span>
		<?php if ($iface_stats['unknown'] > 0): ?>
		<span class="sonic-iface-sep">&bull;</span>
		<span class="sonic-iface-unk">&#9679; <?= $iface_stats['unknown'] ?> Unknown</span>
		<?php endif; ?>
		<span class="sonic-iface-total">(<?= $iface_stats['up'] + $iface_stats['down'] + $iface_stats['unknown'] ?> total)</span>
	</div>

	<!-- ── Main Table ── -->
	<div class="sonic-scroll">
		<table class="sonic-table">
			<thead>
				<tr>
					<th class="col-host">Hostname</th>
					<th class="col-ip">IP Address</th>
					<th class="col-status">Status</th>
					<th class="col-pct">CPU %</th>
					<th class="col-pct">Memory %</th>
					<th class="col-pct">Disk %</th>
					<th class="col-bw">BW In</th>
					<th class="col-bw">BW Out</th>
					<th class="col-alarms">Alarms</th>
				</tr>
			</thead>
			<tbody>
<?php foreach ($groups as $type => $rows):
	$meta = $group_meta[$type] ?? ['label' => $type, 'icon' => '&bull;', 'css' => 'grp-other'];
	$url  = $grp_url($rows);
?>
				<tr class="sonic-group-row <?= $meta['css'] ?>">
					<td colspan="9">
						<a href="<?= $url ?>" target="_top" class="sonic-grp-link">
							<?= $meta['icon'] ?> <?= htmlspecialchars($meta['label']) ?> — <?= count($rows) ?> hosts
						</a>
					</td>
				</tr>
<?php if (empty($rows)): ?>
				<tr>
					<td colspan="9" class="sonic-empty-group">
						No hosts in SONIC/<?= htmlspecialchars($meta['label']) ?> group yet
					</td>
				</tr>
<?php else: ?>
<?php foreach ($rows as $r):
	$sc        = match(strtolower($r['status'])) { 'up' => 'status-up', 'down' => 'status-down', default => 'status-unknown' };
	$alarm_url = 'zabbix.php?action=problem.view&filter_set=1&show=1&hostids%5B0%5D=' . urlencode($r['hostid']);
?>
				<tr class="<?= $r['alarms'] > 0 ? 'sonic-alarm-row' : '' ?>">
					<td class="col-host sonic-hostname"><?= htmlspecialchars($r['name']) ?></td>
					<td class="col-ip sonic-ip"><?= htmlspecialchars($r['ip'] ?: '—') ?></td>
					<td class="col-status">
						<span class="sonic-status-pill <?= $sc ?>"><?= htmlspecialchars($r['status']) ?></span>
					</td>
					<td class="col-pct <?= $pct_cls($r['cpu'], 70, 90) ?>"><?= $r['cpu'] !== null ? $r['cpu'] . '%' : '<span class="sonic-na">N/A</span>' ?></td>
					<td class="col-pct <?= $pct_cls($r['mem'], 80, 90) ?>"><?= $r['mem'] !== null ? $r['mem'] . '%' : '<span class="sonic-na">N/A</span>' ?></td>
					<td class="col-pct <?= $pct_cls($r['disk'], 80, 90) ?>"><?= $r['disk'] !== null ? $r['disk'] . '%' : '<span class="sonic-na">N/A</span>' ?></td>
					<td class="col-bw sonic-bw"><?= $fmt_bps($r['bw_in']) ?></td>
					<td class="col-bw sonic-bw"><?= $fmt_bps($r['bw_out']) ?></td>
					<td class="col-alarms">
<?php if ($r['alarms'] > 0): ?>
						<a href="<?= $alarm_url ?>" target="_top" class="sonic-alarm-link <?= $r['alarms'] >= 3 ? 'sonic-alarm-high' : 'sonic-alarm-low' ?>"><?= (int) $r['alarms'] ?></a>
<?php else: ?>
						<span class="sonic-alarm-zero">0</span>
<?php endif; ?>
					</td>
				</tr>
<?php endforeach; ?>
<?php endif; ?>
<?php endforeach; ?>
			</tbody>
		</table>
	</div>

	<!-- ── Footer ── -->
	<div class="sonic-footer">
		<span><?= $total_all ?> hosts &bull; SONIC</span>
		<span><?= date('H:i:s') ?></span>
	</div>

<?php endif; ?>
</div>
<?php
$html = ob_get_clean();
(new CWidgetView($data))->addItem($html)->show();

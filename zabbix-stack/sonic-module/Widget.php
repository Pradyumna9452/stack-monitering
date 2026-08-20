<?php declare(strict_types = 0);

namespace Modules\SonicOverview;

use Zabbix\Core\CWidget;

class Widget extends CWidget {

	public function getDefaultName(): string {
		return 'SONIC Site Overview';
	}
}

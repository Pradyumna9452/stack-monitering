<?php

namespace Modules\uxMAX\Actions;

use CController, CControllerResponseRedirect, CMessageHelper, CUrl, CWebUser;
use Modules\uxMAX\Module;

/**
 * POST controller that persists per-user uxMAX preferences into CProfile.
 */
class UserPrefsUpdate extends CController {

    public Module $module;

    protected function checkInput() {
        $fields = [
            'override' => 'in 0,1',
            'colortags' => 'array'
        ];

        $ret = $this->validateInput($fields);

        if (!$ret) {
            $response = new CControllerResponseRedirect(
                (new CUrl('zabbix.php'))->setArgument('action', 'mod.uxmax.userprefs')
            );
            $response->setFormData($this->getInputAll());
            CMessageHelper::setErrorTitle(_('Cannot update preferences'));
            $this->setResponse($response);
        }

        return $ret;
    }

    protected function checkPermissions() {
        return !CWebUser::isGuest() && $this->module->preferences->isUserOverrideAllowed();
    }

    protected function doAction() {
        $override = (bool) $this->getInput('override', 0);
        $colortags_input = $this->getInput('colortags', []);

        $colortags = array_filter($colortags_input, fn($t) => trim($t['value'] ?? '') !== '');
        $colortags = array_values($colortags);

        $this->module->preferences->setUserOverride($override, $colortags);

        CMessageHelper::setSuccessTitle(_('Preferences updated'));
        $curl = (new CUrl('zabbix.php'))->setArgument('action', 'mod.uxmax.userprefs');
        $this->setResponse(new CControllerResponseRedirect($curl));
    }
}

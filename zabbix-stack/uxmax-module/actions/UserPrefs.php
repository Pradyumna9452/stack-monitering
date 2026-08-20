<?php

namespace Modules\uxMAX\Actions;

use CController, CControllerResponseData, CWebUser;
use Modules\uxMAX\Module;

/**
 * GET controller for per-user uxMAX preferences (currently: color tags
 * override). Accessible to any logged-in non-guest user.
 */
class UserPrefs extends CController {

    public Module $module;

    protected function init() {
        $this->disableCsrfValidation();
    }

    protected function checkInput() {
        return true;
    }

    protected function checkPermissions() {
        return !CWebUser::isGuest() && $this->module->preferences->isUserOverrideAllowed();
    }

    protected function doAction() {
        $admin_prefs = $this->module->preferences->get();
        $user_data = $this->module->preferences->getUserOverride();

        $this->setResponse(new CControllerResponseData([
            'override' => (int) $user_data['override'],
            'colortags' => $user_data['colortags'],
            'admin_colortags' => $admin_prefs['colortags'] ?? []
        ]));
    }
}

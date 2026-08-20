<?php

namespace Modules\uxMAX;

use APP, CMenu, CMenuItem, CWebUser;
use CController as Action;
use Modules\uxMAX\Services\ModuleTranslator;
use Modules\uxMAX\Services\Preferences;
use Zabbix\Core\CModule;

/**
 * @property Preferences $preferences
 */
class Module extends CModule {

    public Preferences $preferences;

    public function getAssets(): array {
        $assets = parent::getAssets();
        $action = APP::Component()->router->getAction();
        $preferences = $this->preferences->get();

        if ($action === 'mod.uxmax.form') {
            $assets['js'][] = 'uxmax.form.js';
        }

        if ($preferences['state']['windrag'] || $action === 'mod.uxmax.form') {
            $assets['js'][] = 'uxmax.dragm.js';
        }

        if ($preferences['state']['bodybg']) {
            zbx_add_post_js("document.documentElement.setAttribute('uxmax-coloring-body', 'on')");
        }

        if ($preferences['state']['asidebg']) {
            zbx_add_post_js("document.documentElement.setAttribute('uxmax-coloring-sidebar', 'on')");
        }

        if ($preferences['state']['latestshowdisabled'] && $action === 'latest.view') {
            zbx_add_post_js("document.documentElement.setAttribute('uxmax-latest-show-disabled', 'on')");
        }

        if ($preferences['state']['hidewidgetheader']) {
            zbx_add_post_js("document.documentElement.setAttribute('uxmax-hide-widget-header', 'on')");
        }

        if ($preferences['state']['compactdashboard']) {
            zbx_add_post_js("document.documentElement.setAttribute('uxmax-compact-dashboard', 'on')");
        }

        if ($preferences['state']['colortags'] || $preferences['state']['bodybg'] || $preferences['state']['asidebg']
            || $preferences['state']['syntax'] || $preferences['state']['exprhighlight']) {
            $assets['css'][] = '../../../../zabbix.php?action=mod.uxmax.css';
        }

        if ($preferences['state']['exprhighlight'] || $preferences['state']['syntax'] || $action === 'mod.uxmax.form') {
            $assets['js'][] = 'ace.1.5.0/ace.js';
        }

        if ($preferences['state']['exprhighlight']) {
            $assets['js'][] = 'ace.1.5.0/mode-zabbix_expr.js';
            $assets['js'][] = 'uxmax.expr.js';
        }

        if ($preferences['state']['syntax'] || $action === 'mod.uxmax.form') {
            $assets['js'] = array_merge($assets['js'], [
                'uxmax.ace.js', 'ace.1.5.0/ext-language_tools.js', 'ace.1.5.0/worker-base.js',
                'ace.1.5.0/worker-javascript.js', 'ace.1.5.0/mode-javascript.js', 'ace.1.5.0/worker-css.js',
                'ace.1.5.0/mode-css.js', 'ace.1.5.0/theme-twilight.js'
            ]);
        }

        $assets['css'][] = 'uxmax.css';
        $assets['css'][] = 'custom-nms.css'; // LOCAL: professional NMS styling for Problems view

        return $assets;
    }

    public function init(): void {
        ModuleTranslator::setRelativePath($this->getRelativePath());
        
        $this->preferences = new Preferences($this);
        $this->registerMenuEntry();
    }

    public function onBeforeAction(Action $action): void {
        if (strpos($action::class, __NAMESPACE__) === 0) {
            $action->module = $this;
        }
    }

    public function onTerminate(Action $action): void {
    }

    protected function registerMenuEntry() {
        /** @var CMenuItem $menu */
        $menu = APP::Component()->get('menu.main')->find(_('Administration'));

        if ($menu instanceof CMenuItem) {
            $menu->getSubMenu()
                ->add((new CMenuItem(ModuleTranslator::translate('menu.uxmax-configuration')))->setAction('mod.uxmax.form'));
        }

        // Per-user preferences entry under the user menu, hidden for guest
        // and when the admin has disabled the per-user override feature.
        if (!CWebUser::isGuest() && $this->preferences->isUserOverrideAllowed()) {
            $user_menu = APP::Component()->get('menu.user');

            if ($user_menu instanceof CMenu) {
                $user_settings = $user_menu->find(_('User settings'));

                if ($user_settings instanceof CMenuItem) {
                    $user_settings->getSubMenu()
                        ->add((new CMenuItem(ModuleTranslator::translate('menu.uxmax-user-preferences')))
                            ->setAction('mod.uxmax.userprefs'));
                }
            }
        }
    }
}

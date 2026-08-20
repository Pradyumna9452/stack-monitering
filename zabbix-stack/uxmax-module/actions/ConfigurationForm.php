<?php

namespace Modules\uxMAX\Actions;

use API, CController, CControllerResponseData;
use Modules\uxMAX\Module;
use Modules\uxMAX\Services\Preferences;

/**
 * @property Modules\uxMAX\Module $module
 */
class ConfigurationForm extends CController {

    public Module $module;

    public function init() {
        $this->disableCsrfValidation();
    }

    protected function checkInput() {
        $fields = [
            'state' =>      'array',
            'color' =>      'array',
            'colortags' =>  'array',
            'syntax' =>     'array',
            'fonts' =>      'array',
        ];

        $ret = $this->validateInput($fields);

        return $ret;
    }

    protected function checkPermissions() {
        return true;
    }

    protected function doAction() {
        $data = $this->module->preferences->get();
        $this->getInputs($data, array_keys($data));

        if ($data['fonts'] ?? []) {
            $data['fonts'] = $this->unsetNonExistingPngFonts($data['fonts']);
        }

        $this->setResponse((new CControllerResponseData($data)));
    }

    /**
     * Unset fonts with non-existing pngid.
     *
     * @param array $fonts  Array of fonts
     *
     * @return array  Filtered array of fonts
     */
    protected function unsetNonExistingPngFonts(array $fonts): array {
        $pngids = array_column($fonts, 'pngid', 'pngid');
        unset($pngids[0]);

        if (!$pngids) {
            return $fonts;
        }

        $db_pngids = API::Image()->get([
            'output' => ['imageid'],
            'imageids' => $pngids,
            'filter' => ['type' => IMAGE_TYPE_ICON],
            'preservekeys' => true
        ]);

        if (count($db_pngids) === count($pngids)) {
            return $fonts;
        }

        foreach ($fonts as $i => &$font) {
            if (!array_key_exists('pngid', $font) || array_key_exists($font['pngid'], $db_pngids)) {
                continue;
            }

            if ($font['type'] === Preferences::FONT_TYPE_CSS_URL && $font['selfhosted']) {
                unset($font['selfhosted'], $font['pngid']);

                continue;
            }

            unset($fonts[$i]);
        }
        unset($font);

        return $fonts;
    }
}

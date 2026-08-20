<?php

namespace Modules\uxMAX\Actions;

use API, CController, CControllerResponseData, CWebUser;
use Modules\uxMAX\Module;
use Modules\uxMAX\Services\Preferences;
use Modules\uxMAX\Services\DatabaseFont;

class Css extends CController {

    public Module $module;

    protected function init() {
        $this->disableCsrfValidation();
    }

    public function checkInput() {
        return true;
    }

    public function checkPermissions() {
        return true;
    }

    public function doAction() {
        $preferences = $this->module->preferences->get();
        $uri = $_SERVER['HTTP_REFERER'] ?? '';

        $this->setResponse((new CControllerResponseData([
            'css' => $this->getCssForAction($uri, $preferences)
        ])));
    }

    /**
     * Get custom styles matched passed$action.
     *
     * @param string $uri
     * @param array  $preferences
     */
    protected function getCssForAction(string $uri, array $preferences): string {
        $vars = [];
        $css = [];
        $css_imports = [];

        if ($preferences['state']['customfont']) {
            [$css_imports, $css] = $this->getCustomFontCss($preferences);
        }

        $debug = CWebUser::getDebugMode();
        parse_str(parse_url($uri, PHP_URL_QUERY), $query_args);
        $action = $query_args['action']??'';

        if ($action === '') {
            $action = basename(parse_url($uri, PHP_URL_PATH));
            $query_args['action'] = $action;
        }

        if ($debug) {
            $css[] = "/* uri: {$uri} */";
            $css[] = "/* action: {$action} */";
        }

        // Color tags are special — every logged-in user may override the
        // central rules through their own uxMAX preferences. When the user
        // override toggle is on, getEffectiveColorTags() returns the user's
        // rules; otherwise it falls back to the admin's central rules.
        // The state[colortags] master switch still gates the whole feature.
        $tags = $preferences['state']['colortags']
            ? $this->module->preferences->getEffectiveColorTags()
            : [];
        if ($debug) {
            $css[] = '/* tags css */';
        }

        foreach ($tags as $tag) {
            $rule = '';

            switch ($tag['match']) {
                case Preferences::MATCH_BEGIN:
                    $rule = '.tag[data-hintbox-contents^="%1$s"] { background-color: %2$s }';
                    break;

                case Preferences::MATCH_CONTAIN:
                    $rule = '.tag[data-hintbox-contents*="%1$s"] { background-color: %2$s }';
                    break;

                case Preferences::MATCH_END:
                    $rule = '.tag[data-hintbox-contents$="%1$s"] { background-color: %2$s }';
                    break;
            }

            if ($rule !== '') {
                $css[] = sprintf($rule, $tag['value'], $tag['color']);
            }
        }

        if ($preferences['state']['syntax'] || $preferences['state']['exprhighlight']) {
            if (Preferences::FONT_IMPORT_URL[$preferences['syntax']['font']] ?? false) {
                $css_imports[] = '@import url("'.Preferences::FONT_IMPORT_URL[$preferences['syntax']['font']].'");';
            }

            $font_family = Preferences::FONT[$preferences['syntax']['font']];
            $css[] = <<<CSS
            .ace_editor {
                font-family: {$font_family};
                font-size: {$preferences['syntax']['fontSize']};
            }
            CSS;
        }

        $vars[] = <<<CSS
        --uxmax-body-bgcolor: {$preferences['color']['bodybg']};
        --uxmax-sidebar-bgcolor: {$preferences['color']['asidebg']};
        CSS;

        if ($preferences['state']['modalwidth'] && $preferences['modalwidth']['value'] !== '') {
            $vars[] = '--uxmax-modal-width: '.$preferences['modalwidth']['value']
                .(substr($preferences['modalwidth']['value'], -2) === 'px' ? '' : 'px');
            $css[] = <<<'CSS'
            body .overlay-dialogue.modal-popup {
                min-width: var(--uxmax-modal-width) !important;
            }
            .overlay-dialogue.modal .overlay-dialogue-body { width: 100%; max-width: 100% }
            CSS;
        }

        // Directive @import must be at the top of the file.
        // See https://developer.mozilla.org/en-US/docs/Web/CSS/@import
        return implode("\r\n", array_merge($css_imports, [':root {'.implode("\r\n", $vars).'}'], $css));
    }

    /**
     * Add CSS styles for custom font.
     *
     * @param array $preferences  Preferences array.
     * @return array  Array of css and css @import rules.
     */
    protected function getCustomFontCss(array $preferences): array {
        $css = [];
        $css_imports = [];
        $font = array_filter($preferences['fonts'], fn($f) => $f['enabled']);
        $font = reset($font);

        if (!$font) {
            return [$css_imports, $css];
        }

        if ($font['type'] === Preferences::FONT_TYPE_CSS_URL && !($font['selfhosted']??0)) {
            $css_imports[] = "@import url('{$font['url']}');";
            $css[] = <<<CSS
            html body, input, textarea, button, [class^="btn"], z-select button
            { font-family: "{$font['font_family']}", sans-serif; }
            CSS;
            return [$css_imports, $css];
        }

        if (!($font['pngid'] ?? false)) {
            return [$css_imports, $css];
        }

        $png = API::Image()->get([
            'output' => [],
            'select_image' => true,
            'imageids' => $font['pngid']
        ]);

        if (!$png) {
            return [$css_imports, $css];
        }

        $database_font = new DatabaseFont;
        $css[] = $database_font->getDataBlockFromPng(base64_decode(reset($png)['image']), 0);
        $css[] = <<<CSS
            html body, input, textarea, button, [class^="btn"], z-select button
            { font-family: "{$font['font_family']}", sans-serif; }
            CSS;

        return [$css_imports, $css];
    }
}

<?php

namespace Modules\uxMAX\Actions;

use API, CController, CControllerResponseRedirect, CMessageHelper, CUrl;
use Modules\uxMAX\Module;
use Modules\uxMAX\Services\DatabaseFont;
use Modules\uxMAX\Services\Preferences;

/**
 * @property Modules\uxMAX\Module $module
 */
class ConfigurationFormUpdate extends CController {

    public Module $module;

    protected DatabaseFont $database_font;

    protected function checkInput() {
        $fields = [
            'state' =>          'array',
            'color' =>          'array',
            'colortags' =>      'array',
            'css' =>            'array',
            'syntax' =>         'array',
            'modalwidth' =>     'array',
            'fonts' =>          'array',
            'fonts_enabled' =>  'int32'
        ];

        $ret = $this->validateInput($fields) && $this->validatePreferences($this->getInputAll());

        if (!$ret) {
            $response = new CControllerResponseRedirect(
                (new CUrl('zabbix.php'))->setArgument('action', 'mod.uxmax.form')
            );
            $response->setFormData($this->getInputAll());
            CMessageHelper::setErrorTitle(_('Cannot update configuration'));
            $this->setResponse($response);
        }

        return $ret;
    }

    protected function checkPermissions() {
        return true;
    }

    protected function validatePreferences(array $data) {
        return $this->module->preferences->validate($data);
    }

    protected function doAction() {
        $default = $this->module->preferences->getDefault();
        $data = [
            'state' => array_replace($default['state'], $this->getInput('state', [])),
            'color' => array_replace($default['color'], $this->getInput('color', [])),
            'colortags' => $this->getInput('colortags', $default['colortags']),
            'syntax' => array_replace($default['syntax'], $this->getInput('syntax', [])),
            'modalwidth' => array_replace($default['modalwidth'], $this->getInput('modalwidth', []))
        ];
        $data['fonts'] = $this->processCustomFonts();
        $this->module->preferences->set($data);

        $curl = (new CUrl('zabbix.php'))->setArgument('action', 'mod.uxmax.form');
        $this->setResponse((new CControllerResponseRedirect($curl)));
    }

    protected function processCustomFonts(): array {
        $fonts = $this->getInput('fonts', []);

        if (!$fonts) {
            return $this->module->preferences->getDefault()['fonts'];
        }

        $uploads = $_FILES['fonts'] ?? [];
        $this->database_font = new DatabaseFont;
        $this->database_font->loadThumbnail(__DIR__.'/../assets/thumbnail.png');

        $png_names = API::Image()->get([
            'output' => ['imageid', 'name'],
            'search' => ['name' => DatabaseFont::PNG_NAME_SEARCH],
            'startSearch' => true,
        ]);
        $png_names = array_column($png_names, 'name', 'imageid');
        $indexes = array_map(
            fn ($name) => sscanf($name, DatabaseFont::PNG_NAME_FORMAT, $index) ? (int) $index : 0,
            array_unique($png_names)
        );
        $new_png_index = $indexes ? max(1, ...$indexes) + 1 : 1;

        $add_pngs = [];
        $upd_pngs = [];
        $pngids_index = [];

        foreach ($fonts as $i => &$font) {
            $png_data = [];
            $font['enabled'] = $i == $this->getInput('fonts_enabled', -1);
            $png_file_name = array_key_exists('pngid', $font) && array_key_exists($font['pngid'], $png_names)
                ? $png_names[$font['pngid']]
                : sprintf(DatabaseFont::PNG_NAME_FORMAT, $new_png_index);

            if (($font['type'] === Preferences::FONT_TYPE_CSS_URL && $font['url'] === '' && $font['pngid'] === '')
                    || ($font['type'] === Preferences::FONT_TYPE_FILE && $font['file_name'] === '')) {
                unset($fonts[$i]);

                continue;
            }

            switch ($font['type']) {
                case Preferences::FONT_TYPE_CSS_URL:
                    if (!array_key_exists('selfhosted', $font)) {
                        unset($font['pngid']);
                        $css = $font['url'] !== '' ? $this->getCssFromUrl($font['url']) : '';
                        $font_family = $css !== '' ? $this->getFontFamily($css) : '';

                        if ($font_family === '') {
                            error(_('Failed to extract font-family from CSS'));
                            break;
                        }
                        else {
                            $font['font_family'] = $font_family;
                        }
                    }
                    else if (!$font['pngid']) {
                        $font = $this->processCssUrlFont($font, $png_file_name);
                        $png_data = $font['png_data'] ?? [];
                        unset($font['png_data']);
                    }

                    break;

                case Preferences::FONT_TYPE_FILE:
                    if ($uploads['name'][$i]['file'] === '' && $font['pngid']) {
                        // No new file uploaded, keep existing font.
                        break;
                    }

                    if ($uploads['error'][$i]['file'] === UPLOAD_ERR_OK && is_uploaded_file($uploads['tmp_name'][$i]['file'])) {
                        $font['file_name'] = basename($uploads['name'][$i]['file']);
                        $font['font_family'] = pathinfo($font['file_name'], PATHINFO_FILENAME);
                        $file_ext = pathinfo($font['file_name'], PATHINFO_EXTENSION);
                        $png_font_url = (new CUrl('zabbix.php'))
                            ->setArgument('action', 'mod.uxmax.font')
                            ->setArgument('i', 1)
                            ->setArgument('png', $png_file_name)
                            ->setArgument('format', $file_ext)
                            ->getUrl();
                        $format = DatabaseFont::EXTENSION_FORMAT[strtolower($file_ext)] ?? 'truetype';
                        $png_data = [
                            <<<CSS
                            @font-face {
                                font-family: '{$font['font_family']}';
                                font-display: swap;
                                src: url('{$png_font_url}') format('{$format}');
                            }
                            CSS,
                            file_get_contents($uploads['tmp_name'][$i]['file'])
                        ];
                    }
                    else if (($font['file_name'] ?? '') === '') {
                        error(_s('Failed to upload font file: %1$s', $uploads['name'][$i]['file'] ?? ''));
                    }

                    break;
            }

            if (!$png_data) {
                continue;
            }

            $png_data = base64_encode($this->database_font->embedDataBlocksInPng($png_data));

            if ($font['pngid'] ?? false) {
                $upd_pngs[] = [
                    'imageid' => $font['pngid'],
                    'image' => $png_data
                ];
            }
            else {
                ++$new_png_index;
                $pngids_index[] = $i;
                $add_pngs[] = [
                    'name' => $png_file_name,
                    'imagetype' => IMAGE_TYPE_ICON,
                    'image' => $png_data
                ];
            }
        }
        unset($font);

        if ($upd_pngs) {
            API::Image()->update($upd_pngs);
        }

        if ($add_pngs && ($result = API::Image()->create($add_pngs))) {
            foreach ($result['imageids'] as $i => $pngid) {
                $fonts[$pngids_index[$i]]['pngid'] = $pngid;
            }
        }

        $del_pngids = array_keys(array_column($this->module->preferences->get()['fonts'], 'pngid', 'pngid'));
        $del_pngids = array_diff($del_pngids, array_column($fonts, 'pngid'));
        $del_pngids = array_filter($del_pngids);

        if ($del_pngids) {
            API::Image()->delete($del_pngids);
        }

        return array_values($fonts);
    }

    /**
     * Process a CSS URL font by fetching its CSS and associated font files.
     *
     * @param array $font Font data containing at least 'url' key.
     *
     * @return array with 'font_family' and 'png_data' keys if successful.
     *               If unsuccessful, returns the original font data.
     */
    protected function processCssUrlFont(array $font, string $png_file_name): array {
        $css = $this->getCssFromUrl($font['url']);
        $font_family = $css !== '' ? $this->getFontFamily($css) : '';

        if ($font_family === '') {
            error(_('Failed to extract font-family from CSS'));
            return $font;
        }

        $font_files = $this->getFontFilesFromCss($css);

        if (!$font_files) {
            error(_('No valid font files found.'));
            return $font;
        }

        $font['font_family'] = $font_family;
        $png_data = [];

        foreach (array_unique($font_files) as $i => $font_url) {
            $content = @file_get_contents($font_url);

            if ($content === false) {
                error(_('Failed to fetch font file: %s', $font_url));
                continue;
            }

            $png_data[] = $content;
            $font_url_embedded[$font_url] = (new CUrl('zabbix.php'))
                ->setArgument('action', 'mod.uxmax.font')
                ->setArgument('i', $i + 1)
                ->setArgument('png', $png_file_name)
                ->setArgument('format', pathinfo($font_url, PATHINFO_EXTENSION))
                ->getUrl();
        }

        if ($png_data) {
            $font['png_data'] = array_merge([strtr($css, $font_url_embedded)], $png_data);
        }

        return $font;
    }

    /**
     * Fetch CSS content from a given URL.
     *
     * @param string $url URL to fetch CSS from.
     *
     * @return string The fetched CSS content or empty string on failure.
     */
    protected function getCssFromUrl(string $url): string {
        if (strpos($url, 'http://') !== 0 && strpos($url, 'https://') !== 0) {
            error(_('Invalid URL. Only HTTP and HTTPS URLs are supported.'));

            return '';
        }

        $context = stream_context_create([
            'http' => [
                // Force google fonts API to return .woff files URLs.
                'header' => 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            ]
        ]);
        $css = @file_get_contents($url, false, $context);

        if ($css === false) {
            error(_('Failed to load CSS from provided URL.'));

            $css = '';
        }

        return $css;
    }

    /**
     * Extract font-family from CSS content.
     *
     * @param string $css CSS content to parse.
     *
     * @return string The extracted font-family or empty string on failure.
     */
    protected function getFontFamily(string $css): string {
        $font_family = '';

        preg_match('/@font-face\s*{[^}]*font-family:\s*["\']([^"\']+)["\'][^}]*}/', $css, $matches);
        $font_family = $matches[1] ?? '';

        if ($font_family === '') {
            error(_('Failed to extract font-family from CSS'));
        }

        return $font_family;
    }

    /**
     * Extract font file URLs from CSS content.
     *
     * @param string $css  CSS content to parse.
     *
     * @return array       Array of extracted font file URLs.
     */
    public function getFontFilesFromCss(string $css): array {
        $fonts = [];

        preg_match_all('/^\s+src:\s*url\((["\']?)(https?:\/\/[^\)]+)\1\)/im', $css, $matches);

        foreach ($matches[2] as $url) {
            if (preg_match('/\.(woff2?|ttf|otf)$/i', $url, $font_type)) {
                $fonts[] = $url;
            }
        }

        return $fonts;
    }
}

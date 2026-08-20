<?php

namespace Modules\uxMAX\Services;

use Modules\uxMAX\Module;

class Preferences {

    const MATCH_BEGIN = 1;
    const MATCH_CONTAIN = 2;
    const MATCH_END = 3;

    public const FONT_TYPE_CSS_URL = 'css_url';
    public const FONT_TYPE_FILE = 'local_file';

    public const FONT = [
        'monospace' => 'default',
        'Courier New' => '"Courier New", Courier, monospace',
        'Lucida Console' => '"Lucida Console", Monaco, monospace',
        'Source Code Pro' => '"Source Code Pro", monospace',
        'JetBrains Mono' => '"JetBrains Mono", monospace',
        'Fira Code' => '"Fira Code", monospace',
        'Ubuntu Mono' => '"Ubuntu Mono", monospace'
    ];

    public const FONT_IMPORT_URL = [
        'Source Code Pro' => 'https://fonts.googleapis.com/css2?family=Source+Code+Pro:wght@400;700&display=swap',
        'Fira Code' => 'https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500&display=swap',
        'JetBrains Mono' => 'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap',
        'Ubuntu Mono' => 'https://fonts.googleapis.com/css2?family=Ubuntu+Mono:wght@400;700&display=swap'
    ];

    protected Module $module;

    public function __construct(Module $module) {
        $this->module = $module;
    }

    public function getDefault(): array {
        return [
            'state' => [
                'windrag' => 0,
                'bodybg' => 0,
                'asidebg' => 0,
                'colortags' => 0,
                'syntax' => 0,
                'modalwidth' => 0,
                'customfont' => 0,
                'exprhighlight' => 0,
                'latestshowdisabled' => 0,
                'hidewidgetheader' => 0,
                'compactdashboard' => 0,
                'allowuseroverride' => 1
            ],
            'color' => [
                'bodybg' => '#000000',
                'asidebg' => '#403030'
            ],
            'colortags' => [
                ['value' => '', 'match' => Preferences::MATCH_BEGIN, 'color' => '#ff0000']
            ],
            'syntax' => [
                'theme' => 'auto',
                'font' => 'Lucida Console',
                'fontSize' => '12px'
            ],
            'modalwidth' => [
                'value' => ''
            ],
            'fonts' => [
                [
                    'enabled' => 0,
                    'type' => self::FONT_TYPE_CSS_URL,
                    'url' => '',
                    'font_family' => '',
                    'selfhosted' => 0
                ]
            ]
        ];
    }

    public function get(): array {
        $data = $this->getDefault();
        $config = $this->module->getConfig();

        if (is_array($config)) {
            $data = array_replace_recursive($data, $config);
        }

        return $data;
    }

    public function set(array $data) {
        $db_data = $this->module->getConfig();
        $data['colortags'] = array_filter($data['colortags']??[], fn ($tag) => trim($tag['value']??'') !== '');

        if (!$data['colortags']) {
            unset($data['colortags']);
        }

        foreach ($data as $property => $values) {
            $db_data[$property] = array_replace($db_data[$property] ?? [], $values);
        }

        $this->module->setConfig($data);
    }

    public const USER_COLORTAGS_OVERRIDE_KEY = 'web.uxmax.colortags.override';
    public const USER_COLORTAGS_RULES_KEY = 'web.uxmax.colortags.rules';

    /**
     * Read the current user's color tags override settings from CProfile.
     *
     * @return array{override: int, colortags: array}
     */
    public function getUserOverride(): array {
        $override = (int) \CProfile::get(self::USER_COLORTAGS_OVERRIDE_KEY, 0);
        $rules_json = \CProfile::get(self::USER_COLORTAGS_RULES_KEY, '');
        $rules = ($rules_json !== '' && $rules_json !== null) ? json_decode($rules_json, true) : [];

        if (!is_array($rules)) {
            $rules = [];
        }

        return [
            'override' => $override,
            'colortags' => $rules
        ];
    }

    /**
     * Persist the current user's color tags override + rules into CProfile.
     */
    public function setUserOverride(bool $override, array $rules): void {
        \CProfile::update(self::USER_COLORTAGS_OVERRIDE_KEY, $override ? 1 : 0, PROFILE_TYPE_INT);
        \CProfile::update(self::USER_COLORTAGS_RULES_KEY, json_encode(array_values($rules)), PROFILE_TYPE_STR);
        \CProfile::flush();
    }

    /**
     * Is per-user color tag override enabled centrally by the admin?
     */
    public function isUserOverrideAllowed(): bool {
        return (bool) ($this->get()['state']['allowuseroverride'] ?? 0);
    }

    /**
     * Effective color tags for the current user.
     *
     * Admin's central rules are the base layer. When user overrides are
     * allowed and the user has their toggle on, the user's own rules are
     * layered on top — rules sharing the same (match, value) key replace
     * the admin colour; new (match, value) combinations are appended.
     */
    public function getEffectiveColorTags(): array {
        $admin = $this->get()['colortags'] ?? [];

        if (!$this->isUserOverrideAllowed()) {
            return $admin;
        }

        $user = $this->getUserOverride();

        if (!$user['override'] || empty($user['colortags'])) {
            return $admin;
        }

        $key = static fn (array $t): string => ((int) ($t['match'] ?? 0)).'|'.($t['value'] ?? '');
        $merged = [];

        foreach ($admin as $tag) {
            $merged[$key($tag)] = $tag;
        }
        foreach ($user['colortags'] as $tag) {
            $merged[$key($tag)] = $tag;
        }

        return array_values($merged);
    }

    public function validate($data): bool {
        $valid = true;
        $default = $this->getDefault();

        if (is_array($data['state'] ?? null) && array_diff_key($data['state'], $default['state'])) {
            $valid = false;
        }

        if (is_array($data['color'] ?? null) && array_diff_key($data['color'], $default['color'])) {
            $valid = false;
        }

        foreach ($data['colortags'] ?? [] as $colortag) {
            if (array_diff_key($colortag, $default['colortags'][0])) {
                $valid = false;

                break;
            }
        }

        if (is_array($data['syntax'] ?? null) && array_diff_key($data['syntax'], $default['syntax'])) {
            $valid = false;
        }

        return $valid;
    }
}

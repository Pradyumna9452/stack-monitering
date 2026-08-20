<?php declare(strict_types=1);
/*
** Copyright (C) 2021-2025 initMAX s.r.o.
**
** This program is free software: you can redistribute it and/or modify it under the terms of
** the GNU Affero General Public License as published by the Free Software Foundation, version 3.
**
** This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
** without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
** See the GNU Affero General Public License for more details.
**
** You should have received a copy of the GNU Affero General Public License along with this program.
** If not, see <https://www.gnu.org/licenses/>.
**/


namespace Modules\uxMAX\Services;

use APP;
use CWebUser;
use Symfony\Component\Yaml\Exception\ParseException;
use Symfony\Component\Yaml\Yaml;

final class ModuleTranslator
{
    private const FALLBACK_LOCALE = 'en_US';
    private const FILE_DOMAIN     = 'messages';   // Symfony-style domain
    private const FILE_EXT        = 'yaml';       // Symfony-style extension

    /** @var array<string,array<string,string>> Cached translation catalogues per locale */
    private static array $catalogues = [];

    /** @var string|null Cached current user locale */
    private static ?string $currentLocale = null;

    /** @var string|null Cached relative path for the module */
    private static ?string $relativePath = null;

    /** Returns a translated string or the original key if translation is missing. */
    public static function translate(string $key): string
    {
        $catalogue = self::getCatalogue();
        return $catalogue[$key] ?? $key;
    }

    /** Translates and formats the string using sprintf(). */
    public static function tf(string $key, mixed ...$args): string
    {
        return sprintf(self::translate($key), ...$args);
    }

    /**
     * Loads and merges catalogues for current locale in Symfony order:
     *   messages.<lang>.yaml  → base
     *   messages.<lang>_<REGION>.yaml → overrides
     *
     * @return array<string,string>
     */
    private static function getCatalogue(): array
    {
        $locale = self::getUserLocale();

        if (isset(self::$catalogues[$locale])) {
            return self::$catalogues[$locale];
        }

        [$lang, $region] = self::splitLocale($locale);
        $catalogue = [];

        // 1) messages.<lang>.yaml (e.g. messages.en.yaml)
        if ($lang !== '') {
            $catalogue = self::loadYamlCatalogue(self::buildPath($lang));
        }

        // 2) messages.<lang>_<REGION>.yaml (e.g. messages.en_US.yaml)
        if ($region !== '') {
            $regional = self::loadYamlCatalogue(self::buildPath(sprintf('%s_%s', $lang, $region)));
            if ($regional !== []) {
                $catalogue = array_replace($catalogue, $regional);
            }
        }

        // Fallback to default locale files if nothing was found for current locale
        if ($catalogue === [] && $locale !== self::FALLBACK_LOCALE) {
            [$fbLang, $fbRegion] = self::splitLocale(self::FALLBACK_LOCALE);

            $fallback = self::loadYamlCatalogue(self::buildPath($fbLang));
            if ($fbRegion !== '') {
                $fallbackRegional = self::loadYamlCatalogue(self::buildPath(self::FALLBACK_LOCALE));
                if ($fallbackRegional !== []) {
                    $fallback = array_replace($fallback, $fallbackRegional);
                }
            }
            $catalogue = $fallback;
        }

        return self::$catalogues[$locale] = $catalogue;
    }

    /** Returns full user locale (e.g. en_US); normalizes to xx_YY. */
    private static function getUserLocale(): string
    {
        if (self::$currentLocale !== null) {
            return self::$currentLocale;
        }

        // $sessionId = CSessionHelper::getId();
        // $user = API::User()->checkAuthentication(['sessionid' => $sessionId]);

        // $raw = (string)($user['lang'] ?? '');
        // $locale = self::normalizeLocale($raw);

        $locale = CWebUser::$data['lang'] ?? null;

        if ($locale === '') {
            // @phpstan-ignore-next-line – CWebUser is provided by Zabbix
            $short = (string)\CWebUser::getLang(); // e.g. "en" / "cs"
            $locale = self::normalizeLocale($short);
        }

        if ($locale === '' || strlen($locale) === 2) {
            $locale = self::FALLBACK_LOCALE;
        }

        return self::$currentLocale = $locale;
    }

    /** Normalizes "en-us"/"enUS"/"en" → "en_US"/"en". */
    private static function normalizeLocale(string $value): string
    {
        $value = trim($value);
        if ($value === '') {
            return '';
        }

        $value = str_replace('-', '_', $value);

        // No region → just lowercased language
        if (!str_contains($value, '_')) {
            return strtolower($value);
        }

        [$lang, $region] = explode('_', $value, 2);
        return sprintf('%s_%s', strtolower($lang), strtoupper($region));
    }

    /**
     * Splits locale into [language, region].
     *
     * @return array{0:string,1:string}
     */
    private static function splitLocale(string $locale): array
    {
        if (!str_contains($locale, '_')) {
            return [$locale, ''];
        }
        [$lang, $region] = explode('_', $locale, 2);
        return [$lang, $region];
    }

    /**
     * Sets relative path for the module. 
     *
     * @param string $path Relative path within Zabbix UI modules directory 
     **/
    public static function setRelativePath(string $path): void
    {
        self::$relativePath = $path;
    }

    /** Builds: <root>/<module>/translation/messages.<locale>.yaml */
    private static function buildPath(string $locale): string
    {
        $rootDir = APP::getInstance()->getRootDir();

        return sprintf(
            '%s/%s/translation/%s.%s.%s',
            $rootDir,
            self::$relativePath,
            self::FILE_DOMAIN,
            $locale,
            self::FILE_EXT
        );
    }

    /**
     * Loads YAML and flattens nested keys into dot notation.
     *
     * Example YAML:
     * ```yaml
     * category:
     *   key: "Hello"
     *   label: "Greeting"
     *   options:
     *     first: "Option 1"
     *     second: "Option 2"
     *
     * other:
     *   nested:
     *     value: "Deep"
     * ```
     *
     * Resulting array:
     * ```php
     * [
     *   "category.key" => "Hello",
     *   "category.label" => "Greeting",
     *   "category.options.first" => "Option 1",
     *   "category.options.second" => "Option 2",
     *   "other.nested.value" => "Deep"
     * ]
     * ```
     *
     * @return array<string,string>
     */
    private static function loadYamlCatalogue(string $path): array
    {
        if (!is_file($path)) {
            return [];
        }

        try {
            $data = Yaml::parse(file_get_contents($path) ?: '');
        } catch (ParseException) {
            return [];
        }

        if (!is_array($data)) {
            return [];
        }

        $out = [];
        self::flattenYaml($data, $out);

        return $out;
    }

    /**
     * Recursively flattens YAML arrays into dot-notated keys.
     *
     * - Only string keys are considered.
     * - Scalar values are cast to string.
     * - Null/non-scalar leaves are ignored.
     *
     * @param array<mixed>              $data
     * @param array<string,string>      $out
     * @param string                    $prefix
     */
    private static function flattenYaml(array $data, array &$out, string $prefix = ''): void
    {
        foreach ($data as $k => $v) {
            if (!is_string($k)) {
                continue;
            }

            $key = $prefix !== '' ? $prefix . '.' . $k : $k;

            if (is_array($v)) {
                self::flattenYaml($v, $out, $key);
            } elseif (is_scalar($v)) {
                $out[$key] = (string) $v;
            } // null / objects are ignored
        }
    }
}

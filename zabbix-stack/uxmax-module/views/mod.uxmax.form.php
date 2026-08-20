<?php

use Modules\CSRF\Module;
use Modules\uxMAX\Services\ModuleTranslator;
use Modules\uxMAX\Services\Preferences;

/**
 * @var Cview $this
 * @var array $data
 */

$this->addJsFile('multilineinput.js');

// Produces one settings row: label on the left, field on the right with
// a description box below the field. Rows are separated by a horizontal
// line via CSS (.uxmax-setting-row + border-bottom).
$row = function ($label_text, $field, string $description, ?string $for = null): CDiv {
    return (new CDiv([
        (new CDiv($for !== null ? new CLabel($label_text, $for) : new CLabel($label_text)))
            ->addClass('uxmax-setting-label'),
        (new CDiv([
            $field,
            (new CDiv($description))->addClass('uxmax-field-desc')
        ]))->addClass('uxmax-setting-field')
    ]))->addClass('uxmax-setting-row');
};

$section = function (string $title, array $rows): CDiv {
    return (new CDiv([
        (new CDiv($title))->addClass('uxmax-section-title'),
        (new CDiv($rows))->addClass('uxmax-section-body')
    ]))->addClass('uxmax-section');
};

// ── Dashboards ──────────────────────────────────────────────────────────────
$dashboards_rows = [
    $row(
        ModuleTranslator::translate('form.hide-widget-header'),
        (new CCheckBox('state[hidewidgetheader]', 1))->setChecked((int) $data['state']['hidewidgetheader']),
        ModuleTranslator::translate('hints.hide-widget-header'),
        'hidewidgetheader'
    ),
    $row(
        ModuleTranslator::translate('form.compact-dashboard'),
        (new CCheckBox('state[compactdashboard]', 1))->setChecked((int) $data['state']['compactdashboard']),
        ModuleTranslator::translate('hints.compact-dashboard'),
        'compactdashboard'
    ),
];

// ── Interface behavior ──────────────────────────────────────────────────────
$interface_rows = [
    $row(
        ModuleTranslator::translate('form.enable-dragging-of-modal-windows'),
        (new CCheckBox('state[windrag]', 1))->setChecked((int) $data['state']['windrag']),
        ModuleTranslator::translate('hints.windrag'),
        'windrag'
    ),
    $row(
        ModuleTranslator::translate('form.modal-window-minimal-width.label'),
        [
            (new CCheckBox('state[modalwidth]', 1))->setChecked((int) $data['state']['modalwidth']),
            (new CTextBox('modalwidth[value]', $data['modalwidth']['value']))
                ->removeId()
                ->setWidth(ZBX_TEXTAREA_SMALL_WIDTH),
            (new CDiv())->addClass(ZBX_STYLE_FORM_INPUT_MARGIN),
            (new CSimpleButton(ModuleTranslator::translate('form.modal-window-minimal-width.button.open')))
                ->setId('uxmax-modal-button')
                ->addClass(ZBX_STYLE_BTN_ALT)
        ],
        ModuleTranslator::translate('hints.modal-width')
    ),
    $row(
        ModuleTranslator::translate('form.latest-show-disabled-items'),
        (new CCheckBox('state[latestshowdisabled]', 1))->setChecked((int) $data['state']['latestshowdisabled']),
        ModuleTranslator::translate('hints.latest-show-disabled'),
        'latestshowdisabled'
    ),
];

// ── Appearance ──────────────────────────────────────────────────────────────
$appearance_rows = [
    $row(
        ModuleTranslator::translate('form.custom-color-theme'),
        [
            new CDiv([
                (new CCheckBox('state[asidebg]', 1))->setChecked((int) $data['state']['asidebg']),
                (new CLabel([
                    (new CInput('color', 'color[asidebg]', $data['color']['asidebg']))
                        ->setEnabled(!!$data['state']['asidebg']),
                    ModuleTranslator::translate('form.navigation-background-color')
                ]))->addClass(!!$data['state']['asidebg'] ? null : ZBX_STYLE_DISABLED)
            ]),
            new CDiv([
                (new CCheckBox('state[bodybg]', 1))->setChecked((int) $data['state']['bodybg']),
                (new CLabel([
                    (new CInput('color', 'color[bodybg]', $data['color']['bodybg']))
                        ->setEnabled(!!$data['state']['bodybg']),
                    ModuleTranslator::translate('form.body-background-color')
                ]))->addClass(!!$data['state']['bodybg'] ? null : ZBX_STYLE_DISABLED)
            ])
        ],
        ModuleTranslator::translate('hints.color-theme')
    ),

    $row(
        ModuleTranslator::translate('form.custom-font.label'),
        [
            (new CCheckBox('state[customfont]', 1))->setChecked((int) $data['state']['customfont']),
            (new CDiv([
                (new CTable())
                    ->setFooter(
                        (new CCol(
                            (new CButtonLink(ModuleTranslator::translate('form.custom-font.button.add')))->addClass('element-table-add')
                        ))->setColSpan(3)
                    ),
                new CTemplateTag('fonts-row-tmpl', (new CRow([
                        [
                            (new CInput('radio', 'fonts_enabled', '#{rowNum}'))
                                ->setAttribute('#{enabled}', '')
                                ->removeId(),
                            NBSP(),
                            (new CSelect('fonts[#{rowNum}][type]'))
                                ->setId('fonts_type_#{rowNum}')
                                ->addOptions(CSelect::createOptionsFromArray([
                                    Preferences::FONT_TYPE_CSS_URL => ModuleTranslator::translate('form.custom-font.variant.use-external-css'),
                                    Preferences::FONT_TYPE_FILE => ModuleTranslator::translate('form.custom-font.variant.upload-font-file')
                                ]))
                                ->setWidth(ZBX_TEXTAREA_SMALL_WIDTH)
                        ],
                        [
                            (new CDiv([
                                (new CTextBox('fonts[#{rowNum}][url]', '#{url}'))
                                    ->removeId()
                                    ->setAttribute('placeholder', ModuleTranslator::translate('form.custom-font.variant.google-font-url'))
                                    ->setWidth(ZBX_TEXTAREA_STANDARD_WIDTH),
                                NBSP(),
                                (new CCheckBox('fonts[#{rowNum}][selfhosted]', 1))
                                    ->setId('fonts_selfhosted_#{rowNum}')
                                    ->setAttribute('#{selfhosted}', ''),
                                (new CLabel(ModuleTranslator::translate('form.custom-font.hint.store-font-locally'), 'fonts_selfhosted_#{rowNum}'))
                            ]))->setId('vs_fonts_url_#{rowNum}'),
                            (new CDiv([
                                (new CFile('fonts[#{rowNum}][file]', ''))
                                    ->setId('fonts_file_#{rowNum}')
                                    ->setAttribute('accept', '.woff,.woff2,.ttf,.otf,.eot')
                                    ->addStyle('display: none;'),
                                (new CTextBox('fonts[#{rowNum}][file_name]', '#{file_name}', true))
                                    ->setAttribute('data-file-name', '#{file_name}')
                                    ->setAttribute('placeholder', ModuleTranslator::translate('form.custom-font.hint.supported-formats'))
                                    ->setWidth(ZBX_TEXTAREA_STANDARD_WIDTH),
                                    NBSP(),
                                (new CButton('fonts[#{rowNum}][select]', ('Select')))->addClass(ZBX_STYLE_BTN_ALT)
                            ]))->setId('vs_fonts_file_#{rowNum}'),
                            new CVar('fonts[#{rowNum}][pngid]', '#{pngid}'),
                            new CVar('fonts[#{rowNum}][font_family]', '#{font_family}')
                        ],
                        (new CButtonLink(ModuleTranslator::translate('form.custom-font.button.remove')))->addClass('element-table-remove')
                    ]))->addClass('form_row')
                ),
                new CTemplateTag('fonts-data', json_encode($data['fonts']))
            ]))
                ->setId('uxmax-fonts-table')
                ->addStyle('vertical-align: top;')
                ->addClass(ZBX_STYLE_TABLE_FORMS_SEPARATOR)
        ],
        ModuleTranslator::translate('hints.custom-font')
    ),
];

// ── Color tags ──────────────────────────────────────────────────────────────
$color_tags_rows = [
    $row(
        ModuleTranslator::translate('form.color-tags.label'),
        [
            (new CCheckBox('state[colortags]', 1))->setChecked((int) $data['state']['colortags']),
            (new CDiv([
                (new CTable())
                    ->setHeader([
                        new CColHeader(ModuleTranslator::translate('form.color-tags.table.match')),
                        new CColHeader(ModuleTranslator::translate('form.color-tags.table.string')),
                        '',
                        ''
                    ])
                    ->setFooter(
                        (new CCol(
                            (new CButtonLink(ModuleTranslator::translate('form.color-tags.button.add')))->addClass('element-table-add')
                        ))->setColSpan(4)
                    ),
                new CTemplateTag('colortag-row-tmpl', (new CRow([
                        (new CSelect('colortags[#{rowNum}][match]'))
                            ->removeId()
                            ->addOptions(CSelect::createOptionsFromArray([
                                Preferences::MATCH_BEGIN => ModuleTranslator::translate('form.color-tags.match.starts-with'),
                                Preferences::MATCH_CONTAIN => ModuleTranslator::translate('form.color-tags.match.contains'),
                                Preferences::MATCH_END => ModuleTranslator::translate('form.color-tags.match.ends-with')
                            ]))
                            ->setWidth(ZBX_TEXTAREA_SMALL_WIDTH),
                        (new CTextBox('colortags[#{rowNum}][value]', '#{value}'))
                            ->removeId()
                            ->setAttribute('placeholder', ModuleTranslator::translate('form.color-tags.value'))
                            ->setWidth(ZBX_TEXTAREA_STANDARD_WIDTH),
                        (new CLabel([
                            (new CInput('color', 'colortags[#{rowNum}][color]', '#{color}'))->removeId()
                        ])),
                        (new CButtonLink(ModuleTranslator::translate('form.color-tags.button.remove')))->addClass('element-table-remove')
                    ]))->addClass('form_row')
                ),
                new CTemplateTag('colortag-data', json_encode($data['colortags']))
            ]))
                ->setId('uxmax-colortag-table')
                ->addClass(ZBX_STYLE_TABLE_FORMS_SEPARATOR)
        ],
        ModuleTranslator::translate('hints.color-tags')
    ),

    $row(
        ModuleTranslator::translate('form.allow-user-override'),
        [
            new CVar('state[allowuseroverride]', '0'),
            (new CCheckBox('state[allowuseroverride]', 1))->setChecked((int) $data['state']['allowuseroverride'])
        ],
        ModuleTranslator::translate('hints.allow-user-override'),
        'allowuseroverride'
    ),
];

// ── Syntax highlighting ─────────────────────────────────────────────────────
$syntax_rows = [
    $row(
        ModuleTranslator::translate('form.syntax-highlight.label'),
        [
            (new CTextBox('syntax[fontSize]', $data['syntax']['fontSize']))
                ->removeId()
                ->setWidth(ZBX_TEXTAREA_SMALL_WIDTH),
            (new CDiv())->addClass(ZBX_STYLE_FORM_INPUT_MARGIN),
            (new CSelect('syntax[font]'))
                ->removeId()
                ->setValue($data['syntax']['font'])
                ->addOptions(CSelect::createOptionsFromArray(Preferences::FONT))
                ->setWidth(ZBX_TEXTAREA_MEDIUM_WIDTH),
            new CTemplateTag('import-fonts-data', json_encode(array_values(Preferences::FONT_IMPORT_URL))),
            new CDiv([
                (new CCheckBox('state[syntax]', 1))->setChecked((int) $data['state']['syntax']),
                new CLabel(ModuleTranslator::translate('form.syntax-highlight.js'), 'state[syntax]')
            ]),
            new CDiv([
                (new CCheckBox('state[exprhighlight]', 1))->setChecked((int) $data['state']['exprhighlight']),
                new CLabel(ModuleTranslator::translate('form.syntax-highlight.expression'), 'state[exprhighlight]')
            ]),
            (new CDiv(implode("\n", [
                    '// Playground syntax higlight mode javascript.',
                    'function foo() {',
                    '    let x = "Hello world";',
                    '',
                    '    return x;',
                    '}'
                ])))
                    ->setId('uxmax-ace-playground')
        ],
        ModuleTranslator::translate('hints.syntax-highlight')
    ),
];

$content = (new CDiv([
    $section(ModuleTranslator::translate('form.section.color-tags'), $color_tags_rows),
    $section(ModuleTranslator::translate('form.section.dashboards'), $dashboards_rows),
    $section(ModuleTranslator::translate('form.section.interface'), $interface_rows),
    $section(ModuleTranslator::translate('form.section.appearance'), $appearance_rows),
    $section(ModuleTranslator::translate('form.section.syntax-highlighting'), $syntax_rows),
]))->addClass('uxmax-form-container');

(new CHtmlPage())
    ->setTitle(ModuleTranslator::translate('menu.uxmax-configuration'))
    ->addItem(
        (new CForm('post', (new CUrl('zabbix.php'))->getUrl(), 'multipart/form-data'))
            ->addClass('uxmax-form')
            ->addVar(CSRF_TOKEN_NAME, CCsrfTokenHelper::get('mod.uxmax.form.update'))
            ->addVar('action', 'mod.uxmax.form.update')
            ->addItem(getMessages())
            ->addItem(
                (new CTabView())
                    ->addTab('uxmax', ModuleTranslator::translate('tabs.general'), $content)
                    ->setFooter(makeFormFooter(new CSubmit('update', ModuleTranslator::translate('form.button.update'))))
    ))
    ->show();

<?php

use Modules\CSRF\Module;
use Modules\uxMAX\Services\ModuleTranslator;
use Modules\uxMAX\Services\Preferences;

/**
 * @var CView $this
 * @var array $data
 *
 * $data structure:
 *   override        int   0/1 — is the user's override toggle on?
 *   colortags       array User's own override rules (editable).
 *   admin_colortags array Admin's central rules (read-only display).
 */

$colortag_match_options = [
    Preferences::MATCH_BEGIN => ModuleTranslator::translate('form.color-tags.match.starts-with'),
    Preferences::MATCH_CONTAIN => ModuleTranslator::translate('form.color-tags.match.contains'),
    Preferences::MATCH_END => ModuleTranslator::translate('form.color-tags.match.ends-with')
];

// Read-only mirror of the admin colour-tag table — same structure as the
// editable override table below, just with disabled inputs and no Add /
// Remove buttons. The form inputs use dummy names that UserPrefsUpdate
// does not validate; disabled inputs are not submitted by the browser.
$make_readonly_row = function (array $rule) use ($colortag_match_options) {
    $select = (new CSelect('_global_match'))
        ->removeId()
        ->addOptions(CSelect::createOptionsFromArray($colortag_match_options))
        ->setValue((int) ($rule['match'] ?? Preferences::MATCH_BEGIN))
        ->setReadonly()
        ->setWidth(ZBX_TEXTAREA_SMALL_WIDTH);

    return new CRow([
        $select,
        (new CTextBox('_global_value', $rule['value'] ?? ''))
            ->removeId()
            ->setEnabled(false)
            ->setWidth(ZBX_TEXTAREA_STANDARD_WIDTH),
        new CLabel([
            (new CInput('color', '_global_color', $rule['color'] ?? '#000000'))
                ->removeId()
                ->setEnabled(false)
        ]),
        // Placeholder to mirror the Remove column of the override table.
        new CCol('')
    ]);
};

$global_table = (new CTable())
    ->setHeader([
        new CColHeader(ModuleTranslator::translate('form.color-tags.table.match')),
        new CColHeader(ModuleTranslator::translate('form.color-tags.table.string')),
        '',
        ''
    ]);

if (empty($data['admin_colortags'])) {
    $global_table->addRow(
        (new CCol(new CSpan(ModuleTranslator::translate('form.user.no-global-rules'))))
            ->setColSpan(4)
            ->addStyle('text-align:center;color:#888;font-style:italic;padding:8px;')
    );
}
else {
    foreach ($data['admin_colortags'] as $rule) {
        $global_table->addRow($make_readonly_row($rule));
    }
}

$make_row = function (string $row_num_token, $rule) use ($colortag_match_options) {
    $select = (new CSelect("colortags[{$row_num_token}][match]"))
        ->removeId()
        ->addOptions(CSelect::createOptionsFromArray($colortag_match_options))
        ->setWidth(ZBX_TEXTAREA_SMALL_WIDTH);

    if (is_array($rule) && array_key_exists('match', $rule)) {
        $select->setValue($rule['match']);
    }

    return (new CRow([
        $select,
        (new CTextBox("colortags[{$row_num_token}][value]", is_array($rule) ? ($rule['value'] ?? '') : '#{value}'))
            ->removeId()
            ->setAttribute('placeholder', ModuleTranslator::translate('form.color-tags.value'))
            ->setWidth(ZBX_TEXTAREA_STANDARD_WIDTH),
        new CLabel([
            (new CInput('color', "colortags[{$row_num_token}][color]", is_array($rule) ? ($rule['color'] ?? '#000000') : '#{color}'))->removeId()
        ]),
        (new CButtonLink(ModuleTranslator::translate('form.color-tags.button.remove')))
            ->addClass('element-table-remove')
    ]))->addClass('form_row');
};

$override_table = (new CTable())
    ->setHeader([
        new CColHeader(ModuleTranslator::translate('form.color-tags.table.match')),
        new CColHeader(ModuleTranslator::translate('form.color-tags.table.string')),
        '',
        ''
    ])
    ->setFooter(
        (new CCol(
            (new CButtonLink(ModuleTranslator::translate('form.color-tags.button.add')))
                ->addClass('element-table-add')
        ))->setColSpan(4)
    );

// Pre-render existing user rules as real table rows server-side so the
// table is fully visible immediately on page load (no JS-time generation
// flash).
foreach ($data['colortags'] as $i => $rule) {
    $override_table->addRow($make_row((string) $i, $rule));
}

$section = function (string $title, $body): CDiv {
    return (new CDiv([
        (new CDiv($title))->addClass('uxmax-section-title'),
        (new CDiv($body))->addClass('uxmax-section-body')
    ]))->addClass('uxmax-section');
};

$global_section_body = (new CDiv($global_table))
    ->addClass(ZBX_STYLE_TABLE_FORMS_SEPARATOR)
    ->addClass('uxmax-colortag-rules');

$override_section_body = new CDiv([
    new CDiv([
        (new CCheckBox('override', 1))->setChecked((int) $data['override']),
        (new CLabel(ModuleTranslator::translate('form.user.override-colortags'), 'override'))
            ->addStyle('margin-left:6px;')
    ]),
    (new CDiv(new CSpan(ModuleTranslator::translate('form.user.collision-info'))))
        ->addStyle('margin:10px 0 8px 0;color:#555;font-size:12px;line-height:1.5;'),
    (new CDiv([
        $override_table,
        new CTemplateTag('colortag-row-tmpl', $make_row('#{rowNum}', null))
    ]))
        ->setId('uxmax-colortag-table')
        ->addClass(ZBX_STYLE_TABLE_FORMS_SEPARATOR)
        ->addClass('uxmax-colortag-rules')
]);

$grid = (new CDiv([
    $section(ModuleTranslator::translate('form.user.section.global-rules'), $global_section_body),
    $section(ModuleTranslator::translate('form.user.section.my-overrides'), $override_section_body),
]))->addClass('uxmax-form-container');

(new CHtmlPage())
    ->setTitle(ModuleTranslator::translate('menu.uxmax-user-preferences'))
    ->addItem(
        (new CForm('post', (new CUrl('zabbix.php'))->getUrl()))
            ->addClass('uxmax-form')
            ->addVar(CSRF_TOKEN_NAME, CCsrfTokenHelper::get('mod.uxmax.userprefs.update'))
            ->addVar('action', 'mod.uxmax.userprefs.update')
            ->addItem(getMessages())
            ->addItem(
                (new CTabView())
                    ->addTab('uxmax', ModuleTranslator::translate('tabs.general'), $grid)
                    ->setFooter(makeFormFooter(new CSubmit('update', ModuleTranslator::translate('form.button.update'))))
    ))
    ->show();

?>
<script>
(function() {
    // Standalone Add / Remove handling for the user's override table.
    // No "Load central" anymore — the global rules are shown read-only
    // above the override table, so users compose their overrides from a
    // blank slate.

    let nextRowNum = <?= count($data['colortags']) ?>;

    function escapeHtmlAttr(s) {
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function renderRow(rule) {
        const tplEl = document.getElementById('colortag-row-tmpl');
        if (!tplEl) return null;

        let html = tplEl.innerHTML;

        html = html
            .replace(/#\{rowNum\}/g, String(nextRowNum))
            .replace(/#\{value\}/g, escapeHtmlAttr(rule.value || ''))
            .replace(/#\{color\}/g, rule.color || '#000000');

        nextRowNum++;
        return html;
    }

    function appendRow(rule) {
        const html = renderRow(rule);
        if (!html) return null;

        const $footerRow = $('#uxmax-colortag-table .element-table-add').closest('tr');
        const $row = $(html);

        if ($footerRow.length) {
            $row.insertBefore($footerRow);
        }
        else {
            $('#uxmax-colortag-table table tbody').append($row);
        }

        const matchEl = $row.find('z-select[name$="[match]"]')[0]
            || $row.find('select[name$="[match]"]')[0];
        if (matchEl && rule.match !== undefined && rule.match !== '') {
            matchEl.value = String(rule.match);
        }
        return $row;
    }

    $(document).on('click', '#uxmax-colortag-table .element-table-add', function (e) {
        e.preventDefault();
        appendRow({match: '', value: '', color: '#000000'});
    });

    $(document).on('click', '#uxmax-colortag-table .element-table-remove', function (e) {
        e.preventDefault();
        $(this).closest('tr.form_row').remove();
    });
})();
</script>

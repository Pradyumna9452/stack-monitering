$(() => {
    const $nav = $('#uxmax');

    $nav.on('click', '[name="state[bodybg]"],[name="state[asidebg]"]', e => {
        const input = e.target.parentNode.querySelector('input[type="color"]');
        const input_bodyattr = {
            'state[bodybg]': 'uxmax-coloring-body',
            'state[asidebg]': 'uxmax-coloring-sidebar'
        }

        input.toggleAttribute('disabled', !e.target.checked);
        input.closest('label').classList.toggle('disabled', !e.target.checked);
        document.documentElement.toggleAttribute(input_bodyattr[e.target.getAttribute('name')], e.target.checked);
    });
    $nav.on('input', '[name="color[bodybg]"],[name="color[asidebg]"]', e => {
        const input_cssvar = {
            'color[bodybg]': '--uxmax-body-bgcolor',
            'color[asidebg]': '--uxmax-sidebar-bgcolor'
        }

        document.body.style.setProperty(input_cssvar[e.target.getAttribute('name')], e.target.value);
    });

    $nav.find('#uxmax-fonts-table table').dynamicRows({
        template: '#fonts-row-tmpl',
        rows: JSON.parse($nav.find('#fonts-data').html()),
        dataCallback: (row) => ({...row,
            selfhosted: row.selfhosted ? 'checked' : 'skip',
            enabled: row.enabled ? 'checked' : 'skip'
        })
    }).on('afteradd.dynamicRows', e => {
        const row_index = $(e.target).data('dynamicRows').counter - 1;

        new CViewSwitcher(`fonts_type_${row_index}`, 'change', {
            css_url: [`vs_fonts_url_${row_index}`],
            local_file: [`vs_fonts_file_${row_index}`]
        });
    }).on('click', 'button[name$="[select]"]', e => (
        e.target.parentNode.querySelector('[type="file"]').click()
    )).on('change', 'input[name$="[file]"]', e => (
        e.target.nextElementSibling.value = e.target.files.length ? e.target.files[0].name : e.target.nextElementSibling.dataset.fileName
    )).find('.form_row').each(row_index => {
        new CViewSwitcher(`fonts_type_${row_index}`, 'change', {
            css_url: [`vs_fonts_url_${row_index}`],
            local_file: [`vs_fonts_file_${row_index}`]
        });
    });

    $nav.find('#uxmax-colortag-table table').dynamicRows({
        template: '#colortag-row-tmpl',
        rows: JSON.parse($nav.find('#colortag-data').html()),
        dataCallback: (row) => ({color: '#000000', ...row})
    });

    const style = document.createElement("style");

    style.type = "text/css";
    style.textContent = JSON.parse($nav.find('#import-fonts-data').html()).map(url => `@import url("${url}");`).join("\n");
    document.head.appendChild(style);

    initCodeHighlight('uxmax-ace-playground');

    $nav.on('change', 'state[syntax],[name="syntax[fontSize]"],[name="syntax[font]"]', e => {
        const container = $nav.find('.ace_editor');
        const enabled = $nav.find('input[name="state[syntax]"]:checked').length > 0;

        container.css('font-size','');
        container.css('font-family','');

        if (enabled) {
            container.css('font-family', $nav.find('[name="syntax[font]"]').val());
            container.css('font-size', $nav.find('[name="syntax[fontSize]"]').val());
        }
    });

    $nav.on('click', '#uxmax-modal-button', openDemoModal.bind(this));
    $nav.on('change input', '[name="modalwidth[value]"]', e => {
        const width = e.target.value + (e.target.value.endsWith('px') ? '' : 'px');

        document.body.style.setProperty('--uxmax-modal-width', width);
        $nav.find('#uxmax-modal-button')[0].disabled = e.target.value === '';
    });
    $nav.find('#uxmax-modal-button')[0].disabled = $nav.find('[name="modalwidth[value]"]').val() === '';


    function initCodeHighlight(containerid) {
        const theme = document.documentElement.getAttribute('color-scheme') === 'dark' ? 'ace/theme/twilight' : '';
        const editor = ace.edit(containerid, {
            mode: 'ace/mode/javascript',
            theme,
            enableBasicAutocompletion: true,
            enableLiveAutocompletion: true,
            showGutter: true,
            readOnly: document.querySelector('[name="state[syntax]"]:checked') === null,
            tooltipFollowsMouse: true
        });

        document.querySelector('[name="state[syntax]"]').addEventListener('change', e => {
            editor.setOption('readOnly', !e.target.checked);
            editor.renderer.$cursorLayer.element.style.display = editor.getReadOnly() ? 'none' : '';
        });

        editor.session.setUseWorker(true);
        editor.renderer.$cursorLayer.element.style.display = editor.getReadOnly() ? 'none' : '';
    }

    function openDemoModal(e) {
        overlayDialogue({
            'title': t('Demo modal'),
            'class': 'modal-popup uxmax-demo-modal',
            'content': $('<span>').text('This is demo modal content.'),
            'buttons': [
                {
                    'title': t('S_CLOSE'),
                    'cancel': true,
                    'class': ZBX_STYLE_BTN_ALT,
                    'action': function() {}
                }
            ]
        }, e.target);
    }
});

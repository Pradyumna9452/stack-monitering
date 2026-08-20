(() => {
    const TARGETS = [
        'textarea#expression.monospace-font',
        'textarea#recovery_expression.monospace-font',
        'textarea#params_f.monospace-font'
    ];

    document.addEventListener('DOMContentLoaded', () => {
        (new MutationObserver(mutations => {
            for (const mutation of mutations) {
                for (const elm of mutation.addedNodes) {
                    if (elm.nodeType !== 1) {
                        continue;
                    }

                    for (const selector of TARGETS) {
                        if (elm.matches && elm.matches(selector) && !elm.dataset.uxmaxExpr) {
                            initExprEditor(elm);
                        }
                    }

                    if (elm.querySelector) {
                        for (const selector of TARGETS) {
                            const ta = elm.querySelector(selector);

                            if (ta && !ta.dataset.uxmaxExpr) {
                                initExprEditor(ta);
                            }
                        }
                    }
                }
            }
        })).observe(document.body, {childList: true, subtree: true});
    });

    function initExprEditor(textarea) {
        textarea.dataset.uxmaxExpr = '1';

        const is_readonly = textarea.readOnly || textarea.hasAttribute('readonly');
        const rows = parseInt(textarea.getAttribute('rows'), 10) || 7;

        // Create ACE container matching textarea dimensions.
        const editor_div = document.createElement('div');
        editor_div.className = 'uxmax-expr-ace';

        if (is_readonly) {
            editor_div.classList.add('uxmax-expr-readonly');
        }

        // Match textarea width.
        editor_div.style.width = window.getComputedStyle(textarea).width;

        // Hide original textarea (keep in DOM for form submission).
        textarea.style.display = 'none';
        textarea.parentNode.insertBefore(editor_div, textarea);

        const editor = ace.edit(editor_div, {
            mode: 'ace/mode/zabbix_expr',
            value: textarea.value,
            readOnly: is_readonly,
            maxLines: Infinity,
            minLines: rows,
            showGutter: false,
            showPrintMargin: false,
            highlightActiveLine: !is_readonly,
            wrap: true,
            useWorker: false,
            // Disable auto-indent — expressions are single logical lines.
            enableAutoIndent: false
        });

        // Force no indentation on new lines.
        editor.session.setOption('indentedSoftWrap', false);
        editor.session.setTabSize(1);

        // Sync changes back to hidden textarea for form submission.
        editor.session.on('change', () => {
            textarea.value = editor.getValue();
            textarea.dispatchEvent(new Event('change', {bubbles: true}));
        });

        if (is_readonly) {
            editor.renderer.$cursorLayer.element.style.display = 'none';
        }

        // Resize handle — allow vertical resizing like the original textarea.
        const handle = document.createElement('div');
        handle.className = 'uxmax-expr-resize-handle';
        editor_div.appendChild(handle);

        let startY, startH;

        let startX, startW;

        handle.addEventListener('mousedown', e => {
            e.preventDefault();
            startY = e.clientY;
            startX = e.clientX;
            startH = editor_div.offsetHeight;
            startW = editor_div.offsetWidth;

            // Switch from auto-height to fixed height mode.
            editor.setOption('maxLines', null);

            const onMove = e => {
                const newH = Math.max(50, startH + (e.clientY - startY));
                const newW = Math.max(200, startW + (e.clientX - startX));
                editor_div.style.height = newH + 'px';
                editor_div.style.width = newW + 'px';
                editor.resize();
            };

            const onUp = () => {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
            };

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }
})();

ace.define("ace/mode/zabbix_expr_highlight_rules", ["require", "exports", "module", "ace/lib/oop", "ace/mode/text_highlight_rules"], function(require, exports, module) {
    "use strict";

    var oop = require("../lib/oop");
    var TextHighlightRules = require("./text_highlight_rules").TextHighlightRules;

    var ZabbixExprHighlightRules = function() {
        this.$rules = {
            "start": [
                {
                    token: "string",
                    regex: '"[^"]*"'
                },
                {
                    token: "variable",
                    regex: '\\{\\$[^}]+\\}'
                },
                {
                    token: "variable",
                    regex: '\\{#[^}]+\\}'
                },
                {
                    token: "support.function",
                    regex: '\\b[a-z_][a-z_0-9]*(?=\\s*\\()'
                },
                {
                    token: "keyword",
                    regex: '\\b(?:and|or|not)\\b'
                },
                {
                    token: "keyword.operator",
                    regex: '<=|>=|<>|[<>=+\\-*]'
                },
                {
                    // ( followed by / — start of host path (state-based for multi-line).
                    token: ["paren.lparen", "punctuation"],
                    regex: '(\\()(\\/)',
                    next: "host"
                },
                {
                    // Standalone / — division operator.
                    token: "keyword.operator",
                    regex: '\\/'
                },
                {
                    token: "constant.numeric",
                    regex: '#?\\d+[smhdwMy]?\\b'
                },
                {
                    token: "paren.lparen",
                    regex: '[({]'
                },
                {
                    token: "paren.rparen",
                    regex: '[)}]'
                },
                {
                    token: "punctuation",
                    regex: ','
                },
                {
                    defaultToken: "text"
                }
            ],
            "host": [
                {
                    // End of host name, / starts the item key.
                    token: "punctuation",
                    regex: '\\/',
                    next: "key"
                },
                {
                    // Host name content — everything except / (spans across lines).
                    token: "variable.parameter",
                    regex: '[^\\/]+'
                }
            ],
            "key": [
                {
                    // Item key: chars, dots, brackets with params.
                    token: "support.type",
                    regex: '(?:[^,)\\s\\[\\]]|\\[[^\\]]*\\])+',
                    next: "start"
                },
                {
                    // Immediate comma or paren — empty key, back to start.
                    token: "text",
                    regex: '',
                    next: "start"
                }
            ]
        };
    };

    oop.inherits(ZabbixExprHighlightRules, TextHighlightRules);
    exports.ZabbixExprHighlightRules = ZabbixExprHighlightRules;
});

ace.define("ace/mode/zabbix_expr", ["require", "exports", "module", "ace/lib/oop", "ace/mode/text", "ace/mode/zabbix_expr_highlight_rules"], function(require, exports, module) {
    "use strict";

    var oop = require("../lib/oop");
    var TextMode = require("./text").Mode;
    var ZabbixExprHighlightRules = require("./zabbix_expr_highlight_rules").ZabbixExprHighlightRules;

    var Mode = function() {
        this.HighlightRules = ZabbixExprHighlightRules;
        this.$behaviour = this.$defaultBehaviour;
    };
    oop.inherits(Mode, TextMode);

    (function() {
        this.$id = "ace/mode/zabbix_expr";
    }).call(Mode.prototype);

    exports.Mode = Mode;
});

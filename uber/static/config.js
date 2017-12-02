System.config({
  baseURL: "../static/",
  defaultJSExtensions: true,
  transpiler: "babel",
  babelOptions: {
    "optional": [
      "runtime",
      "optimisation.modules.system"
    ]
  },
  paths: {
    "github:*": "jspm_packages/github/*",
    "npm:*": "jspm_packages/npm/*",
    "bower:*": "jspm_packages/bower/*"
  },

  map: {
    "angular": "github:angular/bower-angular@1.6.7",
    "angular-bootstrap": "github:angular-ui/bootstrap-bower@2.5.0",
    "angular-route": "github:angular/bower-angular-route@1.6.7",
    "babel": "npm:babel-core@5.8.38",
    "babel-runtime": "npm:babel-runtime@5.8.38",
    "bootbox": "npm:bootbox@4.4.0",
    "bootstrap": "github:twbs/bootstrap@3.3.7",
    "core-js": "npm:core-js@1.2.7",
    "css": "github:systemjs/plugin-css@0.1.36",
    "datatables": "github:DataTables/DataTables@1.10.16",
    "jquery": "npm:jquery@3.2.1",
    "jquery-confirm": "npm:jquery-confirm@3.3.2",
    "jquery-datetextentry": "github:grantm/jquery-datetextentry@2.0.11",
    "jquery-form": "npm:jquery-form@4.2.2",
    "jquery-validate": "npm:jquery-validate@2.0.0",
    "jquery-validation/jquery-validation": "github:jquery-validation/jquery-validation@1.17.0",
    "jqueryui": "npm:jqueryui@1.11.1",
    "lodash": "npm:lodash@4.17.4",
    "moment": "npm:moment@2.19.2",
    "patternfly": "bower:patternfly@3.30.2",
    "select2": "github:select2/select2@4.0.5",
    "toastr": "github:CodeSeven/toastr@2.1.3",
    "bower:bootstrap-datepicker@1.6.4": {
      "css": "github:systemjs/plugin-css@0.1.36",
      "jquery": "bower:jquery@3.2.1"
    },
    "bower:bootstrap-select@1.12.4": {
      "css": "github:systemjs/plugin-css@0.1.36",
      "jquery": "bower:jquery@3.2.1"
    },
    "bower:bootstrap-switch@3.3.3": {
      "bootstrap": "bower:bootstrap@3.3.7",
      "css": "github:systemjs/plugin-css@0.1.36",
      "jquery": "bower:jquery@3.2.1"
    },
    "bower:bootstrap-touchspin@3.1.2": {
      "bootstrap": "bower:bootstrap@3.3.7",
      "css": "github:systemjs/plugin-css@0.1.36",
      "jquery": "bower:jquery@3.2.1"
    },
    "bower:bootstrap@3.3.7": {
      "jquery": "bower:jquery@3.2.1"
    },
    "bower:c3@0.4.18": {
      "css": "github:systemjs/plugin-css@0.1.36",
      "d3": "bower:d3@3.5.17"
    },
    "bower:datatables-colreorder@1.3.3": {
      "datatables": "bower:datatables@1.10.16",
      "jquery": "bower:jquery@3.2.1"
    },
    "bower:datatables-colvis@1.1.2": {
      "css": "github:systemjs/plugin-css@0.1.36",
      "datatables": "bower:datatables@1.10.16",
      "jquery": "bower:jquery@3.2.1"
    },
    "bower:datatables@1.10.16": {
      "css": "github:systemjs/plugin-css@0.1.36",
      "jquery": "bower:jquery@3.2.1"
    },
    "bower:eonasdan-bootstrap-datetimepicker@4.17.47": {
      "css": "github:systemjs/plugin-css@0.1.36",
      "jquery": "bower:jquery@3.2.1",
      "moment": "bower:moment@2.18.1"
    },
    "bower:google-code-prettify@1.0.5": {
      "css": "github:systemjs/plugin-css@0.1.36"
    },
    "bower:patternfly-bootstrap-combobox@1.1.7": {
      "css": "github:systemjs/plugin-css@0.1.36"
    },
    "bower:patternfly-bootstrap-treeview@2.1.5": {
      "bootstrap": "bower:bootstrap@3.3.7",
      "jquery": "bower:jquery@3.2.1"
    },
    "bower:patternfly@3.30.2": {
      "bootstrap": "bower:bootstrap@3.3.7",
      "bootstrap-datepicker": "bower:bootstrap-datepicker@1.6.4",
      "bootstrap-select": "bower:bootstrap-select@1.12.4",
      "bootstrap-switch": "bower:bootstrap-switch@3.3.3",
      "bootstrap-touchspin": "bower:bootstrap-touchspin@3.1.2",
      "c3": "bower:c3@0.4.18",
      "css": "github:systemjs/plugin-css@0.1.36",
      "d3": "bower:d3@3.5.17",
      "datatables": "bower:datatables@1.10.16",
      "datatables-colreorder": "bower:datatables-colreorder@1.3.3",
      "datatables-colvis": "bower:datatables-colvis@1.1.2",
      "eonasdan-bootstrap-datetimepicker": "bower:eonasdan-bootstrap-datetimepicker@4.17.47",
      "font-awesome": "bower:font-awesome@4.7.0",
      "google-code-prettify": "bower:google-code-prettify@1.0.5",
      "jquery": "bower:jquery@3.2.1",
      "matchHeight": "bower:matchHeight@0.7.2",
      "moment": "bower:moment@2.18.1",
      "patternfly-bootstrap-combobox": "bower:patternfly-bootstrap-combobox@1.1.7",
      "patternfly-bootstrap-treeview": "bower:patternfly-bootstrap-treeview@2.1.5"
    },
    "github:CodeSeven/toastr@2.1.3": {
      "css": "github:systemjs/plugin-css@0.1.36",
      "jquery": "npm:jquery@3.2.1"
    },
    "github:DataTables/DataTables@1.10.16": {
      "css": "github:systemjs/plugin-css@0.1.36",
      "jquery": "npm:jquery@3.2.1"
    },
    "github:angular/bower-angular-route@1.6.7": {
      "angular": "github:angular/bower-angular@1.6.7"
    },
    "github:grantm/jquery-datetextentry@2.0.11": {
      "jquery": "npm:jquery@3.2.1"
    },
    "github:jspm/nodelibs-assert@0.1.0": {
      "assert": "npm:assert@1.4.1"
    },
    "github:jspm/nodelibs-buffer@0.1.1": {
      "buffer": "npm:buffer@5.0.8"
    },
    "github:jspm/nodelibs-path@0.1.0": {
      "path-browserify": "npm:path-browserify@0.0.0"
    },
    "github:jspm/nodelibs-process@0.1.2": {
      "process": "npm:process@0.11.10"
    },
    "github:jspm/nodelibs-util@0.1.0": {
      "util": "npm:util@0.10.3"
    },
    "github:jspm/nodelibs-vm@0.1.0": {
      "vm-browserify": "npm:vm-browserify@0.0.4"
    },
    "github:select2/select2@4.0.5": {
      "jquery": "npm:jquery@2.2.4"
    },
    "github:twbs/bootstrap@3.3.7": {
      "jquery": "npm:jquery@3.2.1"
    },
    "npm:assert@1.4.1": {
      "assert": "github:jspm/nodelibs-assert@0.1.0",
      "buffer": "github:jspm/nodelibs-buffer@0.1.1",
      "process": "github:jspm/nodelibs-process@0.1.2",
      "util": "npm:util@0.10.3"
    },
    "npm:babel-runtime@5.8.38": {
      "process": "github:jspm/nodelibs-process@0.1.2"
    },
    "npm:bootbox@4.4.0": {
      "process": "github:jspm/nodelibs-process@0.1.2"
    },
    "npm:buffer@5.0.8": {
      "base64-js": "npm:base64-js@1.2.1",
      "ieee754": "npm:ieee754@1.1.8"
    },
    "npm:core-js@1.2.7": {
      "fs": "github:jspm/nodelibs-fs@0.1.2",
      "path": "github:jspm/nodelibs-path@0.1.0",
      "process": "github:jspm/nodelibs-process@0.1.2",
      "systemjs-json": "github:systemjs/plugin-json@0.1.2"
    },
    "npm:inherits@2.0.1": {
      "util": "github:jspm/nodelibs-util@0.1.0"
    },
    "npm:jquery-confirm@3.3.2": {
      "jquery": "npm:jquery@3.2.1",
      "process": "github:jspm/nodelibs-process@0.1.2"
    },
    "npm:jquery-form@4.2.2": {
      "jquery": "npm:jquery@3.2.1",
      "process": "github:jspm/nodelibs-process@0.1.2"
    },
    "npm:jqueryui@1.11.1": {
      "process": "github:jspm/nodelibs-process@0.1.2"
    },
    "npm:path-browserify@0.0.0": {
      "process": "github:jspm/nodelibs-process@0.1.2"
    },
    "npm:process@0.11.10": {
      "assert": "github:jspm/nodelibs-assert@0.1.0",
      "fs": "github:jspm/nodelibs-fs@0.1.2",
      "vm": "github:jspm/nodelibs-vm@0.1.0"
    },
    "npm:util@0.10.3": {
      "inherits": "npm:inherits@2.0.1",
      "process": "github:jspm/nodelibs-process@0.1.2"
    },
    "npm:vm-browserify@0.0.4": {
      "indexof": "npm:indexof@0.0.1"
    }
  }
});

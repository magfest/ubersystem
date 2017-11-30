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
    "npm:*": "jspm_packages/npm/*"
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
    "datatables": "github:DataTables/DataTables@1.10.16",
    "grantm/jquery-datetextentry": "github:grantm/jquery-datetextentry@2.0.11",
    "jquery": "npm:jquery@3.2.1",
    "jquery-confirm": "npm:jquery-confirm@3.3.2",
    "jquery-datetextentry": "github:grantm/jquery-datetextentry@2.0.11",
    "jquery-form": "npm:jquery-form@4.2.2",
    "jquery-validate": "npm:jquery-validate@2.0.0",
    "jquery-validation/jquery-validation": "github:jquery-validation/jquery-validation@1.17.0",
    "jqueryui": "npm:jqueryui@1.11.1",
    "lodash": "npm:lodash@4.17.4",
    "moment": "npm:moment@2.19.2",
    "select2": "github:select2/select2@4.0.5",
    "toastr": "github:CodeSeven/toastr@2.1.3",
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

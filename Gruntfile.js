module.exports = function (grunt) {
    grunt.initConfig({
        pkg: grunt.file.readJSON('package.json'),
        npmcopy: {
            libs: {
                files: {
                    'uber/static/deps/libs/jquery.js': 'jquery:main',
                    'uber/static/deps/libs/datepicker.js': 'eonasdan-bootstrap-datetimepicker:main',
                    'uber/static/deps/libs/jquery-scanner.js': 'jQuery-Scanner-Detection:main',
                    'uber/static/deps/libs/moment.js': 'moment:main',
                    'uber/static/deps/libs/jquery-ui.js': 'jquery-ui-dist/jquery-ui.js',
                    'uber/static/deps/libs/jquery-ui.css': 'jquery-ui-dist/jquery-ui.css',
                    'uber/static/deps/libs/select2.js': 'select2/dist/js/select2.full.js',
                    'uber/static/deps/libs/select2.css': 'select2/dist/css/select2.css',
                    'uber/static/deps/libs/geocomplete.js': 'geocomplete:main',
                }
            }
        },
        concat: {
            js: {
                options: {
                    separator: ';',
                },
                src: ['uber/static/deps/libs/jquery.js', //Jquery must be first.
                    'uber/static/deps/libs/moment.js',
                    'uber/static/deps/libs/*.js',
                    'uber/static/deps/jquery-datetextentry/jquery.datetextentry.js',
                    'uber/static/deps/selectToAutocomplete/jquery.select-to-autocomplete.js'],
                dest: 'uber/static/deps/combined.js',

            },
            css: {
                src: ['uber/static/deps/libs/*.css', 'uber/static/deps/jquery-datetextentry/jquery.datetextentry.css'],
                dest: 'uber/static/deps/combined.css',
            }
        },
        uglify: {
            options: {
                mangle: false,
                output: {comments: 'some'},
                sourceMap: true
            },
            target: {
                files: {
                    'uber/static/deps/combined.min.js': ['uber/static/deps/combined.js']
                }
            }
        },
        cssmin: {
            options: {
                sourceMap: true,
                rebaseTo: 'uber/static/deps'
            },
            target: {
                files: {
                    'uber/static/deps/combined.min.css': ['uber/static/deps/combined.css']
                }
            }
        },
        replace: {
            correct_sourcemap: {
                src: ['uber/static/deps/combined.min.css.map'],
                overwrite: true,
                replacements: [{
                    from: '"uber/static/deps/combined.css"',
                    to: '"/uber/static/deps/combined.css"'
                }]
            }
        }
    });
    grunt.loadNpmTasks('grunt-npmcopy');
    grunt.loadNpmTasks('grunt-contrib-concat');
    grunt.loadNpmTasks('grunt-contrib-uglify');
    grunt.loadNpmTasks('grunt-contrib-cssmin');
    grunt.loadNpmTasks('grunt-text-replace');
    grunt.registerTask('default', ['npmcopy', 'concat', 'uglify', 'cssmin', 'replace']);
};

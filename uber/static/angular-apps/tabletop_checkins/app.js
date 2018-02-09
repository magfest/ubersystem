angular.module('tabletop.checkins', ['ngRoute', 'magfest', 'ui.bootstrap'])
    .config(function ($routeProvider){
        $routeProvider
            .when('/', {controller: 'GameListController', templateUrl: '../static/angular-apps/tabletop_checkins/game_list.html'})
            .when('/form', {controller: 'GameFormController', templateUrl: '../static/angular-apps/tabletop_checkins/form.html'})
            .otherwise({redirectTo: '/'});
    })
    .directive('attendeeLink', function () {
        return {
            restrict: 'E',
            template: '<span>' +
                          '<a target="_blank" href="../registration/form?id={{ attendee.id }}">{{ attendee.name }}</a>' +
                          '<span ng-if="badge"> (Badge #{{ attendee.badge }})</span>' +
                      '</span>',
            scope: {
                attendee: '=attendee',
                badge: '=badge'
            }
        };
    })
    .service('MatchMaker', function () {
        return function () {
            var args = arguments;
            return function (expected) {
                return function (actual) {
                    var concatted = '';
                    angular.forEach(args, function (key) {
                        concatted += actual[key];
                    });
                    return concatted.toLowerCase().indexOf(expected.toLowerCase()) !== -1;
                };
            };
        };
    })
    .service('Random', function () {
        var self = {
            randInt: function (x) {
                return Math.floor(x * Math.random());
            },
            choice: function (xs) {
                return xs[self.randInt(xs.length)];
            },
            id: function () {
                var id = '';
                for(var i = 0; i < 3; i++) {
                    id += self.choice('ABCDEFGHJKMNPRSTUVWXYZ') + (2 + self.randInt(8));
                }
                return id;
            }
        };
        return self;
    })
    .service('Attendees', function ($http, $window) {
        var self = {
            attendees: $window.ATTENDEES,
            set: function (xs) {
                self.attendees.splice.apply(self.attendees, [0, self.attendees.length].concat(xs));
            },
            update: function () {
                $http({
                    url: 'badged_attendees'
                }).then(function (response) {
                    self.set(response.data);
                })
            }
        };
        return self;
    })
    .service('Games', function ($window) {
        var self = {
            games: $window.GAMES,
            set: function (xs) {
                self.games.splice.apply(self.games, [0, self.games.length].concat(xs));
            }
        };
        return self;
    })
    .controller('GameListController', function ($scope, $http, Games, Attendees, MatchMaker) {
        $scope.games = Games.games;
        $scope.attendees = Attendees.attendees;
        $scope.nameOrCode = MatchMaker('name', 'code');
        $scope.nameOrBadge = MatchMaker('name', 'badge');
        $scope.checkout = function (game, attendee) {
            $http({
                method: 'post',
                url: 'checkout',
                params: {
                    game_id: game.id,
                    attendee_id: attendee.id
                }
            }).then(function (response) {
                Games.set(response.data.games);
            });
            $scope.game = $scope.attendee = '';
        };
        $scope.returned = function (game) {
            $http({
                method: 'post',
                url: 'returned',
                params: {game_id: game.id}
            }).then(function (response) {
                Games.set(response.data.games);
            });
            $scope.game = '';
        };
        $scope.returnToOwner = function (game) {
            $http({
                method: 'post',
                url: 'return_to_owner',
                params: {game_id: game.id}
            }).then(function (response) {
                Games.set(response.data.games);
            });
        };
    })
    .controller('GameFormController', function ($scope, $http, $location, Random, Games, Attendees, MatchMaker) {
        $scope.games = Games.games;
        $scope.attendees = Attendees.attendees;
        $scope.code = Random.id();
        $scope.nameOrBadge = MatchMaker('name', 'badge');
        $scope.create = function () {
            $http({
                method: 'post',
                url: 'add_game',
                params: {
                    code: $scope.code,
                    name: $scope.name,
                    attendee_id: $scope.owner.id
                }
            }).then(function (response) {
                Games.set(response.data.games);
                $location.path('/');
            });
        };
    });

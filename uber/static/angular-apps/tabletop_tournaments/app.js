angular.module('tabletop.tournaments', ['ngRoute', 'ui.bootstrap', 'magfest'])
    .config(function ($routeProvider) {
        $routeProvider
            .when('/', {
                controller: 'TournamentListController',
                templateUrl: '../static/angular-apps/tabletop_tournaments/tournament_list.html'
            })
            .when('/add-tournament', {
                controller: 'AddTournamentController',
                templateUrl: '../static/angular-apps/tabletop_tournaments/add_tournament.html'
            })
            .otherwise({redirectTo: '/'});
    })
    .factory('Tournaments', function ($window, $http, $q) {
        var self = {
            events: [],
            attendees: [],
            tournaments: [],
            _update: function (dst, src) {
                if (src) {
                    dst.length = 0;
                    Array.prototype.splice.apply(dst, [0, 0].concat(src));
                }
            },
            update: function (data) {
                angular.forEach(['events', 'attendees', 'tournaments'], function (name) {
                    self._update(self[name], _(data).get(name));
                });
            },
            _handleResponse: function (response) {
                self.update(response.data.state);
                return response.data.error ? $q.reject(response.data.error) : response;
            },
            _handleError: function (error) {
                toastr.error(error);
                return $q.reject(error);
            },
            create: function (tournament) {
                return $http({
                    method: 'POST',
                    url: 'create_tournament',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    data: $.param(tournament)
                }).then(self._handleResponse).catch(self._handleError);
            },
            signUp: function (pair) {
                return $http({
                    method: 'POST',
                    url: 'sign_up',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    data: $.param(pair)
                }).then(self._handleResponse).catch(self._handleError);
            },
            drop: function (pair) {
                return $http({
                    method: 'POST',
                    url: 'drop',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    data: $.param(pair)
                }).then(self._handleResponse).catch(self._handleError);
            }
        };
        self.update($window.PRELOAD_DATA || {});
        return self;
    })
    .controller('TournamentListController', function ($scope, $route, Tournaments) {
        $scope.attendees = Tournaments.attendees;
        $scope.tournaments = Tournaments.tournaments;
        $scope.signUp = function (tournament, attendee) {
            Tournaments.signUp({
                attendee_id: attendee.id,
                tournament_id: tournament.id,
                cellphone: attendee.cellphone
            }).then(function () {
                $route.reload();
            });
        };
        $scope.drop = function (tournament, entrant) {
            Tournaments.drop({
                attendee_id: entrant.id,
                tournament_id: tournament.id
            }).then(function () {
                $route.reload();
            });
        };
        $scope.futureTournaments = function (tournament) {
            var searchText = $scope.search || '';
            return ($scope.showAllTournaments || tournament.when > new Date().getTime() / 1000 - 15 * 60)
                && _(tournament.name.toLowerCase()).includes(searchText.toLowerCase());
        };
    })
    .controller('AddTournamentController', function ($scope, $q, $location, Tournaments) {
        $scope.events = Tournaments.events;
        $scope.tournament = {
            name: '',
            event: null
        };
        $scope.$watch('tournament.event', function () {
            if ($scope.tournament.event) {
                var name = $scope.tournament.event.name;
                if (_(name.toLowerCase()).endsWith('tournament')) {
                    name = name.substring(0, name.length - 'tournament'.length).trim();
                }
                $scope.tournament.name = name;
            }
        });
        $scope.create = function () {
            Tournaments.create({
                name: $scope.tournament.name,
                event_id: $scope.tournament.event.id
            }).finally(function () {
                $location.path('/');
            });
        };
        $scope.cancel = function () {
            $location.path('/');
        };
    });

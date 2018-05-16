angular.module('hotel', ['ngRoute', 'magfest'])
    .directive("keepScrollController", function($route, $timeout, $location) {
        var cache = {};
        return {
            restrict : 'A',
            link: function($scope, elements, attrs) {
                $scope.$on('$routeChangeStart', function() {
                    if(!attrs.keepScrollController || attrs.keepScrollController.indexOf($route.current.controller) !== -1) {
                        cache[$route.current.controller] = [$(window).scrollLeft(), $(window).scrollTop()];
                    }
                });

                $scope.$on('$routeChangeSuccess', function() {
                    var pos = cache[$route.current.controller];
                    if(pos) {
                        $timeout(function() {
                            $(window).scrollLeft(pos[0]);
                            $(window).scrollTop(pos[1]);
                        }, 0);
                    }
                });
            }
        }
    })
    .service('errorHandler', function () {
        return function () {
            alert('I AM ERROR');  // TODO: better error handling
        };
    })
    .service('Hotel', function ($window) {
        var self = {
            lists: {
                rooms: [],
                eligible: [],
                assigned: [],
                declined: [],
                unassigned: [],
                unconfirmed: [],
                all_attendees: []
            },
            _set: function (dst, src) {
                dst.splice.apply(dst, [0, dst.length].concat(src));
            },
            set: function (data) {
                angular.forEach(self.lists, function(xs, name) {
                    self._set(xs, data[name] || []);
                });
                angular.forEach(self.lists, function (xs, name) {
                    if (name != 'rooms' && name != 'all_attendees') {
                        self.lists.all_attendees.push.apply(self.lists.all_attendees, xs);
                    }
                });
                if (data.message) {
                    alert(data.message);  // TODO: use something other than alert() for better testability
                }
            },
            get: function (name, id) {
                for (var i=0, x; x=self.lists[name][i]; i++) {
                    if (x.id === id) {
                        return x;
                    }
                }
            }
        };
        if ($window.ROOM_DUMP) {
            self.set(ROOM_DUMP);
        }
        return self;
    })
    .config(function($routeProvider){
        $routeProvider
            .when('/', {controller: 'HotelController', templateUrl: '../static/angular-apps/hotel/schedule.html'})
            .when('/create-room', {controller: 'CreateController', templateUrl: '../static/angular-apps/hotel/room_form.html'})
            .when('/edit-room/:roomId', {controller: 'EditController', templateUrl: '../static/angular-apps/hotel/room_form.html'})
            .when('/attendee/:id', {controller: 'AttendeeController', templateUrl: '../static/angular-apps/hotel/attendee.html'})
            .when('/add-to-room/:roomId', {controller: 'AddController', templateUrl: '../static/angular-apps/hotel/add_to_room.html'})
            .otherwise({redirectTo: '/'});
    })
    .controller('HotelController', function($scope, $http, Hotel, errorHandler) {
        $scope.wrongNights = function (room, attendee) {
            return room.nights != attendee.nights;
        };
        $scope.remove = function (attendee_id, room_id) {
            $http({
                method: 'post',
                url: 'unassign_from_room',
                params: {
                    room_id: room_id,
                    attendee_id: attendee_id
                }
            }).success(Hotel.set).error(errorHandler);
        };
        $scope.deleteRoom = function (room_id) {
            $http({
                method: 'post',
                url: 'delete_room',
                params: {id: room_id}
            }).success(Hotel.set).error(errorHandler);
        };
        $scope.lockInRoom = function (room_id) {
            $http({
                method: 'post',
                url: 'lock_in_room',
                params: {id: room_id}
            }).success(Hotel.set).error(errorHandler);
        };
    })
    .controller('CreateController', function($scope, $http, $location, errorHandler, Hotel) {
        $scope.room = {notes: ''};
        $scope.nights = [];
        angular.forEach($scope.NIGHTS, function (night) {
            $scope.nights.push(angular.extend({checked: night.core}, night));
            if (night.core) {
                $scope.room[night.name] = night.val;
            }
        });
        $scope.save = function() {
            $http({
                method: 'post',
                url: 'create_room',
                params: $scope.room
            }).success(function(response) {
                Hotel.set(response);
                $location.path('/');
            }).error(errorHandler);
        };
        $scope.cancel = function() {
            $location.path('/');
        };
    })
    .controller('EditController', function($scope, $http, $location, $routeParams, errorHandler, Hotel) {
        $scope.room = Hotel.get('rooms', $routeParams.roomId);
        $scope.nights = [];
        angular.forEach($scope.NIGHTS, function (night) {
            $scope.nights.push(angular.extend({checked: $scope.room[night.name]}, night));
        });
        $scope.save = function() {
            $http({
                method: 'post',
                url: 'edit_room',
                params: $scope.room
            }).success(function(response) {
                Hotel.set(response);
                $location.path('/');
            }).error(errorHandler);
        };
        $scope.cancel = function() {
            $location.path('/');
        };
    })
    .controller('AddController', function ($scope, $http, $location, $routeParams, $window, Hotel, errorHandler) {
        $scope.room = Hotel.get('rooms', $routeParams.roomId);
        $scope.assignment = {
            room_id: $scope.room.id,
            attendee_id: _.get($scope.lists.eligible[0], 'id')
        };
        $scope.isSetupOrTeardown = function (modelWithNights) {
            return _($scope.NIGHTS).any(function (night) {
                !night.core && modelWithNights[night.name];
            });
        };
        $scope.cancel = function () {
            $location.path('/');
        };
        $scope.add = function () {
            $scope.lists = Hotel.lists;
            var room = Hotel.get('rooms', $scope.assignment.room_id);
            var attendee = Hotel.get('eligible', $scope.assignment.attendee_id);
            var autoDecline = !attendee.approved && $scope.isSetupOrTeardown(attendee.nights_lookup) && !$scope.isSetupOrTeardown(room);
            // TODO: replace confirm with an async Angular-driven UI component (for better testability)
            if (!autoDecline || confirm('This attendee has requested setup/teardown and you are assigning them to a regular room, which will automatically decline their request to help with setup/teardown.')) {
                $http({
                    method: 'post',
                    url: 'assign_to_room',
                    params: $scope.assignment
                }).then(function (response) {
                    Hotel.set(response.data);
                }).catch(errorHandler).finally(function () {
                    $window.location.reload();
                });
            }
        };
    })
    .controller('AttendeeController', function($scope, $routeParams, Hotel) {
        $scope.attendee = Hotel.get('all_attendees', $routeParams.id);
    });

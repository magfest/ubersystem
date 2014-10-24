//
// TODO: nights should be configurable
//
angular.module('hotel', ['ngRoute', 'magfest'])
    .service('errorHandler', function () {
        return function () {
            alert('I AM ERROR');
        };
    })
    .service('Hotel', function ($window) {
        var self = {
            lists: {
                rooms: [],
                assigned: [],
                unassigned: [],
                unconfirmed: [],
                assigned_elsewhere: [],
                declined: [],
                all_attendees: []
            },
            _set: function(dst, src) {
                dst.splice.apply(dst, [0, dst.length].concat(src));
            },
            set: function(data) {
                angular.forEach(self.lists, function(xs, name) {
                    self._set(xs, data[name] || []);
                });
                angular.forEach(self.lists, function (xs, name) {
                    if (name != 'rooms' && name != 'all_attendees') {
                        self.lists.all_attendees.push.apply(self.lists.all_attendees, xs);
                    }
                });
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
            .when('/', {controller: 'HotelController', templateUrl: '../static/lib/angular/hotel/schedule.html'})
            .when('/create-room', {controller: 'CreateController', templateUrl: '../static/lib/angular/hotel/room_form.html'})
            .when('/edit-room/:roomId', {controller: 'EditController', templateUrl: '../static/lib/angular/hotel/room_form.html'})
            .when('/attendee/:id', {controller: 'AttendeeController', templateUrl: '../static/lib/angular/hotel/attendee.html'})
            .otherwise({redirectTo: '/'});
    })
    .controller('HotelController', function($scope, $http, Hotel, errorHandler) {
        $scope.wrongNights = function (room, attendee) {
            return room.nights.replace('Tue / ', '') != attendee.nights;    // needs to be configurable
        };
        $scope.remove = function (attendee_id) {
            $http({
                method: 'post',
                url: 'unassign_from_room',
                params: {
                    attendee_id: attendee_id,
                    department: $scope.department
                }
            }).success(Hotel.set).error(errorHandler);
        };
        $scope.deleteRoom = function(room_id) {
            $http({
                method: 'post',
                url: 'delete_room',
                params: {id: room_id}
            }).success(Hotel.set).error(errorHandler);
        };
    })
    .controller('CreateController', function($scope, $http, $location, magconsts, errorHandler, Hotel) {
        $scope.room = {
            department: $scope.department,
            thursday: magconsts.THURSDAY,   // needs to be configurable
            friday: magconsts.FRIDAY,
            saturday: magconsts.SATURDAY,
            notes: ''
        };
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
    .controller('AddController', function($scope, $http, Hotel, errorHandler) {
        $scope.assignment = {
            room_id: $scope.room.id,
            attendee_id: $scope.lists.unassigned[0] && $scope.lists.unassigned[0].id
        };
        $scope.add = function() {
            var room = Hotel.get('rooms', $scope.assignment.room_id);
            var attendee = Hotel.get('unassigned', $scope.assignment.attendee_id);
            var limited = $scope.wrongNights(room, attendee) 
                       && (room.nights.indexOf('Wed') === -1 || room.nights.indexOf('Sun') === -1);
            if (!limited || confirm('This attendee has requested setup/teardown and you are assigning them to a regular room, wnich will automatically decline their request to help with setup/teardown.')) {
                $http({
                    method: 'post',
                    url: 'assign_to_room',
                    params: $scope.assignment
                }).success(Hotel.set).error(errorHandler);
            }
        };
    })
    .controller('AttendeeController', function($scope, $routeParams, Hotel) {
        $scope.attendee = Hotel.get('all_attendees', $routeParams.id);
    });

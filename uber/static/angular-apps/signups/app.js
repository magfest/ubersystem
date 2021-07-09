angular.module('signups', ['ngRoute', 'magfest'])
    .config(function ($routeProvider) {
        $routeProvider
            .when('/', {controller: 'ScheduleController', templateUrl: '../static/angular-apps/signups/possible.html'})
            .when('/schedule', {controller: 'ScheduleController', templateUrl: '../static/angular-apps/signups/taken.html'})
            .otherwise({redirectTo: '/'});
    })
    .service('Jobs', function ($http, $window, $timeout) {
        var self = {
            nextTimeout: 1000,
            currentTimeout: null,
            jobs: [],
            set: function (jobs) {
                self.jobs.splice.apply(self.jobs, [0, self.jobs.length].concat(jobs));
                self._sumWeightedHours();
            },
            _sumWeightedHours: function () {
                self.jobs.weightedHours = 0;
                angular.forEach(self.jobs, function (job) {
                    if (job.taken) {
                        self.jobs.weightedHours += job.weighted_hours;
                    }
                });
            },
            _success: function (response) {
                self.nextTimeout = 1000;
                self.set(response.jobs);
                if (response.error) {
                    $window.alert(response.error);
                }
            },
            _error: function () {
                console.log('unexpected error', arguments);
                $timeout.cancel(self.currentTimeout);
                self.nextTimeout = Math.min(600000, self.nextTimeout * 2);
                self.currentTimeout = $timeout(self.refresh, self.nextTimeout);
            },
            refresh: function () {
                $http({
                    method: 'get',
                    url: 'jobs'
                }).success(self._success).error(self._error);
            },
            signUp: function (jobId) {
                $http({
                    method: 'post',
                    url: 'sign_up',
                    params: {job_id: jobId}
                }).success(self._success).error(self._error);
            },
            drop: function(jobId) {
                $http({
                    method: 'post',
                    url: 'drop',
                    params: {job_id: jobId}
                }).success(self._success).error(self._error);
            }
        };
        if ($window.JOBS) {
            self.set($window.JOBS);
        }
        return self;
    })
    .filter('hourDay', function() {
        return function (start_time_local) {
            return moment(start_time_local, 'YYYY-MM-DD hh:mm:ss').format('ha ddd');
        };
    })
    .filter('popupLink', function() {
        return function (url, text) {
            return '<a style="text-decoration:none" onClick="window.open(\'' + url + '\', \'info\', \'toolbar=no,height=500,width=375,scrollbars=yes\').focus(); return false;" href="' + url + '">' + (text || "<sup>?</sup>") + "</a>";
        };
    })
    .controller('ScheduleController', function($scope, $http, $timeout, magconsts, Jobs) {
        $scope.c = magconsts;
        $scope.jobs = Jobs.jobs;
        $scope.signUp = Jobs.signUp;
        $scope.drop = Jobs.drop;
        $scope.taken = function(job) {
            return job.taken;
        };
        $scope.showDesc = function(job) {
            if (!$("#desc" + job.id).length) 
                $('#job' + job.id).parent('tr').after('<tr id="desc' + job.id + '"><td colspan="6"><i>' + job.description + '</i></td></tr>');
            else
                $("#desc" + job.id).remove();
        };
        $scope.refreshInterval = function() {
            Jobs.refresh();
            $timeout($scope.refreshInterval, 300000);
        };
        $timeout($scope.refreshInterval, 10000);
    });

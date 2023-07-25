$('.nav-tabs button').click(function() {
    window.location.hash = $(this).data('bs-target');
})
$().ready(function() {
    var tabID = window.location.hash;
    var tab = $(tabID + '-tab');
    if(tab.length) {
      new bootstrap.Tab(tab).show();
    } else {
      new bootstrap.Tab($('.nav-tabs button').first()).show();
    }
})
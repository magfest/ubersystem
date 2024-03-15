$('.nav-tabs button').click(function() {
    window.location.hash = $(this).data('bs-target');
})
$().ready(function() {
    var tabID = window.location.hash;
    try {
      var tab = $(tabID + '-tab');
    } catch(error) {
      new bootstrap.Tab($('.nav-tabs button').first()).show();
    }
    if(tab && tab.length) {
      new bootstrap.Tab(tab).show();
    } else {
      new bootstrap.Tab($('.nav-tabs button').first()).show();
    }
})
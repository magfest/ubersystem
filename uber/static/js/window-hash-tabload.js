$('.nav-tabs button').click(function() {
    window.location.hash = $(this).data('bs-target');
})
$().ready(function() {
    var tabID = window.location.hash;
    tabID = tabID.slice(1,);
    var tab = $('#' + tabID + '-tab');
    if(tab.length) {
      tab.tab('show');
    } else {
      $('.nav-tabs button').first().tab('show');
    }
})
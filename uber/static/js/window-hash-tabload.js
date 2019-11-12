$('.nav-tabs a').click(function() {
    window.location.hash = this.hash;
})
$().ready(function() {
    var tabID = window.location.hash;
    tabID = tabID.slice(1,);
    var tab = $('.nav-tabs a[href="#' + tabID + '"]');
    if(tab.length) {
      tab.tab('show');
    } else {
      $('.nav-tabs a').first().tab('show');
    }
})
let updateLinkHashes = function() {
  $('a.include-tab-hash').each(function() {
    let baseLink = $(this).attr('href').split('#')[0];
    $(this).attr('href', baseLink + window.location.hash);
  });
}

$('.nav-tabs button').click(function() {
    window.location.hash = $(this).data('bs-target');
    updateLinkHashes();
})
$().ready(function() {
    var tabID = window.location.hash;
    updateLinkHashes();
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
$(function(){
  var td = $("td:first-child").contents().andSelf();

  td.mouseover(function(event){
      $(event.target).find(":radio").focus();
  });

  td.click(function(event){
      if (event.target.nodeName == "TD") {
          $(event.target).find(":radio").click();
      } else {
          $(event.target).siblings(":radio").click();
      }
      badgeTypeChanged();
  });

  td.css("cursor", "default");
});

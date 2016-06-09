function renderMainMenu() {
    var MainMenu = window.MENU;
    var $menu = $('#main-menu');
    $.each(MENU, function (i, menuitem) {
        if (!menuitem) {
            return;
        }
        if (menuitem['href']) {
            $menu.append(
                $('<li></li>').append(
                    $('<a></a>').attr('href', menuitem.href).text(menuitem.name)));
        } else if (menuitem['submenu']) {
            var $submenu = $('<ul class="dropdown-menu" role="menu"></ul>');
            $.each(menuitem.submenu, function (i, submenuitem) {
                if (!submenuitem) {
                    return;
                }
                var $li = $('<li></li>');
                var $link = $('<a></a>').text(submenuitem.name);
                if (submenuitem.href) {
                    $link.attr('href', submenuitem.href);
                } else {
                    $li.addClass('disabled');
                }
                $submenu.append($li.append($link));
            });
            $('<li></li>')
                .addClass('dropdown')
                .append('<a href="#" class="dropdown-toggle" data-toggle="dropdown">' + menuitem.name + '<span class="caret"></span></a>')
                .append($submenu)
                .appendTo($menu);
        }
    });
}

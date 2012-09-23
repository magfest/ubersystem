Ext.define("App.ScheduleGrid", {
    extend: "Ext.grid.Panel",
    selModel: {mode: "MULTI"},
    width: 100,
    locationId: null,
    locatonName: null,
    
    showContextMenu: function(grid, record, item, rowIndex, event) {
        console.log("contextmenu", record, item, rowIndex, event);
        event.preventDefault();
        var el = Ext.fly(item);
        var menu = record.get("name") == "_blank" ? App.blankMenu : App.eventMenu;
        menu.showAt(el.getX() + 10, el.getY() + 10);
    },
    
    initComponent: function() {
        this.columns = [{
            flex: 1,
            text: this.locationName,
            dataIndex: "name",
            renderer: function(value, metaData, record, rowIndex) {
                if (value == "_blank") {
                    return '<div style="height: 50px">&nbsp;</div>';
                } else {
                    var height = 50 + 52 * (record.get("duration") - 1);
                    return '<div style="height: ' + height + 'px">' + value + '</div>';
                }
            }
        }];
        
        this.listeners = {
            scope: this,
            itemcontextmenu: this.showContextMenu,
            itemdblclick: this.showContextMenu
        };
        
        this.store = Ext.create("Ext.data.JsonStore", {
            autoLoad: true,
            fields: ["name", "duration"],
            proxy: {
                type: "ajax",
                autoLoad: true,
                url: "events",
                extraParams: {location: this.locationId}
            }
        });
        this.store.load();  // autoload doesn't work
        
        this.callParent(arguments);
    }
});

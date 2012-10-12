Ext.define("App.EventMover", {
    extend: "Ext.window.Window",
    title: "Move an Event Here",
    modal: true,
    autoShow: true,
    items: [{
        xtype: "form",
        items: [{
            xtype: "combobox",
            allowBlank: false,
            editable: false,
            displayField: "name",
            valueField: "id",
            store: Ext.create("Ext.data.JsonStore", {
                fields: ["id", "name", "duration"],
                proxy: {
                    type: "ajax",
                    url: "available_events",
                    reader: {
                        type: "json",
                        root: "events",
                        idProperty: "id"
                    }
                }
            })
        }],
        buttons: [{
            text: "Cancel",
            handler: function() {
                this.up("window").close();
            }
        }, {
            text: "Move",
            formBind: true,
            handler: function(btn) {

            }
        }]
    }],
    
    initComponent: function() {
        this.callParent(arguments);
        this.store = this.items.get(0).items.get(0).store;
    }
});

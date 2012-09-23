Ext.define("App.EventForm", {
    extend: "Ext.window.Window",
    title: "Create an Event",
    autoShow: true,
    items: [{
        xtype: "form",
        cls: "eventform",
        url: "event",
        items: [{
            xtype: "textfield",
            name: "name",
            fieldLabel: "Event Name",
            allowBlank: false
        }, {
            xtype: "combobox",
            name: "duration",
            allowBlank: false,
            editable: false,
            fieldLabel: "Duration",
            store: {{ EVENT_DURATION_OPTS|jsonize }}
        }, {
            xtype: "textarea",
            name: "description",
            fieldLabel: "Description"
        }, {
            xtype: "button",
            text: "Add a Panelist",
            handler: function(btn) {
                btn.up("form").add({
                    xtype: "container",
                    layout: "hbox",
                    items: [{
                        xtype: "combobox",
                        name: "panelists",
                        fieldLabel: "Panelist",
                        valueField: "id",
                        displayField: "full_name",
                        editable: false,
                        store: Ext.create("Ext.data.JsonStore", {
                            fields: ["id", "full_name"],
                            proxy: {
                                type: "ajax",
                                url: "panelists",
                                reader: {
                                    type: "json",
                                    idProperty: "id"
                                }
                            }
                        })
                    }]
                });
            }
        }],
        buttons: [{
            text: "Cancel",
            handler: function() {
                this.up("window").close();
            }
        }, {
            text: "Create",
            formBind: true,
            disabled: true,
            handler: function(btn) {
                btn.up("form").getForm().submit({
                    success: function(form, action) {
                        btn.up("window").close();
                        Ext.Msg.alert("Success", action.result.msg);
                    },
                    failure: function(form, action) {
                        btn.up("window").close();
                        Ext.Msg.alert("Failed", action.result.msg);
                    }
                });
            }
        }]
    }]
});

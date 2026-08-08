// Assignee modal for hotel_lottery_admin/hotel_inventory.html: any
// .assignee-link opens the modal listing who's assigned to that
// inventory block (optionally for one night).
//
// The template provides the current partition filter BEFORE this
// script loads:
//
//   window.hotelInventoryConfig = { partition: 'all' | 'default' | id };
(function () {
  var cfg = window.hotelInventoryConfig || {};
  var currentPartition = cfg.partition || '';

  function showAssignees(inventoryId, nightDate, title) {
    document.getElementById('assignees-title').textContent = 'Assigned: ' + title;
    document.getElementById('assignees-loading').style.display = '';
    document.getElementById('assignees-content').style.display = 'none';
    new bootstrap.Modal(document.getElementById('assigneesModal')).show();
    $.ajax({
        method: 'POST',
        url: 'inventory_assignees',
        dataType: 'json',
        data: { inventory_id: inventoryId, night_date: nightDate, partition: currentPartition, csrf_token: csrf_token },
        success: function(json) {
            document.getElementById('assignees-loading').style.display = 'none';
            var container = document.getElementById('assignees-content');
            container.textContent = '';
            if (json.assignees && json.assignees.length) {
                var table = document.createElement('table');
                table.className = 'table table-sm table-hover';
                var thead = table.createTHead();
                var hrow = thead.insertRow();
                ['Name', 'Conf #', 'Status', 'Check-in', 'Check-out', 'Partition'].forEach(function(h) {
                    var th = document.createElement('th');
                    th.textContent = h;
                    hrow.appendChild(th);
                });
                var tbody = table.createTBody();
                json.assignees.forEach(function(a) {
                    var row = tbody.insertRow();
                    var nameCell = row.insertCell();
                    var nameLink = document.createElement('a');
                    nameLink.href = '../registration/form?id=' + encodeURIComponent(a.attendee_id);
                    nameLink.target = '_blank';
                    nameLink.textContent = a.name;
                    nameCell.appendChild(nameLink);

                    var confCell = row.insertCell();
                    var confLink = document.createElement('a');
                    confLink.href = 'form?id=' + encodeURIComponent(a.app_id);
                    confLink.textContent = a.conf_num;
                    confCell.appendChild(confLink);

                    row.insertCell().textContent = a.status;
                    row.insertCell().textContent = a.check_in;
                    row.insertCell().textContent = a.check_out;
                    row.insertCell().textContent = a.partition || '—';
                });
                container.appendChild(table);
            } else {
                var p = document.createElement('p');
                p.className = 'text-muted text-center';
                p.textContent = 'No assignees found.';
                container.appendChild(p);
            }
            container.style.display = '';
        }
    });
  }

  $(document).on('click', '.assignee-link', function(e) {
    e.preventDefault();
    var el = $(this);
    showAssignees(el.data('inventory-id'), el.data('night'), el.data('title'));
  });
})();

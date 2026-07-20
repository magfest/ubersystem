// Assignee-modal + inventory-chart glue for
// hotel_lottery_admin/hotel_inventory.html.
//
// The template provides its data via a config stanza BEFORE this
// script loads:
//
//   window.hotelInventoryConfig = {
//     partition: ...,     // current partition tab ('all', 'default', or id)
//     nightLabels: [...], // x-axis labels, one per event night
//     charts: {           // canvas id -> Chart.js dataset arrays
//       chart_total: {assigned: [...], available: [...], waitlisted: [...]},
//       ...
//     }
//   };
//
// Chart.js (deps/chartjs/chart.umd.min.js) must be loaded first when
// any charts are passed.
(function () {
  var cfg = window.hotelInventoryConfig || {};
  var currentPartition = cfg.partition || '';
  var nightLabels = cfg.nightLabels || [];

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

  function renderChart(canvasId, data) {
    new Chart(document.getElementById(canvasId), {
        type: 'bar',
        data: {
            labels: nightLabels,
            datasets: [
                { label: 'Assigned', data: data.assigned, backgroundColor: 'rgba(54, 162, 235, 0.7)' },
                { label: 'Available', data: data.available, backgroundColor: 'rgba(200, 200, 200, 0.5)' },
                { label: 'Waitlisted', data: data.waitlisted, backgroundColor: 'rgba(255, 159, 64, 0.7)' }
            ]
        },
        options: {
            responsive: true,
            scales: { y: { beginAtZero: true } }
        }
    });
  }

  $(document).on('click', '.assignee-link', function(e) {
    e.preventDefault();
    var el = $(this);
    showAssignees(el.data('inventory-id'), el.data('night'), el.data('title'));
  });

  // Render charts
  Object.keys(cfg.charts || {}).forEach(function (canvasId) {
    renderChart(canvasId, cfg.charts[canvasId]);
  });
})();

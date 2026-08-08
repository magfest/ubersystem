// Floor-map modal for the hotel lottery admin: a room picker for one
// booking, and a whole-hotel inspector.
//
// Load via:  {{ "js/hotel-room-map.js"|serve_static_content }}
// (the hotel_lottery_admin/_macros.html `room_map_modal` macro does this,
// along with emitting the #room-map-modal shell and #room-map-data JSON.)
//
// Any `.room-map-open` button opens the modal in PICK mode for the
// <select name=physical_room_id> in its own <form>; the select's option
// values define which rooms are offered, so eligibility always agrees
// with the plain dropdown. Button data attributes give the booking
// context:
//   data-inventory-id    the booking's block (rooms in other blocks
//                        render as unfilled outlines)
//   data-physical-types  the block's declared physical type codes,
//                        comma-separated; when non-empty, rooms with
//                        other codes render as unfilled outlines
//   data-check-in/out    ISO dates, used to pick which of a room's
//                        bookings conflicts (checkout day exclusive)
//   data-context-label   shown in the modal header
//
// A suite booking that carries connector rooms may only take a room
// whose connected neighbours can host the whole group, so the picker
// asks the server (vacant_rooms_json) which rooms qualify and which
// rooms each one would take. Hovering any of them highlights the whole
// group, and picking one assigns them together.
//
// Any `.room-map-inspect` button opens INSPECT mode: every room is
// painted by its current occupancy and clicking one shows its details
// in the side panel instead of assigning anything.
//
// The SVG comes from the modal's data-map-url, fetched once per page and
// inlined so shapes can be styled and clicked. Shapes carry data-room /
// data-floor attributes (rendered by uber.hotel.floormap);
// #room-map-data supplies {number -> catalog room + live bookings}.
// The map is scaled to fit the modal, rotating 90 degrees when the map
// and viewport aspects disagree.
(function () {
  var modalEl = document.getElementById('room-map-modal');
  if (!modalEl) return;

  var rooms = JSON.parse(
      document.getElementById('room-map-data').textContent || '[]');
  var byNumber = {};
  rooms.forEach(function (r) { byNumber[r.number] = r; });

  // state -> [fill, legend label]; 'other' renders as outline only.
  var STATES = {
    vacant:   ['#198754', 'Vacant'],
    assigned: ['#ffc107', 'Assigned'],
    secured:  ['#0d6efd', 'Secured'],
    oos:      ['#adb5bd', 'Out of service'],
    other:    [null,      'Different block or type'],
  };
  var OUTLINE = '#6c757d';
  var SOFT_GREEN = '#d1e7dd';  // fill for a floor with rooms
  var PAINTABLE = 'path,rect,circle,ellipse,polygon,polyline';
  var SVG_NS = 'http://www.w3.org/2000/svg';

  var body = modalEl.querySelector('.room-map-body');
  var info = modalEl.querySelector('.room-map-info');
  var hover = modalEl.querySelector('.room-map-hover');
  var floorsHost = modalEl.querySelector('.room-map-floors');
  var subtitle = modalEl.querySelector('.room-map-subtitle');
  var legend = modalEl.querySelector('.room-map-legend');
  var svgPromise = null;
  var shapes = [];       // [{el, room, floor}]
  var context = null;    // set per open: {mode, ...pick fields}
  var modal = null;

  function buildLegend() {
    legend.replaceChildren();
    Object.keys(STATES).forEach(function (state) {
      if (context.mode === 'inspect' && state === 'other') return;
      var fill = STATES[state][0];
      var label = STATES[state][1];
      if (state === 'vacant' && context.mode === 'pick') {
        label += ' (click to assign)';
      }
      var item = document.createElement('span');
      item.className = 'me-3';
      item.innerHTML = '<span style="display:inline-block;width:0.9em;' +
          'height:0.9em;vertical-align:-0.1em;border:1px solid ' + OUTLINE +
          ';' + (fill ? 'background:' + fill + ';' : '') + '"></span> ';
      item.appendChild(document.createTextNode(label));
      legend.appendChild(item);
    });
  }

  function loadSvg() {
    if (!svgPromise) {
      svgPromise = fetch(modalEl.getAttribute('data-map-url'),
                         {credentials: 'same-origin'})
        .then(function (resp) {
          if (!resp.ok) throw new Error('HTTP ' + resp.status);
          return resp.text();
        })
        .then(function (text) {
          body.innerHTML = text;
          var svg = body.querySelector('svg');
          // Room-number labels sit on top of the shapes; let clicks
          // fall through to the room under them.
          svg.querySelectorAll('text').forEach(function (el) {
            el.style.pointerEvents = 'none';
          });
          // The map's <title>s would raise the browser's own tooltip
          // on top of the hover card, which says the same thing.
          svg.querySelectorAll('title').forEach(function (el) {
            el.remove();
          });
          collectShapes(svg);
          buildFloorTabs(svg);
          return svg;
        });
    }
    return svgPromise;
  }

  // Rotate the whole drawing 90 degrees by wrapping it in a <g> and
  // swapping the viewBox, so labels stay crisp and hit-testing works.
  function rotateSvg(svg) {
    var vb = svg.viewBox.baseVal;
    var g = document.createElementNS(SVG_NS, 'g');
    while (svg.firstChild) g.appendChild(svg.firstChild);
    svg.appendChild(g);
    g.setAttribute('transform', 'rotate(90) translate(' + (-vb.x) + ' ' +
                   (-(vb.y + vb.height)) + ')');
    svg.setAttribute('viewBox', '0 0 ' + vb.height + ' ' + vb.width);
  }

  function fitMap() {
    var svg = body.querySelector('svg');
    if (!svg) return;
    body.style.height = Math.max(320, window.innerHeight - 220) + 'px';
    var availW = body.clientWidth;
    var availH = body.clientHeight;
    // The modal may still be transitioning open, so the body has no
    // size yet; the shown.bs.modal handler re-fits once it does.
    if (!availW || !availH) return;
    var vb = svg.viewBox.baseVal;
    if ((vb.width < vb.height) !== (availW < availH)) {
      rotateSvg(svg);
      vb = svg.viewBox.baseVal;
    }
    var scale = Math.min(availW / vb.width, availH / vb.height);
    svg.style.width = Math.floor(vb.width * scale) + 'px';
    svg.style.height = Math.floor(vb.height * scale) + 'px';
    svg.style.display = 'block';
    svg.style.margin = '0 auto';
  }
  window.addEventListener('resize', fitMap);
  // The map may arrive before or after the open transition finishes;
  // fit on both events (and once more on a timer, since a modal that
  // was already open fires no shown event).
  modalEl.addEventListener('shown.bs.modal', fitMap);
  modalEl.addEventListener('hide.bs.modal', hideHover);

  function collectShapes(svg) {
    svg.querySelectorAll('[data-room]').forEach(function (el) {
      var room = byNumber[el.getAttribute('data-room')];
      if (!room) return;  // named decoration, or a room not in the catalog
      var layer = el.closest('g[data-floor]');
      var shape = {el: el, room: room,
                   floor: layer ? layer.getAttribute('data-floor') : null};
      shapes.push(shape);
      el.addEventListener('click', function () { pick(room, el); });
      el.addEventListener('mouseenter', function (event) {
        highlight(shape, true);
        showHover(shape, event);
      });
      el.addEventListener('mousemove', moveHover);
      el.addEventListener('mouseleave', function () {
        highlight(shape, false);
        hideHover();
      });
    });
  }

  function overlapsContext(booking) {
    if (!context.checkIn || !context.checkOut) return true;
    if (!booking.check_in || !booking.check_out) return false;
    return booking.check_in < context.checkOut &&
           context.checkIn < booking.check_out;
  }

  // The connector groups the server offered for this booking, read at
  // use time: the select loads them asynchronously, so a snapshot taken
  // when the modal opened would often still be empty.
  function placements() {
    return (context.select && context.select.roomGroups) || [];
  }

  // Every room that would be taken along with this one - the group a
  // room belongs to, whether it's the suite or one of its connectors.
  function groupFor(room) {
    var match = placements().filter(function (opt) {
      return opt.group && opt.group.indexOf(room.id) !== -1;
    })[0];
    return match || null;
  }

  // Rooms that would be assigned together, so hovering any of them
  // lights up the whole group (across floors - a connector on another
  // floor still counts, and the hover card names it).
  function groupShapes(shape) {
    var match = groupFor(shape.room);
    if (!match) return [shape];
    return shapes.filter(function (s) {
      return match.group.indexOf(s.room.id) !== -1;
    });
  }

  function highlight(shape, on) {
    groupShapes(shape).forEach(function (s) {
      s.el.style.filter = on ? 'brightness(0.8)' : '';
      s.el.style.strokeWidth = on ? '3' : '';
    });
  }

  function typeMatches(room) {
    return !context.physicalTypes.size ||
        context.physicalTypes.has((room.type_code || '').toUpperCase());
  }

  function classify(room) {
    if (context.mode === 'inspect') {
      if (room.out_of_service) return 'oos';
      var current = room.bookings[0];
      if (!current) return 'vacant';
      var state = current.status.toLowerCase();
      return STATES[state] ? state : 'assigned';
    }
    // A room the suite would take along is offered too - same colour
    // as the suite, and clicking it assigns the group.
    if (groupFor(room)) return 'vacant';
    if (!typeMatches(room)) return 'other';
    if (context.eligible.has(room.id)) return 'vacant';
    if (room.inventory_id !== context.inventoryId) return 'other';
    if (room.out_of_service) return 'oos';
    var conflict = room.bookings.filter(overlapsContext)[0];
    if (conflict) {
      var state = conflict.status.toLowerCase();
      return STATES[state] ? state : 'assigned';
    }
    return 'other';
  }

  function paint() {
    shapes.forEach(function (shape) {
      var state = classify(shape.room);
      var fill = STATES[state][0];
      var targets = shape.el.matches(PAINTABLE)
          ? [shape.el]
          : Array.prototype.slice.call(
                shape.el.querySelectorAll(PAINTABLE));
      targets.forEach(function (el) {
        el.style.fill = fill || 'none';
        el.style.fillOpacity = fill ? '0.8' : '';
        el.style.stroke = OUTLINE;
        // Without this an unfilled shape only responds along its
        // outline, leaving most of the room un-hoverable.
        el.style.pointerEvents = 'all';
      });
      shape.el.style.cursor =
          (context.mode === 'inspect' || state === 'vacant')
              ? 'pointer' : 'default';
      shape.state = state;
    });
  }

  function buildFloorTabs(svg) {
    svg.querySelectorAll('g[data-floor]').forEach(function (layer) {
      var floor = layer.getAttribute('data-floor');
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-outline-secondary';
      btn.textContent = floor;
      btn.addEventListener('click', function () { showFloor(floor); });
      floorsHost.appendChild(btn);
    });
    var first = svg.querySelector('g[data-floor]');
    if (first) showFloor(first.getAttribute('data-floor'));
  }

  // Floors that have something to offer are tinted, so a whole hotel's
  // worth of tabs shows where to look without opening each one.
  function floorsWithVacancy() {
    var floors = {};
    shapes.forEach(function (shape) {
      if (shape.floor && shape.state === 'vacant') floors[shape.floor] = true;
    });
    return floors;
  }

  function showFloor(floor) {
    hideHover();
    body.querySelectorAll('g[data-floor]').forEach(function (layer) {
      layer.style.display =
          layer.getAttribute('data-floor') === floor ? '' : 'none';
    });
    var vacant = floorsWithVacancy();
    floorsHost.querySelectorAll('button').forEach(function (btn) {
      var name = btn.textContent;
      var has = vacant[name];
      var current = name === floor;
      btn.className = 'btn ' + (has
          ? (current ? 'btn-success' : 'btn-outline-success')
          : (current ? 'btn-secondary' : 'btn-outline-secondary'));
      // Bootstrap 5.0 has no subtle-fill variant, so tint the
      // non-selected floors that have rooms by hand: green at a glance,
      // fully saturated once you're on it.
      btn.style.backgroundColor = has && !current ? SOFT_GREEN : '';
      btn.title = has ? 'Rooms available on this floor'
                      : 'No rooms available on this floor';
    });
  }

  // Re-tint the tabs for the floor currently shown (states change per
  // booking, so this runs after every paint).
  function refreshFloorTabs() {
    var active = floorsHost.querySelector('.btn-secondary, .btn-success');
    showFloor(active ? active.textContent
                     : (shapes[0] && shapes[0].floor) || '');
  }

  // Open on the floor with something to offer, so a vacant room is
  // visible without hunting through the tabs.
  function showBestFloor() {
    var first = shapes.filter(function (s) {
      return s.state === 'vacant' && s.floor;
    })[0];
    if (first) showFloor(first.floor);
  }

  function link(text, href) {
    var a = document.createElement('a');
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = text;
    return a;
  }

  function infoRow(label, value) {
    var row = document.createElement('div');
    row.className = 'mb-1';
    var tag = document.createElement('span');
    tag.className = 'text-muted small me-1';
    tag.textContent = label + ':';
    row.appendChild(tag);
    row.appendChild(value instanceof Node
        ? value : document.createTextNode(value));
    return row;
  }

  // Full details for one room, shared by the hover card and the
  // click-through side panel. `linked` renders the cross-references as
  // anchors (the hover card is pointer-events: none, so it stays text).
  function roomDetails(room, floor, state, linked) {
    var frag = document.createDocumentFragment();
    var heading = document.createElement('h6');
    heading.className = 'mb-1';
    heading.appendChild(linked
        ? link('Room ' + room.number, 'edit_physical_room?id=' + room.id)
        : document.createTextNode('Room ' + room.number));
    frag.appendChild(heading);

    if (state) frag.appendChild(infoRow('Status', STATES[state][1]));
    if (floor) frag.appendChild(infoRow('Floor', floor));
    frag.appendChild(infoRow('Block',
        linked && room.inventory_id
            ? link(room.block, 'edit_inventory_item?id=' + room.inventory_id)
            : (room.block || 'uncategorized')));
    if (room.type_code) frag.appendChild(infoRow('Type', room.type_code));
    if (room.ada) frag.appendChild(infoRow('ADA', 'yes'));
    if (room.accessibility.length) {
      frag.appendChild(infoRow('Accessibility',
                               room.accessibility.join(', ')));
    }
    if (room.out_of_service) {
      frag.appendChild(infoRow('Service', 'out of service'));
    }
    if (room.notes) frag.appendChild(infoRow('Notes', room.notes));
    var match = groupFor(room);
    if (match && match.group_numbers && match.group_numbers.length > 1) {
      frag.appendChild(infoRow('Assigns together',
                               match.group_numbers.join(', ')));
    }

    var bookings = document.createElement('div');
    bookings.className = 'mt-2';
    var label = document.createElement('div');
    label.className = 'text-muted small';
    label.textContent = room.bookings.length
        ? 'Bookings:' : 'No live bookings.';
    bookings.appendChild(label);
    room.bookings.forEach(function (b) {
      var line = document.createElement('div');
      line.className = 'small mb-2';

      var who = document.createElement('div');
      who.className = 'fw-bold';
      var name = b.guest || '(no guest)';
      who.appendChild(linked && b.attendee_id
          ? link(name, '../registration/form?id=' + b.attendee_id)
          : document.createTextNode(name));
      line.appendChild(who);

      line.appendChild(document.createTextNode(
          (b.check_in || '?') + ' \u2192 ' + (b.check_out || '?') +
          ' \u00b7 ' + b.status +
          (b.auto ? ' \u00b7 auto-placed' : '')));

      if (linked) {
        var links = document.createElement('div');
        links.appendChild(link('Booking', 'edit_room_assignment?id=' + b.id));
        if (b.application_id) {
          links.appendChild(document.createTextNode(' \u00b7 '));
          links.appendChild(link('Application', 'form?id=' + b.application_id));
        }
        line.appendChild(links);
      }
      bookings.appendChild(line);
    });
    frag.appendChild(bookings);
    return frag;
  }

  function showInfo(room, shape) {
    info.replaceChildren(
        roomDetails(room, shape.floor, shape.state, true));
    info.classList.remove('d-none');
    fitMap();
  }

  function showHover(shape, event) {
    hover.replaceChildren(
        roomDetails(shape.room, shape.floor, shape.state, false));
    hover.classList.remove('d-none');
    moveHover(event);
  }

  // Follow the pointer, staying inside the modal body.
  function moveHover(event) {
    var host = hover.offsetParent || hover.parentNode;
    var rect = host.getBoundingClientRect();
    var x = Math.min(event.clientX - rect.left + 14,
                     host.clientWidth - hover.offsetWidth - 4);
    var y = Math.min(event.clientY - rect.top + 14,
                     host.clientHeight - hover.offsetHeight - 4);
    hover.style.left = Math.max(4, x) + 'px';
    hover.style.top = Math.max(4, y) + 'px';
  }

  function hideHover() {
    hover.classList.add('d-none');
  }

  function pick(room, el) {
    if (context.mode === 'inspect') {
      showInfo(room, shapes.filter(function (s) {
        return s.el === el;
      })[0] || {floor: null, state: null});
      return;
    }
    var match = groupFor(room);
    // Clicking a connector room assigns through its suite, since the
    // group is placed from the suite's room.
    var target = match ? match.id : room.id;
    if (!match && classify(room) !== 'vacant') return;
    context.select.value = target;
    context.select.dispatchEvent(new Event('change', {bubbles: true}));
    modal.hide();
  }

  function open(context_) {
    context = context_;
    info.classList.add('d-none');
    info.replaceChildren();
    buildLegend();
    modal = modal || new bootstrap.Modal(modalEl);
    modal.show();
    loadSvg()
      .then(function () {
        paint();
        refreshFloorTabs();
        if (context.mode === 'pick') showBestFloor();
        fitMap();
        window.setTimeout(fitMap, 250);
      })
      .catch(function (err) {
        var alert = document.createElement('div');
        alert.className = 'alert alert-danger';
        alert.textContent = 'Could not load the map (' + err + ').';
        body.replaceChildren(alert);
        svgPromise = null;
      });
  }

  document.addEventListener('click', function (event) {
    var inspectBtn = event.target.closest('.room-map-inspect');
    if (inspectBtn) {
      subtitle.textContent = 'All rooms by current occupancy';
      open({mode: 'inspect'});
      return;
    }
    var btn = event.target.closest('.room-map-open');
    if (!btn) return;
    var form = btn.closest('form');
    var select = form &&
        form.querySelector('select[name=physical_room_id]');
    if (!select) return;
    subtitle.textContent = btn.getAttribute('data-context-label') || '';
    open({
      mode: 'pick',
      select: select,
      eligible: new Set(Array.prototype.map.call(select.options,
          function (o) { return o.value; }).filter(Boolean)),
      inventoryId: btn.getAttribute('data-inventory-id') || null,
      physicalTypes: new Set(
          (btn.getAttribute('data-physical-types') || '')
              .split(',')
              .map(function (code) { return code.trim().toUpperCase(); })
              .filter(Boolean)),
      checkIn: btn.getAttribute('data-check-in') || null,
      checkOut: btn.getAttribute('data-check-out') || null,
    });
  });
})();

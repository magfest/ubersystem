"""Hotel floor maps for the physical-room picker.

A hotel's map is uploaded as one YAML file describing every floor's
room shapes in a shared coordinate space; ``build`` validates it and
renders the SVG the picker consumes, which is stored alongside the
source on LotteryHotel (map_svg / map_yaml).

The YAML doubles as the physical-room catalog source: uploads sync
PhysicalRoom rows (via ``catalog_rows`` -> uber.hotel.physical
.import_rows) and ``export_yaml`` merges the current catalog back into
the stored geometry for round-trip editing.

YAML schema (coordinates are unitless; the viewBox is computed):

    floors:                 # required, ordered as displayed
      - floor: "2"          # tab label, matched by data-floor
        rooms:
          - number: "2000"  # becomes PhysicalRoom.room_number
            type: RS        # optional hotel type code
            x: 10, y: 20, w: 30, h: 8   # optional: no box = catalog
            rotated: true   # optional: rotate the number label 90deg
            ada: true       # optional catalog fields
            accessibility: [roll-in shower]
            connects_to: ["2001"]
            notes: ""
        stairs:             # optional decorative markers
          - {x: 1, y: 2, w: 3, h: 4}
        walls:              # optional decorative segments (wing
          - [x0, y0, x1, y1]  # outlines, connected-room boxes)
    areas:                  # optional context drawn behind every floor
      - kind: plate         # plate|courtyard|atrium|entrance|water
        label: ATRIUM       # optional centered caption
        x: 0, y: 0, w: 100, h: 100
    labels:                 # optional free-floating captions
      - {text: "TO RIVER", x: 50, y: 99, size: 18}

The rendered SVG is the picker's contract: one ``<g data-floor>`` per
floor, each room a ``<g data-room>`` wrapping its shape, everything
else unnamed decoration. The client JS (hotel-room-map.js) only does
attribute lookups and replaces each room group's ``<title>``.
"""

import xml.etree.ElementTree as ET

import yaml

PADDING = 20

# kind -> (fill, stroke) for context areas; the plate is the building
# outline, so it gets a heavier stroke when rendered.
_AREA_COLORS = {
    'plate': ('#b9d2e0', '#2a5a8c'),
    'courtyard': ('#d9e8cf', '#2a5a8c'),
    'atrium': ('#eae2cf', '#2a5a8c'),
    'entrance': ('#e3d7bd', '#2a5a8c'),
    'water': ('#7ec4e8', '#2a5a8c'),
}
_ROOM_FILL, _ROOM_STROKE = '#ffffff', '#888888'
_STAIR_FILL, _WALL_STROKE = '#e0e0e0', '#222222'
_TEXT_COLOR, _CAPTION_COLOR = '#333333', '#1c4670'


class FloorMapError(Exception):
    """Upload rejected; the message is shown to the admin as-is."""


def _number(value, what):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise FloorMapError(f'{what} must be a number, got {value!r}.')
    return float(value)


def _box(item, what):
    if not isinstance(item, dict):
        raise FloorMapError(f'{what} must be a mapping with x/y/w/h.')
    box = tuple(_number(item.get(k), f'{what} {k}') for k in 'xywh')
    if box[2] <= 0 or box[3] <= 0:
        raise FloorMapError(f'{what} must have positive w/h.')
    return box


def _str_list(value, what):
    """A list of strings from a YAML list or comma-separated string."""
    if value is None:
        return []
    if isinstance(value, str):
        value = value.split(',')
    if not isinstance(value, (list, tuple)):
        raise FloorMapError(f'{what} must be a list.')
    return [str(v).strip() for v in value if str(v).strip()]


def parse(raw):
    """Validated map structure from uploaded YAML bytes/text."""
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise FloorMapError(f'Not valid YAML ({e}).')
    if not isinstance(data, dict) or not isinstance(data.get('floors'), list) \
            or not data['floors']:
        raise FloorMapError("The file must be a mapping with a non-empty "
                            "'floors' list.")

    seen_floors, seen_rooms = set(), set()
    floors = []
    for fl in data['floors']:
        if not isinstance(fl, dict) or not str(fl.get('floor', '')).strip():
            raise FloorMapError("Each floor needs a non-empty 'floor' name.")
        name = str(fl['floor']).strip()
        if name in seen_floors:
            raise FloorMapError(f'Duplicate floor {name!r}.')
        seen_floors.add(name)

        rooms = []
        for room in fl.get('rooms') or []:
            what = f'Floor {name} room'
            if not isinstance(room, dict) \
                    or not str(room.get('number', '')).strip():
                raise FloorMapError(f"{what}s each need a 'number'.")
            number = str(room['number']).strip()
            if number in seen_rooms:
                raise FloorMapError(f'Room {number} appears twice.')
            seen_rooms.add(number)
            has_box = any(k in room for k in 'xywh')
            rooms.append({
                'number': number,
                'type': str(room.get('type') or '').strip(),
                'box': _box(room, f'{what} {number}') if has_box else None,
                'rotated': bool(room.get('rotated')),
                'ada': bool(room.get('ada')),
                'accessibility': _str_list(room.get('accessibility'),
                                           f'{what} {number} accessibility'),
                'connects_to': _str_list(room.get('connects_to'),
                                         f'{what} {number} connects_to'),
                'notes': str(room.get('notes') or '').strip(),
            })
        if not rooms:
            raise FloorMapError(f'Floor {name} has no rooms.')

        stairs = [_box(s, f'Floor {name} stair')
                  for s in fl.get('stairs') or []]
        walls = []
        for seg in fl.get('walls') or []:
            if not isinstance(seg, (list, tuple)) or len(seg) != 4:
                raise FloorMapError(
                    f'Floor {name} walls must be [x0, y0, x1, y1] lists.')
            walls.append(tuple(_number(v, f'Floor {name} wall coordinate')
                               for v in seg))
        floors.append({'floor': name, 'rooms': rooms, 'stairs': stairs,
                       'walls': walls})

    areas = []
    for area in data.get('areas') or []:
        kind = (area or {}).get('kind')
        if kind not in _AREA_COLORS:
            raise FloorMapError(
                f'Area kind must be one of {sorted(_AREA_COLORS)}, '
                f'got {kind!r}.')
        areas.append({'kind': kind,
                      'label': str(area.get('label') or '').strip(),
                      'box': _box(area, f'{kind} area')})

    labels = []
    for label in data.get('labels') or []:
        if not isinstance(label, dict) or not str(
                label.get('text', '')).strip():
            raise FloorMapError("Labels each need a 'text'.")
        labels.append({
            'text': str(label['text']).strip(),
            'x': _number(label.get('x'), 'Label x'),
            'y': _number(label.get('y'), 'Label y'),
            'size': _number(label.get('size', 18), 'Label size'),
        })

    return {'floors': floors, 'areas': areas, 'labels': labels}


def _bounds(data):
    xs, ys = [], []
    for area in data['areas']:
        x, y, w, h = area['box']
        xs += [x, x + w]
        ys += [y, y + h]
    for fl in data['floors']:
        for room in fl['rooms']:
            if not room['box']:
                continue
            x, y, w, h = room['box']
            xs += [x, x + w]
            ys += [y, y + h]
        for x, y, w, h in fl['stairs']:
            xs += [x, x + w]
            ys += [y, y + h]
        for x0, y0, x1, y1 in fl['walls']:
            xs += [x0, x1]
            ys += [y0, y1]
    for label in data['labels']:
        xs.append(label['x'])
        ys.append(label['y'])
    if not xs:
        raise FloorMapError('No room on the map has x/y/w/h geometry, so '
                            'there is nothing to draw.')
    return (min(xs) - PADDING, min(ys) - PADDING,
            max(xs) + PADDING, max(ys) + PADDING)


def _text(parent, x, y, size, content, fill, rotated=False, spacing=None):
    el = ET.SubElement(parent, 'text', {
        'x': f'{x:.1f}', 'y': f'{y:.1f}', 'font-size': f'{size:.1f}',
        'fill': fill, 'text-anchor': 'middle', 'pointer-events': 'none'})
    if rotated:
        el.set('transform', f'rotate(-90 {x:.1f} {y:.1f})')
    if spacing:
        el.set('letter-spacing', spacing)
    el.text = content
    return el


def _reads_vertically(box, content, rotated):
    _x, _y, w, h = box
    return rotated or (h > w and len(content) > 2)


def _fitted_size(box, content, rotated=False):
    """Largest font that fits `content` in `box`, before capping."""
    _x, _y, w, h = box
    if _reads_vertically(box, content, rotated):
        return min(w * 0.72, h / (max(len(content), 1) * 0.62))
    return min(h * 0.72, w / (max(len(content), 1) * 0.62))


def _label_in_box(parent, box, content, fill, rotated=False, max_size=None):
    """Caption centered in a box, sized to fit its short dimension."""
    x, y, w, h = box
    vertical = _reads_vertically(box, content, rotated)
    size = _fitted_size(box, content, rotated)
    if max_size:
        size = min(size, max_size)
    _text(parent, x + w / 2, y + h / 2 + size * 0.35, size, content, fill,
          rotated=vertical)


def _rect(parent, box, fill, stroke, stroke_width='1', **extra):
    x, y, w, h = box
    return ET.SubElement(parent, 'rect', {
        'x': f'{x:.1f}', 'y': f'{y:.1f}', 'width': f'{w:.1f}',
        'height': f'{h:.1f}', 'fill': fill, 'stroke': stroke,
        'stroke-width': stroke_width, **extra})


def render(data):
    """The stored/served SVG for a parsed map."""
    x0, y0, x1, y1 = _bounds(data)
    root = ET.Element('svg', {
        'xmlns': 'http://www.w3.org/2000/svg',
        'viewBox': f'{x0:.0f} {y0:.0f} {x1 - x0:.0f} {y1 - y0:.0f}',
        'font-family': 'sans-serif'})

    if data['areas'] or data['labels']:
        base = ET.SubElement(root, 'g', {'pointer-events': 'none'})
        for area in data['areas']:
            fill, stroke = _AREA_COLORS[area['kind']]
            width = '3' if area['kind'] == 'plate' else '1.5'
            _rect(base, area['box'], fill, stroke, width, rx='10')
            if area['label']:
                _label_in_box(base, area['box'], area['label'],
                              _CAPTION_COLOR, max_size=22)
        for label in data['labels']:
            _text(base, label['x'], label['y'], label['size'],
                  label['text'], _CAPTION_COLOR, spacing='3')

    # Cap room labels near the typical room's own fitted size, so a big
    # merged suite cell doesn't get a number many times larger than its
    # neighbours (and spill over them when cells abut).
    fitted = sorted(_fitted_size(room['box'], room['number'],
                                 room['rotated'])
                    for fl in data['floors'] for room in fl['rooms']
                    if room['box'])
    label_cap = fitted[len(fitted) // 2] * 1.25 if fitted else None

    for fl in data['floors']:
        layer = ET.SubElement(root, 'g', {'data-floor': fl['floor']})
        for room in fl['rooms']:
            if not room['box']:
                continue
            group = ET.SubElement(layer, 'g', {'data-room': room['number']})
            title = ET.SubElement(group, 'title')
            title.text = 'Room {}{}'.format(
                room['number'],
                f" ({room['type']})" if room['type'] else '')
            _rect(group, room['box'], _ROOM_FILL, _ROOM_STROKE)
            _label_in_box(group, room['box'], room['number'], _TEXT_COLOR,
                          rotated=room['rotated'], max_size=label_cap)
        for stair in fl['stairs']:
            _rect(layer, stair, _STAIR_FILL, _ROOM_STROKE,
                  **{'pointer-events': 'none'})
            _label_in_box(layer, stair, 'S', '#777777')
        if fl['walls']:
            path = ''.join(
                f'M{sx0:.1f} {sy0:.1f}L{sx1:.1f} {sy1:.1f}'
                for sx0, sy0, sx1, sy1 in fl['walls'])
            ET.SubElement(layer, 'path', {
                'd': path, 'fill': 'none', 'stroke': _WALL_STROKE,
                'stroke-width': '2.5', 'stroke-linecap': 'square',
                'pointer-events': 'none'})

    return ET.tostring(root, encoding='unicode')


def build(raw):
    """Uploaded YAML -> (yaml_text, svg_text) to store on the hotel.
    Raises FloorMapError on anything we can't accept."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise FloorMapError('The file is not UTF-8 text.')
    return raw, render(parse(raw))


def catalog_rows(data):
    """Spreadsheet-shaped rows for uber.hotel.physical.import_rows, so
    a map upload syncs the physical-room catalog in the same pass."""
    rows = []
    for fl in data['floors']:
        for room in fl['rooms']:
            rows.append({
                'room_number': room['number'],
                'floor': fl['floor'],
                'type': room['type'],
                'ada': 'yes' if room['ada'] else '',
                'accessibility': ', '.join(room['accessibility']),
                'connects_to': ', '.join(room['connects_to']),
                'notes': room['notes'],
            })
    return rows


def export_yaml(stored_yaml, catalog):
    """The stored map's geometry merged with the current catalog, as
    YAML text for download/re-upload.

    ``catalog`` is a list of dicts (number, floor, type, ada,
    accessibility list, connects_to list, notes). Catalog rooms with no
    shape on the map are appended to their floor without geometry;
    map-only rooms keep their uploaded values.
    """
    data = parse(stored_yaml) if stored_yaml else {
        'floors': [], 'areas': [], 'labels': []}
    by_number = {row['number']: row for row in catalog}

    def room_entry(room, row):
        entry = {'number': room['number']}
        if room['box']:
            x, y, w, h = room['box']
            entry.update(x=round(x, 2), y=round(y, 2),
                         w=round(w, 2), h=round(h, 2))
        if room['rotated']:
            entry['rotated'] = True
        source = row if row is not None else room
        for key in ('type', 'ada', 'accessibility', 'connects_to', 'notes'):
            value = source[key]
            if value:
                entry[key] = value
        return entry

    floors, floor_names = [], {}
    for fl in data['floors']:
        entry = {'floor': fl['floor'], 'rooms': [
            room_entry(room, by_number.pop(room['number'], None))
            for room in fl['rooms']]}
        if fl['stairs']:
            entry['stairs'] = [
                {'x': x, 'y': y, 'w': w, 'h': h}
                for x, y, w, h in fl['stairs']]
        if fl['walls']:
            entry['walls'] = [list(seg) for seg in fl['walls']]
        floors.append(entry)
        floor_names[fl['floor']] = entry

    # Catalog rooms the map has never seen, grouped under their floor.
    def natural(value):
        return ((0, int(value)) if value.isdigit()
                else (1, 0), value.lower())

    for row in sorted(by_number.values(),
                      key=lambda r: (natural(r['floor']),
                                     natural(r['number']))):
        floor = floor_names.get(row['floor'])
        if floor is None:
            floor = {'floor': row['floor'] or 'unknown', 'rooms': []}
            floor_names[floor['floor']] = floor
            floors.append(floor)
        floor['rooms'].append(room_entry(
            {'number': row['number'], 'box': None, 'rotated': False}, row))

    doc = {'floors': floors}
    if data['areas']:
        doc['areas'] = [
            {'kind': a['kind'],
             **({'label': a['label']} if a['label'] else {}),
             'x': a['box'][0], 'y': a['box'][1],
             'w': a['box'][2], 'h': a['box'][3]}
            for a in data['areas']]
    if data['labels']:
        doc['labels'] = data['labels']
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True,
                          width=78)


def extract(svg_text):
    """[{'floor': name, 'rooms': [shape names]}] from a stored map."""
    root = ET.fromstring(svg_text)
    floors = []
    for layer in root:
        floor = layer.get('data-floor')
        if floor is None:
            continue
        rooms = [el.get('data-room') for el in layer.iter()
                 if el.get('data-room')]
        floors.append({'floor': floor, 'rooms': rooms})
    return floors


def coverage(svg_text, room_numbers):
    """Compare a stored map against the catalog's room numbers.

    missing = catalog rooms with no shape on the map;
    extra = named shapes that match no catalog room (usually typos).
    """
    floors = extract(svg_text)
    shapes = {name for f in floors for name in f['rooms']}
    numbers = {(n or '').strip() for n in room_numbers} - {''}
    return {
        'floors': [f['floor'] for f in floors],
        'matched': sorted(numbers & shapes),
        'missing': sorted(numbers - shapes),
        'extra': sorted(shapes - numbers),
    }

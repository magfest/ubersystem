"""uber.hotel.floormap: YAML parsing/rendering, the extract/coverage
readers, catalog round-tripping, and the floor_map_rooms payload."""

import xml.etree.ElementTree as ET

import pytest
import yaml

from uber.config import c
from uber.hotel import floormap
from uber.hotel.physical import connection_map, floor_map_rooms, import_rows

from tests.hotel.factories import (N, make_assignment, make_attendee,
                                   make_hotel, make_inventory)


RAW_YAML = """
floors:
  - floor: "2"
    rooms:
      - {number: "201", type: T2A, x: 0, y: 0, w: 30, h: 8,
         connects_to: ["202"]}
      - {number: "202", type: T2, x: 0, y: 8, w: 30, h: 8,
         ada: true, accessibility: [roll-in shower, visual alarm]}
      - {number: "B99", x: 40, y: 0, w: 8, h: 30, rotated: true}
    stairs:
      - {x: 32, y: 0, w: 6, h: 6}
    walls:
      - [0, 0, 30, 0]
      - [0, 16, 30, 16]
  - floor: "3"
    rooms:
      - {number: "301", type: ES, x: 0, y: 0, w: 30, h: 16, notes: corner}
areas:
  - {kind: atrium, label: ATRIUM, x: 60, y: 0, w: 40, h: 40}
labels:
  - {text: TO RIVER, x: 80, y: 50}
"""


@pytest.fixture(scope='module')
def parsed():
    return floormap.parse(RAW_YAML)


@pytest.fixture(scope='module')
def svg(parsed):
    return floormap.render(parsed)


def test_render_svg_contract(svg):
    root = ET.fromstring(svg)
    layers = [g for g in root if g.get('data-floor')]
    assert [g.get('data-floor') for g in layers] == ['2', '3']

    rooms = {el.get('data-room'): el for el in layers[0].iter()
             if el.get('data-room')}
    assert sorted(rooms) == ['201', '202', 'B99']
    # The static title sits on the room group itself so the picker JS
    # can find and replace it with the live-status tooltip.
    title = next((child for child in rooms['201']
                  if child.tag.endswith('title')), None)
    assert title is not None and title.text == 'Room 201 (T2A)'
    # The number label is rendered rotated when asked.
    assert 'rotate(-90' in ET.tostring(rooms['B99'], encoding='unicode')

    assert root.get('viewBox'), 'picker CSS sizing needs a viewBox'
    assert root.get('width') is None


def test_render_draws_decoration_outside_room_groups(svg):
    assert 'ATRIUM' in svg and 'TO RIVER' in svg
    root = ET.fromstring(svg)
    base = root[0]
    assert base.get('data-floor') is None, \
        'context areas must not read as a floor layer'


def test_extract_and_coverage(svg):
    report = floormap.coverage(svg, ['201', '202', '301', '401', ''])
    assert report['floors'] == ['2', '3']
    assert report['matched'] == ['201', '202', '301']
    assert report['missing'] == ['401']
    assert report['extra'] == ['B99']


@pytest.mark.parametrize('doc, fragment', [
    ('nope: {', 'Not valid YAML'),
    ('floors: []', "non-empty 'floors'"),
    ('floors: [{rooms: []}]', "'floor' name"),
    ('floors: [{floor: "2", rooms: []}]', 'has no rooms'),
    ('floors: [{floor: "2", rooms: [{number: "1", x: 1, y: 1, w: 1}]}]',
     'must be a number'),
    ('floors: [{floor: "2", rooms: [{number: "1", x: 1, y: 1, w: 0, h: 1}]}]',
     'positive w/h'),
    ('floors: [{floor: "2", rooms: [{number: "1", x: 1, y: 1, w: 1, h: 1}]},'
     ' {floor: "3", rooms: [{number: "1", x: 9, y: 9, w: 1, h: 1}]}]',
     'appears twice'),
    ('floors: [{floor: "2", rooms: [{number: "1", x: 1, y: 1, w: 1, h: 1}],'
     ' walls: [[1, 2]]}]', 'walls must be'),
    ('floors: [{floor: "2", rooms: [{number: "1", x: 1, y: 1, w: 1, h: 1}]}]\n'
     'areas: [{kind: pool, x: 1, y: 1, w: 1, h: 1}]', 'Area kind'),
    ('floors: [{floor: "2", rooms: [{number: "1"}]}]', 'nothing to draw'),
])
def test_parse_rejections(doc, fragment):
    with pytest.raises(floormap.FloorMapError, match=fragment):
        floormap.render(floormap.parse(doc))


def test_catalog_rows(parsed):
    rows = {row['room_number']: row for row in floormap.catalog_rows(parsed)}
    assert rows['201']['floor'] == '2'
    assert rows['201']['type'] == 'T2A'
    assert rows['201']['connects_to'] == '202'
    assert rows['202']['ada'] == 'yes'
    assert rows['202']['accessibility'] == 'roll-in shower, visual alarm'
    assert rows['301']['notes'] == 'corner'
    assert rows['B99']['type'] == ''


def test_upload_syncs_catalog_and_export_round_trips(session):
    from uber.models.hotel import PhysicalRoom

    hotel = make_hotel(session)
    block = make_inventory(session, hotel, name='Queens',
                           physical_room_types='T2, T2A')
    parsed = floormap.parse(RAW_YAML)
    result = import_rows(session, hotel, [block],
                         floormap.catalog_rows(parsed), apply_changes=True)
    session.flush()

    assert not result['errors']
    assert sorted(result['created']) == ['201', '202', '301', 'B99']
    # Block resolution by declared type code; ES/blank stay uncategorized.
    assert sorted(result['uncategorized']) == ['301']
    rooms = {r.room_number: r for r in session.query(PhysicalRoom)
             .filter_by(hotel_id=hotel.id)}
    assert rooms['201'].inventory_id == block.id
    assert rooms['201'].type_code == 'T2A'
    assert rooms['B99'].inventory_id is None
    assert rooms['202'].ada is True
    assert rooms['202'].accessibility == 'roll-in shower, visual alarm'
    assert connection_map(session, hotel.id)[rooms['201'].id] == ['202']

    # Catalog edits flow back into the export; geometry is preserved.
    rooms['202'].accessibility = 'grab bars'
    extra = PhysicalRoom(hotel_id=hotel.id, room_number='204', floor='2',
                         type_code='T2')
    session.add(extra)
    session.flush()

    catalog = [{
        'number': r.room_number, 'floor': r.floor, 'type': r.type_code,
        'ada': r.ada, 'accessibility': r.accessibility_list,
        'connects_to': connection_map(session, hotel.id).get(r.id, []),
        'notes': r.notes,
    } for r in rooms.values()] + [{
        'number': '204', 'floor': '2', 'type': 'T2', 'ada': False,
        'accessibility': [], 'connects_to': [], 'notes': '',
    }]
    exported = floormap.export_yaml(RAW_YAML, catalog)
    doc = yaml.safe_load(exported)
    by_floor = {f['floor']: f for f in doc['floors']}
    by_number = {r['number']: r for f in doc['floors'] for r in f['rooms']}

    assert by_number['202']['accessibility'] == ['grab bars']
    assert by_number['202']['x'] == 0 and by_number['202']['h'] == 8
    assert 'x' not in by_number['204'], 'catalog-only room has no geometry'
    assert by_number['204'] in by_floor['2']['rooms']
    assert doc['areas'][0]['kind'] == 'atrium'
    assert by_floor['2']['walls'] == [[0, 0, 30, 0], [0, 16, 30, 16]]

    # And the export itself is a valid upload.
    reparsed = floormap.parse(exported)
    assert floormap.render(reparsed)
    assert {row['room_number'] for row in floormap.catalog_rows(reparsed)} \
        == {'201', '202', '204', '301', 'B99'}


def test_rooms_by_floor_natural_order(session):
    from uber.hotel.physical import rooms_by_floor
    from uber.models.hotel import PhysicalRoom

    hotel = make_hotel(session)
    for floor, number in [('10', '10001'), ('2', '2001'), ('PH', 'PH1'),
                          ('M', 'M1'), ('19', '19001'), ('3', '3001')]:
        session.add(PhysicalRoom(hotel_id=hotel.id, room_number=number,
                                 floor=floor))
    session.flush()

    floors = [floor for floor, _ in rooms_by_floor(session, hotel.id)]
    assert floors == ['2', '3', '10', '19', 'M', 'PH']


def test_floor_map_rooms_payload(session):
    from uber.models.hotel import PhysicalRoom

    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, name='King Block')
    room = PhysicalRoom(hotel_id=hotel.id, inventory_id=inv.id,
                        room_number='201', floor='2', ada=True,
                        type_code='T2A',
                        accessibility='roll-in shower, visual alarm')
    empty = PhysicalRoom(hotel_id=hotel.id, room_number='202', floor='2',
                         out_of_service=True)
    session.add_all([room, empty])
    session.flush()

    attendee = make_attendee(session, first='Mappy')
    ra = make_assignment(session, attendee, inventory=inv,
                         check_in=N[1], check_out=N[3],
                         physical_room_id=room.id)

    payload = floor_map_rooms(
        [('2', [room, empty])], {room.id: [ra]})
    by_number = {entry['number']: entry for entry in payload}

    assert by_number['201']['inventory_id'] == inv.id
    assert by_number['201']['block'] == inv.display_name
    assert by_number['201']['type_code'] == 'T2A'
    assert by_number['201']['ada'] is True
    assert by_number['201']['accessibility'] == ['roll-in shower',
                                                 'visual alarm']
    booking = by_number['201']['bookings'][0]
    assert booking['guest'] == attendee.full_name
    assert booking['status'] == dict(c.HOTEL_ASSIGNMENT_STATUS_OPTS)[c.ASSIGNED]
    assert booking['check_in'] == str(N[1])
    assert booking['check_out'] == str(N[3])

    assert by_number['202']['out_of_service'] is True
    assert by_number['202']['inventory_id'] is None
    assert by_number['202']['bookings'] == []

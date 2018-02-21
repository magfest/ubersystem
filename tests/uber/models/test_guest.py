from uber.models.group import Group
from uber.models.guests import GuestGroup


class TestGuestProperties:
    def test_normalized_group_name(self):
        group = Group(name="$Test's Cool Band &     Friends#%@", guest=GuestGroup())
        assert group.guest.normalized_group_name == "tests_cool_band_friends"

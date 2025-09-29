from collections import defaultdict
from ortools.linear_solver import pywraplp
import uuid
import random
import time

def generate_data(num_apps=25000, num_rooms=2000, single_ratio=0.75):
    hotels = [
        "Gaylord",
        "ResidenceInn",
        "CardboardBox"
    ]

    room_types = [
        "Queen",
        "King"
    ]

    class Application():
        def __init__(self):
            self.id = str(uuid.uuid4())
            self.parent_application = None
            self.entry_type = False
            if random.random() < 0.9:
                self.entry_type = True
            self.hotel_preference = ",".join(random.sample(hotels, random.randrange(len(hotels)) + 1))
            self.room_type_preference = ",".join(random.sample(room_types, random.randrange(len(room_types) + 1)))
            
        def __repr__(self):
            return self.id

    applications = []
    for i in range(num_apps):
        applications.append(Application())
        
    num_groups = 0
    num_singles = len(applications)
    unused_applications = random.sample(applications, int(single_ratio*len(applications)))
    while unused_applications:
        group_size = random.randrange(1, 4)
        leader = unused_applications.pop()
        if unused_applications:
            num_groups += 1
            num_singles -= 1
        for i in range(min(group_size, len(unused_applications))):
            member = unused_applications.pop()
            member.parent_application = leader.id
            num_singles -= 1

    total_rooms = 0
    hotel_rooms = []
    for hotel in hotels:
        for room_type in room_types:
            hotel_rooms.append({
                "id": hotel,
                "capacity": 4,
                "room_type": room_type,
                "quantity": num_rooms // (len(hotels) * len(room_types)),
                "count": 0
            })
            total_rooms += hotel_rooms[-1]["quantity"]
    hotel_rooms[-1]["quantity"] += num_rooms - total_rooms
    return applications, hotel_rooms, num_groups, num_singles

def weight_entry(entry, hotel_room):
    """Takes a lottery entry and a hotel room and returns an arbitrary score for how likely that applicant
        should be to get that particular room.
    """
    # Higher weight increases the odds of them getting this room.
    weight = 1.0
    
    # Give 10 points for being the first choice hotel, 9 points for the second, etc
    hotel_choice_rank = 10 - entry["hotels"].index(hotel_room["id"])
    weight += hotel_choice_rank
    
    # Give 10 points for being the first choice room type, 9 points for the second, etc
    try:
        room_type_rank = 10 - entry["room_types"].index(hotel_room["room_type"])
        assert room_type_rank >= 0
        weight += room_type_rank
    except ValueError:
        # room types are optional, so we need to figure out how much weight to give people who don't choose any
        weight += 9 # Probably fine?

    # Give one point for each group member
    weight += len(entry["members"])
    
    return weight
    
def solve_lottery(applications, hotel_rooms):
    """Takes a set of hotel_rooms and applications and assigns the hotel_rooms mostly randomly.
        Parameters:
        applications List[Application]: Iterable set of Application objects to assign
        hotel_rooms  List[hotels]: Iterable set of hotel rooms, represented as dictionaries with the following keys:
        * id: c.HOTEL_LOTTERY_HOTELS_OPTS
        * capacity: int
        * room_type: c.HOTEL_LOTTERY_ROOM_TYPE_OPTS
        * quantity: int
        
        Returns Dict[Applications -> hotel, room_type]: A mapping of Application.id -> (id, room_type) or None if it failed
    """
    solver = pywraplp.Solver.CreateSolver("GLOP")
    
    # Set up our data structures
    for hotel_room in hotel_rooms:
        hotel_room["constraints"] = []

    ####ORIGINAL SOLUTION UNCOMMENT FOR COMPARATIVE TESTING
    # entries = {}
    # for app in applications:
    #     if app.entry_type and not app.parent_application:
    #         entry = {
    #             "members": [app],
    #             "hotels": app.hotel_preference.split(","),
    #             "room_types": app.room_type_preference.split(","),
    #             "constraints": []
    #         }
    #         entries[app.id] = entry
    #         for hotel_room in hotel_rooms:
    #             if hotel_room["id"] in entry["hotels"]:
    #                 weight = weight_entry(entry, hotel_room)                 
                    
    #                 # Each constraint is a tuple of (BoolVar(), weight, hotel_room)
    #                 constraint = solver.BoolVar(f'{app.id}_assigned_to_{hotel_room["id"]}')
    #                 entry["constraints"].append((constraint, weight, hotel_room))
    #                 hotel_room["constraints"].append(constraint)
                    
    # for app in applications:
    #     if app.entry_type and app.parent_application in entries:
    #         entries[app.parent_application]["members"].append(app)
    ###########
    

    
    #### PROPOSED CHANGE COMMENT/UNCOMMENT FOR TESTING
    entries = {}
    for app in applications:
        if app.entry_type and not app.parent_application:
            entry = {
                "members": [app],
                "hotels": app.hotel_preference.split(","),
                "room_types": app.room_type_preference.split(","),
                "constraints": []
            }
            entries[app.id] = entry

    for app in applications:
        if app.entry_type and app.parent_application in entries:
            entries[app.parent_application]["members"].append(app)

    for app_id, entry in entries.items():
        for hotel_room in hotel_rooms:
            if hotel_room["id"] in entry["hotels"]:
                weight = weight_entry(entry, hotel_room)                 
                # Each constraint is a tuple of (BoolVar(), weight, hotel_room)
                constraint = solver.BoolVar(f'{app_id}_assigned_to_{hotel_room["id"]}')
                entry["constraints"].append((constraint, weight, hotel_room))
                hotel_room["constraints"].append(constraint)
    ######################

    ## Limit capacity of each room to fit the groups
    for app, entry in entries.items():
        num_entrants = len(entry["members"])
        for is_assigned, weight, hotel_room in entry["constraints"]:
            solver.Add(is_assigned * num_entrants <= hotel_room["capacity"])
    
    ## Only allow each group to have one room
        solver.Add(solver.Sum([x[0] for x in entry["constraints"]]) <= 1)
    
    ## Only allow each room type to fit only the quantity available
    for hotel_room in hotel_rooms:
        if hotel_room["constraints"]:
            solver.Add(solver.Sum(hotel_room["constraints"]) <= hotel_room["quantity"])
            
    # Set up Objective function
    objective = solver.Objective()
    
    for app, entry in entries.items():
        for is_assigned, weight, hotel_room in entry["constraints"]:
            objective.SetCoefficient(is_assigned, weight)
    
    objective.SetMaximization()
    
    # Run the solver
    status = solver.Solve()
    if status in [pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE]:
        # If it's optimal we know we got an ideal solution
        # If it's feasible then we may have been on the way to an ideal solution,
        # but we gave up searching because we ran out of time or something
        assignments = {}
        for app, entry in entries.items():
            for is_assigned, weight, hotel_room in entry["constraints"]:
                if is_assigned.solution_value() > 0.5:
                    assert not app in assignments
                    assignments[app] = hotel_room
        return assignments
    else:
        print(f"Error solving room lottery: {status}")
        return None
    
    
#for apps in range(1000, 25000, 1000):
apps = 24000
num_rooms = 3000
applications, hotel_rooms, num_groups, num_singles = generate_data(num_apps=apps, num_rooms=num_rooms)
start = time.time()
results = solve_lottery(applications, hotel_rooms)
duration = time.time() - start
print(f"{len(results)} rooms assigned out of {num_rooms} ({len(results) / num_rooms * 100:.1f}%)")
# print(f"Allocated {len(results)} room groups out of {num_groups + num_singles} ({len(results) / (num_groups + num_singles) * 100:.1f}%)")
# print(f"{len(applications)} applications and {num_rooms} hotel rooms")
# print(f"Solve took {duration:.2f}s")
# print()

for hotel_room in results.values():
    hotel_room["count"] += 1
for hotel_room in hotel_rooms:
    #print(f"{hotel_room['id']}-{hotel_room['room_type']}: {hotel_room['count']} / {hotel_room['quantity']}")
    assert hotel_room['count'] <= hotel_room['quantity']


child_count = defaultdict(int)
for app in applications:
    if app.entry_type and app.parent_application:
        child_count[app.parent_application] += 1

assigned_groups = len(results)
assigned_people = sum(1 + child_count[parent_id] for parent_id in results.keys())

eligible_people = sum(1 for app in applications if app.entry_type)

print(f"{assigned_groups} groups assigned out of {num_groups + num_singles} "
      f"({assigned_groups / (num_groups + num_singles) * 100:.1f}%)")
print(f"{assigned_people} people assigned out of {eligible_people} "
      f"({assigned_people / eligible_people * 100:.1f}%)")
print(f"{len(applications)} applications and {num_rooms} hotel rooms")
print(f"Solve took {duration:.2f}s")
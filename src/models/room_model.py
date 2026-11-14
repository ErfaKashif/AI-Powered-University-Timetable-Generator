
class Room:
    def __init__(self, room_id, capacity=None, room_type="lecture"):
        self.room_id = str(room_id)
        self.capacity = None if capacity in (None, "") else int(capacity)
        self.room_type = str(room_type).lower()

    def can_accommodate(self, students):
        if self.capacity is None or students is None:
            return True
        return self.capacity >= int(students)

    def __repr__(self):
        return f"Room({self.room_id!r}, capacity={self.capacity!r}, room_type={self.room_type!r})"


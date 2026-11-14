
class Teacher:
    def __init__(self, teacher_id, name, unavailable_slots=None, preferred_slots=None):
        self.teacher_id = str(teacher_id)
        self.name = str(name)
        self.unavailable_slots = set(unavailable_slots or [])
        self.preferred_slots = set(preferred_slots or [])

    def is_available(self, day, slot):
        return (day, slot) not in self.unavailable_slots

    def __repr__(self):
        return f"Teacher({self.teacher_id!r}, {self.name!r})"

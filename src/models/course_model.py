
class Course:
    def __init__(self, course_id, name, credit_hours=0, course_type="lecture"):
        self.course_id = str(course_id)
        self.name = str(name)
        self.credit_hours = int(credit_hours)
        self.course_type = str(course_type).lower()

    def __repr__(self):
        return f"Course({self.course_id!r}, {self.name!r})"

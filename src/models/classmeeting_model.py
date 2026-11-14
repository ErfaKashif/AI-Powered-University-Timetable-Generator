class ClassMeeting:
    def __init__(
        self,
        meeting_id,
        course,
        section,
        teacher,
        duration=1,
        meeting_type=None,
        students=None,
        day=None,
        slot=None,
        room=None,
    ):
        self.meeting_id = str(meeting_id)
        self.course = course
        self.section = str(section)
        self.teacher = teacher
        self.duration = int(duration)
        self.meeting_type = str(
            meeting_type if meeting_type is not None else getattr(course, "course_type", "lecture")
        ).lower()
        self.students = None if students in (None, "") else int(students)

        # These are optional current timetable values, not required for an
        # unassigned meeting used by the CSP solver.
        self.day = day
        self.slot = slot
        self.room = room

    def is_assigned(self):
        return self.day is not None and self.slot is not None and self.room is not None

    def __repr__(self):
        return (
            f"ClassMeeting({self.meeting_id!r}, section={self.section!r}, "
            f"course={getattr(self.course, 'course_id', self.course)!r})"
        )

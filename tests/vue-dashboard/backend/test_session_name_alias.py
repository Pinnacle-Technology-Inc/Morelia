from app.repositories.sessions import SessionRepository


def test_session_names_are_auto_suffixed_and_resolvable(app):
    with app.app_context():
        repository = SessionRepository()

        first = repository.create({"name": "dual-device"})
        second = repository.create({"name": "dual-device"})
        third = repository.create({"name": "dual-device"})

        assert [first.name, second.name, third.name] == [
            "dual-device",
            "dual-device-1",
            "dual-device-2",
        ]
        assert repository.get_by_name("dual-device-1").id == second.id

from aiogram.fsm.state import State, StatesGroup


class RequestFSM(StatesGroup):
    title = State()
    committee = State()
    date = State()
    time = State()
    duration = State()
    repeat = State()
    weeks = State()
    confirm = State()


class AdminFSM(StatesGroup):
    caldav_login = State()
    caldav_password = State()
    caldav_pick = State()
    template = State()
    extra = State()
    link_value = State()

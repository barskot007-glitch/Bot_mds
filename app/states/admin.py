from aiogram.fsm.state import State, StatesGroup


class AdminEventStates(StatesGroup):
    title = State()
    short_description = State()
    full_description = State()
    start_at = State()
    end_at = State()
    country = State()
    city = State()
    address = State()
    capacity = State()
    details_url = State()
    confirm = State()
    edit_value = State()


class AdminBroadcastStates(StatesGroup):
    title = State()
    text = State()
    audience = State()
    schedule = State()
    confirm = State()
    edit_value = State()


class AdminFAQStates(StatesGroup):
    question = State()
    answer = State()
    edit_question = State()
    edit_answer = State()


class AdminSupportStates(StatesGroup):
    reply = State()


class AdminManagementStates(StatesGroup):
    telegram_id = State()
    role = State()

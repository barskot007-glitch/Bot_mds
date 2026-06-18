from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    first_name = State()
    last_name = State()
    age = State()
    country = State()
    phone = State()
    email = State()
    participation_history = State()
    notifications_consent = State()
    data_consent = State()


class SupportStates(StatesGroup):
    subject = State()
    message = State()
    reply = State()

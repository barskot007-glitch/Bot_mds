from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    country = State()
    age = State()
    notifications_consent = State()
    data_consent = State()


class SupportStates(StatesGroup):
    subject = State()
    message = State()
    reply = State()

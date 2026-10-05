from aiogram.filters.callback_data import CallbackData


class Menu(CallbackData, prefix="m"):
    a: str            # request | manage | home


class Flow(CallbackData, prefix="f"):
    step: str         # dur | rep | wk | conflict | confirm
    v: str


class Rev(CallbackData, prefix="rv"):
    a: str            # approve | reject | check
    id: int


class Card(CallbackData, prefix="cd"):
    a: str            # open | cancel | cancel_yes | cancel_no | cr_ok | cr_no | request_cancel | withdraw
    id: int


class Pg(CallbackData, prefix="pg"):
    scope: str        # all | mine
    n: int


class Adm(CallbackData, prefix="ad"):
    a: str            # zoom | caldav | template | tpl_edit | tpl_reset | extra | extra_edit | extra_clear | cal_pick
    v: str = ""

"""
Telegram-бот клуба Win-Win.
Функции:
  • Запись на падел-тренировку (показ цены + реквизиты)
  • Запись на турнир по паделу
  • Заявка на Сайкл (имя + контакт -> админу)
  • Заявка на Camp в Турцию (имя + контакт -> админу)
  • Правила оплаты и отмены
"""
import asyncio
import logging
import os
from aiohttp import web

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
router = Router()


@router.errors()
async def global_error_handler(event, exception):
    logger.error("Ошибка при обработке апдейта: %s", exception, exc_info=True)
    return True


# ---------- Состояния для сбора заявок (Сайкл / Турция) ----------
class RequestForm(StatesGroup):
    service = State()
    name = State()
    contact = State()


# Подсказка для шага «вид услуги» — у сайкла и Турции разная
SERVICE_PROMPTS = {
    "cycle": (
        "Что именно вас интересует?\n"
        "Например: <i>групповое занятие, удобный день и время, абонемент или разовое.</i>"
    ),
    "turkey": (
        "Что именно вас интересует?\n"
        "Например: <i>желаемые даты, уровень игры, сколько человек поедет.</i>"
    ),
}


# Какую заявку сейчас оформляет пользователь — храним в FSM-данных
LEAD_TITLES = {
    "cycle": "🚴 Сайкл",
    "turkey": "🌴 Camp в Турцию",
}


# ---------- Клавиатуры ----------
def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎾 Запись на падел", callback_data="menu_padel")],
            [InlineKeyboardButton(text="🏆 Запись на падел турнир", callback_data="menu_tournament")],
            [InlineKeyboardButton(text="🚴 Запись на сайкл", callback_data="lead_cycle")],
            [InlineKeyboardButton(text="🌴 Camp в Турцию", callback_data="lead_turkey")],
            [InlineKeyboardButton(text="📋 Правила оплаты и отмены", callback_data="menu_rules")],
        ]
    )


def padel_menu() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=text, callback_data=key)]
        for key, text in config.PADEL_OPTIONS.items()
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="back_main")]]
    )


def cancel_kb() -> InlineKeyboardMarkup:
    """Кнопка отмены на шагах заполнения заявки (если нажал случайно/передумал)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="back_main")]]
    )


# ---------- /start и /menu ----------
@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Добро пожаловать в комьюнити Ольги Первой!\n\n"
        "Здесь можно записаться на тренировки, турниры и оставить заявку "
        "на КЕМП в Турцию. Выберите, что вас интересует:",
        reply_markup=main_menu(),
    )


# ---------- /id — узнать свой Telegram ID (для настройки ADMIN_ID) ----------
@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(
        f"Ваш Telegram ID: <code>{message.from_user.id}</code>\n"
        "Вставьте его в файл .env в строку ADMIN_ID."
    )


# ---------- Навигация по меню ----------
@router.callback_query(F.data == "back_main")
async def cb_back_main(call: CallbackQuery, state: FSMContext) -> None:
    # сбрасываем шаги заявки, но сохраняем последний выбор (чтобы чек был привязан к заказу)
    data = await state.get_data()
    last_order = data.get("last_order")
    await state.clear()
    if last_order:
        await state.update_data(last_order=last_order)
    await call.message.edit_text("Главное меню. Выберите раздел:", reply_markup=main_menu())
    await call.answer()


@router.callback_query(F.data == "menu_padel")
async def cb_padel(call: CallbackQuery) -> None:
    await call.message.edit_text(
        f"🎾 <b>Падел-тренировки</b>\n📍 {config.ADDRESS_PADEL}\n\n"
        "Выберите формат тренировки:",
        reply_markup=padel_menu(),
    )
    await call.answer()


@router.callback_query(F.data.in_(config.PADEL_OPTIONS.keys()))
async def cb_padel_choice(call: CallbackQuery, state: FSMContext) -> None:
    chosen = config.PADEL_OPTIONS[call.data]
    # запоминаем выбор клиента, чтобы показать его админу вместе с чеком
    await state.update_data(last_order=f"Падел-тренировка: {chosen}")
    await call.message.edit_text(
        f"✅ Вы выбрали:\n<b>{chosen}</b>\n📍 {config.ADDRESS_PADEL}\n\n"
        f"{config.PAYMENT_INFO}",
        reply_markup=back_main_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "menu_tournament")
async def cb_tournament(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(last_order="Турнир по падел-теннису — 5000 ₽")
    await call.message.edit_text(
        f"{config.TOURNAMENT_TEXT}\n📍 {config.ADDRESS_PADEL}\n\n{config.PAYMENT_INFO}",
        reply_markup=back_main_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "menu_rules")
async def cb_rules(call: CallbackQuery) -> None:
    await call.message.edit_text(config.RULES_TEXT, reply_markup=back_main_kb())
    await call.answer()


# ---------- Заявки на Сайкл / Турцию ----------
@router.callback_query(F.data.in_(["lead_cycle", "lead_turkey"]))
async def cb_lead_start(call: CallbackQuery, state: FSMContext) -> None:
    lead_type = call.data.split("_", 1)[1]  # cycle / turkey
    await state.update_data(lead_type=lead_type)
    await state.set_state(RequestForm.service)

    if lead_type == "cycle":
        text = (
            f"🚴 <b>Запись на сайкл</b>\n"
            f"📍 {config.ADDRESS_CYCLE}\n\n"
            f"{config.CYCLE_DESCRIPTION}\n\n"
            f"{SERVICE_PROMPTS['cycle']}"
        )
    elif lead_type == "turkey":
        text = (
            f"{config.TURKEY_DESCRIPTION}\n\n"
            f"🌴 <b>Camp в Турцию — оставьте заявку.</b>\n\n"
            f"{SERVICE_PROMPTS['turkey']}"
        )
    else:
        text = (
            f"{LEAD_TITLES[lead_type]} — оставьте заявку.\n\n"
            f"{SERVICE_PROMPTS[lead_type]}"
        )
    await call.message.edit_text(text, reply_markup=cancel_kb())
    await call.answer()


@router.message(RequestForm.service)
async def lead_service(message: Message, state: FSMContext) -> None:
    await state.update_data(service=message.text.strip())
    await state.set_state(RequestForm.name)
    await message.answer(
        "Спасибо! Теперь напишите, пожалуйста, <b>ваше имя</b>:",
        reply_markup=cancel_kb(),
    )


@router.message(RequestForm.name)
async def lead_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip())
    await state.set_state(RequestForm.contact)
    await message.answer(
        "Спасибо! Теперь оставьте <b>контакт для связи</b> "
        "(телефон или @username):",
        reply_markup=cancel_kb(),
    )


@router.message(RequestForm.contact)
async def lead_contact(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    lead_type = data.get("lead_type", "?")
    name = data.get("name", "—")
    service = data.get("service", "—")
    contact = message.text.strip()
    user = message.from_user

    title = LEAD_TITLES.get(lead_type, "Заявка")
    admin_text = (
        f"🔔 <b>Новая заявка: {title}</b>\n\n"
        f"📝 Интересует: {service}\n"
        f"👤 Имя: {name}\n"
        f"📞 Контакт: {contact}\n"
        f"💬 Telegram: @{user.username or '—'} (id {user.id})"
    )

    sent = False
    if config.ADMIN_ID:
        try:
            await bot.send_message(config.ADMIN_ID, admin_text)
            sent = True
        except Exception as e:  # noqa: BLE001
            logging.error("Не удалось отправить заявку админу: %s", e)

    if not sent:
        logging.warning("ADMIN_ID не настроен или отправка не удалась. Заявка: %s", admin_text)

    await state.clear()
    await message.answer(
        "✅ <b>Заявка принята!</b>\n"
        "Она передана администратору и находится на рассмотрении. "
        "Мы свяжемся с вами в ближайшее время.",
        reply_markup=main_menu(),
    )


# ---------- Чек об оплате (фото) ----------
@router.message(F.photo)
async def payment_receipt(message: Message, state: FSMContext, bot: Bot) -> None:
    user = message.from_user
    full_name = user.full_name or "—"
    caption = message.caption or ""

    data = await state.get_data()
    last_order = data.get("last_order", "не указан (клиент не выбрал в меню)")

    admin_caption = (
        f"🧾 <b>Новый чек об оплате</b>\n\n"
        f"🛒 Заказ: {last_order}\n"
        f"👤 От: {full_name}\n"
        f"💬 Telegram: @{user.username or '—'} (id {user.id})"
    )
    if caption:
        admin_caption += f"\n📝 Комментарий клиента: {caption}"

    sent = False
    if config.ADMIN_ID:
        try:
            # пересылаем само фото чека админу с подписью
            await bot.send_photo(
                config.ADMIN_ID,
                photo=message.photo[-1].file_id,
                caption=admin_caption,
            )
            sent = True
        except Exception as e:  # noqa: BLE001
            logging.error("Не удалось отправить чек админу: %s", e)

    if not sent:
        logging.warning("ADMIN_ID не настроен или отправка чека не удалась.")

    await message.answer(
        "✅ <b>Чек принят!</b>\n"
        "Он передан администратору и находится на рассмотрении. "
        "После проверки оплаты мы подтвердим вашу запись.",
        reply_markup=back_main_kb(),
    )


# ---------- Любой другой текст ----------
@router.message(F.text)
async def fallback(message: Message) -> None:
    await message.answer("Выберите действие в меню 👇", reply_markup=main_menu())


async def health(request: web.Request) -> web.Response:
    """Health-check для Render Web Service — без него сервис не запустится."""
    return web.Response(text="OK")


def build_bot() -> Bot:
    """Создаёт бота с нужной сессией (через прокси, если задан)."""
    # Если задан прокси — весь трафик бота идёт через него (обход блокировки).
    session = AiohttpSession(proxy=config.PROXY_URL) if config.PROXY_URL else None
    if config.PROXY_URL:
        logging.info("Использую прокси: %s", config.PROXY_URL)
    return Bot(
        token=config.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def run_webhook(bot: Bot, dp: Dispatcher) -> None:
    """Режим webhook: Telegram сам шлёт апдейты на публичный URL (для Render)."""
    port = int(os.getenv("PORT", "8080"))
    webhook_url = f"{config.WEBHOOK_URL}{config.WEBHOOK_PATH}"

    async def on_startup(bot: Bot) -> None:
        # Регистрируем webhook в Telegram при старте сервиса.
        kwargs = dict(url=webhook_url, drop_pending_updates=True)
        if config.WEBHOOK_SECRET:
            kwargs["secret_token"] = config.WEBHOOK_SECRET
        await bot.set_webhook(**kwargs)
        logging.info("Webhook установлен: %s", webhook_url)

    # ВАЖНО: webhook при остановке НЕ удаляем. Иначе при передеплое старый
    # инстанс затирает webhook, который только что поставил новый (race condition).
    dp.startup.register(on_startup)

    app = web.Application()
    app.router.add_get("/", health)  # health-check для Render
    handler_kwargs = dict(dispatcher=dp, bot=bot)
    if config.WEBHOOK_SECRET:
        handler_kwargs["secret_token"] = config.WEBHOOK_SECRET
    SimpleRequestHandler(**handler_kwargs).register(app, path=config.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    logging.info("Запуск в режиме webhook на порту %s", port)
    web.run_app(app, host="0.0.0.0", port=port)


async def run_polling(bot: Bot, dp: Dispatcher) -> None:
    """Режим polling: бот сам опрашивает Telegram (для локального запуска)."""
    # На случай, если ранее был установлен webhook — снимаем его.
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Запуск в режиме polling.")
    await dp.start_polling(bot)


def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан. Заполните файл .env")

    bot = build_bot()
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    logging.info("Бот запущен.")

    if config.WEBHOOK_URL:
        # Публичный адрес есть (Render) — работаем через webhook.
        run_webhook(bot, dp)
    else:
        # Адреса нет (локальный запуск) — работаем через polling.
        asyncio.run(run_polling(bot, dp))


if __name__ == "__main__":
    main()

import requests
import re
import asyncio
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler
from telegram.error import TelegramError
import logging

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

logging.getLogger('httpx').setLevel(logging.WARNING)

bot_token = '' #УКАЖИ ТОКЕН
chain_id = 'abstract' # УКАЖИ ГОВНОЧЕЙН, НАПРИМЕР: SOLANA / TON

TOKEN_ADDRESS, UPDATE_INTERVAL = range(2)

def send_message(chat_id, message):
    telegram_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML'
    }
    try:
        response = requests.post(telegram_url, data=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"Ошибка при отправке сообщения: {response.text}")
    except requests.RequestException as e:
        logger.error(f"Ошибка сети при отправке сообщения: {e}")

def format_large_number(value):
    """Форматирует большое число в вид $29.7M или $299k."""
    try:
        value = float(value)
        if value >= 1_000_000:
            return f"${value / 1_000_000:.1f}M"
        elif value >= 1_000:
            return f"${value / 1_000:.0f}k"
        else:
            return f"${value:.2f}"
    except (ValueError, TypeError):
        return "N/A"

async def start(update, context):
    try:
        await update.message.reply_text("Введите CA токена:")
        return TOKEN_ADDRESS
    except TelegramError as e:
        logger.error(f"Ошибка при выполнении команды /start: {e}")
        await update.message.reply_text("Ошибка. Трайни снова")
        return ConversationHandler.END

async def get_token_address(update, context):
    chat_id = update.message.chat_id
    token_address = update.message.text.strip().lower()

    if not re.match(r'^0x[a-f0-9]{40}$', token_address):
        try:
            await update.message.reply_text(
                "Неверный формат CA"
                "Трайни снова"
            )
            return TOKEN_ADDRESS
        except TelegramError as e:
            logger.error(f"Ошибка при чеке адреса: {e}")
            await update.message.reply_text("ошибка(пиздец).")
            return TOKEN_ADDRESS

    context.user_data['token_address'] = token_address
    context.user_data['chat_id'] = chat_id

    try:
        await update.message.reply_text("Введите интервал обновления данных о токене(в секундах):")
        return UPDATE_INTERVAL
    except TelegramError as e:
        logger.error(f"Ошибка Telegram: {e}")
        await update.message.reply_text("Ошибка Telegram")
        return ConversationHandler.END

async def get_update_interval(update, context):
    chat_id = update.message.chat_id
    try:
        interval = int(update.message.text.strip())
        if interval < 5:
            await update.message.reply_text("Интервал должен быть не менее 5 секунд")
            return UPDATE_INTERVAL
    except ValueError:
        await update.message.reply_text("введите число: ")
        return UPDATE_INTERVAL

    context.user_data['interval'] = interval
    context.user_data['running'] = True

    try:
        await fetch_token_info(chat_id, context.user_data['token_address'])
    except Exception as e:
        logger.error(f"Ошибка при первом запросе данных: {e}")
        await update.message.reply_text("Попробуйте снова с /start")
        return ConversationHandler.END

    try:
        await update.message.reply_text(f"Данные о токене будут обновляться каждые {interval} секунд. Чтобы остановить, отправьте /stop.")
        asyncio.create_task(periodic_fetch_token_info(context, chat_id, context.user_data['token_address']))
    except TelegramError as e:
        logger.error(f"Ошибка Telegram: {e}")
        await update.message.reply_text("Попробуйте снова с /start.")
    return ConversationHandler.END

async def fetch_token_info(chat_id, token_address):
    try:
        url = f"https://api.dexscreener.com/token-pairs/v1/{chain_id}/{token_address}"
        response = requests.get(url, headers={"Accept": "*/*"}, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0:
                # Ищем пул тута (ебля пиздец была)
                for pair_data in data:
                    if pair_data.get('baseToken', {}).get('address', '').lower() == token_address:
                        txns = pair_data['txns']
                        volume = pair_data['volume']
                        price_change = pair_data.get('priceChange', {})
                        token_name = pair_data['baseToken']['name']
                        fdv = pair_data.get('fdv', 0)  # Получаем FDV, по умолчанию 0
                        fdv_display = format_large_number(fdv) if fdv != 0 else "N/A"
                        price_usd = pair_data.get('priceUsd', 'N/A')  # Получаем priceUsd
                        message = (
                            f"<b>{token_name}</b>\n\n"
                            f"📈 Покупки за 5 минут: {txns['m5']['buys']}\n"
                            f"📉 Продажи за 5 минут: {txns['m5']['sells']}\n"
                            f"📈 Покупки за 1 час: {txns['h1']['buys']}\n"
                            f"📉 Продажи за 1 час: {txns['h1']['sells']}\n"
                            f"📈 Покупки за 6 часов: {txns['h6']['buys']}\n"
                            f"📉 Продажи за 6 часов: {txns['h6']['sells']}\n"
                            f"📈 Покупки за 24 часа: {txns['h24']['buys']}\n"
                            f"📉 Продажи за 24 часа: {txns['h24']['sells']}\n\n"
                            f"💸 Объём за 5 минут: {volume['m5']:.2f} USD\n"
                            f"💸 Объём за 1 час: {volume['h1']:.2f} USD\n"
                            f"💸 Объём за 6 часов: {volume['h6']:.2f} USD\n"
                            f"💰 Объём за 24 часа: {volume['h24']:.2f} USD\n\n"
                            f"📊 Изменение цены за 24 часа: {price_change.get('h24', 'N/A'):.2f}%\n"
                            f"💲 Цена: ${price_usd if price_usd != 'N/A' else 'N/A'}\n\n"
                            f"🏦 FDV: {fdv_display}"
                        )
                        send_message(chat_id, message)
                        return
                # Если не нашли подходящий пул(bad)
                send_message(chat_id, "Токен не найден в пулах")
            else:
                send_message(chat_id, "Нет данных о токенах")
        else:
            send_message(chat_id, f"Ошибка при получении данных из DexScreener: {response.status_code}")
    except requests.RequestException as e:
        logger.error(f"Ошибка сети при запросе к DexScreener: {e}")
        send_message(chat_id, "Ошибка при получении данных.")

async def periodic_fetch_token_info(context, chat_id, token_address):
    while context.user_data.get('running', False):
        await fetch_token_info(chat_id, token_address)
        await asyncio.sleep(context.user_data.get('interval', 30))

async def stop(update, context):
    try:
        context.user_data['running'] = False
        context.user_data.clear()
        await update.message.reply_text("Обновление данных остановлено. Отправьте /start.")
    except TelegramError as e:
        logger.error(f"Ошибка Telegram при выполнении команды /stop: {e}")
        await update.message.reply_text("Ошибка Telegram. Попробуйте снова.")
    return ConversationHandler.END

async def cancel(update, context): #самая конченая часть
    try:
        context.user_data['running'] = False
        context.user_data.clear()
        await update.message.reply_text("Операция отменена. Чтобы начать заново, отправьте /start.")
    except TelegramError as e:
        logger.error(f"Ошибка Telegram при выполнении команды /cancel: {e}")
        await update.message.reply_text("Ошибка Telegram. Попробуйте снова.")
    return ConversationHandler.END

async def error_handler(update, context):
    if isinstance(context.error, TelegramError):
        logger.error(f"Ошибка Telegram: {context.error}")
        if str(context.error).startswith("Conflict: terminated by other getUpdates request"):
            error_message = "бот уже запущен в другом процессе"
        else:
            error_message = "Ошибка Telegram"
        if update and update.message:  # Проверяем, что update не None
            await update.message.reply_text(error_message)
    else:
        logger.error(f"полный пездец: {context.error}")
        if update and update.message:
            await update.message.reply_text("Произошла ошибка. Снова с /start пропиши")
    return None

async def unknown_command(update, context):
    try:
        await update.message.reply_text("используйте команду /start, чтобы начать")
    except TelegramError as e:
        logger.error(f"Ошибка Telegram при обработке неизвестной команды: {e}")

def main():
    application = Application.builder().token(bot_token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            TOKEN_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_token_address)],
            UPDATE_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_update_interval)]
        },
        fallbacks=[CommandHandler('cancel', cancel), CommandHandler('stop', stop)],
        allow_reentry=True
    )

    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_command))
    application.add_handler(CommandHandler('stop', stop))
    application.add_error_handler(error_handler)

    application.run_polling()

if __name__ == '__main__':

    main()

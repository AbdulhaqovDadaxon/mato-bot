import logging
import base64
import json
import re
from datetime import datetime
import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ===== SOZLAMALAR =====
TELEGRAM_TOKEN = "8584043315:AAFCPZuQ8jIGtt9r9iQXielvDCFbiLyF5xg"
GOOGLE_VISION_API_KEY = "AIzaSyAOH5fLerbK_Qr3t9gYufqkIRo2e_Kkye8"
SPREADSHEET_ID = "1KD47gg9pUKVue49s6pnoRHB0xutjHxGABn610mgH9mw"
GOOGLE_APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxKAsxVijAYdZlRTXWA2ItiiGFirG6hsGhZ-F7lgR1s_gbghJF9nEN-WTeTTanM8fOSgg/exec"

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

WAITING_PRICE = 1
pending_data = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Salom! Men mato nakladnoy botiman.\n\n"
        "📸 Nakladnoy rasmini yuboring!\n\n"
        "/hisobot — Fabrikalar hisoboti\n"
        "/cancel — Bekor qilish"
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await update.message.reply_text("📸 Rasm qabul qilindi. O'qilmoqda... ⏳")

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    async with httpx.AsyncClient() as client:
        response = await client.get(file.file_path)
        image_bytes = response.content

    image_base64 = base64.standard_b64encode(image_bytes).decode('utf-8')
    raw_text = await read_text_with_vision(image_base64)

    if not raw_text:
        await update.message.reply_text("❌ Rasmdan matn o'qib bo'lmadi. Aniqroq rasm yuboring.")
        return ConversationHandler.END

    extracted = parse_nakladnoy(raw_text)
    pending_data[user_id] = extracted

    summary = format_data(extracted)
    await update.message.reply_text(
        f"✅ O'qildi!\n\n{summary}\n\n"
        f"💰 Narxini kiriting (so'm/metr):\nMasalan: 45000"
    )
    return WAITING_PRICE


async def read_text_with_vision(image_base64: str) -> str:
    try:
        url = f"https://vision.googleapis.com/v1/images:annotate?key={GOOGLE_VISION_API_KEY}"
        payload = {
            "requests": [{
                "image": {"content": image_base64},
                "features": [{"type": "TEXT_DETECTION", "maxResults": 1}],
                "imageContext": {"languageHints": ["ru", "uz"]}
            }]
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            data = response.json()

        responses = data.get("responses", [])
        if not responses:
            return ""
        text_annotations = responses[0].get("textAnnotations", [])
        if not text_annotations:
            return ""
        return text_annotations[0].get("description", "")
    except Exception as e:
        logger.error(f"Vision API xatosi: {e}")
        return ""


def parse_nakladnoy(text: str) -> dict:
    lines = text.strip().split('\n')
    result = {
        "fabrika": "",
        "sana": datetime.now().strftime('%d.%m.%Y'),
        "oluvchi": "",
        "mahsulotlar": [],
        "jami_metr": 0,
        "jami_dona": 0,
    }

    for line in lines:
        if 'ER-TEX' in line.upper() or 'ERTEX' in line.upper():
            result["fabrika"] = "ER-TEX"
            break

    date_pattern = re.compile(r'\b(\d{2}[./]\d{2}[./]\d{4})\b')
    for line in lines:
        match = date_pattern.search(line)
        if match:
            result["sana"] = match.group(1).replace('/', '.')
            break

    for line in lines:
        if 'ABDULAZIZ' in line.upper():
            result["oluvchi"] = line.strip()
            break

    amounts = []
    for line in lines:
        matches = re.findall(r'(\d+[.,]\d+)', line)
        for m in matches:
            try:
                val = float(m.replace(',', '.'))
                if val > 5:
                    amounts.append(val)
            except:
                pass
    if amounts:
        result["jami_metr"] = round(sum(amounts), 1)

    total_dona = 0
    for line in lines:
        match = re.search(r'(\d+)\s*(шт|dona)', line, re.IGNORECASE)
        if match:
            try:
                total_dona += int(match.group(1))
            except:
                pass
    result["jami_dona"] = total_dona

    mahsulot_matches = re.findall(r'(30/1[^\n]*(?:Ribana|Suprem|Penye)[^\n]*)', text, re.IGNORECASE)
    for m in mahsulot_matches[:6]:
        result["mahsulotlar"].append({"nomi": m.strip()})

    return result


def format_data(data: dict) -> str:
    lines = [
        f"🏭 Fabrika: {data.get('fabrika') or 'Aniqlanmadi'}",
        f"📅 Sana: {data.get('sana', '')}",
        f"👤 Oluvchi: {data.get('oluvchi') or 'Aniqlanmadi'}",
        f"📏 Jami metr: {data.get('jami_metr', 0)}",
        f"📦 Jami dona: {data.get('jami_dona', 0)}",
    ]
    mahsulotlar = data.get('mahsulotlar', [])
    if mahsulotlar:
        lines.append("\n📋 Mahsulotlar:")
        for i, m in enumerate(mahsulotlar, 1):
            lines.append(f"  {i}. {m.get('nomi', '')}")
    return '\n'.join(lines)


async def handle_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    try:
        narx = float(update.message.text.strip().replace(' ', '').replace(',', '.'))
    except ValueError:
        await update.message.reply_text("❌ Faqat raqam kiriting. Masalan: 45000")
        return WAITING_PRICE

    if user_id not in pending_data:
        await update.message.reply_text("❌ Ma'lumot topilmadi. Qaytadan rasm yuboring.")
        return ConversationHandler.END

    data = pending_data[user_id]
    jami_metr = float(data.get('jami_metr') or 0)
    jami_summa = jami_metr * narx

    await update.message.reply_text("📊 Google Sheets ga yozilmoqda... ⏳")
    success = await send_to_sheets(data, narx, jami_summa)

    if success:
        await update.message.reply_text(
            f"✅ Saqlandi!\n\n"
            f"🏭 Fabrika: {data.get('fabrika') or 'Noma\\'lum'}\n"
            f"📏 Jami: {jami_metr} metr\n"
            f"💰 Narx: {narx:,.0f} so'm/metr\n"
            f"💵 Jami summa: {jami_summa:,.0f} so'm\n\n"
            f"📊 Google Sheets yangilandi!"
        )
    else:
        await update.message.reply_text(
            f"⚠️ Sheets ga yozishda muammo.\n\n"
            f"{format_data(data)}\n"
            f"💵 Jami: {jami_summa:,.0f} so'm"
        )

    del pending_data[user_id]
    return ConversationHandler.END


async def send_to_sheets(data: dict, narx: float, jami_summa: float) -> bool:
    try:
        payload = {
            "action": "addNakladnoy",
            "fabrika": data.get('fabrika', 'Noma\\'lum'),
            "sana": data.get('sana', datetime.now().strftime('%d.%m.%Y')),
            "oluvchi": data.get('oluvchi', ''),
            "mahsulotlar": data.get('mahsulotlar', []),
            "jami_metr": data.get('jami_metr', 0),
            "jami_dona": data.get('jami_dona', 0),
            "narx_metr": narx,
            "jami_summa": jami_summa
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(GOOGLE_APPS_SCRIPT_URL, json=payload)
            result = response.json()
            return result.get('success', False)
    except Exception as e:
        logger.error(f"Sheets xatosi: {e}")
        return False


async def hisobot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(GOOGLE_APPS_SCRIPT_URL, params={"action": "getHisobot"})
            data = response.json()

        hisobotlar = data.get('hisobot', [])
        if not hisobotlar:
            await update.message.reply_text("📊 Hozircha ma'lumot yo'q.")
            return

        lines = ["📊 *FABRIKALAR HISOBOTI*\n"]
        jami_qarz = 0
        for h in hisobotlar:
            qarz = float(h.get('qoldiq', 0))
            jami_qarz += qarz
            status = "🔴" if qarz > 0 else "✅"
            lines.append(f"{status} *{h.get('fabrika', '')}*")
            lines.append(f"   Jami: {float(h.get('jami_summa', 0)):,.0f} so'm")
            lines.append(f"   To'landi: {float(h.get('tolandi', 0)):,.0f} so'm")
            lines.append(f"   Qoldiq: {qarz:,.0f} so'm\n")

        lines.append(f"━━━━━━━━━━━━━")
        lines.append(f"💰 *Jami qarz: {jami_qarz:,.0f} so'm*")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Hisobot xatosi: {e}")
        await update.message.reply_text("❌ Hisobotni olishda xato.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in pending_data:
        del pending_data[user_id]
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO, handle_photo)],
        states={WAITING_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("hisobot", hisobot))
    app.add_handler(conv_handler)
    logger.info("Bot ishga tushdi!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

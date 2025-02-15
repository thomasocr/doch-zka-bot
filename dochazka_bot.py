import logging
import gspread
import requests
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, CallbackContext

# 🌟 Tvůj Telegram bot token
TELEGRAM_BOT_TOKEN = "7604445726:AAGN3ePh5JFe9bNrcwJByRD_FFxZ5XH7sMc"

# 🌟 Tvůj Google Sheets ID
SHEET_ID = "1-SxNlaML9aZICfCgN_ZX9UK_xuUEEwP0DmCYwl2_tPI"

# Připojení k Google Sheets
import json
import os

# Načítáme JSON přímo z proměnné prostředí
CREDENTIALS_JSON = os.getenv("CREDENTIALS_JSON")

if CREDENTIALS_JSON:
    creds_info = json.loads(CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
else:
    raise ValueError("❌ CREDENTIALS_JSON není nastaveno!")
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1

# Stavy konverzace
DATUM, PRICHOD_ODCHOD, CAS, STAVBA, POCET_LIDI, POLOHA, POZNAMKA, UZAVRENI_TYDNE, SAZBA = range(9)

def get_address_from_coordinates(lat, lon):
    """ Používá OpenStreetMap Nominatim API pro převod souřadnic na adresu. """
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}"
    headers = {"User-Agent": "TelegramBot/1.0"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        return data.get("display_name", "Adresa nenalezena")

    return "Adresa nenalezena"

async def start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("📋 Vítej! Pošli mi datum (DD.MM.YYYY):")
    return DATUM

async def get_datum(update: Update, context: CallbackContext) -> int:
    context.user_data["datum"] = update.message.text
    reply_keyboard = [["Příjezd", "Odjezd"]]
    await update.message.reply_text("🔄 Jde o PŘÍJEZD nebo ODJEZD?",
                              reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True))
    return PRICHOD_ODCHOD

async def get_prichod_odchod(update: Update, context: CallbackContext) -> int:
    choice = update.message.text
    context.user_data["typ"] = choice

    if choice == "Příjezd":
        # Vymazání hodnot hruby_cas a cisty_cas při zadávání příjezdu
        context.user_data.pop("hruby_cas", None)
        context.user_data.pop("cisty_cas", None)
        await update.message.reply_text("⏰ Pošli čas příjezdu (HH:MM):")
    else:
        await update.message.reply_text("🚪 Pošli čas odjezdu (HH:MM):")

    return CAS

async def get_cas(update: Update, context: CallbackContext) -> int:
    context.user_data["cas"] = update.message.text

    if context.user_data["typ"] == "Příjezd":
        await update.message.reply_text("🏗️ Jaká je název/číslo stavby?")
        return STAVBA
    else:
        await update.message.reply_text("📍 Pošli svoji polohu.")
        return POLOHA

async def get_stavba(update: Update, context: CallbackContext) -> int:
    context.user_data["stavba"] = update.message.text
    await update.message.reply_text("👷‍♂️ Kolik lidí je na stavbě?")
    return POCET_LIDI

async def get_pocet_lidi(update: Update, context: CallbackContext) -> int:
    context.user_data["pocet_lidi"] = update.message.text
    await update.message.reply_text("📍 Pošli svoji polohu.")
    return POLOHA

async def get_poloha(update: Update, context: CallbackContext) -> int:
    location = update.message.location
    if location:
        lat, lon = location.latitude, location.longitude
        context.user_data["poloha"] = f"{lat}, {lon}"
        context.user_data["adresa"] = get_address_from_coordinates(lat, lon)
    else:
        context.user_data["poloha"] = "Nezadáno"
        context.user_data["adresa"] = "Neznámá adresa"

    await update.message.reply_text("📝 Chceš přidat poznámku?")
    return POZNAMKA

async def get_poznamka(update: Update, context: CallbackContext) -> int:
    context.user_data["poznamka"] = update.message.text

    if context.user_data["typ"] == "Odjezd":
        # Výpočet hrubého a čistého času
        datum = context.user_data["datum"]
        cas_odjezd = datetime.strptime(context.user_data["cas"], "%H:%M")
        
        # Najít řádek s odpovídajícím datem a typem "Příjezd"
        cell = sheet.find(datum)
        if cell:
            row = cell.row
            cas_prijezd = sheet.cell(row, 3).value
            if cas_prijezd:
                cas_prijezd = datetime.strptime(cas_prijezd, "%H:%M")
                hruby_cas = (cas_odjezd - cas_prijezd).total_seconds() / 3600
                ciste_hodiny = hruby_cas - (hruby_cas // 5) * 0.5

                context.user_data["hruby_cas"] = hruby_cas
                context.user_data["cisty_cas"] = ciste_hodiny

    reply_keyboard = [["Ano", "Ne"]]
    await update.message.reply_text(
        "📅 Chceš uzavřít pracovní týden?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    )
    return UZAVRENI_TYDNE

async def uzavreni_tydne(update: Update, context: CallbackContext) -> int:
    # Zaznamenání aktuálního odjezdu do Google Sheets
    sheet.append_row([
        context.user_data["datum"],
        context.user_data["typ"],
        context.user_data["cas"],
        context.user_data.get("stavba", ""),
        context.user_data.get("pocet_lidi", ""),
        context.user_data["poloha"],
        context.user_data["adresa"],
        context.user_data.get("hruby_cas", ""),
        context.user_data.get("cisty_cas", ""),
        context.user_data["poznamka"]
    ], table_range="A:A")  # Zajistí, že data začnou od prvního sloupce

    if update.message.text == "Ne":
        await update.message.reply_text("✅ Docházka byla zaznamenána do Google Sheets!")
        return ConversationHandler.END

    await update.message.reply_text("✅ Docházka byla zaznamenána do Google Sheets!\nKolik máme € na hodinu?")
    return SAZBA

async def get_sazba(update: Update, context: CallbackContext) -> int:
    sazba = float(update.message.text)
    
    records = sheet.get_all_values()
    total_clean_hours = 0
    start_index = 0

    # Najít poslední prázdný řádek, který odděluje týdny
    for i, row in enumerate(records):
        if not any(row):
            start_index = i + 1

    # Počítat čisté hodiny od posledního prázdného řádku
    for row in records[start_index:]:
        if row[8].replace(',', '.').replace('.', '', 1).isdigit():
            total_clean_hours += float(row[8].replace(',', '.'))

    total_earning = total_clean_hours * sazba

    # ✅ Odsazení pro týdenní souhrn
    sheet.append_row([""])
    sheet.append_row(["📅 Týdenní souhrn", "", "", "", "", "", "", "", "", total_clean_hours, total_earning])
    sheet.format(f"A{len(records)+2}:K{len(records)+2}", {"textFormat": {"bold": True}})
    sheet.append_row([""])

    message = (
        f"📅 *Týdenní souhrn*\n"
        f"🗓️ *Období:* {records[start_index][0]} ➡️ {records[-1][0]}\n"
        f"⏳ *Odpracované hodiny:* {total_clean_hours} ⏱️\n"
        f"💰 *Celkový zisk:* {total_earning} € 💵"
    )
    await update.message.reply_text(message, parse_mode="Markdown")

    # Přidání prázdného řádku pro oddělení týdnů
    sheet.append_row([""])

    return ConversationHandler.END

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            DATUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_datum)],
            PRICHOD_ODCHOD: [MessageHandler(filters.Regex("^(Příjezd|Odjezd)$"), get_prichod_odchod)],
            CAS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_cas)],
            STAVBA: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stavba)],
            POCET_LIDI: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pocet_lidi)],
            POLOHA: [MessageHandler(filters.LOCATION, get_poloha)],
            POZNAMKA: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_poznamka)],
            UZAVRENI_TYDNE: [MessageHandler(filters.Regex("^(Ano|Ne)$"), uzavreni_tydne)],
            SAZBA: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_sazba)]
        },
        fallbacks=[],
    )

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == "__main__":
    main()

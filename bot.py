import os
import asyncio
import logging
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ====== الإعدادات (تنحط كمتغيرات في السيرفر، لا تكتبها هنا) ======
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "20"))  # رسائل يومية لكل طالب

logging.basicConfig(level=logging.INFO)
client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM = """أنت مساعد دراسي ذكي ولطيف للطلاب.
- اشرح بأسلوب بسيط وواضح خطوة بخطوة مع أمثلة.
- لخّص الدروس بنقاط مرتبة.
- اصنع أسئلة تدريبية وصحّحها عند الطلب.
- ساعد الطالب يفهم الحل ولا تعطه الجواب فقط.
- أجب بنفس لغة الطالب، وإذا كتب بالعامية أجب ببساطة.
- خلّ الجواب مختصر ومناسب لشاشة الموبايل."""

history = {}  # ذاكرة المحادثة لكل طالب
usage = {}  # عداد الاستخدام اليومي


# ====== سيرفر صغير يخلي الاستضافة المجانية ما تنام ======
class Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def run_ping_server():
    port = int(os.environ.get("PORT", "10000"))
    HTTPServer(("0.0.0.0", port), Ping).serve_forever()


# ====== منطق البوت ======
def check_limit(uid: int) -> bool:
    today = date.today().isoformat()
    d, n = usage.get(uid, (today, 0))
    if d != today:
        n = 0
    if n >= DAILY_LIMIT:
        return False
    usage[uid] = (today, n + 1)
    return True


def ask_ai(uid: int, text: str) -> str:
    msgs = history.setdefault(uid, [])
    msgs.append({"role": "user", "text": text})
    del msgs[:-10]  # آخر 10 رسائل فقط
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)

    contents = [
        types.Content(role=m["role"], parts=[types.Part(text=m["text"])])
        for m in msgs
    ]
    resp = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM, max_output_tokens=1500
        ),
    )
    answer = resp.text or "ما قدرت أجاوب، جرّب صياغة ثانية."
    msgs.append({"role": "model", "text": answer})
    return answer


async def reply(update: Update, prompt: str):
    uid = update.effective_user.id
    if not check_limit(uid):
        await update.message.reply_text("وصلت الحد اليومي 🙏 ارجع باچر.")
        return
    await update.message.chat.send_action("typing")
    try:
        answer = await asyncio.to_thread(ask_ai, uid, prompt)
    except Exception as e:
        logging.exception(e)
        answer = "صار خطأ مؤقت أو الزحمة كثيرة، جرّب بعد دقيقة."
    await update.message.reply_text(answer)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً! أنا مساعدك الدراسي 📚\n\n"
        "اسألني أي سؤال، أو استخدم:\n"
        "/lakhis نص الدرس ← تلخيص\n"
        "/test الموضوع ← أسئلة تدريبية\n"
        "/sharh الموضوع ← شرح مبسط\n"
        "/reset ← مسح المحادثة"
    )


async def lakhis(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = " ".join(ctx.args)
    if not text:
        await update.message.reply_text("اكتب النص بعد الأمر، مثال:\n/lakhis نص الدرس هنا")
        return
    await reply(update, f"لخّص هذا الدرس بنقاط واضحة:\n\n{text}")


async def test(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(ctx.args)
    if not topic:
        await update.message.reply_text("اكتب الموضوع بعد الأمر، مثال:\n/test الجهاز الهضمي")
        return
    await reply(update, f"اسألني 5 أسئلة تدريبية عن: {topic}. اسألني سؤال واحد بس وانتظر جوابي.")


async def sharh(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(ctx.args)
    if not topic:
        await update.message.reply_text("اكتب الموضوع بعد الأمر، مثال:\n/sharh قانون نيوتن الثاني")
        return
    await reply(update, f"اشرح لي بشكل مبسط مع مثال: {topic}")


async def reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    history.pop(update.effective_user.id, None)
    await update.message.reply_text("تم مسح المحادثة ✅")


async def chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await reply(update, update.message.text)


def main():
    threading.Thread(target=run_ping_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lakhis", lakhis))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("sharh", sharh))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    app.run_polling()


if __name__ == "__main__":
    main()

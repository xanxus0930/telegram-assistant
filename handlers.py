import logging
import os
import tempfile
from datetime import datetime, time as dt_time

import pytz
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

import db
import utils
from ai_manager import ai_manager
from config import DEFAULT_PERSONA, MAX_HISTORY, PROVIDER_ORDER

logger = logging.getLogger(__name__)

TIMEZONE = pytz.timezone("Asia/Taipei")

PROVIDER_LABELS = {
    "gemini": "🟢 Google Gemini",
    "nvidia": "🔵 NVIDIA NIM",
    "openrouter": "🟣 OpenRouter",
}
PROVIDER_BADGE = {"gemini": "🟢", "nvidia": "🔵", "openrouter": "🟣"}


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _typing(update: Update):
    await update.effective_chat.send_chat_action(ChatAction.TYPING)


async def _ensure_user(update: Update):
    u = update.effective_user
    await db.get_or_create_user(u.id, username=u.username or "", first_name=u.first_name or "")


async def _get_context(user_id: int) -> tuple[list[dict], str]:
    history = await db.get_conversation(user_id, MAX_HISTORY)
    user = await db.get_user(user_id)
    persona = user["persona"] if user else DEFAULT_PERSONA
    return history, persona


# ── Commands ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    name = update.effective_user.first_name or "朋友"
    await update.message.reply_text(
        f"嗨 {name}！我是你的個人 AI 助理 🤖\n\n"
        "功能：\n"
        "• 💬 對話（記憶上下文）\n"
        "• 🖼️ 圖片分析\n"
        "• 🎤 語音轉文字\n"
        "• 🔗 網頁自動摘要\n"
        "• 🌐 翻譯\n"
        "• ⏰ 提醒事項\n"
        "• 🔄 多 Provider 自動輪替\n\n"
        "輸入 /help 查看所有指令"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>📋 指令列表</b>\n\n"
        "<b>基本</b>\n"
        "/start — 開始使用\n"
        "/help — 顯示此說明\n"
        "/clear — 清除對話記憶\n"
        "/status — 查看目前狀態\n\n"
        "<b>AI 設定</b>\n"
        "/switch [provider] — 切換 Provider\n"
        "  · gemini / nvidia / openrouter\n"
        "/model [model_name] — 查看/設定模型\n"
        "/persona [文字] — 設定 AI 人格\n"
        "/persona reset — 重設為預設\n\n"
        "<b>加密貨幣新聞</b>\n"
        "/news — 立即取得最新新聞摘要\n"
        "/setnews [HH:MM] — 設定每日推送時間\n"
        "/newsoff — 關閉每日推送\n\n"
        "<b>實用功能</b>\n"
        "/translate [文字] — 翻譯\n"
        "/summarize [URL] — 摘要網頁\n"
        "/export — 匯出對話記錄\n"
        "/summaryday — 今日對話摘要\n\n"
        "<b>提醒事項</b>\n"
        "/remind [時間] [內容] — 設定提醒\n"
        "  範例: /remind 10:30 開會\n"
        "  範例: /remind tomorrow 9am 買菜\n"
        "  範例: /remind in 2h 休息一下\n"
        "/reminders — 查看所有提醒\n"
        "/delremind [ID] — 刪除提醒"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    await db.clear_conversation(update.effective_user.id)
    await update.message.reply_text("✅ 對話記憶已清除")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    provider = user["current_provider"] if user else "gemini"
    model = await db.get_user_model(user_id, provider)
    token_rows = await db.get_token_usage(user_id)
    history = await db.get_conversation(user_id)
    available = ai_manager.available_providers()

    token_lines = "\n".join(
        f"  · {PROVIDER_LABELS.get(r['provider'], r['provider'])}: {r['total']:,} tokens"
        for r in token_rows
    ) or "  · 今日尚未使用"

    await update.message.reply_text(
        f"<b>📊 目前狀態</b>\n\n"
        f"🤖 Provider: {PROVIDER_LABELS.get(provider, provider)}\n"
        f"📌 Model: <code>{utils.escape_html(model)}</code>\n"
        f"💬 對話筆數: {len(history)}\n\n"
        f"<b>📈 今日 Token 用量:</b>\n{token_lines}\n\n"
        f"✅ 可用 Provider: {', '.join(available)}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_switch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    user_id = update.effective_user.id
    available = ai_manager.available_providers()

    if not context.args:
        lines = "\n".join(
            f"  · {p} {'✅' if p in available else '❌ (未設定 API Key)'}"
            for p in PROVIDER_ORDER
        )
        await update.message.reply_text(
            f"<b>🔄 切換 Provider</b>\n\n{lines}\n\n"
            "使用方式: /switch gemini",
            parse_mode=ParseMode.HTML,
        )
        return

    provider = context.args[0].lower()
    if provider not in PROVIDER_ORDER:
        await update.message.reply_text(f"❌ 不支援的 provider: {provider}\n可選: {', '.join(PROVIDER_ORDER)}")
        return
    if provider not in available:
        await update.message.reply_text(f"❌ {provider} 尚未設定 API Key")
        return

    await db.update_user_provider(user_id, provider)
    await update.message.reply_text(f"✅ 已切換至 {PROVIDER_LABELS.get(provider, provider)}")


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    provider = user["current_provider"] if user else "gemini"

    if not context.args:
        model = await db.get_user_model(user_id, provider)
        await update.message.reply_text(
            f"<b>📌 目前 Provider:</b> {provider}\n"
            f"<b>📌 目前 Model:</b> <code>{utils.escape_html(model)}</code>\n\n"
            "更改: /model &lt;model_name&gt;",
            parse_mode=ParseMode.HTML,
        )
        return

    new_model = context.args[0]
    await db.set_user_model(user_id, provider, new_model)
    await update.message.reply_text(
        f"✅ {provider} 模型已設定為: <code>{utils.escape_html(new_model)}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_persona(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    current_persona = user["persona"] if user else DEFAULT_PERSONA

    if not context.args:
        await update.message.reply_text(
            f"<b>🎭 目前 Persona</b>\n\n{utils.escape_html(current_persona)}\n\n"
            "更改: /persona &lt;新的人格描述&gt;\n"
            "重設: /persona reset",
            parse_mode=ParseMode.HTML,
        )
        return

    text = " ".join(context.args)
    if text.lower() == "reset":
        await db.update_user_persona(user_id, DEFAULT_PERSONA)
        await update.message.reply_text("✅ Persona 已重設為預設值")
    else:
        await db.update_user_persona(user_id, text)
        await update.message.reply_text(f"✅ Persona 已更新")


async def cmd_translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    user_id = update.effective_user.id
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("使用方式: /translate &lt;文字&gt;", parse_mode=ParseMode.HTML)
        return

    await _typing(update)
    try:
        reply, provider = await ai_manager.chat(
            user_id=user_id,
            history=[],
            user_message=f"請翻譯以下文字（自動偵測語言：中文↔英文，其他語言翻成繁體中文）：\n\n{text}",
            system="你是翻譯助手，只輸出翻譯結果，不加任何說明。",
        )
        badge = PROVIDER_BADGE.get(provider, "🤖")
        await update.message.reply_text(f"🌐 翻譯結果:\n\n{reply}\n\n{badge} {provider}")
    except Exception as e:
        await update.message.reply_text(f"❌ 翻譯失敗: {e}")


async def cmd_summarize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    user_id = update.effective_user.id
    url = context.args[0] if context.args else ""
    if not url or not url.startswith("http"):
        await update.message.reply_text("使用方式: /summarize &lt;URL&gt;", parse_mode=ParseMode.HTML)
        return

    await _typing(update)
    status_msg = await update.message.reply_text("🔍 正在抓取網頁內容...")
    content = await utils.fetch_webpage(url)
    if not content:
        await status_msg.edit_text("❌ 無法抓取網頁內容")
        return

    try:
        reply, provider = await ai_manager.chat(
            user_id=user_id,
            history=[],
            user_message=f"請用繁體中文摘要以下內容（300字以內，列出重點）：\n\n{content}",
            system="你是內容摘要助手。",
        )
        badge = PROVIDER_BADGE.get(provider, "🤖")
        await status_msg.edit_text(
            f"<b>📄 網頁摘要</b>\n🔗 {utils.escape_html(url)}\n\n{utils.escape_html(reply)}\n\n{badge} {provider}",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ 摘要失敗: {e}")


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    user_id = update.effective_user.id
    rows = await db.get_full_conversation_export(user_id)
    if not rows:
        await update.message.reply_text("📭 目前沒有對話記錄")
        return

    lines = ["對話記錄匯出", "=" * 40]
    for r in rows:
        role_label = "你" if r["role"] == "user" else "AI"
        lines.append(f"\n[{r['created_at']}] {role_label} ({r['provider'] or '-'}):")
        lines.append(r["content"])

    content = "\n".join(lines)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(content)
        tmp_path = f.name

    try:
        with open(tmp_path, "rb") as f:
            ts = datetime.now(TIMEZONE).strftime("%Y%m%d_%H%M%S")
            await update.message.reply_document(
                document=f,
                filename=f"對話記錄_{ts}.txt",
                caption="📋 對話記錄匯出完成",
            )
    finally:
        os.unlink(tmp_path)


async def cmd_summaryday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    user_id = update.effective_user.id
    await _typing(update)

    rows = await db.get_full_conversation_export(user_id)
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    today_rows = [r for r in rows if r["created_at"][:10] == today]

    if not today_rows:
        await update.message.reply_text("📭 今天還沒有對話記錄")
        return

    convo = "\n".join(
        f"{'你' if r['role'] == 'user' else 'AI'}: {r['content']}" for r in today_rows
    )
    try:
        reply, provider = await ai_manager.chat(
            user_id=user_id,
            history=[],
            user_message=f"請用繁體中文摘要今天的對話重點（條列式）：\n\n{convo}",
            system="你是對話摘要助手。",
        )
        badge = PROVIDER_BADGE.get(provider, "🤖")
        await update.message.reply_text(
            f"<b>📊 今日對話摘要</b>\n\n{utils.escape_html(reply)}\n\n{badge} {provider}",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 摘要失敗: {e}")


async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text(
            "<b>⏰ 設定提醒</b>\n\n"
            "用法:\n"
            "• /remind 10:30 開會\n"
            "• /remind tomorrow 9am 買菜\n"
            "• /remind in 2h 休息一下\n"
            "• /remind in 30m 喝水\n"
            "• /remind 2026-05-01 09:00 勞動節",
            parse_mode=ParseMode.HTML,
        )
        return

    text = " ".join(context.args)
    result = utils.parse_remind_time(text)
    if not result:
        await update.message.reply_text(
            "❌ 無法解析時間格式\n\n範例:\n• /remind 10:30 開會\n• /remind in 2h 休息"
        )
        return

    remind_at, message = result
    reminder_id = await db.add_reminder(user_id, message, remind_at)

    delay = (remind_at - datetime.now(TIMEZONE)).total_seconds()
    if delay > 0 and context.job_queue:
        context.job_queue.run_once(
            _fire_reminder,
            when=delay,
            data={"user_id": user_id, "message": message, "reminder_id": reminder_id},
            name=f"reminder_{reminder_id}",
        )

    time_str = remind_at.strftime("%Y-%m-%d %H:%M")
    await update.message.reply_text(
        f"✅ 提醒已設定\n\n"
        f"📌 內容: {message}\n"
        f"⏰ 時間: {time_str}\n"
        f"🆔 ID: {reminder_id}"
    )


async def _fire_reminder(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    try:
        await context.bot.send_message(
            chat_id=data["user_id"],
            text=f"⏰ <b>提醒</b>\n\n{utils.escape_html(data['message'])}",
            parse_mode=ParseMode.HTML,
        )
    finally:
        await db.mark_reminder_sent(data["reminder_id"])


async def cmd_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    reminders = await db.get_user_reminders(update.effective_user.id)
    if not reminders:
        await update.message.reply_text("📭 目前沒有待發送的提醒")
        return

    lines = ["<b>⏰ 待發送提醒</b>\n"]
    for r in reminders:
        t = r["remind_at"].replace("T", " ")[:16]
        lines.append(f"🆔 {r['id']}  |  {t}\n📌 {utils.escape_html(r['message'])}\n")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_delremind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    if not context.args:
        await update.message.reply_text("用法: /delremind &lt;ID&gt;", parse_mode=ParseMode.HTML)
        return
    try:
        rid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID 格式錯誤")
        return
    await db.delete_reminder(rid, update.effective_user.id)
    await update.message.reply_text(f"✅ 已刪除提醒 #{rid}")


# ── News Handlers ────────────────────────────────────────────────────────────

def schedule_news_job(job_queue, user_id: int, time_str: str):
    for job in job_queue.get_jobs_by_name(f"news_{user_id}"):
        job.schedule_removal()
    h, m = map(int, time_str.split(":"))
    tz = pytz.timezone("Asia/Taipei")
    job_queue.run_daily(
        _push_news,
        time=dt_time(h, m, tzinfo=tz),
        data={"user_id": user_id},
        name=f"news_{user_id}",
    )


async def _build_news_text(user_id: int, articles: list[dict]) -> str:
    if not articles:
        return "❌ 目前無法取得新聞，請稍後再試"

    article_list = "\n".join(
        f"{i+1}. [{a['source']}] {a['title']}\n   {a['url']}"
        for i, a in enumerate(articles[:15])
    )
    try:
        summary, _ = await ai_manager.chat(
            user_id=user_id,
            history=[],
            user_message=(
                "以下是今日加密貨幣新聞，請用繁體中文摘要前6則最重要的新聞，"
                "每則格式為：\n• [新聞標題或簡短摘要]（一句話）\n  🔗 [保留原始連結]\n\n"
                f"{article_list}"
            ),
            system="你是加密貨幣新聞摘要助手，提供簡潔重點摘要並保留原始連結。",
        )
        return f"📰 <b>加密貨幣每日新聞</b>\n\n{utils.escape_html(summary)}"
    except Exception:
        lines = ["📰 <b>加密貨幣最新新聞</b>\n"]
        for a in articles[:10]:
            title = utils.escape_html(a["title"])
            lines.append(f'• <a href="{a["url"]}">{title}</a>\n  <i>{a["source"]}</i>')
        return "\n\n".join(lines)


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    user_id = update.effective_user.id
    status = await update.message.reply_text("📡 正在抓取最新加密貨幣新聞...")
    articles = await utils.fetch_crypto_news()
    msg = await _build_news_text(user_id, articles)
    await status.edit_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def cmd_setnews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    user_id = update.effective_user.id

    if not context.args:
        sub = await db.get_news_sub(user_id)
        if sub:
            await update.message.reply_text(
                f"⏰ 目前每日推送時間: <b>{sub}</b>（台灣時間）\n\n"
                "更改: /setnews HH:MM\n取消: /newsoff",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text(
                "設定每日加密貨幣新聞推送時間:\n/setnews 08:00"
            )
        return

    time_str = context.args[0]
    try:
        h, m = map(int, time_str.split(":"))
        assert 0 <= h < 24 and 0 <= m < 60
        time_str = f"{h:02d}:{m:02d}"
    except Exception:
        await update.message.reply_text("❌ 格式錯誤，請用 HH:MM，例如 08:00")
        return

    await db.set_news_sub(user_id, time_str)
    schedule_news_job(context.job_queue, user_id, time_str)
    await update.message.reply_text(
        f"✅ 每日加密貨幣新聞將於 <b>{time_str}</b>（台灣時間）推送\n\n"
        "隨時可用 /news 立即取得最新新聞",
        parse_mode=ParseMode.HTML,
    )


async def cmd_newsoff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    user_id = update.effective_user.id
    await db.del_news_sub(user_id)
    for job in context.job_queue.get_jobs_by_name(f"news_{user_id}"):
        job.schedule_removal()
    await update.message.reply_text("✅ 每日新聞推送已關閉")


async def _push_news(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data["user_id"]
    articles = await utils.fetch_crypto_news()
    msg = await _build_news_text(user_id, articles)
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=msg,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error(f"Failed to push news to {user_id}: {e}")


# ── Message Handlers ──────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    user_id = update.effective_user.id
    user_text = update.message.text or ""

    await _typing(update)

    # Auto-summarize URLs when message is mostly a link
    urls = utils.extract_urls(user_text)
    if urls and len(user_text.strip()) < 200:
        url = urls[0]
        status = await update.message.reply_text("🔍 偵測到網址，正在抓取內容...")
        content = await utils.fetch_webpage(url)
        if content:
            user_text = f"請摘要這個網頁：{url}\n\n內容：\n{content}"
        await status.delete()

    history, persona = await _get_context(user_id)
    await db.add_message(user_id, "user", update.message.text or user_text)

    try:
        reply, provider = await ai_manager.chat(
            user_id=user_id,
            history=history,
            user_message=user_text,
            system=persona,
        )
        await db.add_message(user_id, "assistant", reply, provider)
        badge = PROVIDER_BADGE.get(provider, "🤖")
        await update.message.reply_text(f"{reply}\n\n{badge} {provider}")
    except Exception as e:
        await update.message.reply_text(f"❌ 發生錯誤: {e}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    user_id = update.effective_user.id
    await _typing(update)

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await file.download_as_bytearray())
    caption = update.message.caption or "請描述這張圖片"

    history, persona = await _get_context(user_id)
    await db.add_message(user_id, "user", f"[圖片] {caption}")

    try:
        reply, provider = await ai_manager.chat(
            user_id=user_id,
            history=history,
            user_message=caption,
            system=persona,
            image_bytes=image_bytes,
        )
        await db.add_message(user_id, "assistant", reply, provider)
        badge = PROVIDER_BADGE.get(provider, "🤖")
        await update.message.reply_text(f"{reply}\n\n{badge} {provider}")
    except Exception as e:
        await update.message.reply_text(f"❌ 圖片分析失敗: {e}")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    user_id = update.effective_user.id
    await _typing(update)

    status = await update.message.reply_text("🎤 正在轉錄語音...")

    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        tmp_path = tmp.name

    try:
        transcribed = await ai_manager.transcribe(tmp_path)
        await status.edit_text(f"📝 轉錄結果:\n{transcribed}")

        history, persona = await _get_context(user_id)
        await db.add_message(user_id, "user", f"[語音] {transcribed}")

        reply, provider = await ai_manager.chat(
            user_id=user_id,
            history=history,
            user_message=transcribed,
            system=persona,
        )
        await db.add_message(user_id, "assistant", reply, provider)
        badge = PROVIDER_BADGE.get(provider, "🤖")
        await update.message.reply_text(f"{reply}\n\n{badge} {provider}")

    except RuntimeError as e:
        await status.edit_text(f"❌ {e}")
    except Exception as e:
        await status.edit_text(f"❌ 語音處理失敗: {e}")
    finally:
        os.unlink(tmp_path)
